/**
 * frontend/src/services/snapshotRecovery.js
 * 
 * Standalone authoritative snapshot recovery manager.
 * Implements a strict state machine:
 * DISCONNECTED -> CONNECTING -> RECOVERING -> SYNCHRONIZED
 * (with RECOVERY_ERROR and OFFLINE_SYNC_FAILED circuit breaker).
 * 
 * Enforces fenced pre/post verification, buffer overflow safety,
 * and a persistent recovery failure budget across WebSocket drops.
 */

import { api } from './api.js';
import { trafficWS } from './websocket.js';

export class SnapshotRecoveryManager {
  constructor(options = {}) {
    this.api = options.api || api;
    this.trafficWS = options.trafficWS || trafficWS;

    // State machine
    this.state = 'DISCONNECTED'; // 'DISCONNECTED', 'CONNECTING', 'RECOVERING', 'SYNCHRONIZED', 'RECOVERY_ERROR', 'OFFLINE_SYNC_FAILED'
    this.stateListeners = new Set();
    this.telemetryListeners = new Set();

    // Telemetry buffer during recovery
    this.recoveryBuffer = [];
    this.bufferCapacity = options.bufferCapacity || 64;
    this.hasBufferOverflowed = false;
    this.overflowRetryCount = 0;

    // Persistent recovery failure budget (survives socket reconnections)
    this.persistentRecoveryFailures = 0;
    this.maxPersistentFailures = options.maxPersistentFailures || 5;

    // Temporal drift tolerance for fenced REST reconciliation (F-SYNC-01)
    this.maxDriftToleranceS = options.maxDriftToleranceS !== undefined ? options.maxDriftToleranceS : 2.0;

    // In-flight recovery control
    this.isRecovering = false;
    this.recoveryCancelled = false;
    this.retryTimeout = null;
    this.retryAttempt = 0;

    // Track active snapshot state
    this.lastSynchronizedSnapshot = null;

    // Bindings
    this._unsubWsStatus = null;
    this._unsubWsMessage = null;
  }

  /**
   * Initializes integration with the WebSocket client.
   */
  init() {
    this._unsubWsStatus = this.trafficWS.onStatusChange((wsStatus) => {
      this._handleWsStatusChange(wsStatus);
    });

    this._unsubWsMessage = this.trafficWS.subscribe((data) => {
      this.handleIncomingTelemetry(data);
    });
  }

  /**
   * Destroys listeners and cancels pending recovery timers.
   */
  destroy() {
    if (this._unsubWsStatus) this._unsubWsStatus();
    if (this._unsubWsMessage) this._unsubWsMessage();
    if (this.retryTimeout) {
      clearTimeout(this.retryTimeout);
      this.retryTimeout = null;
    }
    this.recoveryCancelled = true;
    this.isRecovering = false;
  }

  _handleWsStatusChange(wsStatus) {
    if (wsStatus === 'CONNECTING') {
      if (this.state !== 'OFFLINE_SYNC_FAILED') {
        this._setState('CONNECTING');
      }
    } else if (wsStatus === 'CONNECTED') {
      if (this.state === 'OFFLINE_SYNC_FAILED') {
        return;
      }
      this.startRecovery();
    } else if (wsStatus === 'DISCONNECTED') {
      if (this.isRecovering) {
        this.recoveryCancelled = true;
        this.isRecovering = false;
      }
      if (this.retryTimeout) {
        clearTimeout(this.retryTimeout);
        this.retryTimeout = null;
      }
      if (this.state !== 'OFFLINE_SYNC_FAILED') {
        this._setState('DISCONNECTED');
      }
    }
  }

  /**
   * Intercepts incoming WebSocket frames.
   * While RECOVERING or RECOVERY_ERROR, buffers telemetry and suppresses UI dispatch.
   * When SYNCHRONIZED, forwards live updates.
   */
  handleIncomingTelemetry(data) {
    if (!data || typeof data !== 'object') return false;

    // PONG transport frame always passes through
    if (data.type === 'PONG') {
      this._dispatchTelemetry(data);
      return true;
    }

    if (this.state === 'RECOVERING' || this.state === 'RECOVERY_ERROR') {
      if (this.recoveryBuffer.length >= this.bufferCapacity) {
        this.hasBufferOverflowed = true;
        this.recoveryBuffer.shift(); // Evict oldest frame
      }
      this.recoveryBuffer.push(data);
      return false; // Suppressed from UI
    }

    if (this.state === 'SYNCHRONIZED') {
      this._dispatchTelemetry(data);
      return true;
    }

    return false;
  }

  /**
   * Initiates authoritative snapshot recovery.
   */
  async startRecovery() {
    if (this.isRecovering) return;
    if (this.state === 'OFFLINE_SYNC_FAILED') return;

    this.isRecovering = true;
    this.recoveryCancelled = false;
    this._setState('RECOVERING');

    await this.executeRecovery();
  }

