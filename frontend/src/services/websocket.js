/**
 * frontend/src/services/websocket.js
 * 
 * Hardened resilient WebSocket client with connection-generation isolation,
 * bounded CLOSING teardown, randomized jittered exponential backoff,
 * heartbeat monitoring, and stale-frame protection.
 */

export class TrafficWebSocket {
  constructor(options = {}) {
    this.ws = null;
    this.pendingClosingSocket = null;
    this.listeners = new Set();
    this.statusListeners = new Set();
    this.status = 'DISCONNECTED'; // 'CONNECTING', 'CONNECTED', 'DISCONNECTED'
    this.reconnectTimeout = null;
    this.pingInterval = null;
    this.reconnectAttempts = 0;
    this.isExplicitDisconnect = false;
    this.teardownStalled = false;
    this.activeConnectPromise = null;

    // Backoff configuration
    this.baseDelayMs = options.baseDelayMs || 1000;
    this.maxDelayMs = options.maxDelayMs || 15000;
    this.backoffFactor = options.backoffFactor || 1.5;
    this.jitterRatio = options.jitterRatio !== undefined ? options.jitterRatio : 0.2; // +/- 20%
    this.teardownTimeoutMs = options.teardownTimeoutMs || 2000;

    // Environment & factory injection
    this.customUrl = options.url || null;
    this.WebSocketClass = options.WebSocketClass || null;

    // Lifecycle token to isolate superseded socket events
    this.connectionGeneration = 0;

    // Session tracking & stale-frame protection (Phase 2B-3B)
    this.currentSessionUuid = null;
    this.lastSequenceNumber = -1;
    this.previousSessions = new Set();
  }

  /**
   * Resolves native or injected WebSocket implementation.
   */
  _getWebSocketClass() {
    if (this.WebSocketClass) return this.WebSocketClass;
    if (typeof WebSocket !== 'undefined') return WebSocket;
    if (typeof globalThis !== 'undefined' && globalThis.WebSocket) return globalThis.WebSocket;
    throw new Error('WebSocket implementation not available in current environment');
  }

  /**
   * Resolves WebSocket connection URL.
   */
  _getUrl() {
    if (this.customUrl) return this.customUrl;
    if (typeof window !== 'undefined' && window.location) {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      return `${protocol}//${window.location.host}/ws/traffic`;
    }
    return 'ws://localhost:8000/ws/traffic';
  }

  /**
   * Computes exponential backoff with randomized jitter.
   * delay in [base * (1 - jitter), min(maxDelay, base) * (1 + jitter)]
   */
  _calculateBackoffDelay() {
    const rawBase = this.baseDelayMs * Math.pow(this.backoffFactor, this.reconnectAttempts);
    const clampedBase = Math.min(rawBase, this.maxDelayMs);
    const jitterRange = clampedBase * this.jitterRatio;
    const jitter = (Math.random() * 2 - 1) * jitterRange;
    const computed = clampedBase + jitter;
    return Math.max(100, Math.min(this.maxDelayMs * (1 + this.jitterRatio), computed));
  }

  /**
   * Bounded wait for a closing socket to reach WebSocket.CLOSED state.
   */
  _waitForSocketClosed(socket, timeoutMs = 2000) {
    const WS = this._getWebSocketClass();
    if (!socket || socket.readyState === WS.CLOSED) {
      return Promise.resolve(true);
    }

    return new Promise((resolve) => {
      let timer = null;

      const cleanup = () => {
        if (timer) clearTimeout(timer);
        socket.removeEventListener?.('close', onClose);
      };

      const onClose = () => {
        cleanup();
        resolve(true);
      };

      timer = setTimeout(() => {
        cleanup();
        resolve(socket.readyState === WS.CLOSED);
      }, timeoutMs);

      if (typeof socket.addEventListener === 'function') {
        socket.addEventListener('close', onClose, { once: true });
      } else {
        const origOnClose = socket.onclose;
        socket.onclose = (event) => {
          onClose();
          if (typeof origOnClose === 'function') origOnClose(event);
        };
      }
    });
  }

  /**
   * Initiates connection with serialized execution, duplicate prevention,
   * and bounded closing teardown.
   */
  connect() {
    if (this.activeConnectPromise) {
      return this.activeConnectPromise;
    }
    // Intentional connection attempt authorized: reset explicit disconnect state
    this.isExplicitDisconnect = false;
    const currentPromise = this._executeConnect().finally(() => {
      // Guard promise clearing by reference equality to prevent obsolete attempts from clearing newer promises
      if (this.activeConnectPromise === currentPromise) {
        this.activeConnectPromise = null;
      }
    });
    this.activeConnectPromise = currentPromise;
    return this.activeConnectPromise;
  }

