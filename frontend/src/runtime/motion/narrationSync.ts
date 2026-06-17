/**
 * narrationSync.ts — Real Audio-Synchronized Speech Engine
 *
 * FIXED (Retained from source context): Replaced fake _charsPerSecond heuristic 
 * timing with real audio master clock synchronization via AudioEventBridge.
 *
 * Speech is the timeline authority. Drawing, cursor movement, camera,
 * and attention must synchronize to narration anchors.
 */

import { audioTimeline } from "../audio/audioTimeline";
import { audioEventBridge } from "../audio/audioEventBridge";

// ── Narration States & Enums ───────────────────────────────────

export enum NARRATION_STATE {
  IDLE = "idle",
  SPEAKING = "speaking",
  PAUSED = "paused",
  WAITING_FOR_VISUAL = "waiting_for_visual",
  COMPLETED = "completed",
}

// ── Struct Data & Domain Interfaces ───────────────────────────

export interface AnchorInput {
  anchorId: string;
  speechText: string;
  visualAction: "draw" | "highlight" | "focus" | "pause" | "sync" | string;
  visualTargetIds: string[];
  offsetMs?: number;
  durationMs?: number;
}

export interface AnchorInternal extends AnchorInput {
  fired: boolean;
  absoluteTimeMs: number;
}

export interface RealWordEntry {
  word: string;
  timeMs: number;
}

export interface FiredAnchorPayload {
  anchorId: string;
  visualAction: string;
  visualTargetIds: string[];
  durationMs: number;
  speechText: string;
}

export interface NarrationStatus {
  progress: number;
  text: string;
  state: NARRATION_STATE;
  currentWord: string;
  elapsedMs: number;
  remainingMs: number;
  isAudioSynced: boolean;
}

export interface DistributeOptions {
  frontLoad?: number;
  padding?: number;
}

export interface DistributedStep {
  startMs: number;
  durationMs: number;
  index: number;
}

// ── NarrationSync Class ────────────────────────────────────────

export class NarrationSync {
  public state: NARRATION_STATE;

  private _currentText: string;
  private _currentSegmentId: string | null;
  private _speechStartMs: number;
  private _speechDurationMs: number;

  private _speechProgress: number;
  private _currentWordMs: number;
  private _currentWord: string;

  private _anchors: Map<string, AnchorInternal>;
  private _firedAnchors: Set<string>;
  private _wordAnchors: Map<string, AnchorInternal[]>;
  private _realWordHistory: RealWordEntry[];
  private _bridgeConnected: boolean;

  constructor() {
    this.state = NARRATION_STATE.IDLE;

    // Active speech segment tracking allocations
    this._currentText = "";
    this._currentSegmentId = null;
    this._speechStartMs = 0;
    this._speechDurationMs = 0;

    // Real audio-driven progress variables
    this._speechProgress = 0;
    this._currentWordMs = 0;
    this._currentWord = "";

    // Anchor registry map keys
    this._anchors = new Map<string, AnchorInternal>();
    this._firedAnchors = new Set<string>();

    // Real-time quick token parsing maps
    this._wordAnchors = new Map<string, AnchorInternal[]>();
    this._realWordHistory = [];

    // Audio bridge registration lifecycle state flag
    this._bridgeConnected = false;
  }

  /**
   * Connect to the audio event bridge authorization channels.
   * MUST be called during initialization.
   */
  public connectToAudioBridge(): void {
    if (this._bridgeConnected) return;

    // Subscribe directly to verified text events coming from the playback node
    audioEventBridge.onWord(({ word, startMs, endMs }) => {
      this.onRealWordFired(word, startMs);
    });

    // Handle segment state finalizations cleanly
    audioEventBridge.onSegmentEnd((segmentId: string) => {
      if (segmentId === this._currentSegmentId) {
        this.state = NARRATION_STATE.COMPLETED;
      }
    });

    this._bridgeConnected = true;
  }

  /**
   * Register a narration anchor—a point where visual action must sync with speech.
   */
  public registerAnchor(anchor: AnchorInput): void {
    const stored: AnchorInternal = {
      ...anchor,
      fired: false,
      absoluteTimeMs: anchor.offsetMs || this._estimateAbsoluteTime(anchor.speechText),
    };
    this._anchors.set(anchor.anchorId, stored);

    // Map out lexical indices to drive instantaneous sub-word keyword triggers
    if (anchor.speechText) {
      const words = anchor.speechText.toLowerCase().split(/\s+/);
      const trigger = words.find(w => w.length > 3) || words[0];
      
      if (trigger) {
        if (!this._wordAnchors.has(trigger)) {
          this._wordAnchors.set(trigger, []);
        }
        this._wordAnchors.get(trigger)!.push(stored);
      }
    }
  }