  /**
   * Executes fenced REST snapshot query and sequence reconciliation.
   */
  async executeRecovery() {
    try {
      // 1. Pre-flight fence: capture status before fetching live data
      const statusBefore = await this.api.getSimulationStatus();
      if (this.recoveryCancelled) return;

      const sessionBefore = statusBefore.run_uuid || null;
      const seqBefore = statusBefore.sequence_number ?? 0;
      const timeBefore = statusBefore.simulation_time ?? 0.0;

      // 2. Fetch mandatory operational data in parallel
      const [liveRes, signalsRes] = await Promise.all([
        this.api.getTrafficLive(),
        this.api.getSignals(),
      ]);
      if (this.recoveryCancelled) return;

      // F-SYNC-01: Simulation-time temporal drift validation
      const liveTime = liveRes?.simulation_time ?? timeBefore;
      const signalsTime = signalsRes?.simulation_time ?? timeBefore;

      if (Math.abs(liveTime - timeBefore) > this.maxDriftToleranceS) {
        console.warn(
          `[SnapshotRecovery] Traffic state drift exceeded tolerance: liveTime=${liveTime}, timeBefore=${timeBefore}, delta=${Math.abs(liveTime - timeBefore).toFixed(2)}s > ${this.maxDriftToleranceS}s`
        );
        throw new Error(`TEMPORAL_DRIFT_EXCEEDED: traffic drift ${Math.abs(liveTime - timeBefore).toFixed(2)}s`);
      }

      if (Math.abs(signalsTime - timeBefore) > this.maxDriftToleranceS) {
        console.warn(
          `[SnapshotRecovery] Signal state drift exceeded tolerance: signalsTime=${signalsTime}, timeBefore=${timeBefore}, delta=${Math.abs(signalsTime - timeBefore)}s > ${this.maxDriftToleranceS}s`
        );
        throw new Error(`TEMPORAL_DRIFT_EXCEEDED: signals drift ${Math.abs(signalsTime - timeBefore).toFixed(2)}s`);
      }

      // 3. Fetch optional metrics and analytics (best-effort)
      const [metricsRes, emergenciesRes, risksRes, compareRes, healthRes] = await Promise.allSettled([
        this.api.getTrafficMetrics(),
        this.api.getEmergencies(),
        this.api.getRisks(),
        this.api.getExperimentsCompare(),
        this.api.getHealth(),
      ]);
      if (this.recoveryCancelled) return;

      // 4. Post-flight fence: verify simulation did not restart during fetch
      const statusAfter = await this.api.getSimulationStatus();
      if (this.recoveryCancelled) return;

      const sessionAfter = statusAfter.run_uuid || null;
      const seqAfter = statusAfter.sequence_number ?? 0;

      // Verify session consistency across the fence
      if (sessionBefore !== sessionAfter) {
        console.warn(
          `[SnapshotRecovery] Session mismatch detected during recovery (${sessionBefore} -> ${sessionAfter}). Aborting snapshot.`
        );
        throw new Error('SESSION_MISMATCH_DURING_RECOVERY');
      }

      // Check for recovery buffer overflow
      if (this.hasBufferOverflowed) {
        console.warn(
          '[SnapshotRecovery] Recovery buffer overflow detected. Purging discontinuous frames without advancing sequence floor.'
        );
        this.recoveryBuffer = [];
        this.hasBufferOverflowed = false;

        if (this.overflowRetryCount < 2) {
          this.overflowRetryCount++;
          // Re-execute fresh snapshot recovery from scratch
          return await this.executeRecovery();
        } else {
          // Repeated overflow persists: escalate to failure policy
          throw new Error('PERSISTENT_BUFFER_OVERFLOW');
        }
      }

      // 5. Authoritative sequence and session reconciliation
      // Adopt post-flight status as authoritative sequence floor
      this.trafficWS.adoptSessionAndSequence(sessionAfter, seqAfter);

      // Build consolidated authoritative state
      let consolidated = {
        type: 'INITIAL_STATE',
        sequence_number: seqAfter,
        session_uuid: sessionAfter,
        simulation_time: statusAfter.simulation_time,
        status: statusAfter.status,
        mode: statusAfter.mode,
        simStatus: statusAfter,
        junctions: liveRes?.junctions || {},
        signals: signalsRes?.signals || {},
        metrics: metricsRes.status === 'fulfilled' ? metricsRes.value : null,
        emergencies: emergenciesRes.status === 'fulfilled' ? emergenciesRes.value : [],
        risks: risksRes.status === 'fulfilled' ? risksRes.value : null,
        compare: compareRes.status === 'fulfilled' ? compareRes.value : null,
        health: healthRes.status === 'fulfilled' ? healthRes.value : null,
      };

      // 6. Drain recoveryBuffer: apply only frames strictly newer than the post-fence sequence
      for (const frame of this.recoveryBuffer) {
        if (frame.session_uuid !== sessionAfter) continue; // Drop frames from older sessions
        if (typeof frame.sequence_number === 'number' && frame.sequence_number <= this.trafficWS.lastSequenceNumber) {
          continue; // Already accounted for in REST snapshot
        }

        // Apply newer valid frame
        if (typeof frame.sequence_number === 'number') {
          this.trafficWS.lastSequenceNumber = frame.sequence_number;
        }
        consolidated = this._overlayFrame(consolidated, frame);
      }
      this.recoveryBuffer = [];

      // 7. Success: reset failure budgets and transition to SYNCHRONIZED
      this.persistentRecoveryFailures = 0;
      this.overflowRetryCount = 0;
      this.retryAttempt = 0;
      this.isRecovering = false;
      this.lastSynchronizedSnapshot = consolidated;

      this._dispatchTelemetry(consolidated);
      this._setState('SYNCHRONIZED');
    } catch (err) {
      if (this.recoveryCancelled) {
        this.isRecovering = false;
        return;
      }
      console.warn('[SnapshotRecovery] Authoritative recovery error:', err.message || err);
      this._handleRecoveryFailure(err);
    }
  }

