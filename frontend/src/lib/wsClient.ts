/**
 * wsClient.ts — Motion-Aware WebSocket Client
 *
 * FIXES:
 * - Jitter buffer integration (routes events through motionJitterBuffer)
 * - Priority queuing: narration/speech events bypass buffer
 * - Adaptive latency control based on measured jitter
 * - Network timing reconciliation with server clock
 * - Bursty arrival protection: smooth event delivery to runtime
 * - Automatic reconnection with exponential backoff
 */

import { motionJitterBuffer, audioLatencyCompensator } from "../runtime/audio/audioLatencyCompensator";
import { audioTimeline } from "../runtime/audio/audioTimeline";

// ── Event Priority Classification ──────────────────────────────

const HIGH_PRIORITY_TYPES = new Set([
  "speech",
  "generation_start",
  "generation_end",
  "interruption",
  "narration_sync",
  "pen_state",
  "cursor_move",
  "scene_start",
  "cognitive_pause",
]);

const REAL_TIME_TYPES = new Set(["speech", "generation_start", "generation_end", "interruption", "narration_sync", "pen_state"]);

// ── URL Normalization ──────────────────────────────────────────

function ensureWsUrl(base: string): string | null {
  if (!base) return null;
  if (base.startsWith("ws://") || base.startsWith("wss://"))
    return base.replace(/\/$/, "");
  if (base.startsWith("http://"))
    return base.replace(/^http:/, "ws:").replace(/\/$/, "");
  if (base.startsWith("https://"))
    return base.replace(/^https:/, "wss:").replace(/\/$/, "");
  return base.replace(/\/$/, "");
}

function getAuthToken(explicitToken?: string): string | null {
  let t = explicitToken || null;
  if (!t && typeof window !== "undefined") {
    try {
      t = localStorage.getItem("authToken") || null;
    } catch {
      /* ignore */
    }
    if (!t && typeof document !== "undefined") {
      const m = document.cookie.match(/(?:^|; )auth_token=([^;]+)/);
      if (m) t = decodeURIComponent(m[1]);
    }
  }
  return t;
}

// ── Jitter Measurement ─────────────────────────────────────────

interface JitterSample {
  value: number;
}

class ArrivalJitterTracker {
  private _lastArrivalMs: number = 0;
  private _samples: number[] = [];
  private _maxSamples: number = 50;

  record(expectedIntervalMs: number = 33): void {
    const now = performance.now();
    if (this._lastArrivalMs > 0) {
      const actualInterval = now - this._lastArrivalMs;
      const jitter = Math.abs(actualInterval - expectedIntervalMs);
      this._samples.push(jitter);
      if (this._samples.length > this._maxSamples) this._samples.shift();
      audioLatencyCompensator.addJitterMeasurement(jitter);
    }
    this._lastArrivalMs = now;
  }

  get p90Jitter(): number {
    if (this._samples.length === 0) return 0;
    const sorted = [...this._samples].sort((a, b) => a - b);
    return sorted[Math.floor(sorted.length * 0.9)];
  }
}

// ── Types ──────────────────────────────────────────────────────

export interface MotionEvent {
  type: string;
  server_time?: number;
  server_timestamp?: number;
  [key: string]: any;
}

export interface ClockSyncEvent {
  type: "clock_sync_request" | "clock_sync_response";
  client_time?: number;
  server_time?: number;
}

export interface MotionWSClientOptions {
  token?: string;
  onopen?: (ev: Event) => void;
  onMotionEvent?: (evt: MotionEvent) => void;
  onBufferedEvent?: (evt: MotionEvent) => void;
  onmessage?: (evt: MotionEvent) => void;
  onclose?: (ev: CloseEvent) => void;
  onerror?: (ev: Event) => void;
  onServerClock?: (info: ClockSyncInfo) => void;
}

export interface ClockSyncInfo {
  serverTimeMs: number;
  rttMs: number;
  offsetMs: number;
}

export interface MotionWSMetrics {
  connected: boolean;
  reconnectAttempts: number;
  totalReceived: number;
  highPriorityCount: number;
  bufferedCount: number;
  jitterP90Ms: number;
  jitterBufferDepth: number;
  serverClockOffsetMs: number;
}

// ── MotionWSClient ─────────────────────────────────────────────

export class MotionWSClient {
  private _ws: WebSocket | null = null;

