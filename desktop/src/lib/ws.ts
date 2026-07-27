const WS_URL = "ws://localhost:8765/ws";
const RECONNECT_DELAY_MS = 2000;
const MAX_RECONNECT_ATTEMPTS = 10;
const PING_INTERVAL_MS = 15_000;
const PONG_TIMEOUT_MS  = 5_000;

export type WsStatus = "connecting" | "connected" | "disconnected" | "error";

export interface InboundMessage {
  type: string;
  id?: string;
  content?: string;
  done?: boolean;
  message?: string;
  state?: "idle" | "thinking" | "speaking";
  mode?: string;
  text?: string;
  is_final?: boolean;
  paused?: boolean;
}

type MessageHandler = (msg: InboundMessage) => void;
type StatusHandler = (status: WsStatus) => void;

class WebSocketClient {
  private ws: WebSocket | null = null;
  private messageHandlers: Set<MessageHandler> = new Set();
  private statusHandlers: Set<StatusHandler> = new Set();
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout>  | null = null;
  private pingTimer:      ReturnType<typeof setInterval> | null = null;
  private pongTimer:      ReturnType<typeof setTimeout>  | null = null;
  private intentionallyClosed = false;
  // Ref-count: multiple components can call connect()/disconnect() and we only
  // tear down when the last one releases. React StrictMode causes mount-cleanup-
  // remount in dev — without ref-counting, the WS would close + reopen on every
  // mount, which churns the backend and confuses the user.
  private refCount = 0;

  connect() {
    this.refCount++;
    const state = this.ws?.readyState;
    if (state === WebSocket.OPEN || state === WebSocket.CONNECTING) return;
    this.intentionallyClosed = false;
    this._connect();
  }

  private _connect() {
    this._setStatus("connecting");

    // Tear down any zombie socket before opening a new one
    if (this.ws) {
      try { this.ws.close(); } catch { /* ignore */ }
      this.ws = null;
    }

    let socket: WebSocket;
    try {
      socket = new WebSocket(WS_URL);
    } catch {
      this._scheduleReconnect();
      return;
    }
    this.ws = socket;

    socket.onopen = () => {
      // Ignore handlers from a stale socket whose place we already took
      if (this.ws !== socket) return;
      this.reconnectAttempts = 0;
      this._setStatus("connected");
      this._startKeepalive();
    };

    socket.onmessage = (event) => {
      if (this.ws !== socket) return;
      try {
        const msg: InboundMessage = JSON.parse(event.data);
        if (msg.type === "pong") {
          this._clearPongTimer();
          return;
        }
        this.messageHandlers.forEach((h) => h(msg));
      } catch {
        console.error("[ws] Failed to parse message", event.data);
      }
    };

    socket.onerror = () => {
      // Just signal "error" — onclose will follow and handle cleanup.
      if (this.ws !== socket) return;
      this._setStatus("error");
    };

    socket.onclose = () => {
      // Always tear down keepalive when this socket dies, but only act on the
      // global wsClient state if we still consider it ours.
      if (this.ws !== socket) return;
      this._stopKeepalive();
      this.ws = null;
      if (!this.intentionallyClosed) {
        this._setStatus("disconnected");
        this._scheduleReconnect();
      }
    };
  }

  private _startKeepalive() {
    this._stopKeepalive();
    this.pingTimer = setInterval(() => {
      if (this.ws?.readyState !== WebSocket.OPEN) return;
      try {
        this.ws.send(JSON.stringify({ type: "ping" }));
      } catch { /* ignore */ }
      this._clearPongTimer();
      this.pongTimer = setTimeout(() => {
        console.warn("[ws] no pong within", PONG_TIMEOUT_MS, "ms — reconnecting");
        try { this.ws?.close(); } catch { /* ignore */ }
        // onclose handler schedules the reconnect
      }, PONG_TIMEOUT_MS);
    }, PING_INTERVAL_MS);
  }

  private _stopKeepalive() {
    if (this.pingTimer) clearInterval(this.pingTimer);
    this.pingTimer = null;
    this._clearPongTimer();
  }

  private _clearPongTimer() {
    if (this.pongTimer) clearTimeout(this.pongTimer);
    this.pongTimer = null;
  }

  private _scheduleReconnect() {
    if (this.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) return;
    this.reconnectAttempts++;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = setTimeout(
      () => this._connect(),
      RECONNECT_DELAY_MS * Math.min(this.reconnectAttempts, 5),
    );
  }

  send(payload: object) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload));
    }
  }

  disconnect() {
    this.refCount = Math.max(0, this.refCount - 1);
    if (this.refCount > 0) {
      // Other consumers still want the connection — leave it open.
      return;
    }
    this.intentionallyClosed = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this._stopKeepalive();
    try { this.ws?.close(); } catch { /* ignore */ }
    this.ws = null;
  }

  onMessage(handler: MessageHandler) {
    this.messageHandlers.add(handler);
    return () => this.messageHandlers.delete(handler);
  }

  onStatus(handler: StatusHandler) {
    this.statusHandlers.add(handler);
    return () => this.statusHandlers.delete(handler);
  }

  private _setStatus(status: WsStatus) {
    this.statusHandlers.forEach((h) => h(status));
  }

  get status(): WsStatus {
    if (!this.ws) return "disconnected";
    switch (this.ws.readyState) {
      case WebSocket.CONNECTING: return "connecting";
      case WebSocket.OPEN:       return "connected";
      default:                   return "disconnected";
    }
  }
}

export const wsClient = new WebSocketClient();