  _handleRecoveryFailure(err) {
    this.isRecovering = false;
    this.persistentRecoveryFailures++;
    this.recoveryBuffer = []; // Clear buffer to prevent stale buildup

    if (this.persistentRecoveryFailures >= this.maxPersistentFailures) {
      console.error(
        `[SnapshotRecovery] Persistent recovery failure limit reached (${this.persistentRecoveryFailures}/${this.maxPersistentFailures}). Halting automatic reconnection.`
      );
      this._setState('OFFLINE_SYNC_FAILED');
      this.trafficWS.disconnect(); // Stop automatic reconnect
      return;
    }

    this._setState('RECOVERY_ERROR');
    this._scheduleRetry();
  }

  _scheduleRetry() {
    if (this.retryTimeout) clearTimeout(this.retryTimeout);
    const delay = Math.min(2000 * Math.pow(1.5, this.retryAttempt), 8000);
    this.retryAttempt++;

    this.retryTimeout = setTimeout(() => {
      this.retryTimeout = null;
      if (this.state === 'RECOVERY_ERROR' && this.trafficWS.status === 'CONNECTED') {
        this.startRecovery();
      }
    }, delay);
  }

  /**
   * Manual retry invoked by operator after OFFLINE_SYNC_FAILED.
   */
  manualRetrySync() {
    if (this.isRecovering) return;

    if (this.retryTimeout) clearTimeout(this.retryTimeout);
    this.overflowRetryCount = 0;
    this.retryAttempt = 0;
    this.recoveryBuffer = [];
    this.hasBufferOverflowed = false;

    this._setState('CONNECTING');
    if (this.trafficWS.status === 'CONNECTED') {
      this.startRecovery();
    } else {
      this.trafficWS.connect();
    }
  }

  _overlayFrame(snapshot, frame) {
    return {
      ...snapshot,
      sequence_number: frame.sequence_number ?? snapshot.sequence_number,
      session_uuid: frame.session_uuid ?? snapshot.session_uuid,
      simulation_time: frame.simulation_time ?? snapshot.simulation_time,
      status: frame.status ?? snapshot.status,
      mode: frame.mode ?? snapshot.mode,
      junctions: frame.junctions ? { ...snapshot.junctions, ...frame.junctions } : snapshot.junctions,
      signals: frame.signals ? { ...snapshot.signals, ...frame.signals } : snapshot.signals,
      metrics: frame.metrics ?? snapshot.metrics,
      emergencies: frame.emergencies ?? snapshot.emergencies,
    };
  }

  _setState(newState) {
    if (this.state === newState) return;
    this.state = newState;
    this.stateListeners.forEach((fn) => {
      try {
        fn(newState);
      } catch (e) {
        console.error('[SnapshotRecovery] State listener exception:', e);
      }
    });
  }

  _dispatchTelemetry(data) {
    this.telemetryListeners.forEach((fn) => {
      try {
        fn(data);
      } catch (e) {
        console.error('[SnapshotRecovery] Telemetry listener exception:', e);
      }
    });
  }

  onStateChange(listener) {
    this.stateListeners.add(listener);
    listener(this.state);
    return () => this.stateListeners.delete(listener);
  }

  onTelemetry(listener) {
    this.telemetryListeners.add(listener);
    return () => this.telemetryListeners.delete(listener);
  }

  getState() {
    return {
      state: this.state,
      persistentRecoveryFailures: this.persistentRecoveryFailures,
      overflowRetryCount: this.overflowRetryCount,
      hasBufferOverflowed: this.hasBufferOverflowed,
      bufferLength: this.recoveryBuffer.length,
      isRecovering: this.isRecovering,
    };
  }
}

export const snapshotRecoveryManager = new SnapshotRecoveryManager();
