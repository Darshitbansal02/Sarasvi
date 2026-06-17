/**
 * phonemeClock.ts — Sub-Word Temporal Authority
 *
 * Provides phoneme-level timing for ultra-precise synchronization.
 * Used to drive cursor micro-movements that match the rhythm of speech —
 * the subtle hand stillness between words, the slight lift before a
 * stressed syllable, the pen pause at a period.
 *
 * This is what makes cursor motion feel HUMAN — it breathes with speech.
 */

import { audioTimeline } from "./audioTimeline";

// ── Struct & Callback Interfaces ───────────────────────────────

export type MotionHint = "vowel" | "fricative" | "liquid" | "nasal" | "stop";

export interface InputPhoneme {
  phoneme: string;
  startMs: number;
  durationMs: number;
  stress?: boolean;
}

export interface ProcessingPhoneme extends InputPhoneme {
  absoluteMs: number;
  motionHint: MotionHint;
}

export interface StressPatternEntry {
  absoluteMs: number;
  level: number;
}

export interface WordMarkInput {
  value: string;
  time: number;
  duration: number;
  absoluteMs: number;
}

export type PhonemeCallback = (ph: ProcessingPhoneme) => void;
export type SilenceCallback = (silenceDurationMs: number) => void;

// ── Phoneme Categories for Motion Hints ────────────────────────

const PHONEME_MOTION_HINTS: Record<string, string[]> = {
  stops: ["p", "b", "t", "d", "k", "g", "ʔ"],
  fricatives: ["f", "v", "s", "z", "ʃ", "ʒ", "θ", "ð", "h"],
  nasals: ["m", "n", "ŋ"],
  liquids: ["l", "r", "w", "j"],
  vowels: ["a", "e", "i", "o", "u", "æ", "ə", "ɪ", "ʊ", "ɔ"],
};

// ── PhonemeClock Class ─────────────────────────────────────────

export class PhonemeClock {
  private _phonemes: ProcessingPhoneme[];
  private _currentIdx: number;
  private _stressPattern: StressPatternEntry[];
  
  private _onPhonemeCallbacks: PhonemeCallback[];
  private _onStressCallbacks: PhonemeCallback[];
  private _onSilenceCallbacks: SilenceCallback[];

  private _lastSpeechMs: number;
  private _silenceThresholdMs: number;
  private _frameHandle: any;

  constructor() {
    this._phonemes = [];
    this._currentIdx = 0;
    this._stressPattern = [];

    this._onPhonemeCallbacks = [];
    this._onStressCallbacks = [];
    this._onSilenceCallbacks = [];

    this._lastSpeechMs = 0;
    this._silenceThresholdMs = 300; // Longer than this → draw pause
    this._frameHandle = null;
  }

  /**
   * Load phonemes for a speech segment.
   */
  public loadPhonemes(phonemes: InputPhoneme[], segmentStartMs: number): void {
    this._phonemes = phonemes.map(p => ({
      ...p,
      absoluteMs: segmentStartMs + p.startMs,
      motionHint: this._classifyPhoneme(p.phoneme),
    }));
    this._currentIdx = 0;
    this._computeStressPattern();
  }

  /**
   * Generate approximate phoneme timing from word marks.
   * Used when actual phoneme data is unavailable.
   */
  public synthesizeFromWords(wordMarks: WordMarkInput[]): ProcessingPhoneme[] {
    const phonemes: ProcessingPhoneme[] = [];
    
    for (const mark of wordMarks) {
      const syllables = this._estimateSyllables(mark.value);
      const msPerSyllable = mark.duration / Math.max(1, syllables.length);
      
      syllables.forEach((syl, idx) => {
        phonemes.push({
          phoneme: syl,
          startMs: idx * msPerSyllable,
          absoluteMs: mark.absoluteMs + idx * msPerSyllable,
          durationMs: msPerSyllable * 0.85,
          motionHint: this._classifyPhoneme(syl),
        });
      });
    }
    
    this._phonemes = phonemes;
    this._currentIdx = 0;
    return phonemes;
  }