  // Callbacks
  private _onOpen: ((ev: Event) => void) | null = null;
  private _onMotionEvent: ((evt: MotionEvent) => void) | null = null;
  private _onBufferedEvent: ((evt: MotionEvent) => void) | null = null;
  private _onClose: ((ev: CloseEvent) => void) | null = null;
  private _onError: ((ev: Event) => void) | null = null;
  private _onServerClock: ((info: ClockSyncInfo) => void) | null = null;

  // Reconnection
  private _reconnectAttempts: number = 0;
  private _maxReconnectAttempts: number = 8;
  private _reconnectDelay: number = 1000;
  private _sessionId: string | null = null;
  private _token: string | undefined;
  private _shouldReconnect: boolean = true;

  // Jitter tracking
  private _jitterTracker: ArrivalJitterTracker = new ArrivalJitterTracker();

  // Buffered delivery
  private _deliveryInterval: NodeJS.Timeout | null = null;
  private _deliveryIntervalMs: number = 16; // ~60fps delivery
  private _deliveryLoopStartTime: number = 0;

  // Server clock reconciliation
  private _serverClockOffset: number = 0;
  private _lastServerTimeMs: number = 0;

  // Metrics
  private _totalReceived: number = 0;
  private _highPriorityCount: number = 0;
  private _bufferedCount: number = 0;
  private _droppedCount: number = 0;

  /**
   * Connect to the WebSocket endpoint.
   */
  connect(sessionId: string, options: MotionWSClientOptions = {}): this {
    this._sessionId = sessionId;
    this._token = options.token;
    this._onOpen = options.onopen || null;
    this._onMotionEvent = options.onMotionEvent || options.onmessage || null;
    this._onBufferedEvent = options.onBufferedEvent || options.onmessage || null;
    this._onClose = options.onclose || null;
    this._onError = options.onerror || null;
    this._onServerClock = options.onServerClock || null;
    this._shouldReconnect = true;

    this._connect();
    this._startDeliveryLoop();

    return this;
  }

  /**
   * Send a message to the server.
   */
  send(data: any): void {
    if (!this._ws || this._ws.readyState !== WebSocket.OPEN) return;
    try {
      this._ws.send(typeof data === "object" ? JSON.stringify(data) : String(data));
    } catch {
      /* ignore */
    }
  }

  /**
   * Close the connection.
   */
  close(): void {
    this._shouldReconnect = false;
    this._stopDeliveryLoop();
    if (this._ws) {
      this._ws.close(1000, "Client closed");
      this._ws = null;
    }
  }

  /**
   * Get connection metrics.
   */
  getMetrics(): MotionWSMetrics {
    return {
      connected: this._ws?.readyState === WebSocket.OPEN,
      reconnectAttempts: this._reconnectAttempts,
      totalReceived: this._totalReceived,
      highPriorityCount: this._highPriorityCount,
      bufferedCount: this._bufferedCount,
      jitterP90Ms: this._jitterTracker.p90Jitter,
      jitterBufferDepth: motionJitterBuffer.depth,
      serverClockOffsetMs: this._serverClockOffset,
    };
  }

  // ── Private ────────────────────────────────────────────────

  private _connect(): void {
    const envUrl =
      (typeof window !== "undefined" && (window as any).__Sarasvi_API_WS_URL) ||
      process.env.NEXT_PUBLIC_API_WS_URL ||
      "ws://localhost:8000";

    const clean = ensureWsUrl(envUrl);
    if (!clean) return;

    let wsUrl = clean.endsWith("/ws")
      ? `${clean}/${encodeURIComponent(this._sessionId || "")}`
      : `${clean}/ws/${encodeURIComponent(this._sessionId || "")}`;

    const token = getAuthToken(this._token);
    if (token) {
      wsUrl += `${wsUrl.includes("?") ? "&" : "?"}access_token=${encodeURIComponent(token)}`;
    }

    try {
      this._ws = new WebSocket(wsUrl);
    } catch (err) {
      this._scheduleReconnect();
      return;
    }

    this._ws.onopen = (ev: Event) => {
      this._reconnectAttempts = 0;
      this._reconnectDelay = 1000;

      // Request server clock sync
      this.send({ type: "clock_sync_request", client_time: performance.now() });

      this._onOpen?.(ev);
    };

    this._ws.onmessage = (ev: MessageEvent) => {
      this._onRawMessage(ev.data);
    };

    this._ws.onclose = (ev: CloseEvent) => {
      this._stopDeliveryLoop();
      this._onClose?.(ev);
      if (this._shouldReconnect && this._reconnectAttempts < this._maxReconnectAttempts) {
        this._scheduleReconnect();
      }
    };

    this._ws.onerror = (ev: Event) => {
      this._onError?.(ev);
    };
  }

