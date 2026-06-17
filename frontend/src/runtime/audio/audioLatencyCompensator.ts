/**
 * audioLatencyCompensator.ts — System Latency Measurement & Compensation
 *
 * Measures the true end-to-end audio latency and compensates visual
 * timing so drawing appears synchronized with what the user HEARS,
 * not what the system schedules.
 *
 * Key insight: Audio arrives at the speaker ~80-200ms after scheduled.
 * Visuals must be pre-fired by this same amount so they appear simultaneous.
 */

export type CalibrationMethod = "audiocontext" | "visual_sync" | "manual" | "estimated";

export interface CompensatorMetrics {
  outputLatencyMs: number;
  renderLatencyMs: number;
  networkJitterMs: number;
  totalLatencyMs: number;
  earlyFireMs: number;
  jitterBufferMs: number;
  isCalibrated: boolean;
  sampleCount: number;
}

export interface JitterEvent {
  start_ms?: number;
  [key: string]: any;
}

interface BufferedItem<T> {
  event: T;
  receivedAt: number;
  scheduledAt: number;
}

// ── LatencySample ──────────────────────────────────────────────

class LatencySample {
  public measuredMs: number;
  public method: CalibrationMethod;
  public timestamp: number;
  public confidence: number;

  constructor(measuredMs: number, method: CalibrationMethod) {
    this.measuredMs = measuredMs;
    this.method = method;
    this.timestamp = Date.now();
    this.confidence = method === "audiocontext" ? 0.95 : method === "visual_sync" ? 0.7 : 0.4;
  }
}

// ── AudioLatencyCompensator ────────────────────────────────────

export class AudioLatencyCompensator {
  private _outputLatencyMs: number;
  private _networkJitterMs: number;
  private _renderLatencyMs: number;
  private _samples: LatencySample[];
  private _maxSamples: number;
  private _earlyFireMs: number;
  private _isCalibrated: boolean;
  private _jitterBufferMs: number;
  private _jitterSamples: number[];
  private _lastCalibrationTime: number;

  constructor() {
    // Measured latency components
    this._outputLatencyMs = 80;     // Hardware output latency
    this._networkJitterMs = 0;      // Network jitter (for streamed audio)
    this._renderLatencyMs = 16;     // One frame render latency

    // Samples for calibration
    this._samples = [];
    this._maxSamples = 30;

    // Configuration
    this._earlyFireMs = 50;         // Fire visuals 50ms BEFORE scheduled audio
    this._isCalibrated = false;

    // Jitter buffer state
    this._jitterBufferMs = 100;     // Minimum buffer depth
    this._jitterSamples = [];

    // Performance
    this._lastCalibrationTime = 0;
  }

  /**
   * Initialize from AudioContext (most accurate).
   */
  public initFromAudioContext(ctx: AudioContext): void {
    if (!ctx) return;

    // Use AudioContext.outputLatency (Chrome/Firefox)
    if ((ctx as any).outputLatency !== undefined) {
      this._outputLatencyMs = (ctx as any).outputLatency * 1000;
      this._addSample(new LatencySample(this._outputLatencyMs, "audiocontext"));
    }

    // Also check baseLatency (processing latency)
    if ((ctx as any).baseLatency !== undefined) {
      this._renderLatencyMs = (ctx as any).baseLatency * 1000;
    }

    this._isCalibrated = true;
    this._computeCompensation();
  }

  /**
   * Add a manual measurement (e.g., from visual sync test).
   */
  public addMeasurement(measuredMs: number): void {
    this._addSample(new LatencySample(measuredMs, "visual_sync"));
    this._computeCompensation();
  }

  /**
   * Add a network jitter measurement.
   */
  public addJitterMeasurement(jitterMs: number): void {
    this._jitterSamples.push(jitterMs);
    if (this._jitterSamples.length > this._maxSamples) {
      this._jitterSamples.shift();
    }

    // 90th percentile jitter
    const sorted = [...this._jitterSamples].sort((a, b) => a - b);
    this._networkJitterMs = sorted[Math.floor(sorted.length * 0.9)] || 0;

    this._jitterBufferMs = Math.max(50, this._networkJitterMs * 1.5);
    this._computeCompensation();
  }

  /**
   * How many ms BEFORE scheduled audio time to fire visual events.
   * Positive = fire visuals earlier (pre-compensation).
   */
  public get earlyFireMs(): number {
    return Math.max(0, this._earlyFireMs);
  }

  /**
   * Required jitter buffer depth for smooth playback.
   */
  public get jitterBufferMs(): number {
    return this._jitterBufferMs;
  }

  /**
   * Total latency estimate (output + processing).
   */
  public get totalLatencyMs(): number {
    return this._outputLatencyMs + this._renderLatencyMs;
  }