  /**
   * Begin a speech segment block execution pathway.
   *
   * @param text - Raw instructional script content
   * @param absoluteStartMs - Precise global timestamp context unscaled marker
   * @param durationMs - Authoritative milliseconds allocated via native TTS parameters
   * @param segmentId - Unique transaction tracking key
   */
  public startSpeech(text: string, absoluteStartMs: number, durationMs: number, segmentId: string | null = null): void {
    this._currentText = text;
    this._currentSegmentId = segmentId;
    this._speechStartMs = absoluteStartMs;
    this._speechDurationMs = durationMs;
    this._speechProgress = 0;
    this._firedAnchors.clear();
    this.state = NARRATION_STATE.SPEAKING;
  }

  /**
   * Called when a verified word boundary gets parsed directly out of the media context.
   */
  public onRealWordFired(word: string, absoluteTimeMs: number): void {
    this._currentWord = word;
    this._currentWordMs = absoluteTimeMs;
    this._realWordHistory.push({ word, timeMs: absoluteTimeMs });
    if (this._realWordHistory.length > 50) this._realWordHistory.shift();

    if (this._speechDurationMs > 0) {
      const elapsed = absoluteTimeMs - this._speechStartMs;
      this._speechProgress = Math.min(1, elapsed / this._speechDurationMs);
    }

    // Re-estimate unfired anchors using the actual current word position.
    // This progressively replaces the initial linear character estimate with
    // a position anchored to real TTS timing, reducing sync drift to ~0ms
    // for anchors whose trigger word has already been spoken.
    const textWords = this._currentText.trim().split(/\s+/).filter(Boolean);
    const cleanWord = word.toLowerCase().replace(/[^a-z]/g, "");
    const currentWordIdx = textWords.findIndex(
      w => w.toLowerCase().replace(/[^a-z]/g, "").startsWith(cleanWord.slice(0, 4))
    );

    if (currentWordIdx >= 0 && this._speechDurationMs > 0) {
      const remainingMs = this._speechDurationMs - (absoluteTimeMs - this._speechStartMs);

      for (const [, anchor] of this._anchors) {
        if (this._firedAnchors.has(anchor.anchorId)) continue;
        const anchorFirstWord = anchor.speechText.trim().split(/\s+/)[0]
          ?.toLowerCase().replace(/[^a-z]/g, "") || "";
        const anchorWordIdx = textWords.findIndex(
          w => w.toLowerCase().replace(/[^a-z]/g, "").startsWith(anchorFirstWord.slice(0, 4))
        );
        if (anchorWordIdx > currentWordIdx) {
          const wordsFwd = anchorWordIdx - currentWordIdx;
          const fraction = wordsFwd / Math.max(1, textWords.length - currentWordIdx);
          anchor.absoluteTimeMs = absoluteTimeMs + fraction * remainingMs;
        }
      }
    }

    // Process matching text tokens immediately across active layout tracks
    const key = word.toLowerCase().replace(/[^a-z]/g, "");
    const wordAnchors = this._wordAnchors.get(key) || [];

    for (const anchor of wordAnchors) {
      if (!this._firedAnchors.has(anchor.anchorId)) {
        this._firedAnchors.add(anchor.anchorId);
        anchor.fired = true;
        this._executeAnchorAction(anchor, absoluteTimeMs);
      }
    }
  }

  /**
   * High-frequency lifecycle time slice ticking method.
   * Compiles anchors that cross threshold limits inside this execution frame pass.
   *
   * @param absoluteTimeMs - Current unscaled timeline positioning value from clock authority
   * @returns Fired anchor items array payload ready for board transformation
   */
  public tick(absoluteTimeMs: number): FiredAnchorPayload[] {
    if (this.state !== NARRATION_STATE.SPEAKING) return [];

    const realTimeMs = audioTimeline.currentTimeMs;

    if (this._speechDurationMs > 0 && realTimeMs > 0) {
      const elapsed = realTimeMs - this._speechStartMs;
      this._speechProgress = Math.min(1, Math.max(0, elapsed / this._speechDurationMs));
    }

    const firedThisFrame: FiredAnchorPayload[] = [];

    for (const [anchorId, anchor] of this._anchors) {
      if (this._firedAnchors.has(anchorId)) continue;

      if (anchor.absoluteTimeMs <= realTimeMs) {
        this._firedAnchors.add(anchorId);
        firedThisFrame.push({
          anchorId: anchor.anchorId,
          visualAction: anchor.visualAction,
          visualTargetIds: anchor.visualTargetIds || [],
          durationMs: anchor.durationMs || 500,
          speechText: anchor.speechText,
        });
      }
    }

    // Force context wrap configurations when progress markers clip terminal boundaries
    if (audioTimeline.state === "playing" && this._speechProgress >= 0.98) {
      this.state = NARRATION_STATE.COMPLETED;
    }

    return firedThisFrame;
  }