  /**
   * Tick — returns any phoneme events due this frame.
   */
  public tick(absoluteTimeMs: number): ProcessingPhoneme[] {
    const fired: ProcessingPhoneme[] = [];

    while (this._currentIdx < this._phonemes.length) {
      const ph = this._phonemes[this._currentIdx];
      if (ph.absoluteMs <= absoluteTimeMs) {
        fired.push(ph);
        this._currentIdx++;
        this._lastSpeechMs = absoluteTimeMs;

        this._onPhonemeCallbacks.forEach(cb => cb(ph));

        // Stress events
        if (ph.stress) {
          this._onStressCallbacks.forEach(cb => cb(ph));
        }
      } else {
        break;
      }
    }

    // Silence detection
    if (this._lastSpeechMs > 0 && absoluteTimeMs - this._lastSpeechMs > this._silenceThresholdMs) {
      this._onSilenceCallbacks.forEach(cb => cb(absoluteTimeMs - this._lastSpeechMs));
      this._lastSpeechMs = absoluteTimeMs; // Prevent repeated triggers
    }

    return fired;
  }

  /**
   * Get the current "pen rhythm" — a 0..1 value representing
   * how much the cursor should be moving right now.
   * High on vowels/fricatives, low on stops/silence.
   */
  public getPenRhythm(absoluteTimeMs: number): number {
    if (this._phonemes.length === 0) return 0.5;

    let active: ProcessingPhoneme | null = null;
    for (let i = this._currentIdx - 1; i >= 0 && i >= this._currentIdx - 3; i--) {
      const ph = this._phonemes[i];
      if (ph.absoluteMs <= absoluteTimeMs && absoluteTimeMs < ph.absoluteMs + ph.durationMs) {
        active = ph;
        break;
      }
    }

    if (!active) return 0.2; // Between phonemes → pen slower

    switch (active.motionHint) {
      case "vowel": return 0.9;
      case "fricative": return 0.7;
      case "liquid": return 0.6;
      case "nasal": return 0.4;
      case "stop": return 0.1; // Brief liftoff pause
      default: return 0.5;
    }
  }

  /**
   * Get the stress level at current time.
   * Used to modulate pen pressure and stroke thickness.
   */
  public getStressLevel(absoluteTimeMs: number): number {
    if (this._stressPattern.length === 0) return 0.5;

    let nearest: StressPatternEntry | null = null;
    let minDist = Infinity;
    
    for (const s of this._stressPattern) {
      const dist = Math.abs(s.absoluteMs - absoluteTimeMs);
      if (dist < minDist) {
        minDist = dist;
        nearest = s;
      }
    }

    if (!nearest || minDist > 500) return 0.5;
    // Envelope decay: full stress at 0ms delta, zero baseline at 500ms
    return nearest.level * Math.max(0, 1 - minDist / 500);
  }

  /**
   * Register a phoneme event callback.
   */
  public onPhoneme(cb: PhonemeCallback): void {
    this._onPhonemeCallbacks.push(cb);
  }

  /**
   * Register a stress event callback.
   */
  public onStress(cb: PhonemeCallback): void {
    this._onStressCallbacks.push(cb);
  }

  /**
   * Register a silence detection callback.
   */
  public onSilence(cb: SilenceCallback): void {
    this._onSilenceCallbacks.push(cb);
  }

  /**
   * Reset timeline structural states.
   */
  public reset(): void {
    this._phonemes = [];
    this._currentIdx = 0;
    this._stressPattern = [];
    this._lastSpeechMs = 0;
  }

  // ── Private Heuristic Helpers ──────────────────────────────

  private _classifyPhoneme(phoneme: string): MotionHint {
    const p = phoneme.toLowerCase();
    for (const [cat, phonemes] of Object.entries(PHONEME_MOTION_HINTS)) {
      if (phonemes.some(ph => p.includes(ph))) {
        return cat.slice(0, -1) as MotionHint; // Remove trailing 's' to conform to literal type
      }
    }
    return "vowel";
  }

  private _estimateSyllables(word: string): string[] {
    const cleaned = word.toLowerCase().replace(/[^a-z]/g, "");
    if (!cleaned) return [word];
    const vowelGroups = cleaned.match(/[aeiouy]+/g) || [cleaned[0]];
    return vowelGroups.slice(0, Math.max(1, Math.ceil(cleaned.length / 3)));
  }

  private _computeStressPattern(): void {
    let stressCounter = 0;
    for (const ph of this._phonemes) {
      if (ph.motionHint === "vowel") {
        stressCounter++;
        if (stressCounter % 3 === 0) {
          this._stressPattern.push({
            absoluteMs: ph.absoluteMs,
            level: 0.7 + (stressCounter % 6 === 0 ? 0.3 : 0), // Every 6th vowel maps a primary accent stress boundary
          });
        }
      }
    }
  }
}

// ── Singleton ──────────────────────────────────────────────────
export const phonemeClock = new PhonemeClock();