  async _executeConnect() {
    const WS = this._getWebSocketClass();

    // 1. If an orphaned socket from a previous timed-out teardown is still pending:
    if (this.pendingClosingSocket) {
      if (this.pendingClosingSocket.readyState === WS.CLOSED) {
        this.pendingClosingSocket = null;
        this.teardownStalled = false;
      } else {
        console.warn(
          '[TrafficWebSocket] Teardown still pending on previous socket. Postponing replacement connection.'
        );
        this.teardownStalled = true;
        this._scheduleReconnect();
        return;
      }
    }

    // 2. Prevent duplicate connections if currently open or connecting
    if (this.ws) {
      if (this.ws.readyState === WS.CONNECTING || this.ws.readyState === WS.OPEN) {
        return;
      }

      // 3. Handle CLOSING socket with bounded await
      if (this.ws.readyState === WS.CLOSING) {
        const preWaitToken = this.connectionGeneration;
        const closingSocket = this.ws;

        const closed = await this._waitForSocketClosed(closingSocket, this.teardownTimeoutMs);

        // F-CONC-01: Revalidate authorizations after asynchronous teardown wait
        if (this.isExplicitDisconnect) {
          return;
        }
        if (this.connectionGeneration !== preWaitToken) {
          return;
        }
        if (this.ws !== closingSocket) {
          return;
        }

        if (closed && (!this.ws || this.ws.readyState === WS.CLOSED)) {
          this.ws = null;
        } else {
          // Teardown timeout expired!
          console.warn(
            `[TrafficWebSocket] Socket teardown could not be confirmed within ${this.teardownTimeoutMs}ms (socket remains CLOSING). Postponing replacement connection until CLOSED.`
          );
          if (this.ws) {
            this.ws.onopen = null;
            this.ws.onclose = null;
            this.ws.onerror = null;
            this.ws.onmessage = null;
            this.pendingClosingSocket = this.ws;
            this.ws = null;
          }
          this.connectionGeneration++;
          this.teardownStalled = true;
          this._setStatus('DISCONNECTED');
          this._scheduleReconnect();
          return;
        }
      }
    }

    // Final authorization check before constructing new WebSocket
    if (this.isExplicitDisconnect) {
      return;
    }
    if (this.pendingClosingSocket && this.pendingClosingSocket.readyState !== WS.CLOSED) {
      return;
    }
    if (this.ws && (this.ws.readyState === WS.CONNECTING || this.ws.readyState === WS.OPEN)) {
      return;
    }

    // Clear any pending reconnect timers
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    // Advance generation token to invalidate any previous or delayed socket events
    const currentToken = ++this.connectionGeneration;
    this.isExplicitDisconnect = false;
    this.teardownStalled = false;
    this._setStatus('CONNECTING');

    const wsUrl = this._getUrl();

    try {
      this.ws = new WS(wsUrl);

      this.ws.onopen = (event) => {
        if (this.connectionGeneration !== currentToken) return;
        this.reconnectAttempts = 0;
        this._setStatus('CONNECTED');
        this._startHeartbeat();
      };

      this.ws.onmessage = (event) => {
        if (this.connectionGeneration !== currentToken) return;
        try {
          const data = typeof event.data === 'string' ? JSON.parse(event.data) : event.data;
          if (!this.processMessage(data)) {
            return;
          }
          this.listeners.forEach((fn) => {
            try {
              fn(data);
            } catch (e) {
              console.error('[TrafficWebSocket] Listener exception:', e);
            }
          });
        } catch (e) {
          console.warn('[TrafficWebSocket] Parse error:', e);
        }
      };

      this.ws.onclose = (event) => {
        if (this.connectionGeneration !== currentToken) return;
        this._stopHeartbeat();
        this._setStatus('DISCONNECTED');
        if (!this.isExplicitDisconnect) {
          this._scheduleReconnect();
        }
      };

      this.ws.onerror = (event) => {
        if (this.connectionGeneration !== currentToken) return;
        this._setStatus('DISCONNECTED');
      };
    } catch (err) {
      if (this.connectionGeneration !== currentToken) return;
      console.warn('[TrafficWebSocket] Connection exception:', err);
      this._setStatus('DISCONNECTED');
      this._scheduleReconnect();
    }
  }

  /**
   * Explicitly closes the connection and cancels all timers.
   */
  disconnect() {
    this.isExplicitDisconnect = true;
    this.connectionGeneration++; // Invalidate all existing socket callbacks
    this.activeConnectPromise = null;
    this._stopHeartbeat();

    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    if (this.ws) {
      this.ws.onopen = null;
      this.ws.onclose = null;
      this.ws.onerror = null;
      this.ws.onmessage = null;
      try {
        this.ws.close();
      } catch (_) {}
      this.ws = null;
    }

    if (this.pendingClosingSocket) {
      this.pendingClosingSocket.onopen = null;
      this.pendingClosingSocket.onclose = null;
      this.pendingClosingSocket.onerror = null;
      this.pendingClosingSocket.onmessage = null;
      try {
        this.pendingClosingSocket.close();
      } catch (_) {}
      this.pendingClosingSocket = null;
    }

    this.reconnectAttempts = 0;
    this.teardownStalled = false;
    this._setStatus('DISCONNECTED');
  }