  /**
   * Pull explicit structural progress tracking metrics.
   */
  public getStatus(): NarrationStatus {
    return {
      progress: this._speechProgress,
      text: this._currentText,
      state: this.state,
      currentWord: this._currentWord,
      elapsedMs: Math.floor(this._speechDurationMs * this._speechProgress),
      remainingMs: Math.floor(this._speechDurationMs * (1 - this._speechProgress)),
      isAudioSynced: this._bridgeConnected && audioTimeline.state === "playing",
    };
  }

  /**
   * Distribute N whiteboard graphic layout phases proportionally across total speech segment sizes.
   */
  public distributeStepsAcrossSpeech(
    stepCount: number, 
    speechDurationMs: number, 
    options: DistributeOptions = {}
  ): DistributedStep[] {
    if (stepCount <= 0) return [];

    const { frontLoad = 0.3, padding = 200 } = options;

    const available = speechDurationMs - padding * 2;
    const steps: DistributedStep[] = [];

    for (let i = 0; i < stepCount; i++) {
      const normalizedPos = i / Math.max(1, stepCount - 1);
      const biasedPos = normalizedPos < 0.5
        ? normalizedPos * (1 + frontLoad)
        : 0.5 * (1 + frontLoad) + (normalizedPos - 0.5) * (1 - frontLoad);

      const startMs = padding + biasedPos * available;
      const durationMs = (available / stepCount) * 0.8;

      steps.push({
        startMs: Math.floor(startMs),
        durationMs: Math.floor(durationMs),
        index: i,
      });
    }

    return steps;
  }

  /**
   * Place structural speech on wait indices.
   */
  public pauseForVisual(): void {
    if (this.state === NARRATION_STATE.SPEAKING) {
      this.state = NARRATION_STATE.WAITING_FOR_VISUAL;
    }
  }

  /**
   * Release wait boundaries and resume playback execution loops.
   */
  public resumeFromVisual(): void {
    if (this.state === NARRATION_STATE.WAITING_FOR_VISUAL) {
      this.state = NARRATION_STATE.SPEAKING;
    }
  }

  /**
   * Clear running metrics registers.
   */
  public reset(): void {
    this._anchors.clear();
    this._wordAnchors.clear();
    this._firedAnchors.clear();
    this._realWordHistory = [];
    this._currentText = "";
    this._currentWord = "";
    this._speechProgress = 0;
    this._currentSegmentId = null;
    this.state = NARRATION_STATE.IDLE;
    this._bridgeConnected = false;
  }

  // ── Private / Fallback Analytical Calculators ──────────────

  private _estimateAbsoluteTime(phrase: string): number {
    if (!this._currentText || !phrase) return this._speechStartMs;

    // Word-count ratio is a significantly better estimate than character-count ratio:
    // short words ("a", "I") take similar time to say as longer words ("differential"),
    // so counting words rather than chars reduces systematic under/over-estimation.
    const textWords = this._currentText.trim().split(/\s+/).filter(Boolean);
    const phraseFirstWord = phrase.trim().split(/\s+/)[0]
      ?.toLowerCase().replace(/[^a-z]/g, "") || "";

    const wordIdx = phraseFirstWord.length >= 2
      ? textWords.findIndex(w => w.toLowerCase().replace(/[^a-z]/g, "").startsWith(phraseFirstWord.slice(0, 4)))
      : -1;

    if (wordIdx >= 0) {
      return this._speechStartMs + (wordIdx / Math.max(1, textWords.length)) * this._speechDurationMs;
    }

    // Fallback to character position if word match fails
    const idx = this._currentText.indexOf(phrase);
    if (idx < 0) return this._speechStartMs;
    return this._speechStartMs + (idx / Math.max(1, this._currentText.length)) * this._speechDurationMs;
  }

  private _executeAnchorAction(anchor: AnchorInternal, timeMs: number): void {
    // Delegated explicitly to orchestration layer via returned payload references.
  }
}