/**
 * ttsPlayer.ts — TTS Playback & Audio Event Emission
 *
 * Handles actual audio playback of TTS segments and feeds real timing
 * events into the AudioTimeline master clock.
 *
 * Supports:
 * - Browser Web Speech API (zero-latency fallback)
 * - Streamed audio blob playback with decoded timing
 * - ElevenLabs / Polly / Azure alignment data
 * - Web Audio API scheduling for precision
 */

import { audioTimeline } from "./audioTimeline";
import { speechMarksParser } from "./speechMarksParser";
import { audioLatencyCompensator } from "./audioLatencyCompensator";

// ── Type Interfaces ───────────────────────────────────────────

export type TTSProviderType = "web_speech" | "elevenlabs" | "polly" | "azure" | "openai" | "edge_tts" | "generic";

export const TTS_PROVIDER: Record<string, TTSProviderType> = {
  WEB_SPEECH: "web_speech",
  ELEVENLABS: "elevenlabs",
  POLLY: "polly",
  AZURE: "azure",
  OPENAI: "openai",
  EDGE_TTS: "edge_tts",
  GENERIC: "generic",
};

export type TTSSegmentState = "pending" | "loading" | "ready" | "playing" | "completed" | "error";

export interface TTSSegmentConstructorParams {
  segmentId: string;
  text: string;
  absoluteStartMs: number;
  provider?: TTSProviderType;
  audioData?: ArrayBuffer | string | null;
  speechMarks?: any[];
  voice?: string | null;
}

export interface LoadSegmentParams {
  segmentId: string;
  text: string;
  absoluteStartMs: number;
  audioData: ArrayBuffer | string | null;
  speechMarks?: any[];
  provider: TTSProviderType;
}

export interface WordBoundaryEvent {
  word: string;
  startMs: number;
  endMs: number;
}

export interface AudioSourceHandle {
  stop(): void;
}

// ── TTSSegment Class ───────────────────────────────────────────

class TTSSegment {
  public segmentId: string;
  public text: string;
  public absoluteStartMs: number;
  public provider: TTSProviderType;
  public audioData: ArrayBuffer | string | null;
  public speechMarks: any[];
  public voice: string | null;

  public state: TTSSegmentState;
  public durationMs: number;
  public audioBuffer: AudioBuffer | null;
  public sourceNode: AudioBufferSourceNode | null;

  constructor({
    segmentId,
    text,
    absoluteStartMs,
    provider = TTS_PROVIDER.WEB_SPEECH,
    audioData = null,
    speechMarks = [],
    voice = null
  }: TTSSegmentConstructorParams) {
    this.segmentId = segmentId;
    this.text = text;
    this.absoluteStartMs = absoluteStartMs;
    this.provider = provider;
    this.audioData = audioData;
    this.speechMarks = speechMarks;
    this.voice = voice;

    this.state = "pending";
    this.durationMs = 0;
    this.audioBuffer = null;
    this.sourceNode = null;
  }
}

// ── TTSPlayer Class ────────────────────────────────────────────

export class TTSPlayer {
  private _segments: Map<string, TTSSegment>;
  /** AudioBuffers decoded ahead of fire-time (keyed by segmentId) so playback
   *  starts with ~0 decode latency. Populated by preloadAudio(), consumed once
   *  by loadSegment(). */
  private _preloadedBuffers: Map<string, AudioBuffer>;
  private _speechSynth: SpeechSynthesis | null;
  private _currentUtterance: SpeechSynthesisUtterance | null;
  private _gainNode: GainNode | null;
  private _scheduledSources: Array<AudioBufferSourceNode | AudioSourceHandle>;
  private _calibrationOffsetMs: number;
  private _provider: TTSProviderType;
  private _volume: number;

  private _onWordCallbacks: Array<(ev: WordBoundaryEvent) => void>;
  private _onSegmentEndCallbacks: Array<(segmentId: string) => void>;
  private _onReadyCallbacks: Array<(segmentId: string, durationMs: number) => void>;

