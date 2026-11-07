/**
 * PDA real-time channel, with no React Native or Expo imports.
 *
 * Split out of client.js for the same reason the offline queue is its own
 * module: everything interesting here — the reconnect ladder, the token gate,
 * the ping deadline, what counts as "the link is up" — is plain JavaScript that
 * scripts/test_pda_socket.mjs drives without a simulator.  Whatever the channel
 * needs from the app (a token, and what to do when the link comes up) is passed
 * in, so this file has nothing to stub.
 */

/** Ping often enough to notice a dead link inside a shift. */
export const WS_PING_INTERVAL_MS = 20000;
/** Shorter than the interval, so an unanswered ping is a timeout, not a second ping. */
export const WS_PONG_TIMEOUT_MS = 15000;

export const WS_OFFLINE = "offline";
export const WS_CONNECTING = "connecting";
export const WS_ONLINE = "online";

export class PdaSocket {
  constructor({ getToken, onOnline, url }) {
    if (typeof getToken !== "function") throw new Error("PdaSocket needs getToken");
    if (!url) throw new Error("PdaSocket needs a socket URL");

    this._getToken = getToken;
    this._onOnline = typeof onOnline === "function" ? onOnline : null;
    this._url = url;

    this._callbacks = new Set();
    this._stateListeners = new Set();
    this._ws = null;
    this._reconnectTimer = null;
    // scheduleReconnect() raises this on every attempt, so it has to start at a
    // number: Math.pow(2, undefined) is NaN and Math.min(NaN, 30000) is NaN,
    // which made setTimeout fire instantly instead of backing off.
    this._retryCount = 0;
    // An intentional disconnect must not be reconnected by the close handler.
    this._closedIntentionally = false;
    // A reconnect timer and a screen can both ask for the socket at the same
    // moment, and two sockets from one device make the server see two clients
    // for one handheld.
    this._connecting = false;

    this._state = WS_OFFLINE;
    this._pingTimer = null;
    this._pongTimer = null;
  }

  getState() {
    return this._state;
  }

  /** Subscribe to link state (online | connecting | offline). Returns unsubscribe. */
  subscribeState(cb) {
    this._stateListeners.add(cb);
    try { cb(this._state); } catch { /* a listener must not break the socket */ }
    return () => this._stateListeners.delete(cb);
  }

  /**
   * Open the PDA socket.
   *
   * The token is read here rather than passed in: src/pda/router.py closes with
   * 4001 "token required" unless client_id *and* token arrive as query params,
   * and an anonymous socket the server immediately drops reads as a flaky
   * network to whoever is looking at the logs — while a logged-out device
   * reconnecting forever spends battery on a dial that cannot succeed.
   */
  async connect(deviceId) {
    if (this._ws?.readyState === WebSocket.OPEN || this._connecting) return;
    this._connecting = true;
    this._closedIntentionally = false;

    let token;
    try {
      token = await this._getToken();
    } catch (err) {
      this._connecting = false;
      console.warn("pda socket: token unreadable", err?.message ?? err);
      return;
    }
    if (!token) {
      // Logged out: the server closes every attempt with 4001, so there is
      // nothing to reconnect to until somebody signs in.
      this._connecting = false;
      return;
    }

    const query = `client_id=${encodeURIComponent(deviceId)}&token=${encodeURIComponent(token)}`;
    this._setState(WS_CONNECTING);
    this._ws = new WebSocket(`${this._url}?${query}`);
    this._connecting = false;
    const ws = this._ws;

    ws.onopen = () => {
      // A live socket ends the backoff ladder...
      this._retryCount = 0;
      this._setState(WS_ONLINE);
      this._startHeartbeat();
      // ...and is itself proof the network is back, which is the cheapest
      // possible trigger for replaying whatever the PDA queued up.
      if (this._onOnline) this._onOnline();
    };
    ws.onmessage = ({ data }) => {
      if (data === "pong") {
        clearTimeout(this._pongTimer);
        this._pongTimer = null;
        return;
      }
      try {
        const msg = JSON.parse(data);
        this._callbacks.forEach((cb) => cb(msg));
      } catch { /* a malformed push is not worth a crash */ }
    };
    ws.onerror = () => this.scheduleReconnect(deviceId);
    ws.onclose = (event) => {
      this._stopHeartbeat();
      this._ws = null;
      this._setState(WS_OFFLINE);
      // A 4001 close (bad, expired or missing token) is not a network problem:
      // dialing again cannot fix it, and the loop would run until the battery
      // does.  The operator has to sign in again.
      if (event?.code === 4001) {
        console.warn("pda socket rejected: token refused — sign in again");
        return;
      }
      this.scheduleReconnect(deviceId);
    };
  }

  send(payload) {
    if (this._ws?.readyState !== WebSocket.OPEN) return;
    // A string goes out as-is: the server compares the text "ping", not JSON.
    this._ws.send(typeof payload === "string" ? payload : JSON.stringify(payload));
  }

  scheduleReconnect(deviceId) {
    if (this._closedIntentionally) return;
    clearTimeout(this._reconnectTimer);
    // Exponential backoff: 1s → 2s → 4s → 8s (max 30s)
    const delay = Math.min(1000 * Math.pow(2, this._retryCount++), 30000);
    this._reconnectTimer = setTimeout(() => {
      this.connect(deviceId);
    }, delay);
  }

  onMessage(cb) {
    this._callbacks.add(cb);
    return () => this._callbacks.delete(cb);
  }

  disconnect() {
    this._closedIntentionally = true;
    this._retryCount = 0;
    this._connecting = false;
    this._stopHeartbeat();
    clearTimeout(this._reconnectTimer);
    const ws = this._ws;
    this._ws = null;
    this._setState(WS_OFFLINE);
    if (ws) ws.close();
  }

  _setState(next) {
    if (this._state === next) return;
    this._state = next;
    for (const cb of this._stateListeners) {
      try { cb(next); } catch { /* ignore listener errors */ }
    }
  }

  _stopHeartbeat() {
    clearInterval(this._pingTimer);
    clearTimeout(this._pongTimer);
    this._pingTimer = null;
    this._pongTimer = null;
  }

  /**
   * Ping on a timer, with a deadline on the answer.
   *
   * A socket a proxy dropped without telling either side still reads OPEN, so
   * the app looks connected while everything behind it fails — and nothing ever
   * closes, so the reconnect ladder never runs.  src/pda/router.py answers
   * "ping" with "pong"; no pong inside the deadline means the link is a zombie,
   * so this closes it and lets the reconnect path handle it.
   */
  _startHeartbeat() {
    this._stopHeartbeat();
    this._pingTimer = setInterval(() => {
      if (this._ws?.readyState !== WebSocket.OPEN) return;
      this.send("ping");
      clearTimeout(this._pongTimer);
      this._pongTimer = setTimeout(() => {
        this._ws?.close();
      }, WS_PONG_TIMEOUT_MS);
    }, WS_PING_INTERVAL_MS);
  }
}

export function createPdaSocket(deps) {
  return new PdaSocket(deps);
}
