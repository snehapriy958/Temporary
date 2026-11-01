/**
 * frontend/src/services/websocket.test.js
 * 
 * Comprehensive test suite for Phase 2B-3C:
 * - WebSocket connection-generation lifecycle isolation
 * - Bounded CLOSING teardown and timeout protection
 * - Exponential backoff with randomized jitter
 * - Standalone SnapshotRecoveryManager state machine
 * - Fenced authoritative REST snapshot reconciliation
 * - Recovery buffer overflow protection and unapplied frame safety
 * - Persistent recovery failure budget and circuit breaker
 */

import { test, describe, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

import { TrafficWebSocket } from './websocket.js';
import { SnapshotRecoveryManager } from './snapshotRecovery.js';

/**
 * Deterministic Mock WebSocket for testing connection lifecycles.
 */
class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  constructor(url) {
    this.url = url;
    this.readyState = MockWebSocket.CONNECTING;
    this.onopen = null;
    this.onclose = null;
    this.onerror = null;
    this.onmessage = null;
    this.sentMessages = [];
    this.listeners = new Map();
  }

  addEventListener(event, listener) {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set());
    }
    this.listeners.get(event).add(listener);
  }

  removeEventListener(event, listener) {
    if (this.listeners.has(event)) {
      this.listeners.get(event).delete(listener);
    }
  }

  dispatchEvent(event, data) {
    const set = this.listeners.get(event);
    if (set) {
      set.forEach((fn) => fn(data));
    }
  }

  send(data) {
    this.sentMessages.push(data);
  }

  close(code = 1000, reason = '') {
    this.readyState = MockWebSocket.CLOSING;
    // Default immediate transition for tests, unless overridden
    setTimeout(() => {
      this.readyState = MockWebSocket.CLOSED;
      const ev = { code, reason };
      this.dispatchEvent('close', ev);
      if (typeof this.onclose === 'function') this.onclose(ev);
    }, 5);
  }

  // Test helpers
  triggerOpen() {
    this.readyState = MockWebSocket.OPEN;
    if (typeof this.onopen === 'function') this.onopen({});
    this.dispatchEvent('open', {});
  }

  triggerMessage(data) {
    const payload = typeof data === 'string' ? data : JSON.stringify(data);
    if (typeof this.onmessage === 'function') this.onmessage({ data: payload });
    this.dispatchEvent('message', { data: payload });
  }

  triggerClose(code = 1000, reason = '') {
    this.readyState = MockWebSocket.CLOSED;
    const ev = { code, reason };
    if (typeof this.onclose === 'function') this.onclose(ev);
    this.dispatchEvent('close', ev);
  }

  triggerError(error = new Error('Socket error')) {
    if (typeof this.onerror === 'function') this.onerror(error);
    this.dispatchEvent('error', error);
  }
}