  constructor() {
    this._segments = new Map();
    this._preloadedBuffers = new Map();
    this._speechSynth = typeof window !== "undefined" ? window.speechSynthesis : null;
    this._currentUtterance = null;
    this._gainNode = null;
    this._scheduledSources = [];
    this._calibrationOffsetMs = 0;
    this._provider = TTS_PROVIDER.WEB_SPEECH;
    this._volume = 1.0;

    this._onWordCallbacks = [];
    this._onSegmentEndCallbacks = [];
    this._onReadyCallbacks = [];
  }

  /**
   * Set the active TTS provider.
   */
  public setProvider(provider: TTSProviderType): void {
    this._provider = provider;
  }

  /**
   * Set volume output level.
   * @param vol - Value bound between 0 and 1
   */
  public setVolume(vol: number): void {
    this._volume = Math.max(0, Math.min(1, vol));
    if (this._gainNode) {
      const ctx = (audioTimeline as any)._audioContext as AudioContext | null;
      this._gainNode.gain.setTargetAtTime(this._volume, ctx?.currentTime || 0, 0.02);
    }
  }

  /**
   * Decode a segment's audio buffer AHEAD of fire-time (called when the speech
   * event is ingested, not when it plays). This moves the expensive
   * decodeAudioData off the critical path so the first stroke/word fires the
   * moment the event is due. Best-effort: if the AudioContext is not ready yet
   * or decode fails, loadSegment() decodes normally at fire-time.
   */
  public async preloadAudio(segmentId: string, audioData: ArrayBuffer | string | null): Promise<void> {
    if (!segmentId || !audioData) return;
    // Already decoded, or already fully loaded as a live segment — nothing to do.
    if (this._preloadedBuffers.has(segmentId) || this._segments.has(segmentId)) return;
    const ctx = (audioTimeline as any)._audioContext as AudioContext | null;
    if (!ctx) return;
    try {
      const buffer = await this._decodeAudioData(audioData, ctx);
      // Guard against a reset()/consume that happened during the async decode.
      if (!this._segments.has(segmentId)) {
        this._preloadedBuffers.set(segmentId, buffer);
      }
    } catch {
      /* best-effort — loadSegment will retry/fallback at fire-time */
    }
  }

  /**
   * Load a TTS segment from audio data + speech marks.
   */
  public async loadSegment({
    segmentId,
    text,
    absoluteStartMs,
    audioData,
    speechMarks = [],
    provider
  }: LoadSegmentParams): Promise<void> {
    const segment = new TTSSegment({ segmentId, text, absoluteStartMs, provider, audioData, speechMarks });
    this._segments.set(segmentId, segment);
    segment.state = "loading";

    const ctx = (audioTimeline as any)._audioContext as AudioContext | null;

    try {
      if (audioData && ctx) {
        const cached = this._preloadedBuffers.get(segmentId);
        if (cached) {
          // Decode-ahead hit: this buffer was decoded during ingest, off the
          // critical path, so playback can begin with ~0 decode latency.
          segment.audioBuffer = cached;
          this._preloadedBuffers.delete(segmentId);
        } else {
          segment.audioBuffer = await this._decodeAudioData(audioData, ctx);
        }
        segment.durationMs = segment.audioBuffer.duration * 1000;
      } else {
        if (speechMarks.length > 0) {
          const lastMark = speechMarks[speechMarks.length - 1];
          const markDuration =
            lastMark.duration ??
            (lastMark.end !== undefined && lastMark.start !== undefined
              ? lastMark.end - lastMark.start
              : 0);
          segment.durationMs = Math.max(0, (lastMark.time || 0) + markDuration);
        } else {
          segment.durationMs = this._estimateDuration(text);
        }
      }

      const parsedMarks = speechMarksParser.parse(speechMarks, provider);

      // Register with authoritative AudioTimeline context
      audioTimeline.registerSegment(segmentId, absoluteStartMs, segment.durationMs, parsedMarks);

      segment.state = "ready";
      this._onReadyCallbacks.forEach(cb => cb(segmentId, segment.durationMs));

    } catch (err) {
      console.error(`[TTSPlayer] Failed to load segment ${segmentId}:`, err);
      segment.state = "error";
      segment.durationMs = this._estimateDuration(text);
      audioTimeline.registerSegment(segmentId, absoluteStartMs, segment.durationMs, []);
    }
  }