  private _onRawMessage(data: any): void {
    if (typeof data === "string" && data.includes("\n")) {
      for (const line of data.split("\n")) {
        const trimmed = line.trim();
        if (trimmed) this._onRawMessage(trimmed);
      }
      return;
    }

    let evt: MotionEvent;
    try {
      evt = typeof data === "string" ? JSON.parse(data) : data;
    } catch {
      return;
    }

    this._totalReceived++;
    this._jitterTracker.record();

    // ── Server clock reconciliation ──────────────────────────
    if (evt.type === "clock_sync_response") {
      this._handleClockSync(evt as ClockSyncEvent);
      return;
    }

    const serverTime = evt.server_time ?? evt.server_timestamp;
    if (serverTime) {
      audioTimeline.reconcileWithServer(serverTime + this._serverClockOffset);
    }

    const eventType = evt.type || "";

    // ── Real-time events: bypass jitter buffer ───────────────
    if (REAL_TIME_TYPES.has(eventType)) {
      this._highPriorityCount++;
      this._onMotionEvent?.(evt);
      return;
    }

    // ── High-priority: minimal buffering ────────────────────
    if (HIGH_PRIORITY_TYPES.has(eventType)) {
      this._highPriorityCount++;
      this._onMotionEvent?.(evt);
      return;
    }

    // ── Normal: route through jitter buffer ──────────────────
    this._bufferedCount++;
    motionJitterBuffer.push(evt);
  }

  private _handleClockSync(evt: ClockSyncEvent): void {
    const clientNow = performance.now();
    const roundTripMs = clientNow - (evt.client_time || clientNow);
    const serverTimeMs = evt.server_time || 0;
    const estimatedServerNow = serverTimeMs + roundTripMs / 2;
    this._serverClockOffset = clientNow - estimatedServerNow;

    audioLatencyCompensator.addJitterMeasurement(roundTripMs / 2);
    audioTimeline.reconcileWithServer(estimatedServerNow);

    this._onServerClock?.({
      serverTimeMs: estimatedServerNow,
      rttMs: roundTripMs,
      offsetMs: this._serverClockOffset,
    });
  }

  private _startDeliveryLoop(): void {
    this._stopDeliveryLoop();
    this._deliveryLoopStartTime = performance.now();
    this._deliveryInterval = setInterval(() => {
      const currentMs = (audioTimeline as any)._isRunning
        ? (audioTimeline as any).currentTimeMs
        : performance.now() - this._deliveryLoopStartTime;
      const events = motionJitterBuffer.drain(currentMs);

      for (const evt of events) {
        this._onBufferedEvent?.(evt);
      }

      // Adapt jitter buffer depth based on measured jitter
      motionJitterBuffer.adaptTo(this._jitterTracker.p90Jitter);
    }, this._deliveryIntervalMs);
  }

  private _stopDeliveryLoop(): void {
    if (this._deliveryInterval) {
      clearInterval(this._deliveryInterval);
      this._deliveryInterval = null;
    }
  }

  private _scheduleReconnect(): void {
    this._reconnectAttempts++;
    const delay = Math.min(
      this._reconnectDelay * Math.pow(2, this._reconnectAttempts - 1),
      30000
    );
    setTimeout(() => {
      if (this._shouldReconnect) {
        this._connect();
        this._startDeliveryLoop();
      }
    }, delay);
  }
}

// ── Legacy compatibility: simple factory function ──────────────

export interface LegacyWSHandle {
  raw: WebSocket | null;
  send: (data: any) => void;
  close: () => void;
  _client: MotionWSClient;
}

export function createWS(
  sessionId: string,
  options?: {
    token?: string;
    onopen?: (ev: Event) => void;
    onmessage?: (evt: MotionEvent) => void;
    onclose?: (ev: CloseEvent) => void;
    onerror?: (ev: Event) => void;
  }
): LegacyWSHandle {
  const client = new MotionWSClient();
  client.connect(sessionId, {
    token: options?.token,
    onopen: options?.onopen,
    onMotionEvent: options?.onmessage,
    onBufferedEvent: options?.onmessage,
    onclose: options?.onclose,
    onerror: options?.onerror,
  });

  // Legacy API shape
  return {
    raw: (client as any)._ws,
    send: (data: any) => client.send(data),
    close: () => client.close(),
    _client: client,
  };
}

export default { createWS, MotionWSClient };