describe('Phase 2B-3C: WebSocket Lifecycle & Snapshot Recovery Tests', () => {

  // =========================================================================
  // Scenario 1: Token Invalidation on Superseded Sockets
  // =========================================================================
  test('1. Token Invalidation on Superseded Sockets', async () => {
    let socket1 = null;
    let socket2 = null;
    let createdCount = 0;

    class TestSocket extends MockWebSocket {
      constructor(url) {
        super(url);
        createdCount++;
        if (createdCount === 1) socket1 = this;
        if (createdCount === 2) socket2 = this;
      }
    }

    const wsClient = new TrafficWebSocket({
      WebSocketClass: TestSocket,
      url: 'ws://test-broker/ws',
    });

    await wsClient.connect();
    assert.equal(wsClient.connectionGeneration, 1);
    socket1.triggerOpen();
    assert.equal(wsClient.status, 'CONNECTED');

    // Force second connection (supersedes socket1)
    socket1.readyState = MockWebSocket.CLOSED;
    wsClient.ws = null;
    await wsClient.connect();
    assert.equal(wsClient.connectionGeneration, 2);

    // Socket 1 fires close late
    socket1.triggerClose(1006, 'Abnormal late close');

    // Socket 2 should still be intact and status should remain CONNECTING
    assert.equal(wsClient.status, 'CONNECTING');
    assert.equal(wsClient.connectionGeneration, 2);
    wsClient.disconnect();
  });

  // =========================================================================
  // Scenario 2: Delayed Event Discard
  // =========================================================================
  test('2. Delayed Event Discard on Obsolete Token', async () => {
    let socket1 = null;
    class TestSocket extends MockWebSocket {
      constructor(url) {
        super(url);
        socket1 = this;
      }
    }

    const wsClient = new TrafficWebSocket({ WebSocketClass: TestSocket, url: 'ws://test' });
    await wsClient.connect();
    socket1.triggerOpen();

    const receivedMessages = [];
    wsClient.subscribe((msg) => receivedMessages.push(msg));

    // Invalidate token by disconnecting
    wsClient.disconnect();
    assert.equal(wsClient.connectionGeneration, 2);

    // Socket 1 sends message post-teardown
    socket1.triggerMessage({ type: 'TRAFFIC_UPDATE', sequence_number: 99 });

    assert.equal(receivedMessages.length, 0, 'Obsolete socket messages must be discarded');
  });

  // =========================================================================
  // Scenario 3: Explicit Disconnect Teardown
  // =========================================================================
  test('3. Explicit Disconnect Cancels Timers and Teardown', async () => {
    let socket = null;
    class TestSocket extends MockWebSocket {
      constructor(url) {
        super(url);
        socket = this;
      }
    }

    const wsClient = new TrafficWebSocket({
      WebSocketClass: TestSocket,
      url: 'ws://test',
      baseDelayMs: 50,
    });

    await wsClient.connect();
    socket.triggerOpen();

    // Trigger unexpected close to schedule reconnect
    socket.triggerClose(1006, 'Drop');
    assert.ok(wsClient.reconnectTimeout !== null, 'Reconnect timer must be scheduled');

    // Now explicitly disconnect
    wsClient.disconnect();
    assert.equal(wsClient.reconnectTimeout, null, 'Explicit disconnect must clear reconnect timer');
    assert.equal(wsClient.status, 'DISCONNECTED');
    assert.equal(wsClient.reconnectAttempts, 0);
  });

  // =========================================================================
  // Scenario 4: Duplicate Connection Prevention
  // =========================================================================
  test('4. Duplicate Connection Prevention', async () => {
    let instances = 0;
    class TestSocket extends MockWebSocket {
      constructor(url) {
        super(url);
        instances++;
      }
    }

    const wsClient = new TrafficWebSocket({ WebSocketClass: TestSocket, url: 'ws://test' });

    // First connect
    await wsClient.connect();
    assert.equal(instances, 1);
    assert.equal(wsClient.connectionGeneration, 1);

    // Redundant connect while CONNECTING
    await wsClient.connect();
    assert.equal(instances, 1, 'Must not spawn parallel socket while CONNECTING');
    assert.equal(wsClient.connectionGeneration, 1, 'Must not increment generation token');

    wsClient.ws.triggerOpen();
    // Redundant connect while OPEN
    await wsClient.connect();
    assert.equal(instances, 1, 'Must not spawn parallel socket while OPEN');

    wsClient.disconnect();
  });

  // =========================================================================
  // Scenario 5: Successful CLOSING -> CLOSED Permits Reconnection
  // =========================================================================
  test('5. Successful CLOSING to CLOSED Permits Reconnection', async () => {
    let sockets = [];
    class TestSocket extends MockWebSocket {
      constructor(url) {
        super(url);
        sockets.push(this);
      }
    }

    const wsClient = new TrafficWebSocket({
      WebSocketClass: TestSocket,
      url: 'ws://test',
      teardownTimeoutMs: 500,
    });

    await wsClient.connect();
    const sock1 = sockets[0];
    sock1.triggerOpen();

    // Transition sock1 into CLOSING
    sock1.readyState = MockWebSocket.CLOSING;

    // Simulate sock1 finishing closure in 50ms
    setTimeout(() => {
      sock1.triggerClose(1000, 'Clean close');
    }, 50);

    // Call connect() - should wait for sock1 to reach CLOSED, then connect sock2
    await wsClient.connect();

    assert.equal(sockets.length, 2, 'Second socket must be created after first reaches CLOSED');
    assert.equal(wsClient.ws, sockets[1]);
    assert.equal(wsClient.connectionGeneration, 2);

    wsClient.disconnect();
  });

  // =========================================================================
  // Scenario 6: Teardown Timeout Prevents Replacement Socket Creation
  // =========================================================================
  test('6. Teardown Timeout Prevents Immediate Replacement Socket', async () => {
    let sockets = [];
    class StuckSocket extends MockWebSocket {
      constructor(url) {
        super(url);
        sockets.push(this);
      }
      close() {
        // Deliberately stay stuck in CLOSING
        this.readyState = MockWebSocket.CLOSING;
      }
    }

    const wsClient = new TrafficWebSocket({
      WebSocketClass: StuckSocket,
      url: 'ws://test',
      teardownTimeoutMs: 80, // short timeout for test speed
    });

    await wsClient.connect();
    const sock1 = sockets[0];
    sock1.triggerOpen();

    // Force into CLOSING state
    sock1.readyState = MockWebSocket.CLOSING;

    // Attempt to connect() while socket remains stuck
    await wsClient.connect();

    assert.equal(sockets.length, 1, 'Must NOT create replacement socket when teardown times out');
    assert.equal(wsClient.ws, null, 'Active ws reference must be cleared');
    assert.equal(wsClient.pendingClosingSocket, sock1, 'Stuck socket tracked as pendingClosingSocket');
    assert.equal(wsClient.teardownStalled, true);
    assert.equal(wsClient.status, 'DISCONNECTED');

    wsClient.disconnect();
  });

  // =========================================================================
  // Scenario 7: Delayed CLOSED Permits Subsequent Controlled Reconnect
  // =========================================================================
  test('7. Delayed CLOSED Permits Subsequent Controlled Reconnect', async () => {
    let sockets = [];
    class DelayedSocket extends MockWebSocket {
      constructor(url) {
        super(url);
        sockets.push(this);
      }
    }

    const wsClient = new TrafficWebSocket({
      WebSocketClass: DelayedSocket,
      url: 'ws://test',
      teardownTimeoutMs: 50,
    });

    await wsClient.connect();
    const sock1 = sockets[0];
    sock1.triggerOpen();
    sock1.readyState = MockWebSocket.CLOSING;

    // First reconnect times out
    await wsClient.connect();
    assert.equal(sockets.length, 1);
    assert.equal(wsClient.pendingClosingSocket, sock1);

    // Later, sock1 finally reaches CLOSED
    sock1.readyState = MockWebSocket.CLOSED;

    // Subsequent connect attempt
    await wsClient.connect();
    assert.equal(sockets.length, 2, 'Replacement socket created once pendingClosingSocket is CLOSED');
    assert.equal(wsClient.pendingClosingSocket, null);
    assert.equal(wsClient.teardownStalled, false);

    wsClient.disconnect();
  });

  // =========================================================================
  // Scenario 8: Obsolete Events Cannot Modify New Connection
  // =========================================================================
  test('8. Obsolete Events Cannot Modify New Connection State', async () => {
    let sockets = [];
    class TestSocket extends MockWebSocket {
      constructor(url) {
        super(url);
        sockets.push(this);
      }
    }

    const wsClient = new TrafficWebSocket({ WebSocketClass: TestSocket, url: 'ws://test' });
    await wsClient.connect();
    const sock1 = sockets[0];
    sock1.triggerOpen();

    // Connect second socket cleanly
    sock1.readyState = MockWebSocket.CLOSED;
    wsClient.ws = null;
    await wsClient.connect();
    const sock2 = sockets[1];
    sock2.triggerOpen();
    assert.equal(wsClient.connectionGeneration, 2);

    // Late error and close events on sock1
    sock1.triggerError(new Error('Late network error on dead socket'));
    sock1.triggerClose(1006, 'Dead socket drop');

    assert.equal(wsClient.status, 'CONNECTED', 'Obsolete socket error/close must not alter connected status of gen 2');
    wsClient.disconnect();
  });

  // =========================================================================
  // Scenario 9: Exponential Backoff & Jitter Bounds
  // =========================================================================
  test('9. Exponential Backoff and Randomized Jitter Boundaries', () => {
    const wsClient = new TrafficWebSocket({
      baseDelayMs: 1000,
      maxDelayMs: 10000,
      backoffFactor: 1.5,
      jitterRatio: 0.2, // +/- 20%
    });

    for (let attempt = 0; attempt < 8; attempt++) {
      wsClient.reconnectAttempts = attempt;
      const delay = wsClient._calculateBackoffDelay();

      const expectedBase = Math.min(1000 * Math.pow(1.5, attempt), 10000);
      const minBound = expectedBase * 0.8;
      const maxBound = Math.min(10000 * 1.2, expectedBase * 1.2);

      assert.ok(
        delay >= minBound && delay <= maxBound,
        `Attempt ${attempt}: delay ${delay} must fall between [${minBound}, ${maxBound}]`
      );
    }
  });

  // =========================================================================
  // Scenario 10: Snapshot Recovery Buffering
  // =========================================================================
  test('10. Snapshot Recovery Buffering Suppresses Telemetry to Dashboard', async () => {
    const mockApi = {
      getSimulationStatus: async () => ({ run_uuid: 'session_A', sequence_number: 10, status: 'RUNNING' }),
      getTrafficLive: async () => ({ junctions: { J1: { vehicle_count: 5 } } }),
      getSignals: async () => ({ signals: {} }),
      getTrafficMetrics: async () => ({}),
      getEmergencies: async () => [],
      getRisks: async () => null,
      getExperimentsCompare: async () => null,
      getHealth: async () => ({ sumo_available: true }),
    };

    const mockWs = new TrafficWebSocket({ customUrl: 'ws://mock' });
    const recoveryMgr = new SnapshotRecoveryManager({ api: mockApi, trafficWS: mockWs });

    recoveryMgr.state = 'RECOVERING';

    const dispatched = [];
    recoveryMgr.onTelemetry((data) => dispatched.push(data));

    // Push 3 telemetry frames during recovery
    recoveryMgr.handleIncomingTelemetry({ type: 'TRAFFIC_UPDATE', sequence_number: 11, session_uuid: 'session_A' });
    recoveryMgr.handleIncomingTelemetry({ type: 'TRAFFIC_UPDATE', sequence_number: 12, session_uuid: 'session_A' });
    recoveryMgr.handleIncomingTelemetry({ type: 'TRAFFIC_UPDATE', sequence_number: 13, session_uuid: 'session_A' });

    assert.equal(dispatched.length, 0, 'No telemetry should leak to dashboard while RECOVERING');
    assert.equal(recoveryMgr.recoveryBuffer.length, 3, 'Frames must be queued in recoveryBuffer');

    mockWs.disconnect();
    recoveryMgr.destroy();
  });

  // =========================================================================
  // Scenario 11: Buffer Overflow Discard & Re-Fetch
  // =========================================================================
  test('11. Buffer Overflow Discard & Re-Fetch', async () => {
    let statusCallCount = 0;
    const mockApi = {
      getSimulationStatus: async () => {
        statusCallCount++;
        return { run_uuid: 'session_A', sequence_number: 100, status: 'RUNNING' };
      },
      getTrafficLive: async () => ({ junctions: {} }),
      getSignals: async () => ({ signals: {} }),
      getTrafficMetrics: async () => ({}),
      getEmergencies: async () => [],
      getRisks: async () => null,
      getExperimentsCompare: async () => null,
      getHealth: async () => ({ sumo_available: true }),
    };

    const mockWs = new TrafficWebSocket({ customUrl: 'ws://mock' });
    const recoveryMgr = new SnapshotRecoveryManager({
      api: mockApi,
      trafficWS: mockWs,
      bufferCapacity: 5,
    });

    recoveryMgr.state = 'RECOVERING';
    recoveryMgr.isRecovering = true;

    // Fill and overflow capacity-5 buffer with 8 frames
    for (let i = 1; i <= 8; i++) {
      recoveryMgr.handleIncomingTelemetry({ type: 'TRAFFIC_UPDATE', sequence_number: i, session_uuid: 'session_A' });
    }

    assert.equal(recoveryMgr.hasBufferOverflowed, true, 'Overflow flag must be set');
    assert.equal(recoveryMgr.recoveryBuffer.length, 5, 'Buffer should stay capped at capacity');

    // Run recovery - should detect overflow, discard buffer, and re-fetch fresh snapshot
    await recoveryMgr.executeRecovery();

    assert.ok(statusCallCount >= 3, 'Pre/post fence + re-fetch must invoke status multiple times');
    assert.equal(recoveryMgr.state, 'SYNCHRONIZED');
    assert.equal(recoveryMgr.hasBufferOverflowed, false);

    mockWs.disconnect();
    recoveryMgr.destroy();
  });

  // =========================================================================
  // Scenario 12: Unapplied Frames Never Advance Sequence Floor
  // =========================================================================
  test('12. Unapplied Frames Never Advance Sequence Floor on Overflow', async () => {
    const mockApi = {
      getSimulationStatus: async () => ({ run_uuid: 'session_A', sequence_number: 50, status: 'RUNNING' }),
      getTrafficLive: async () => ({ junctions: {} }),
      getSignals: async () => ({ signals: {} }),
      getTrafficMetrics: async () => ({}),
      getEmergencies: async () => [],
      getRisks: async () => null,
      getExperimentsCompare: async () => null,
      getHealth: async () => ({}),
    };

    const mockWs = new TrafficWebSocket({ customUrl: 'ws://mock' });
    const recoveryMgr = new SnapshotRecoveryManager({
      api: mockApi,
      trafficWS: mockWs,
      bufferCapacity: 3,
    });

    recoveryMgr.state = 'RECOVERING';
    recoveryMgr.isRecovering = true;

    // Push frames with high sequence numbers that overflow
    recoveryMgr.handleIncomingTelemetry({ type: 'TRAFFIC_UPDATE', sequence_number: 100, session_uuid: 'session_A' });
    recoveryMgr.handleIncomingTelemetry({ type: 'TRAFFIC_UPDATE', sequence_number: 200, session_uuid: 'session_A' });
    recoveryMgr.handleIncomingTelemetry({ type: 'TRAFFIC_UPDATE', sequence_number: 300, session_uuid: 'session_A' });
    recoveryMgr.handleIncomingTelemetry({ type: 'TRAFFIC_UPDATE', sequence_number: 400, session_uuid: 'session_A' });

    assert.equal(recoveryMgr.hasBufferOverflowed, true);

    await recoveryMgr.executeRecovery();

    // Sequence floor must reflect authoritative REST status (50), NOT unapplied frame 400!
    assert.equal(
      mockWs.lastSequenceNumber,
      50,
      'Sequence floor must strictly match authoritative REST snapshot, not dropped frame 400'
    );

    mockWs.disconnect();
    recoveryMgr.destroy();
  });

  // =========================================================================
  // Scenario 13: Repeated Overflow Escalates to RECOVERY_ERROR
  // =========================================================================
  test('13. Repeated Overflow Escalates to RECOVERY_ERROR', async () => {
    const mockApi = {
      getSimulationStatus: async () => ({ run_uuid: 'session_A', sequence_number: 10, status: 'RUNNING' }),
      getTrafficLive: async () => ({ junctions: {} }),
      getSignals: async () => ({ signals: {} }),
      getTrafficMetrics: async () => ({}),
      getEmergencies: async () => [],
      getRisks: async () => null,
      getExperimentsCompare: async () => null,
      getHealth: async () => ({}),
    };

    const mockWs = new TrafficWebSocket({ customUrl: 'ws://mock' });
    const recoveryMgr = new SnapshotRecoveryManager({
      api: mockApi,
      trafficWS: mockWs,
      bufferCapacity: 3,
    });

    recoveryMgr.state = 'RECOVERING';
    recoveryMgr.isRecovering = true;
    recoveryMgr.overflowRetryCount = 2; // already attempted re-fetches
    recoveryMgr.hasBufferOverflowed = true;

    await recoveryMgr.executeRecovery();

    assert.equal(
      recoveryMgr.state,
      'RECOVERY_ERROR',
      'Persistent overflow must transition to RECOVERY_ERROR, never SYNCHRONIZED'
    );
    assert.equal(recoveryMgr.persistentRecoveryFailures, 1);

    mockWs.disconnect();
    recoveryMgr.destroy();
  });

  // =========================================================================
  // Scenario 14: Fenced REST Reconciliation
  // =========================================================================
  test('14. Fenced REST Reconciliation Discards Pre-Snapshot Frames', async () => {
    let call = 0;
    const mockApi = {
      getSimulationStatus: async () => {
        call++;
        // Pre-fence seq = 20, post-fence seq = 22
        return { run_uuid: 'session_1', sequence_number: call === 1 ? 20 : 22, status: 'RUNNING' };
      },
      getTrafficLive: async () => ({ junctions: { J1: { count: 10 } } }),
      getSignals: async () => ({ signals: {} }),
      getTrafficMetrics: async () => ({}),
      getEmergencies: async () => [],
      getRisks: async () => null,
      getExperimentsCompare: async () => null,
      getHealth: async () => ({}),
    };

    const mockWs = new TrafficWebSocket({ customUrl: 'ws://mock' });
    const recoveryMgr = new SnapshotRecoveryManager({ api: mockApi, trafficWS: mockWs });

    recoveryMgr.state = 'RECOVERING';
    recoveryMgr.isRecovering = true;

    // Buffer has frame seq 21 (pre-fence post-statusBefore) and seq 25 (post-fence)
    recoveryMgr.recoveryBuffer.push({ type: 'TRAFFIC_UPDATE', sequence_number: 21, session_uuid: 'session_1' });
    recoveryMgr.recoveryBuffer.push({ type: 'TRAFFIC_UPDATE', sequence_number: 25, session_uuid: 'session_1' });

    let appliedSnapshot = null;
    recoveryMgr.onTelemetry((s) => (appliedSnapshot = s));

    await recoveryMgr.executeRecovery();

    assert.equal(recoveryMgr.state, 'SYNCHRONIZED');
    assert.equal(mockWs.lastSequenceNumber, 25, 'Sequence floor must advance to frame 25');

    mockWs.disconnect();
    recoveryMgr.destroy();
  });

  // =========================================================================
  // Scenario 15: Mismatched Session Detection
  // =========================================================================
  test('15. Mismatched Session Detection Aborts Snapshot', async () => {
    let call = 0;
    const mockApi = {
      getSimulationStatus: async () => {
        call++;
        return {
          run_uuid: call === 1 ? 'session_OLD' : 'session_NEW',
          sequence_number: 1,
          status: 'RUNNING',
        };
      },
      getTrafficLive: async () => ({ junctions: {} }),
      getSignals: async () => ({ signals: {} }),
      getTrafficMetrics: async () => ({}),
      getEmergencies: async () => [],
      getRisks: async () => null,
      getExperimentsCompare: async () => null,
      getHealth: async () => ({}),
    };

    const mockWs = new TrafficWebSocket({ customUrl: 'ws://mock' });
    const recoveryMgr = new SnapshotRecoveryManager({ api: mockApi, trafficWS: mockWs });

    recoveryMgr.state = 'RECOVERING';
    recoveryMgr.isRecovering = true;

    await recoveryMgr.executeRecovery();

    assert.equal(
      recoveryMgr.state,
      'RECOVERY_ERROR',
      'Session mismatch across fence must abort snapshot and escalate to error'
    );
    assert.equal(recoveryMgr.persistentRecoveryFailures, 1);

    mockWs.disconnect();
    recoveryMgr.destroy();
  });

  // =========================================================================
  // Scenario 16: Persistent Recovery Retry Budget & OFFLINE_SYNC_FAILED
  // =========================================================================
  test('16. Persistent Recovery Retry Budget Across Disconnects', async () => {
    const failingApi = {
      getSimulationStatus: async () => {
        throw new Error('HTTP 500 Internal Server Error');
      },
      getTrafficLive: async () => ({}),
      getSignals: async () => ({}),
    };

    const mockWs = new TrafficWebSocket({ customUrl: 'ws://mock' });
    const recoveryMgr = new SnapshotRecoveryManager({
      api: failingApi,
      trafficWS: mockWs,
      maxPersistentFailures: 3,
    });

    // Simulate 3 consecutive failed recovery cycles across socket reconnects
    for (let cycle = 1; cycle <= 3; cycle++) {
      recoveryMgr.isRecovering = true;
      recoveryMgr.state = 'RECOVERING';
      await recoveryMgr.executeRecovery();
    }

    assert.equal(
      recoveryMgr.state,
      'OFFLINE_SYNC_FAILED',
      'Exhausted retry budget must halt automatic retries and transition to OFFLINE_SYNC_FAILED'
    );
    assert.equal(recoveryMgr.persistentRecoveryFailures, 3);
    assert.equal(mockWs.status, 'DISCONNECTED', 'WebSocket must be disconnected upon persistent failure');

    mockWs.disconnect();
    recoveryMgr.destroy();
  });

  // =========================================================================
  // Scenario 17: Successful Recovery Resets Budget
  // =========================================================================
  test('17. Successful Authoritative Recovery Resets Persistent Retry Budget', async () => {
    let shouldFail = true;
    const mockApi = {
      getSimulationStatus: async () => {
        if (shouldFail) throw new Error('503 Service Unavailable');
        return { run_uuid: 'session_healthy', sequence_number: 10, status: 'RUNNING' };
      },
      getTrafficLive: async () => ({ junctions: {} }),
      getSignals: async () => ({ signals: {} }),
      getTrafficMetrics: async () => ({}),
      getEmergencies: async () => [],
      getRisks: async () => null,
      getExperimentsCompare: async () => null,
      getHealth: async () => ({}),
    };

    const mockWs = new TrafficWebSocket({ customUrl: 'ws://mock' });
    const recoveryMgr = new SnapshotRecoveryManager({
      api: mockApi,
      trafficWS: mockWs,
      maxPersistentFailures: 5,
    });

    // Accumulate 2 failures
    recoveryMgr.isRecovering = true;
    await recoveryMgr.executeRecovery();
    recoveryMgr.isRecovering = true;
    await recoveryMgr.executeRecovery();
    assert.equal(recoveryMgr.persistentRecoveryFailures, 2);

    // Now restore backend health
    shouldFail = false;
    recoveryMgr.isRecovering = true;
    await recoveryMgr.executeRecovery();

    assert.equal(recoveryMgr.state, 'SYNCHRONIZED');
    assert.equal(
      recoveryMgr.persistentRecoveryFailures,
      0,
      'Successful authoritative recovery must reset persistent failure budget to 0'
    );

    mockWs.disconnect();
    recoveryMgr.destroy();
  });

  // =========================================================================
  // Scenario 18: In-Flight Recovery Cancellation
  // =========================================================================
  test('18. In-Flight Recovery Cancellation on Socket Drop', async () => {
    let finishFetch;
    const slowFetchPromise = new Promise((resolve) => (finishFetch = resolve));

    const slowApi = {
      getSimulationStatus: async () => {
        await slowFetchPromise;
        return { run_uuid: 'session_slow', sequence_number: 10, status: 'RUNNING' };
      },
      getTrafficLive: async () => ({ junctions: {} }),
      getSignals: async () => ({ signals: {} }),
    };

    const mockWs = new TrafficWebSocket({ customUrl: 'ws://mock' });
    const recoveryMgr = new SnapshotRecoveryManager({ api: slowApi, trafficWS: mockWs });

    // Start recovery in background
    const recoveryPromise = recoveryMgr.startRecovery();

    // Socket disconnects while fetch is in-flight
    mockWs.disconnect();
    recoveryMgr.destroy(); // sets recoveryCancelled = true

    // Resolve fetch
    finishFetch();
    await recoveryPromise;

    assert.notEqual(
      recoveryMgr.state,
      'SYNCHRONIZED',
      'Cancelled recovery must never transition state to SYNCHRONIZED'
    );
  });

  // =========================================================================
  // Scenario 19: Optional Endpoint Graceful Degradation
  // =========================================================================
  test('19. Optional Endpoint Degradation Still Reaches SYNCHRONIZED', async () => {
    const mockApi = {
      // Mandatory endpoints succeed
      getSimulationStatus: async () => ({ run_uuid: 'session_A', sequence_number: 5, status: 'RUNNING' }),
      getTrafficLive: async () => ({ junctions: { J1: { count: 4 } } }),
      getSignals: async () => ({ signals: { J1: { phase: 0 } } }),

      // Optional endpoints throw errors
      getTrafficMetrics: async () => {
        throw new Error('Metrics DB timeout');
      },
      getEmergencies: async () => {
        throw new Error('Emergency service unreachable');
      },
      getRisks: async () => {
        throw new Error('GIS server down');
      },
      getExperimentsCompare: async () => {
        throw new Error('Benchmark service 500');
      },
      getHealth: async () => ({ sumo_available: true }),
    };

    const mockWs = new TrafficWebSocket({ customUrl: 'ws://mock' });
    const recoveryMgr = new SnapshotRecoveryManager({ api: mockApi, trafficWS: mockWs });

    recoveryMgr.state = 'RECOVERING';
    recoveryMgr.isRecovering = true;

    let emittedSnapshot = null;
    recoveryMgr.onTelemetry((s) => (emittedSnapshot = s));

    await recoveryMgr.executeRecovery();

    assert.equal(
      recoveryMgr.state,
      'SYNCHRONIZED',
      'Failure of optional endpoints must not prevent state from becoming SYNCHRONIZED'
    );
    assert.ok(emittedSnapshot.junctions.J1 !== undefined, 'Mandatory junctions must be populated');
    assert.equal(emittedSnapshot.metrics, null, 'Failed optional metrics safely degrade to null');
    assert.deepEqual(emittedSnapshot.emergencies, [], 'Failed optional emergencies safely degrade to empty list');

    mockWs.disconnect();
    recoveryMgr.destroy();
  });

  // =========================================================================
  // Scenario 20: F-CONC-01 Disconnect During Asynchronous Teardown Wait
  // =========================================================================
  test('20. F-CONC-01: Disconnect During Asynchronous Teardown Wait Prevents Replacement Socket', async () => {
    let sockets = [];
    class ControlledSocket extends MockWebSocket {
      constructor(url) {
        super(url);
        sockets.push(this);
      }
    }

    const wsClient = new TrafficWebSocket({
      WebSocketClass: ControlledSocket,
      url: 'ws://test',
      teardownTimeoutMs: 500,
    });

    await wsClient.connect();
    assert.equal(sockets.length, 1);
    const sock1 = sockets[0];
    sock1.triggerOpen();

    // 1. Put existing socket in CLOSING
    sock1.readyState = MockWebSocket.CLOSING;

    // 2. Start connect() - begins _waitForSocketClosed
    const connectPromise = wsClient.connect();

    // 3. Call disconnect() while teardown wait is pending
    wsClient.disconnect();

    // 4. Resolve / complete the teardown wait
    sock1.triggerClose(1000, 'Teardown completed');

    // Wait for connect() promise to settle
    await connectPromise;

    // 5. Verify no replacement WebSocket is constructed
    assert.equal(sockets.length, 1, 'Must NOT construct a replacement WebSocket');
    assert.equal(wsClient.ws, null, 'ws instance must remain null');
    assert.equal(wsClient.status, 'DISCONNECTED', 'Status must remain DISCONNECTED');
    assert.equal(wsClient.isExplicitDisconnect, true, 'isExplicitDisconnect must remain true');
  });

  // =========================================================================
  // Scenario 21: F-CONC-02 Concurrent connect() Serialization
  // =========================================================================
  test('21. F-CONC-02: Concurrent connect() Calls Share Teardown Wait and Create Exactly One Socket', async () => {
    let sockets = [];
    class ControlledSocket extends MockWebSocket {
      constructor(url) {
        super(url);
        sockets.push(this);
      }
    }

    const wsClient = new TrafficWebSocket({
      WebSocketClass: ControlledSocket,
      url: 'ws://test',
      teardownTimeoutMs: 500,
    });

    await wsClient.connect();
    assert.equal(sockets.length, 1);
    const sock1 = sockets[0];
    sock1.triggerOpen();

    // 1. Put existing socket in CLOSING
    sock1.readyState = MockWebSocket.CLOSING;

    // 2. Launch multiple concurrent connect() calls while teardown wait is pending
    const p1 = wsClient.connect();
    const p2 = wsClient.connect();
    const p3 = wsClient.connect();

    // Verify p2 and p3 join the active promise
    assert.strictEqual(wsClient.activeConnectPromise, p1);

    // 3. Complete the teardown wait
    sock1.triggerClose(1000, 'Teardown finished');

    await Promise.all([p1, p2, p3]);

    // 4. Verify exactly ONE replacement WebSocket is created
    assert.equal(sockets.length, 2, 'Exactly one replacement WebSocket must be created');
    assert.equal(wsClient.ws, sockets[1]);
    assert.equal(wsClient.activeConnectPromise, null, 'activeConnectPromise must be cleared after completion');

    wsClient.disconnect();
  });

  // =========================================================================
  // Scenario 22: F-SYNC-01 Temporal Drift Exceeds Threshold Rejects Snapshot
  // =========================================================================
  test('22. F-SYNC-01: Temporal Drift Exceeds Threshold Rejects Snapshot and Keeps Sequence Floor', async () => {
    let call = 0;
    const mockApi = {
      getSimulationStatus: async () => {
        call++;
        return {
          run_uuid: 'session_sync',
          sequence_number: call === 1 ? 10 : 15,
          simulation_time: call === 1 ? 100.0 : 101.0,
          status: 'RUNNING',
        };
      },
      // live returns simulation_time with 3.5s drift relative to pre-flight 100.0s (tolerance is 2.0s)
      getTrafficLive: async () => ({
        simulation_time: 103.5,
        junctions: { J1: { count: 12 } },
      }),
      getSignals: async () => ({
        simulation_time: 100.5,
        signals: {},
      }),
      getTrafficMetrics: async () => ({}),
      getEmergencies: async () => [],
      getRisks: async () => null,
      getExperimentsCompare: async () => null,
      getHealth: async () => ({}),
    };

    const mockWs = new TrafficWebSocket({ customUrl: 'ws://mock' });
    mockWs.lastSequenceNumber = 10;
    mockWs.sessionUuid = 'session_sync';

    const recoveryMgr = new SnapshotRecoveryManager({
      api: mockApi,
      trafficWS: mockWs,
      maxDriftToleranceS: 2.0,
    });

    recoveryMgr.state = 'RECOVERING';
    recoveryMgr.isRecovering = true;

    let snapshotEmitted = false;
    recoveryMgr.onTelemetry(() => {
      snapshotEmitted = true;
    });

    await recoveryMgr.executeRecovery();

    // 1. Snapshot rejected
    assert.equal(snapshotEmitted, false, 'Snapshot must not be emitted when temporal drift exceeds tolerance');

    // 2. Sequence floor unchanged
    assert.equal(mockWs.lastSequenceNumber, 10, 'Sequence floor must NOT be advanced when drift exceeds tolerance');

    // 3. State transitions to RECOVERY_ERROR
    assert.equal(recoveryMgr.state, 'RECOVERY_ERROR', 'State must transition to RECOVERY_ERROR on drift failure');
    assert.equal(recoveryMgr.persistentRecoveryFailures, 1, 'Must increment persistent recovery failures');

    mockWs.disconnect();
    recoveryMgr.destroy();
  });

  // =========================================================================
  // Scenario 23: F-SYNC-01 Temporal Drift Within Threshold Accepts Snapshot
  // =========================================================================
  test('23. F-SYNC-01: Temporal Drift Within Threshold Accepts Snapshot and Advances Sequence Floor', async () => {
    let call = 0;
    const mockApi = {
      getSimulationStatus: async () => {
        call++;
        return {
          run_uuid: 'session_sync',
          sequence_number: call === 1 ? 10 : 15,
          simulation_time: call === 1 ? 100.0 : 101.0,
          status: 'RUNNING',
        };
      },
      // live returns simulation_time with 0.8s drift (< 2.0s)
      getTrafficLive: async () => ({
        simulation_time: 100.8,
        junctions: { J1: { count: 8 } },
      }),
      // signals returns simulation_time with 1.1s drift (< 2.0s)
      getSignals: async () => ({
        simulation_time: 101.1,
        signals: { J1: { phase: 1 } },
      }),
      getTrafficMetrics: async () => ({}),
      getEmergencies: async () => [],
      getRisks: async () => null,
      getExperimentsCompare: async () => null,
      getHealth: async () => ({}),
    };

    const mockWs = new TrafficWebSocket({ customUrl: 'ws://mock' });
    mockWs.lastSequenceNumber = 10;
    mockWs.sessionUuid = 'session_sync';

    const recoveryMgr = new SnapshotRecoveryManager({
      api: mockApi,
      trafficWS: mockWs,
      maxDriftToleranceS: 2.0,
    });

    recoveryMgr.state = 'RECOVERING';
    recoveryMgr.isRecovering = true;

    let snapshotEmitted = null;
    recoveryMgr.onTelemetry((s) => {
      snapshotEmitted = s;
    });

    await recoveryMgr.executeRecovery();

    // 1. Snapshot accepted
    assert.ok(snapshotEmitted !== null, 'Snapshot must be emitted when drift is within tolerance');
    assert.equal(snapshotEmitted.junctions.J1.count, 8);

    // 2. Sequence floor advanced to post-fence sequence (15)
    assert.equal(mockWs.lastSequenceNumber, 15, 'Sequence floor must advance to 15');

    // 3. State transitions to SYNCHRONIZED
    assert.equal(recoveryMgr.state, 'SYNCHRONIZED', 'State must transition to SYNCHRONIZED');
    assert.equal(recoveryMgr.persistentRecoveryFailures, 0, 'Persistent failures must be 0');

    mockWs.disconnect();
    recoveryMgr.destroy();
  });

  // =========================================================================
  // Phase 2B-3D Test 1.1: Rapid Frontend Lifecycle Churn
  // =========================================================================
  test('24. Phase 2B-3D Test 1.1: Rapid Frontend Lifecycle Churn (50 Iterations)', async () => {
    let sockets = [];
    class ChurnSocket extends MockWebSocket {
      constructor(url) {
        super(url);
        sockets.push(this);
      }
    }

    const wsClient = new TrafficWebSocket({
      WebSocketClass: ChurnSocket,
      url: 'ws://test',
      teardownTimeoutMs: 100,
    });

    for (let i = 0; i < 50; i++) {
      wsClient.connect();
      wsClient.disconnect();
    }

    // Allow event loop and teardown timeouts to settle
    await new Promise((r) => setTimeout(r, 150));

    assert.equal(wsClient.ws, null, 'ws instance must be null post-churn');
    assert.equal(wsClient.status, 'DISCONNECTED', 'Status must be DISCONNECTED');
    assert.equal(wsClient.isExplicitDisconnect, true, 'isExplicitDisconnect must remain true');
    assert.equal(wsClient.activeConnectPromise, null, 'activeConnectPromise must be null');
    assert.equal(wsClient.reconnectTimeout, null, 'No pending reconnect timeouts');
  });

  // =========================================================================
  // Phase 2B-3D Test 4.1: Implementation-Derived Retry-Delay Bounds with Jitter
  // =========================================================================
  test('25. Phase 2B-3D Test 4.1: Implementation-Derived Retry-Delay Bounds with Jitter', () => {
    const wsClient = new TrafficWebSocket({
      baseDelayMs: 1000,
      maxDelayMs: 15000,
      backoffFactor: 1.5,
      jitterRatio: 0.2, // +/- 20%
    });

    // Exact expected theoretical bounds for k in 0..10
    const expectedBounds = [
      { k: 0, min: 800, max: 1200 },
      { k: 1, min: 1200, max: 1800 },
      { k: 2, min: 1800, max: 2700 },
      { k: 3, min: 2700, max: 4050 },
      { k: 4, min: 4050, max: 6075 },
      { k: 5, min: 6075, max: 9112.5 },
      { k: 6, min: 9112.5, max: 13668.75 },
      { k: 7, min: 12000, max: 18000 },
      { k: 8, min: 12000, max: 18000 },
      { k: 9, min: 12000, max: 18000 },
      { k: 10, min: 12000, max: 18000 },
    ];

    for (const { k, min, max } of expectedBounds) {
      wsClient.reconnectAttempts = k;
      const samples = [];
      for (let i = 0; i < 100; i++) {
        const delay = wsClient._calculateBackoffDelay();
        samples.push(delay);
        assert.ok(
          delay >= min && delay <= max,
          `Attempt ${k} sample ${delay} out of bounds [${min}, ${max}]`
        );
      }
      // Verify variance (pseudo-random distribution)
      const minSample = Math.min(...samples);
      const maxSample = Math.max(...samples);
      assert.ok(maxSample > minSample, `Attempt ${k} must show randomized jitter variance`);
    }
  });

  // =========================================================================
  // Phase 2B-3D Test 5.1: Exact Sequence Number Injection Matrix
  // =========================================================================
  test('26. Phase 2B-3D Test 5.1: Exact Sequence Number Injection Matrix (14 Frames)', () => {
    const wsClient = new TrafficWebSocket({ customUrl: 'ws://mock' });
    wsClient.currentSessionUuid = 'UUID_ACTIVE';
    wsClient.lastSequenceNumber = 100;
    wsClient.previousSessions.add('UUID_OLD');

    const injectionMatrix = [
      { frame: { session_uuid: 'UUID_OLD', sequence_number: 105 }, expectAccepted: false, expectFloor: 100 },
      { frame: { session_uuid: 'UUID_OLD', sequence_number: 90 }, expectAccepted: false, expectFloor: 100 },
      { frame: { session_uuid: 'UUID_ACTIVE', sequence_number: 50 }, expectAccepted: false, expectFloor: 100 },
      { frame: { session_uuid: 'UUID_ACTIVE', sequence_number: 99 }, expectAccepted: false, expectFloor: 100 },
      { frame: { session_uuid: 'UUID_ACTIVE', sequence_number: 100 }, expectAccepted: false, expectFloor: 100 },
      { frame: { session_uuid: 'UUID_ACTIVE', sequence_number: 105 }, expectAccepted: true, expectFloor: 105 },
      { frame: { session_uuid: 'UUID_ACTIVE', sequence_number: 102 }, expectAccepted: false, expectFloor: 105 },
      { frame: { session_uuid: 'UUID_ACTIVE', sequence_number: 104 }, expectAccepted: false, expectFloor: 105 },
      { frame: { session_uuid: 'UUID_ACTIVE', sequence_number: 105 }, expectAccepted: false, expectFloor: 105 },
      { frame: { session_uuid: 'UUID_ACTIVE', sequence_number: 108 }, expectAccepted: true, expectFloor: 108 },
      { frame: { session_uuid: 'UUID_ACTIVE', sequence_number: 106 }, expectAccepted: false, expectFloor: 108 },
      { frame: { session_uuid: 'UUID_ACTIVE', sequence_number: 108 }, expectAccepted: false, expectFloor: 108 },
      { frame: { session_uuid: 'UUID_ACTIVE', sequence_number: 110 }, expectAccepted: true, expectFloor: 110 },
      { frame: { session_uuid: 'UUID_OLD', sequence_number: 115 }, expectAccepted: false, expectFloor: 110 },
    ];

    let acceptedCount = 0;
    let rejectedCount = 0;

    injectionMatrix.forEach(({ frame, expectAccepted, expectFloor }, idx) => {
      const accepted = wsClient.processMessage(frame);
      if (accepted) acceptedCount++;
      else rejectedCount++;

      assert.equal(
        accepted,
        expectAccepted,
        `Frame ${idx + 1} (seq ${frame.sequence_number}, session ${frame.session_uuid}) expected accepted=${expectAccepted}`
      );
      assert.equal(
        wsClient.lastSequenceNumber,
        expectFloor,
        `Frame ${idx + 1} expected floor=${expectFloor}`
      );
    });

    assert.equal(acceptedCount, 3, 'Exactly 3 frames must be accepted');
    assert.equal(rejectedCount, 11, 'Exactly 11 frames must be rejected');
    assert.equal(wsClient.lastSequenceNumber, 110, 'Final sequence floor must be strictly 110');
  });

  // =========================================================================
  // Phase 2B-3D Test 6.1: Exact Sequence Floors During Overflow and Fresh Fetch
  // =========================================================================
  test('27. Phase 2B-3D Test 6.1: Exact Sequence Floors During Overflow and Fresh Fetch', async () => {
    let statusCall = 0;
    const mockApi = {
      getSimulationStatus: async () => {
        statusCall++;
        return {
          run_uuid: 'session_overflow_test',
          sequence_number: statusCall === 1 ? 60 : 135,
          simulation_time: 100.0,
          status: 'RUNNING',
        };
      },
      getTrafficLive: async () => ({ simulation_time: 100.0, junctions: { J1: { count: 10 } } }),
      getSignals: async () => ({ simulation_time: 100.0, signals: {} }),
      getTrafficMetrics: async () => ({}),
      getEmergencies: async () => [],
      getRisks: async () => null,
      getExperimentsCompare: async () => null,
      getHealth: async () => ({}),
    };

    const mockWs = new TrafficWebSocket({ customUrl: 'ws://mock' });
    mockWs.currentSessionUuid = 'session_overflow_test';
    mockWs.lastSequenceNumber = 50; // Initial sequence floor

    const recoveryMgr = new SnapshotRecoveryManager({
      api: mockApi,
      trafficWS: mockWs,
      bufferCapacity: 64,
    });

    recoveryMgr.state = 'RECOVERING';
    recoveryMgr.isRecovering = true;

    // Simulate 70 in-flight frames (seq 61 to 130) arriving before pre-flight status resolves
    for (let s = 61; s <= 130; s++) {
      recoveryMgr.handleIncomingTelemetry({
        type: 'TRAFFIC_UPDATE',
        session_uuid: 'session_overflow_test',
        sequence_number: s,
      });
    }

    assert.equal(recoveryMgr.hasBufferOverflowed, true, 'Buffer must be marked as overflowed');
    assert.equal(recoveryMgr.recoveryBuffer.length, 64, 'Buffer capped at 64');

    // Assert that prior to recovery resolution, sequence floor remains strictly 50
    assert.equal(mockWs.lastSequenceNumber, 50, 'Sequence floor must remain strictly 50 before adoption');

    await recoveryMgr.executeRecovery();

    // After overflow recovery, unapplied frames (61-130) were purged, and floor advances to statusCall 2 (135)
    assert.equal(recoveryMgr.state, 'SYNCHRONIZED', 'State must become SYNCHRONIZED');
    assert.equal(mockWs.lastSequenceNumber, 135, 'Sequence floor must advance strictly to authoritative post-flight sequence 135');
    assert.ok(statusCall >= 3, 'Fresh recovery must re-query status across fences');
    assert.equal(recoveryMgr.overflowRetryCount, 0, 'overflowRetryCount resets to 0 upon reaching SYNCHRONIZED');

    mockWs.disconnect();
    recoveryMgr.destroy();
  });

  // =========================================================================
  // Phase 2B-3D Test 7.1: Persistent Failure Budget Exhaustion & Circuit Breaker
  // =========================================================================
  test('28. Phase 2B-3D Test 7.1: Persistent Failure Budget Exhaustion & Circuit Breaker', async () => {
    const failingApi = {
      getSimulationStatus: async () => {
        throw new Error('503 Service Unavailable');
      },
      getTrafficLive: async () => ({}),
      getSignals: async () => ({}),
    };

    const mockWs = new TrafficWebSocket({ customUrl: 'ws://mock' });
    const recoveryMgr = new SnapshotRecoveryManager({
      api: failingApi,
      trafficWS: mockWs,
      maxPersistentFailures: 5,
    });

    // 5 consecutive failure cycles
    for (let i = 1; i <= 5; i++) {
      recoveryMgr.state = 'RECOVERING';
      recoveryMgr.isRecovering = true;
      await recoveryMgr.executeRecovery();
      if (i < 5) {
        assert.equal(recoveryMgr.state, 'RECOVERY_ERROR');
        assert.equal(recoveryMgr.persistentRecoveryFailures, i);
      }
    }

    assert.equal(recoveryMgr.state, 'OFFLINE_SYNC_FAILED', 'Must transition to OFFLINE_SYNC_FAILED at 5 failures');
    assert.equal(recoveryMgr.persistentRecoveryFailures, 5);
    assert.equal(mockWs.status, 'DISCONNECTED', 'Must disconnect WebSocket upon persistent failure exhaustion');

    mockWs.disconnect();
    recoveryMgr.destroy();
  });

  // =========================================================================
  // Phase 2B-3D Test 7.2: Recovery Failure Budget Reset Strictly on Validated Recovery
  // =========================================================================
  test('29. Phase 2B-3D Test 7.2: Recovery Failure Budget Reset Strictly on Validated Recovery', async () => {
    let mockMode = 'FAIL'; // 'FAIL' | 'SUCCESS'
    const mockApi = {
      getSimulationStatus: async () => {
        if (mockMode === 'FAIL') throw new Error('500 Internal Server Error');
        return { run_uuid: 'session_reset_test', sequence_number: 20, simulation_time: 50.0, status: 'RUNNING' };
      },
      getTrafficLive: async () => ({ simulation_time: 50.0, junctions: {} }),
      getSignals: async () => ({ simulation_time: 50.0, signals: {} }),
      getTrafficMetrics: async () => ({}),
      getEmergencies: async () => [],
      getRisks: async () => null,
      getExperimentsCompare: async () => null,
      getHealth: async () => ({}),
    };

    let testSocket = null;
    class ManualTestSocket extends MockWebSocket {
      constructor(url) {
        super(url);
        testSocket = this;
      }
    }

    const mockWs = new TrafficWebSocket({
      WebSocketClass: ManualTestSocket,
      url: 'ws://mock',
    });

    const recoveryMgr = new SnapshotRecoveryManager({
      api: mockApi,
      trafficWS: mockWs,
      maxPersistentFailures: 5,
    });

    recoveryMgr.init();

    // Trigger failure budget exhaustion to enter OFFLINE_SYNC_FAILED
    for (let i = 0; i < 5; i++) {
      recoveryMgr.state = 'RECOVERING';
      recoveryMgr.isRecovering = true;
      await recoveryMgr.executeRecovery();
    }
    assert.equal(recoveryMgr.state, 'OFFLINE_SYNC_FAILED');
    assert.equal(recoveryMgr.persistentRecoveryFailures, 5);
    assert.equal(mockWs.status, 'DISCONNECTED');

    // Operator invokes manualRetrySync while backend still failing
    recoveryMgr.manualRetrySync();
    assert.equal(recoveryMgr.state, 'CONNECTING');

    // Allow _executeConnect to attempt socket instantiation
    await new Promise((r) => setTimeout(r, 10));

    // DEFECT-2B-3D-01: In production, mockWs._executeConnect() aborts at line 198
    // because isExplicitDisconnect is true from the preceding disconnect(), preventing
    // socket construction during manual retry.
    if (!testSocket) {
      assert.fail('DEFECT-2B-3D-01: manualRetrySync() failed to construct replacement WebSocket because isExplicitDisconnect remains true after disconnect()');
    }

    // Connect socket
    testSocket.triggerOpen();
    assert.equal(mockWs.status, 'CONNECTED');

    // Allow async executeRecovery to settle
    await new Promise((r) => setTimeout(r, 20));

    // Intermediate failure with budget already exhausted: maintains OFFLINE_SYNC_FAILED, persistentFailures increments from 5 to 6
    assert.equal(recoveryMgr.state, 'OFFLINE_SYNC_FAILED', 'Intermediate failure with budget exhausted must maintain OFFLINE_SYNC_FAILED');
    assert.equal(recoveryMgr.persistentRecoveryFailures, 6, 'Persistent failures must increment to 6 without premature reset');

    // Now restore backend to healthy
    mockMode = 'SUCCESS';
    recoveryMgr.state = 'RECOVERING';
    recoveryMgr.isRecovering = true;
    await recoveryMgr.executeRecovery();

    // Validated recovery completed
    assert.equal(recoveryMgr.state, 'SYNCHRONIZED', 'Must reach SYNCHRONIZED');
    assert.equal(
      recoveryMgr.persistentRecoveryFailures,
      0,
      'Persistent failures must reset to 0 strictly upon validated synchronized recovery'
    );

    mockWs.disconnect();
    recoveryMgr.destroy();
  });

  // =========================================================================
  // Phase 2B-3D Test 8.1: Mid-Recovery Session Boundary Cross
  // =========================================================================
  test('30. Phase 2B-3D Test 8.1: Mid-Recovery Session Boundary Cross Rejects Composite Snapshot', async () => {
    let call = 0;
    const mockApi = {
      getSimulationStatus: async () => {
        call++;
        return {
          run_uuid: call === 1 ? 'SESSION_ALPHA' : 'SESSION_BETA',
          sequence_number: call === 1 ? 10 : 1,
          simulation_time: 100.0,
          status: 'RUNNING',
        };
      },
      getTrafficLive: async () => ({ simulation_time: 100.0, junctions: { J1: { count: 5 } } }),
      getSignals: async () => ({ simulation_time: 100.0, signals: {} }),
      getTrafficMetrics: async () => ({}),
      getEmergencies: async () => [],
      getRisks: async () => null,
      getExperimentsCompare: async () => null,
      getHealth: async () => ({}),
    };

    const mockWs = new TrafficWebSocket({ customUrl: 'ws://mock' });
    const recoveryMgr = new SnapshotRecoveryManager({ api: mockApi, trafficWS: mockWs });

    recoveryMgr.state = 'RECOVERING';
    recoveryMgr.isRecovering = true;

    let emittedTelemetry = null;
    recoveryMgr.onTelemetry((d) => (emittedTelemetry = d));

    await recoveryMgr.executeRecovery();

    // Mismatched session should reject composite snapshot
    assert.equal(emittedTelemetry, null, 'Must NOT emit composite snapshot across session boundary');
    assert.equal(recoveryMgr.state, 'RECOVERY_ERROR', 'State must transition to RECOVERY_ERROR');
    assert.equal(recoveryMgr.persistentRecoveryFailures, 1, 'Increments failure counter');

    mockWs.disconnect();
    recoveryMgr.destroy();
  });

  // =========================================================================
  // Phase 2B-3D Test 8.2: Frontend Unmount During Active Recovery
  // =========================================================================
  test('31. Phase 2B-3D Test 8.2: Frontend Unmount During Active Recovery Discards Stale Async Work', async () => {
    let resolveLive;
    const delayedLivePromise = new Promise((resolve) => (resolveLive = resolve));

    const mockApi = {
      getSimulationStatus: async () => ({
        run_uuid: 'session_unmount_test',
        sequence_number: 100,
        simulation_time: 45.0,
        status: 'RUNNING',
      }),
      getTrafficLive: async () => {
        await delayedLivePromise;
        return { simulation_time: 45.0, junctions: { J1: { count: 99 } } };
      },
      getSignals: async () => ({ simulation_time: 45.0, signals: {} }),
      getTrafficMetrics: async () => ({}),
      getEmergencies: async () => [],
      getRisks: async () => null,
      getExperimentsCompare: async () => null,
      getHealth: async () => ({}),
    };

    const mockWs = new TrafficWebSocket({ customUrl: 'ws://mock' });
    mockWs.lastSequenceNumber = 40; // Initial sequence floor
    mockWs.currentSessionUuid = 'session_unmount_test';

    const recoveryMgr = new SnapshotRecoveryManager({ api: mockApi, trafficWS: mockWs });
    recoveryMgr.state = 'RECOVERING';
    recoveryMgr.isRecovering = true;

    let telemetryDispatched = null;
    recoveryMgr.onTelemetry((d) => (telemetryDispatched = d));

    // 1. Start recovery (suspends awaiting delayedLivePromise)
    const recoveryPromise = recoveryMgr.executeRecovery();

    // 2. Simulate component unmount while REST query is in-flight
    mockWs.disconnect();
    recoveryMgr.destroy();

    assert.equal(recoveryMgr.recoveryCancelled, true, 'recoveryCancelled must be true');
    assert.equal(mockWs.isExplicitDisconnect, true, 'isExplicitDisconnect must be true');
    assert.equal(mockWs.ws, null, 'ws instance must be null');

    // 3. Resolve the delayed REST response after unmount
    resolveLive();
    await recoveryPromise;

    // 4. Verify post-unmount isolation
    assert.equal(telemetryDispatched, null, 'No telemetry must be dispatched post-unmount');
    assert.notEqual(recoveryMgr.state, 'SYNCHRONIZED', 'State must NEVER become SYNCHRONIZED post-unmount');
    assert.equal(mockWs.lastSequenceNumber, 40, 'Sequence floor must remain strictly at 40');
    assert.equal(mockWs.ws, null, 'No replacement WebSocket constructed post-unmount');
  });

  // =========================================================================
  // DEFECT-2B-3D-01 Remediation Suite
  // =========================================================================

  // Test 32: Requirement 1 - Explicit disconnect followed by intentional connect successfully creates a socket
  test('32. DEFECT-2B-3D-01: Explicit Disconnect Followed by Intentional Connect Successfully Creates Socket', async () => {
    let sockets = [];
    class ControlledSocket extends MockWebSocket {
      constructor(url) {
        super(url);
        sockets.push(this);
      }
    }

    const wsClient = new TrafficWebSocket({
      WebSocketClass: ControlledSocket,
      url: 'ws://test-broker/ws',
    });

    // Initial connection
    await wsClient.connect();
    assert.equal(sockets.length, 1);
    sockets[0].triggerOpen();
    assert.equal(wsClient.status, 'CONNECTED');

    // Explicit disconnect
    wsClient.disconnect();
    assert.equal(wsClient.status, 'DISCONNECTED');
    assert.equal(wsClient.isExplicitDisconnect, true);
    assert.equal(wsClient.ws, null);
    assert.equal(wsClient.activeConnectPromise, null);

    // Intentional reconnect authorized: Case B
    const connectPromise = wsClient.connect();
    assert.equal(wsClient.isExplicitDisconnect, false, 'isExplicitDisconnect must be reset on intentional connect');
    await connectPromise;

    // Verify replacement socket constructed
    assert.equal(sockets.length, 2, 'Exactly one replacement socket must be created');
    assert.equal(wsClient.ws, sockets[1], 'ws reference must point to replacement socket');
    assert.equal(wsClient.status, 'CONNECTING');

    sockets[1].triggerOpen();
    assert.equal(wsClient.status, 'CONNECTED');

    wsClient.disconnect();
  });

  // Test 33: Requirement 2 - Disconnect during a pending CLOSING wait still prevents socket construction (Case A)
  test('33. DEFECT-2B-3D-01: Disconnect During Pending CLOSING Wait Prevents Replacement Construction (Case A)', async () => {
    let sockets = [];
    class ControlledSocket extends MockWebSocket {
      constructor(url) {
        super(url);
        sockets.push(this);
      }
    }

    const wsClient = new TrafficWebSocket({
      WebSocketClass: ControlledSocket,
      url: 'ws://test-broker/ws',
      teardownTimeoutMs: 500,
    });

    await wsClient.connect();
    assert.equal(sockets.length, 1);
    const sock1 = sockets[0];
    sock1.triggerOpen();

    // 1. Existing socket enters CLOSING
    sock1.readyState = MockWebSocket.CLOSING;

    // 2. Start connect() - awaits teardown
    const connectPromise = wsClient.connect();

    // 3. Disconnect while teardown wait is pending
    wsClient.disconnect();
    assert.equal(wsClient.isExplicitDisconnect, true, 'isExplicitDisconnect must be true after disconnect()');

    // 4. Resolve the CLOSING wait
    sock1.triggerClose(1000, 'Teardown finished');
    await connectPromise;

    // 5. Verify NO replacement socket constructed
    assert.equal(sockets.length, 1, 'Must NOT construct a replacement WebSocket');
    assert.equal(wsClient.ws, null, 'ws instance must remain null');
    assert.equal(wsClient.status, 'DISCONNECTED', 'Status must remain DISCONNECTED');
    assert.equal(wsClient.isExplicitDisconnect, true, 'isExplicitDisconnect must remain true');
  });

  // Test 34: Requirement 3 - Disconnect followed by two concurrent intentional connect calls creates exactly one replacement socket
  test('34. DEFECT-2B-3D-01: Disconnect Followed by Concurrent Intentional Connects Creates Exactly One Socket', async () => {
    let sockets = [];
    class ControlledSocket extends MockWebSocket {
      constructor(url) {
        super(url);
        sockets.push(this);
      }
    }

    const wsClient = new TrafficWebSocket({
      WebSocketClass: ControlledSocket,
      url: 'ws://test-broker/ws',
    });

    await wsClient.connect();
    assert.equal(sockets.length, 1);
    sockets[0].triggerOpen();

    wsClient.disconnect();
    assert.equal(wsClient.isExplicitDisconnect, true);
    assert.equal(sockets.length, 1);

    // Two concurrent intentional connect calls
    const p1 = wsClient.connect();
    const p2 = wsClient.connect();

    // Verify p2 joined p1
    assert.strictEqual(p1, p2, 'Concurrent connect calls must share the exact same activeConnectPromise');
    assert.equal(wsClient.isExplicitDisconnect, false, 'isExplicitDisconnect must be false for authorized attempt');

    await Promise.all([p1, p2]);

    assert.equal(sockets.length, 2, 'Exactly one replacement socket must be created');
    assert.equal(wsClient.ws, sockets[1]);
    assert.equal(wsClient.activeConnectPromise, null, 'activeConnectPromise must be null after completion');

    wsClient.disconnect();
  });

  // Test 35: Requirement 4 - Obsolete pending connect attempt cannot interfere with a newer authorized connect attempt
  test('35. DEFECT-2B-3D-01: Obsolete Pending Connect Cannot Interfere with Newer Authorized Connect', async () => {
    let sockets = [];
    let resolveTeardown1 = null;

    class ControlledSocket extends MockWebSocket {
      constructor(url) {
        super(url);
        sockets.push(this);
      }
    }

    const wsClient = new TrafficWebSocket({
      WebSocketClass: ControlledSocket,
      url: 'ws://test-broker/ws',
      teardownTimeoutMs: 1000,
    });

    // Custom teardown hook for deterministic control of Attempt 1 wait
    const origWaitForClosed = wsClient._waitForSocketClosed.bind(wsClient);
    let waitCount = 0;
    wsClient._waitForSocketClosed = (socket, timeoutMs) => {
      waitCount++;
      if (waitCount === 1) {
        return new Promise((resolve) => {
          resolveTeardown1 = resolve;
        });
      }
      return origWaitForClosed(socket, timeoutMs);
    };

    await wsClient.connect();
    assert.equal(sockets.length, 1);
    const sock1 = sockets[0];
    sock1.triggerOpen();

    // 1. Socket enters CLOSING
    sock1.readyState = MockWebSocket.CLOSING;

    // 2. Attempt 1 begins and suspends in _waitForSocketClosed
    const p1 = wsClient.connect();

    // 3. User cancels Attempt 1 via disconnect()
    wsClient.disconnect();
    assert.equal(wsClient.isExplicitDisconnect, true);

    // 4. User initiates fresh intentional Attempt 2 while S1 is still CLOSING
    const p2 = wsClient.connect();
    assert.equal(wsClient.isExplicitDisconnect, false);

    // 5. Now resolve Attempt 1's teardown
    resolveTeardown1(true);
    await p1; // Attempt 1 completes and aborts due to token mismatch

    // Complete S1 teardown for Attempt 2
    sock1.triggerClose(1000, 'Teardown final');
    await p2;

    // Verify Attempt 1 did not interfere and Attempt 2 created replacement socket
    assert.equal(sockets.length, 2, 'Only Attempt 2 constructs replacement socket');
    assert.equal(wsClient.ws, sockets[1]);
    assert.equal(wsClient.activeConnectPromise, null);

    wsClient.disconnect();
  });

  // Test 36: Requirement 5 - manualRetrySync() after OFFLINE_SYNC_FAILED initiates a new connection
  test('36. DEFECT-2B-3D-01: manualRetrySync() after OFFLINE_SYNC_FAILED Initiates New Connection and Recovers', async () => {
    let canRecover = false;
    const mockApi = {
      getSimulationStatus: async () => {
        if (!canRecover) throw new Error('503 Service Unavailable');
        return { run_uuid: 'session_retry_ok', sequence_number: 10, simulation_time: 25.0, status: 'RUNNING' };
      },
      getTrafficLive: async () => ({ simulation_time: 25.0, junctions: {} }),
      getSignals: async () => ({ simulation_time: 25.0, signals: {} }),
      getTrafficMetrics: async () => ({}),
      getEmergencies: async () => [],
      getRisks: async () => null,
      getExperimentsCompare: async () => null,
      getHealth: async () => ({}),
    };

    let sockets = [];
    class ControlledSocket extends MockWebSocket {
      constructor(url) {
        super(url);
        sockets.push(this);
      }
    }

    const mockWs = new TrafficWebSocket({
      WebSocketClass: ControlledSocket,
      url: 'ws://mock-broker',
    });

    const recoveryMgr = new SnapshotRecoveryManager({
      api: mockApi,
      trafficWS: mockWs,
      maxPersistentFailures: 3,
    });
    recoveryMgr.init();

    // 1. Exhaust failure budget to enter OFFLINE_SYNC_FAILED
    for (let i = 0; i < 3; i++) {
      recoveryMgr.state = 'RECOVERING';
      recoveryMgr.isRecovering = true;
      await recoveryMgr.executeRecovery();
    }

    assert.equal(recoveryMgr.state, 'OFFLINE_SYNC_FAILED');
    assert.equal(mockWs.status, 'DISCONNECTED');
    assert.equal(mockWs.isExplicitDisconnect, true);
    assert.equal(sockets.length, 0);

    // 2. Operator invokes manualRetrySync()
    canRecover = true;
    recoveryMgr.manualRetrySync();

    assert.equal(recoveryMgr.state, 'CONNECTING');
    assert.equal(mockWs.isExplicitDisconnect, false, 'isExplicitDisconnect must be false during manualRetrySync');

    // Allow connect to instantiate socket
    await new Promise((r) => setTimeout(r, 10));

    assert.equal(sockets.length, 1, 'manualRetrySync must construct replacement WebSocket');
    const newSock = sockets[0];

    // Socket opens
    newSock.triggerOpen();
    assert.equal(mockWs.status, 'CONNECTED');

    // Allow recovery execution
    await new Promise((r) => setTimeout(r, 30));

    assert.equal(recoveryMgr.state, 'SYNCHRONIZED', 'Must successfully reach SYNCHRONIZED');
    assert.equal(recoveryMgr.persistentRecoveryFailures, 0);

    mockWs.disconnect();
    recoveryMgr.destroy();
  });

  // Test 37: Requirement 7 - Promise-identity cleanup behavior cannot clear a newer in-flight connection promise
  test('37. DEFECT-2B-3D-01: Promise-Identity Cleanup Cannot Clear Newer In-Flight Connection Promise', async () => {
    let sockets = [];
    let resolveTeardown1 = null;

    class ControlledSocket extends MockWebSocket {
      constructor(url) {
        super(url);
        sockets.push(this);
      }
    }

    const wsClient = new TrafficWebSocket({
      WebSocketClass: ControlledSocket,
      url: 'ws://test-broker/ws',
      teardownTimeoutMs: 1000,
    });

    // Deferred teardown hook
    wsClient._waitForSocketClosed = (socket, timeoutMs) => {
      return new Promise((resolve) => {
        resolveTeardown1 = resolve;
      });
    };

    await wsClient.connect();
    assert.equal(sockets.length, 1);
    const sock1 = sockets[0];
    sock1.triggerOpen();

    // 1. S1 in CLOSING
    sock1.readyState = MockWebSocket.CLOSING;

    // 2. Start Attempt 1
    const p1 = wsClient.connect();
    assert.strictEqual(wsClient.activeConnectPromise, p1, 'activeConnectPromise must be p1');

    // 3. User disconnects: cancels Attempt 1 and clears activeConnectPromise
    wsClient.disconnect();
    assert.equal(wsClient.activeConnectPromise, null);

    // 4. User starts fresh intentional Attempt 2 while another socket is CLOSING
    let resolveTeardown2 = null;
    wsClient._waitForSocketClosed = (socket, timeoutMs) => {
      return new Promise((resolve) => {
        resolveTeardown2 = resolve;
      });
    };
    const sock2 = new ControlledSocket('ws://test-broker/ws');
    sock2.readyState = MockWebSocket.CLOSING;
    wsClient.ws = sock2;

    const p2 = wsClient.connect();
    assert.strictEqual(wsClient.activeConnectPromise, p2, 'activeConnectPromise must be p2');

    // 5. Now resolve Attempt 1's teardown
    resolveTeardown1(false);
    await p1;

    // 6. Verify Attempt 1's .finally() did NOT clear Attempt 2's activeConnectPromise!
    assert.strictEqual(
      wsClient.activeConnectPromise,
      p2,
      'Attempt 1 settlement MUST NOT clear newer activeConnectPromise (p2)'
    );

    // 7. Resolve Attempt 2's teardown
    sock2.readyState = MockWebSocket.CLOSED;
    resolveTeardown2(true);
    await p2;
    assert.equal(wsClient.activeConnectPromise, null, 'activeConnectPromise cleared only after p2 completes');

    wsClient.disconnect();
  });

  // =========================================================================
  // Phase 2B-3D Final Check: Concurrent Manual Recovery & Failure Budget Safety
  // =========================================================================
  test('38. Phase 2B-3D Final Check: Concurrent manualRetrySync Calls Are Serialized and Safe', async () => {
    let activeRestCalls = 0;
    let maxConcurrentRestCalls = 0;
    let shouldFailRecovery = true;
    let resolveFirstStatus = null;
    let resolveSecondStatus = null;
    let callIndex = 0;

    const mockApi = {
      getSimulationStatus: async () => {
        callIndex++;
        activeRestCalls++;
        maxConcurrentRestCalls = Math.max(maxConcurrentRestCalls, activeRestCalls);

        if (callIndex === 1) {
          await new Promise((r) => (resolveFirstStatus = r));
        } else if (callIndex === 2) {
          // Keep second recovery pending to verify persistent counter while pending
          await new Promise((r) => (resolveSecondStatus = r));
        }

        activeRestCalls--;

        if (shouldFailRecovery) {
          throw new Error('Controlled Recovery Failure 503');
        }

        return {
          run_uuid: 'session_concurrent_manual_check',
          sequence_number: 100,
          simulation_time: 50.0,
          status: 'RUNNING',
        };
      },
      getTrafficLive: async () => ({ simulation_time: 50.0, junctions: { J1: { count: 12 } } }),
      getSignals: async () => ({ simulation_time: 50.0, signals: {} }),
      getTrafficMetrics: async () => ({}),
      getEmergencies: async () => [],
      getRisks: async () => null,
      getExperimentsCompare: async () => null,
      getHealth: async () => ({}),
    };

    let sockets = [];
    class ControlledSocket extends MockWebSocket {
      constructor(url) {
        super(url);
        sockets.push(this);
      }
    }

    const mockWs = new TrafficWebSocket({
      WebSocketClass: ControlledSocket,
      url: 'ws://mock-broker',
    });

    const recoveryMgr = new SnapshotRecoveryManager({
      api: mockApi,
      trafficWS: mockWs,
      maxPersistentFailures: 3,
    });
    recoveryMgr.init();

    // 1. Put recovery manager into OFFLINE_SYNC_FAILED
    // 2. Set persistentRecoveryFailures = 3
    recoveryMgr.state = 'OFFLINE_SYNC_FAILED';
    recoveryMgr.persistentRecoveryFailures = 3;
    recoveryMgr.retryAttempt = 2; // Seed transient counter
    recoveryMgr.overflowRetryCount = 1; // Seed transient counter
    mockWs.disconnect();

    assert.equal(recoveryMgr.state, 'OFFLINE_SYNC_FAILED');
    assert.equal(mockWs.status, 'DISCONNECTED');
    assert.equal(mockWs.isExplicitDisconnect, true);
    assert.equal(sockets.length, 0);

    // 3. Invoke three concurrent manual retry calls
    recoveryMgr.manualRetrySync();
    recoveryMgr.manualRetrySync();
    recoveryMgr.manualRetrySync();

    // Verify transient counters reset independently while persistent failure budget remains 3
    assert.equal(recoveryMgr.state, 'CONNECTING');
    assert.equal(mockWs.isExplicitDisconnect, false);
    assert.equal(recoveryMgr.retryAttempt, 0, 'Transient retryAttempt must reset to 0');
    assert.equal(recoveryMgr.overflowRetryCount, 0, 'Transient overflowRetryCount must reset to 0');
    assert.equal(recoveryMgr.hasBufferOverflowed, false);
    assert.equal(recoveryMgr.recoveryBuffer.length, 0);

    // 5. Verify the persistent counter remains 3 before snapshot validation
    assert.equal(
      recoveryMgr.persistentRecoveryFailures,
      3,
      'Persistent counter must remain strictly 3 before snapshot validation'
    );

    // Allow connect() microtasks to run
    await new Promise((r) => setTimeout(r, 10));

    // 4. Verify exactly one replacement WebSocket is constructed
    assert.equal(sockets.length, 1, 'Exactly one replacement WebSocket must be constructed');
    const sock1 = sockets[0];

    // Trigger open on the replacement socket
    sock1.triggerOpen();
    assert.equal(mockWs.status, 'CONNECTED');

    // Allow startRecovery to run and enter getSimulationStatus (suspended on resolveFirstStatus)
    await new Promise((r) => setTimeout(r, 10));

    // Verify recovery operation is active
    assert.equal(recoveryMgr.isRecovering, true, 'isRecovering must be true');
    assert.equal(recoveryMgr.state, 'RECOVERING');

    // Separate assertion: manual retry during an already-running recovery
    // Seed the recovery buffer with known frames
    recoveryMgr.recoveryBuffer = [
      { type: 'TRAFFIC_UPDATE', sequence_number: 101, session_uuid: 'session_concurrent_manual_check' }
    ];
    // Invoke manualRetrySync while isRecovering === true
    recoveryMgr.manualRetrySync();

    // Verify duplicate retry returns immediately without mutating buffer, state, or counters
    assert.equal(recoveryMgr.isRecovering, true, 'Active recovery state must not be replaced');
    assert.equal(recoveryMgr.state, 'RECOVERING', 'State must remain RECOVERING');
    assert.equal(recoveryMgr.recoveryBuffer.length, 1, 'Recovery buffer must not be cleared');
    assert.equal(recoveryMgr.recoveryBuffer[0].sequence_number, 101, 'Buffer content must not be mutated');
    assert.equal(recoveryMgr.persistentRecoveryFailures, 3, 'Persistent budget must not be modified');
    assert.equal(maxConcurrentRestCalls, 1, 'Only one recovery operation must be active concurrently');

    // 6. Inject HTTP 503
    shouldFailRecovery = true;
    resolveFirstStatus();

    // Allow failure handling to settle
    await new Promise((r) => setTimeout(r, 20));

    // 7. Verify the counter becomes 4 and the circuit breaker remains in OFFLINE_SYNC_FAILED
    assert.equal(recoveryMgr.isRecovering, false);
    assert.equal(
      recoveryMgr.persistentRecoveryFailures,
      4,
      'Persistent failure budget must increment from 3 to 4 on failed retry'
    );
    assert.equal(
      recoveryMgr.state,
      'OFFLINE_SYNC_FAILED',
      'Circuit breaker must remain in / transition to OFFLINE_SYNC_FAILED when failures >= maxPersistentFailures'
    );
    assert.equal(mockWs.status, 'DISCONNECTED', 'WebSocket must be disconnected upon OFFLINE_SYNC_FAILED');

    // 8. Invoke manual retry again
    shouldFailRecovery = false;
    recoveryMgr.manualRetrySync();
    assert.equal(recoveryMgr.state, 'CONNECTING');

    // Allow new socket to construct
    await new Promise((r) => setTimeout(r, 10));
    assert.equal(sockets.length, 2, 'Second manual retry constructs replacement socket');
    const sock2 = sockets[1];
    sock2.triggerOpen();

    // Allow startRecovery to run and suspend on resolveSecondStatus
    await new Promise((r) => setTimeout(r, 10));
    assert.equal(recoveryMgr.isRecovering, true);

    // 9 & 10. Keep REST requests pending and verify the persistent counter remains 4
    assert.equal(
      recoveryMgr.persistentRecoveryFailures,
      4,
      'Persistent counter must remain strictly 4 while second recovery REST requests are pending'
    );

    // 11. Resolve a valid snapshot
    resolveSecondStatus();

    // Allow recovery execution to complete
    await new Promise((r) => setTimeout(r, 30));

    // 12. Verify the manager reaches SYNCHRONIZED and only then resets the persistent counter to 0
    assert.equal(recoveryMgr.state, 'SYNCHRONIZED', 'State must reach SYNCHRONIZED on validated snapshot');
    assert.equal(
      recoveryMgr.persistentRecoveryFailures,
      0,
      'Failure budget must reset to 0 strictly after validation succeeds'
    );
    assert.equal(mockWs.lastSequenceNumber, 100, 'Sequence floor must advance to authoritative sequence');

    mockWs.disconnect();
    recoveryMgr.destroy();
  });
});