  /**
   * Play a segment at the correct timeline timestamp.
   */
  public async playSegment(segmentId: string): Promise<void> {
    const segment = this._segments.get(segmentId);
    if (!segment) return;

    // Idempotency guard: a segment is played exactly once. Without this a
    // re-entrant speak() (duplicate event, generation overlap) scheduled a
    // SECOND AudioBufferSourceNode for the same text, so two voices spoke the
    // same sentence over each other — most audible on long equation narration.
    if (segment.state === "playing" || segment.state === "completed") return;

    if (segment.state === "loading") {
      await new Promise<void>((resolve, reject) => {
        const timeout = setTimeout(() => {
          clearInterval(check);
          console.warn(`[TTSPlayer] Segment ${segmentId} loading timed out after 5s`);
          segment.state = segment.audioBuffer ? "ready" : "error";
          resolve();
        }, 5000);
        const check = setInterval(() => {
          if (segment.state !== "loading") {
            clearInterval(check);
            clearTimeout(timeout);
            resolve();
          }
        }, 16);
      });
    }

    const ctx = (audioTimeline as any)._audioContext as AudioContext | null;

    // Decode audioData on-the-fly if AudioContext was unavailable when loading
    if (!segment.audioBuffer && segment.audioData && ctx) {
      try {
        let bufferToDecode: ArrayBuffer;
        if (typeof segment.audioData === "string") {
          const binaryString = atob(segment.audioData);
          const len = binaryString.length;
          const bytes = new Uint8Array(len);
          for (let i = 0; i < len; i++) {
            bytes[i] = binaryString.charCodeAt(i);
          }
          bufferToDecode = bytes.buffer;
        } else {
          bufferToDecode = segment.audioData;
        }
        segment.audioBuffer = await ctx.decodeAudioData(bufferToDecode.slice(0));
        segment.durationMs = segment.audioBuffer.duration * 1000;
        segment.state = "ready";
      } catch (err) {
        console.error(`[TTSPlayer] Failed to decode audioData on the fly for segment ${segmentId}:`, err);
        segment.state = "error";
      }
    }

    if (segment.state === "error") {
      // Only fall back to Web Speech when there is no audio at all (no buffer, no raw data).
      // If the backend sent audio_data but decode failed we log a warning and keep silent
      // (which is still better than two voices speaking simultaneously).
      if (!segment.audioData) {
        this._playWithWebSpeech(segment);
      } else {
        console.warn(`[TTSPlayer] Audio decode failed for segment ${segmentId} — audio muted to avoid double-voice`);
        // Still fire segment-end so the timeline can advance
        setTimeout(() => {
          segment.state = "completed";
          this._onSegmentEndCallbacks.forEach(cb => cb(segment.segmentId));
        }, segment.durationMs || this._estimateDuration(segment.text));
      }
      return;
    }

    segment.state = "playing";

    if (segment.audioBuffer && ctx) {
      // Resume AudioContext if it is suspended (e.g. browser autoplay blocking)
      if (ctx.state === "suspended") {
        try {
          await ctx.resume();
        } catch (e) {
          console.warn("[TTSPlayer] Failed to resume AudioContext in playSegment:", e);
        }
      }
      await this._playWithWebAudio(segment);
    } else {
      this._playWithWebSpeech(segment);
    }
  }