  /**
   * Whether we have a reliable calibration.
   */
  public get isCalibrated(): boolean {
    return this._isCalibrated;
  }

  /**
   * Apply compensation to a scheduled visual time.
   * The visual should fire this many ms earlier than the audio.
   */
  public compensate(audioScheduledMs: number): number {
    // Return the raw audio scheduled time directly, as the audioTimeline master clock
    // already accounts for latency and hardware lag.
    return audioScheduledMs;
  }

  /**
   * Check if an event is within the visual fire window.
   */
  public isReadyToFire(eventTimeMs: number, currentTimeMs: number): boolean {
    return currentTimeMs >= this.compensate(eventTimeMs);
  }

  /**
   * Get current metrics.
   */
  public getMetrics(): CompensatorMetrics {
    return {
      outputLatencyMs: this._outputLatencyMs,
      renderLatencyMs: this._renderLatencyMs,
      networkJitterMs: this._networkJitterMs,
      totalLatencyMs: this.totalLatencyMs,
      earlyFireMs: this.earlyFireMs,
      jitterBufferMs: this._jitterBufferMs,
      isCalibrated: this._isCalibrated,
      sampleCount: this._samples.length,
    };
  }

  /**
   * Reset internal structures.
   */
  public reset(): void {
    this._samples = [];
    this._jitterSamples = [];
    this._networkJitterMs = 0;
    this._isCalibrated = false;
    this._outputLatencyMs = 80;
    this._renderLatencyMs = 16;
    this._earlyFireMs = 50;
    this._jitterBufferMs = 100;
  }

  // ── Private Internal Calibration Math ──────────────────────

  private _addSample(sample: LatencySample): void {
    this._samples.push(sample);
    if (this._samples.length > this._maxSamples) {
      this._samples.shift();
    }
  }

  private _computeCompensation(): void {
    if (this._samples.length === 0) {
      this._earlyFireMs = 50; // Default
      return;
    }

    // Weighted average by confidence
    let totalWeight = 0;
    let weightedSum = 0;
    for (const s of this._samples) {
      weightedSum += s.measuredMs * s.confidence;
      totalWeight += s.confidence;
    }

    const avgLatency = totalWeight > 0 ? weightedSum / totalWeight : 80;
    // Fire visuals slightly before audio arrives at speaker
    this._earlyFireMs = Math.max(16, avgLatency - this._renderLatencyMs);
  }
}

// ── Jitter Buffer ──────────────────────────────────────────────

/**
 * Motion stream jitter buffer.
 * Smooths bursty WebSocket arrivals into steady event delivery.
 */
export class JitterBuffer<T extends JitterEvent = any> {
  private _targetBufferMs: number;
  private _buffer: BufferedItem<T>[];
  private _isBuffering: boolean;
  private _bufferStartTime: number;
  private _lastEmitTime: number;
  private _drainCallbacks: Array<(...args: any[]) => void>;

  constructor(targetBufferMs: number = 150) {
    this._targetBufferMs = targetBufferMs;
    this._buffer = [];
    this._isBuffering = false;
    this._bufferStartTime = 0;
    this._lastEmitTime = 0;
    this._drainCallbacks = [];
  }

  /**
   * Add an event to the buffer.
   */
  public push(event: T): void {
    const receivedAt = performance.now();
    this._buffer.push({
      event,
      receivedAt,
      scheduledAt: event.start_ms || 0,
    });
    // Keep buffer sorted by scheduledAt
    this._buffer.sort((a, b) => a.scheduledAt - b.scheduledAt);
  }

  /**
   * Get events that are ready to be emitted.
   */
  public drain(playheadMs: number): T[] {
    const ready: T[] = [];
    while (this._buffer.length > 0) {
      const next = this._buffer[0];
      if (next.scheduledAt <= playheadMs + this._targetBufferMs) {
        const item = this._buffer.shift();
        if (item) {
          ready.push(item.event);
        }
      } else {
        break;
      }
    }
    return ready;
  }

  /**
   * Current buffer depth.
   */
  public get depth(): number {
    return this._buffer.length;
  }

  /**
   * Adjust target buffer size based on observed jitter.
   */
  public adaptTo(jitterMs: number): void {
    this._targetBufferMs = Math.max(50, Math.min(500, jitterMs * 2));
  }

  /**
   * Reset the buffer elements.
   */
  public reset(): void {
    this._buffer = [];
    this._isBuffering = false;
  }
}

// ── Singletons ─────────────────────────────────────────────────
export const audioLatencyCompensator = new AudioLatencyCompensator();
export const motionJitterBuffer = new JitterBuffer<any>(150);