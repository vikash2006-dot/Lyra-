import { API_TOKEN, WS_URL } from "../config";

/**
 * WebSocket with automatic reconnection (exponential backoff), heartbeat pings and
 * status callbacks. Messages are JSON events: {type, timestamp, ...}.
 */
export class LyraSocket {
  constructor(path, { onEvent, onStatus } = {}) {
    this.path = path;
    this.onEvent = onEvent || (() => {});
    this.onStatus = onStatus || (() => {});
    this.ws = null;
    this.retries = 0;
    this.closedByUser = false;
    this.reconnectTimer = null;
    this.pingTimer = null;
    this.status = "idle";
  }

  connect() {
    this.closedByUser = false;
    clearTimeout(this.reconnectTimer);
    const url = `${WS_URL}${this.path}${API_TOKEN ? `?token=${encodeURIComponent(API_TOKEN)}` : ""}`;
    this._setStatus(this.retries ? "reconnecting" : "connecting");
    let ws;
    try {
      ws = new WebSocket(url);
    } catch {
      this._scheduleReconnect();
      return;
    }
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onopen = () => {
      this.retries = 0;
      this._setStatus("open");
      clearInterval(this.pingTimer);
      this.pingTimer = setInterval(() => this.send({ type: "ping" }), 25_000);
    };
    ws.onmessage = (msg) => {
      if (typeof msg.data !== "string") return;
      try {
        const event = JSON.parse(msg.data);
        if (event.type !== "pong") this.onEvent(event);
      } catch {
        /* ignore malformed frames */
      }
    };
    ws.onclose = () => {
      clearInterval(this.pingTimer);
      if (this.ws === ws) this.ws = null;
      if (this.closedByUser) this._setStatus("closed");
      else this._scheduleReconnect();
    };
    ws.onerror = () => {
      /* onclose follows and handles reconnection */
    };
  }

  _scheduleReconnect() {
    this._setStatus("reconnecting");
    const delay = Math.min(15_000, 500 * 2 ** this.retries) + Math.random() * 300;
    this.retries += 1;
    this.reconnectTimer = setTimeout(() => this.connect(), delay);
  }

  _setStatus(status) {
    this.status = status;
    this.onStatus(status);
  }

  get isOpen() {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  send(data) {
    if (!this.isOpen) return false;
    this.ws.send(data instanceof Blob || data instanceof ArrayBuffer ? data : JSON.stringify(data));
    return true;
  }

  close() {
    this.closedByUser = true;
    clearTimeout(this.reconnectTimer);
    clearInterval(this.pingTimer);
    this.ws?.close();
    this.ws = null;
  }
}