  /**
   * Stop all active playback instances.
   */
  public stop(): void {
    this._scheduledSources.forEach(src => {
      try {
        src.stop();
      } catch (e) {
        /* Execution Guard isolation */
      }
    });
    this._scheduledSources = [];

    if (this._currentUtterance && this._speechSynth) {
      this._speechSynth.cancel();
      this._currentUtterance = null;
    }
  }

  /**
   * Pause current synthetic context.
   */
  public pause(): void {
    if (this._speechSynth) this._speechSynth.pause();
  }

  /**
   * Resume paused context.
   */
  public resume(): void {
    if (this._speechSynth?.paused) this._speechSynth.resume();
  }

  /**
   * Register word boundary callback.
   */
  public onWord(cb: (ev: WordBoundaryEvent) => void): void {
    this._onWordCallbacks.push(cb);
  }

  /**
   * Register segment completion callback.
   */
  public onSegmentEnd(cb: (segmentId: string) => void): void {
    this._onSegmentEndCallbacks.push(cb);
  }

  /**
   * Register ready allocation hook callback.
   */
  public onReady(cb: (segmentId: string, durationMs: number) => void): void {
    this._onReadyCallbacks.push(cb);
  }

  /**
   * Clear active entities.
   */
  public reset(): void {
    this.stop();
    this._segments.clear();
    this._preloadedBuffers.clear();
    this._onWordCallbacks = [];
    this._onSegmentEndCallbacks = [];
    this._onReadyCallbacks = [];
  }

  // ── Private Processing Systems ─────────────────────────────

  /** Base64/ArrayBuffer → decoded AudioBuffer. Shared by preloadAudio + loadSegment. */
  private async _decodeAudioData(audioData: ArrayBuffer | string, ctx: AudioContext): Promise<AudioBuffer> {
    let bufferToDecode: ArrayBuffer;
    if (typeof audioData === "string") {
      const binaryString = atob(audioData);
      const len = binaryString.length;
      const bytes = new Uint8Array(len);
      for (let i = 0; i < len; i++) {
        bytes[i] = binaryString.charCodeAt(i);
      }
      bufferToDecode = bytes.buffer;
    } else {
      bufferToDecode = audioData;
    }
    return ctx.decodeAudioData(bufferToDecode.slice(0));
  }

  private async _playWithWebAudio(segment: TTSSegment): Promise<void> {
    const ctx = (audioTimeline as any)._audioContext as AudioContext | null;
    if (!ctx || !segment.audioBuffer) return;

    if (!this._gainNode) {
      this._gainNode = ctx.createGain();
      this._gainNode.gain.value = this._volume;
      this._gainNode.connect(ctx.destination);
    }

    const source = ctx.createBufferSource();
    source.buffer = segment.audioBuffer;
    source.playbackRate.value = (audioTimeline as any)._playbackRate ?? 1.0;
    source.connect(this._gainNode);

    const now = ctx.currentTime;
    const scheduleOffset = Math.max(0, (segment.absoluteStartMs - audioTimeline.currentTimeMs) / 1000);
    const playAt = now + scheduleOffset;

    // Anchor the master clock BEFORE scheduling audio so no RAF tick sees
    // stale _startAudioContextTime between source.start() and alignClock().
    audioTimeline.alignClock(segment.absoluteStartMs, playAt);

    source.start(playAt);
    this._scheduledSources.push(source);

    source.onended = () => {
      segment.state = "completed";
      this._onSegmentEndCallbacks.forEach(cb => cb(segment.segmentId));
      const idx = this._scheduledSources.indexOf(source);
      if (idx >= 0) this._scheduledSources.splice(idx, 1);
    };

    const timelineSegment = (audioTimeline as any)._segments.get(segment.segmentId);
    if (timelineSegment) {
      for (const mark of (timelineSegment.marks || [])) {
        if (mark.type === "word") {
          const fireAt = playAt + (mark.time / 1000);
          const delayMs = Math.max(0, (fireAt - ctx.currentTime) * 1000 - audioLatencyCompensator.earlyFireMs);
          // mark.duration is in ms from speechMarksParser; never use mark.end - mark.start
          // (those are character byte offsets, not time).
          const wordDurationMs = mark.duration || 200;
          setTimeout(() => {
            this._onWordCallbacks.forEach(cb => cb({
              word: mark.value,
              startMs: mark.absoluteMs,
              endMs: mark.absoluteMs + wordDurationMs,
            }));
          }, delayMs);
        }
      }
    }
  }