  /**
   * Reconciles authoritative session UUID and sequence floor from REST snapshot.
   */
  adoptSessionAndSequence(sessionUuid, sequenceNumber) {
    if (this.currentSessionUuid && sessionUuid && this.currentSessionUuid !== sessionUuid) {
      this.previousSessions.add(this.currentSessionUuid);
    }
    this.currentSessionUuid = sessionUuid || null;
    this.lastSequenceNumber = typeof sequenceNumber === 'number' ? sequenceNumber : 0;
  }

  /**
   * Evaluates message ordering and session validity.
   * Rejects duplicate, out-of-order, or previous-session stale frames.
   */
  processMessage(data) {
    if (!data || typeof data !== 'object') {
      return false;
    }

    const type = data.type;

    // 1. PONG: Transport heartbeat response, always accepted without sequence validation
    if (type === 'PONG') {
      return true;
    }

    const msgSession = data.session_uuid || null;
    const msgSeq = typeof data.sequence_number === 'number' ? data.sequence_number : null;

    // 2. INITIAL_STATE: Establishes session and sequence baseline
    if (type === 'INITIAL_STATE') {
      if (this.currentSessionUuid && msgSession && this.currentSessionUuid !== msgSession) {
        this.previousSessions.add(this.currentSessionUuid);
      }
      this.currentSessionUuid = msgSession;
      this.lastSequenceNumber = msgSeq !== null ? msgSeq : 0;
      return true;
    }

    // 3. Telemetry and lifecycle messages
    // Reject frames belonging to a superseded simulation session
    if (msgSession && this.previousSessions.has(msgSession)) {
      console.debug('[TrafficWebSocket] Stale frame rejected: belongs to previous session', msgSession);
      return false;
    }

    // New session detected dynamically
    if (msgSession && this.currentSessionUuid !== null && msgSession !== this.currentSessionUuid) {
      this.previousSessions.add(this.currentSessionUuid);
      this.currentSessionUuid = msgSession;
      this.lastSequenceNumber = msgSeq !== null ? msgSeq : 0;
      return true;
    }

    // Adopt first observed session if uninitialized
    if (this.currentSessionUuid === null && msgSession) {
      this.currentSessionUuid = msgSession;
      this.lastSequenceNumber = msgSeq !== null ? msgSeq : 0;
      return true;
    }

    // Monotonic sequence number validation within current session
    if (msgSeq !== null) {
      if (msgSeq <= this.lastSequenceNumber) {
        console.debug('[TrafficWebSocket] Stale/duplicate frame rejected: seq', msgSeq, '<= last', this.lastSequenceNumber);
        return false;
      }
      this.lastSequenceNumber = msgSeq;
      return true;
    }

    return true;
  }

  /**
   * Resets active session tracking, archiving current session to previousSessions.
   */
  resetSession() {
    if (this.currentSessionUuid) {
      this.previousSessions.add(this.currentSessionUuid);
    }
    this.currentSessionUuid = null;
    this.lastSequenceNumber = -1;
  }

  /**
   * Returns snapshot of active session and sequence tracking for monitoring/testing.
   */
  getSessionState() {
    return {
      currentSessionUuid: this.currentSessionUuid,
      lastSequenceNumber: this.lastSequenceNumber,
      previousSessions: Array.from(this.previousSessions),
      connectionGeneration: this.connectionGeneration,
      reconnectAttempts: this.reconnectAttempts,
      teardownStalled: this.teardownStalled,
    };
  }

  subscribe(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  onStatusChange(listener) {
    this.statusListeners.add(listener);
    listener(this.status);
    return () => this.statusListeners.delete(listener);
  }

  _setStatus(status) {
    if (this.status === status) return;
    this.status = status;
    this.statusListeners.forEach((fn) => {
      try {
        fn(status);
      } catch (e) {
        console.error('[TrafficWebSocket] Status listener exception:', e);
      }
    });
  }

  _scheduleReconnect() {
    if (this.isExplicitDisconnect) return;
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
    }
    const delay = this._calculateBackoffDelay();
    this.reconnectAttempts++;
    this.reconnectTimeout = setTimeout(() => {
      this.reconnectTimeout = null;
      this.connect();
    }, delay);
  }

  _startHeartbeat() {
    clearInterval(this.pingInterval);
    this.pingInterval = setInterval(() => {
      const WS = this._getWebSocketClass();
      if (this.ws && this.ws.readyState === WS.OPEN) {
        try {
          this.ws.send('ping');
        } catch (_) {}
      }
    }, 15000);
  }

  _stopHeartbeat() {
    clearInterval(this.pingInterval);
  }
}

export const trafficWS = new TrafficWebSocket();