  private _playWithWebSpeech(segment: TTSSegment): void {
    const ctx = (audioTimeline as any)._audioContext as AudioContext | null;
    audioTimeline.alignClock(segment.absoluteStartMs, ctx?.currentTime || 0);

    const duration = segment.durationMs || this._estimateDuration(segment.text);

    // Try Web Speech API if available
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      try {
        const utterance = new SpeechSynthesisUtterance(segment.text);
        utterance.rate = 1.0;
        utterance.pitch = 1.0;
        utterance.volume = this._volume;

        const words = segment.text.split(/\s+/).filter(w => w.trim().length > 0);
        const wordsCount = words.length;
        const msPerWord = duration / Math.max(1, wordsCount);
        let wordIndex = 0;

        utterance.onboundary = (event) => {
          if (event.name === "word" && wordIndex < words.length) {
            const nowMs = audioTimeline.currentTimeMs;
            this._onWordCallbacks.forEach(cb => cb({
              word: words[wordIndex] || "",
              startMs: nowMs,
              endMs: nowMs + msPerWord,
            }));
            wordIndex++;
          }
        };

        utterance.onend = () => {
          segment.state = "completed";
          this._onSegmentEndCallbacks.forEach(cb => cb(segment.segmentId));
        };

        utterance.onerror = () => {
          console.warn("[TTSPlayer] WebSpeech utterance error, falling back to silent");
          this._playSilent(segment, duration, words);
        };

        window.speechSynthesis.cancel(); // Clear any pending
        window.speechSynthesis.speak(utterance);
        console.info(`[TTSPlayer] WebSpeech fallback active: "${segment.text.substring(0, 60)}..."`);
        return;
      } catch (e) {
        console.warn("[TTSPlayer] WebSpeech API failed:", e);
      }
    }

    // Final fallback: silent playback with synthetic timing
    console.info(`[TTSPlayer] Silent fallback: "${segment.text.substring(0, 60)}..."`);
    const words = segment.text.split(/\s+/).filter(w => w.trim().length > 0);
    this._playSilent(segment, duration, words);
  }

  private _playSilent(segment: TTSSegment, duration: number, words: string[]): void {
    const msPerWord = duration / Math.max(1, words.length);

    const timer = setTimeout(() => {
      segment.state = "completed";
      this._onSegmentEndCallbacks.forEach(cb => cb(segment.segmentId));
    }, duration);
    this._scheduledSources.push({ stop: () => clearTimeout(timer) });

    words.forEach((word, idx) => {
      const wordTimer = setTimeout(() => {
        const nowMs = audioTimeline.currentTimeMs;
        this._onWordCallbacks.forEach(cb => cb({
          word,
          startMs: nowMs,
          endMs: nowMs + msPerWord,
        }));
      }, idx * msPerWord);
      this._scheduledSources.push({ stop: () => clearTimeout(wordTimer) });
    });
  }

  private _estimateDuration(text: string): number {
    if (!text) return 0;
    const baseMs = Math.floor((text.length / 15.0) * 1000);
    const punctuationPauseMs = (text.split(".").length - 1) * 300 + (text.split(",").length - 1) * 150;
    return baseMs + punctuationPauseMs;
  }
}

// ── Singleton ──────────────────────────────────────────────────
export const ttsPlayer = new TTSPlayer();
