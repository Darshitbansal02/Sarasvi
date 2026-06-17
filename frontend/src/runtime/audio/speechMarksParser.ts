/**
 * speechMarksParser.ts — Multi-Provider Speech Mark Normalization
 *
 * Normalizes word/phoneme timing data from any TTS provider into a
 * unified format that the AudioTimeline and NarrationSync can consume.
 *
 * Supported providers:
 * - AWS Polly (SSML/SpeechMarks JSON)
 * - ElevenLabs (alignment JSON)
 * - Azure Neural TTS (word boundary events)
 * - OpenAI TTS (no native marks → use Web Speech boundary events)
 * - Browser Web Speech API (boundary events → normalized)
 */

// ── Type Specifications ───────────────────────────────────────

export type SpeechMarkType = "word" | "phoneme" | "sentence" | "ssml" | string;
export type TTSProvider = "polly" | "elevenlabs" | "azure" | "openai" | "edge_tts" | "generic" | string;

export interface NormalizedSpeechMark {
  type: SpeechMarkType;
  value: string;
  time: number;
  start: number;
  end: number;
  duration: number;
  absoluteMs: number;
}

// Raw Provider Specifications
export interface RawPollyMark {
  type: string;
  value: string;
  time: number;
  start: number;
  end: number;
}

export interface RawElevenLabsAlignment {
  characters: string[];
  character_start_times_seconds: number[];
  character_end_times_seconds: number[];
}

export interface RawElevenLabsPayload {
  alignment?: RawElevenLabsAlignment;
  normalized_alignment?: RawElevenLabsAlignment;
}

export interface RawAzureMark {
  "Audio.Offset"?: number;
  "Audio.Duration"?: number;
  Word?: string;
  text?: string;
  TextOffset?: number;
}

export interface RawOpenAIMark {
  transcript: string;
  audio_start_ms?: number;
  audio_end_ms?: number;
}

export interface RawGenericMark {
  type?: string;
  value?: string;
  word?: string;
  text?: string;
  time?: number;
  offset?: number;
  start_ms?: number;
  start?: number;
  char_start?: number;
  end?: number;
  char_end?: number;
  duration?: number;
}

// ── SpeechMarksParser Class ────────────────────────────────────

class SpeechMarksParser {
  /**
   * Parse speech marks from any provider into normalized format.
   *
   * @param rawMarks - Raw marks payload (format depends on provider)
   * @param provider - TTS provider identifier
   * @returns Normalized marks array
   */
  public parse(rawMarks: any, provider: TTSProvider): NormalizedSpeechMark[] {
    if (!rawMarks || (Array.isArray(rawMarks) && rawMarks.length === 0)) {
      return [];
    }

    switch (provider) {
      case "polly":
        return this._parsePolly(rawMarks);
      case "elevenlabs":
        return this._parseElevenLabs(rawMarks);
      case "azure":
        return this._parseAzure(rawMarks);
      case "openai":
        return this._parseOpenAI(rawMarks);
      case "edge_tts":
        // Edge-TTS word boundary events arrive as an array of
        // {type:"word", value:"...", time:<ms>, start:<charOffset>, end:<charEnd>}
        // objects, which is exactly the _parseGeneric expected shape.
        return this._parseGeneric(rawMarks);
      default:
        return this._parseGeneric(rawMarks);
    }
  }

  /**
   * Generate heuristic speech marks from plain text.
   * Used when no TTS alignment data is available.
   */
  public generateFromText(text: string, estimatedDurationMs: number): NormalizedSpeechMark[] {
    if (!text) return [];

    const words = text.split(/\s+/);
    const marks: NormalizedSpeechMark[] = [];
    let charPos = 0;
    let timeMs = 0;

    // Teacher speech rate: ~130-160 wpm average
    const avgMsPerWord = estimatedDurationMs / Math.max(1, words.length);

    for (const word of words) {
      if (!word.trim()) continue;

      // Adjust timing for word length (longer words take more time)
      const lengthFactor = Math.max(0.5, Math.min(2.0, word.length / 5));
      const wordDuration = avgMsPerWord * lengthFactor;

      // Adjust for punctuation pauses
      let pauseAfter = 0;
      if (/[.!?]$/.test(word)) pauseAfter = 300;
      else if (/[,;:]$/.test(word)) pauseAfter = 150;

      const cleanWord = word.replace(/[^a-zA-Z0-9'-]/g, "");
      const wordIdx = text.indexOf(word, charPos);

      marks.push({
        type: "word",
        value: cleanWord,
        time: Math.floor(timeMs),
        start: wordIdx,
        end: wordIdx + word.length,
        duration: Math.floor(wordDuration),
        absoluteMs: 0,
      });

      timeMs += wordDuration + pauseAfter;
      charPos = wordIdx + word.length;
    }

    return marks;
  }

  // ── Provider-Specific Parsers ──────────────────────────────

  /**
   * AWS Polly: NDJSON stream of { time, type, start, end, value }
   */
  private _parsePolly(marks: string | RawPollyMark[]): NormalizedSpeechMark[] {
    let parsed: any[] = [];
    if (typeof marks === "string") {
      parsed = marks
        .trim()
        .split("\n")
        .map(line => {
          try {
            return JSON.parse(line);
          } catch {
            return null;
          }
        })
        .filter((item): item is RawPollyMark => item !== null);
    } else if (Array.isArray(marks)) {
      parsed = marks;
    }

    return parsed
      .filter(m => m && (m.type === "word" || m.type === "sentence"))
      .map((m, idx, arr) => {
        // Polly start/end are BYTE OFFSETS into the input text, not time values.
        // Compute duration from inter-mark time instead.
        const nextMark = arr[idx + 1];
        const duration = nextMark ? Math.max(50, nextMark.time - m.time) : 300;
        return {
          type: m.type,
          value: m.value,
          time: m.time,
          start: m.start,
          end: m.end,
          duration,
          absoluteMs: 0,
        };
      });
  }

  /**
   * ElevenLabs: Character index translation array groupings
   */
  private _parseElevenLabs(raw: RawElevenLabsPayload): NormalizedSpeechMark[] {
    const alignment = raw?.alignment || raw?.normalized_alignment || null;
    if (!alignment) return [];

    const chars = alignment.characters || [];
    const starts = alignment.character_start_times_seconds || [];
    const ends = alignment.character_end_times_seconds || [];

    if (chars.length === 0) return [];

    const words: NormalizedSpeechMark[] = [];
    let currentWord = "";
    let wordStart = 0;
    let wordEnd = 0;
    let wordStartChar = 0;

    for (let i = 0; i < chars.length; i++) {
      const ch = chars[i];
      if (ch === " " || i === chars.length - 1) {
        if (i === chars.length - 1 && ch !== " ") {
          currentWord += ch;
          wordEnd = ends[i] * 1000;
        }
        if (currentWord.trim()) {
          words.push({
            type: "word",
            value: currentWord.trim(),
            time: Math.floor(wordStart),
            start: wordStartChar,
            end: wordStartChar + currentWord.length,
            duration: Math.floor(wordEnd - wordStart),
            absoluteMs: 0,
          });
        }
        currentWord = "";
        wordStartChar = i + 1;
        wordStart = (starts[i + 1] || 0) * 1000;
      } else {
        if (!currentWord) {
          wordStart = starts[i] * 1000;
          wordStartChar = i;
        }
        currentWord += ch;
        wordEnd = ends[i] * 1000;
      }
    }

    return words;
  }

  /**
   * Azure Neural TTS: 100-nanosecond tick conversion layout tracking
   */
  private _parseAzure(marks: RawAzureMark[]): NormalizedSpeechMark[] {
    if (!Array.isArray(marks)) return [];

    return marks.map((m, idx) => {
      const timeMs = (m["Audio.Offset"] || 0) / 10000; // 10,000 ticks = 1 ms
      const durationMs = (m["Audio.Duration"] || 0) / 10000;
      const textOffset = m.TextOffset !== undefined ? m.TextOffset : idx * 5;
      const wordValue = m["Word"] || m.text || "";

      return {
        type: "word",
        value: wordValue,
        time: Math.floor(timeMs),
        start: textOffset,
        end: textOffset + wordValue.length,
        duration: Math.floor(durationMs),
        absoluteMs: 0,
      };
    });
  }

  /**
   * OpenAI TTS: Realtime layout structural parser fallback
   */
  private _parseOpenAI(raw: RawOpenAIMark[]): NormalizedSpeechMark[] {
    if (Array.isArray(raw) && raw.length > 0 && raw[0].transcript) {
      return raw.map(segment => {
        const start = segment.audio_start_ms || 0;
        const end = segment.audio_end_ms || start + 200;
        
        return {
          type: "word",
          value: segment.transcript,
          time: Math.floor(start),
          start: 0,
          end: segment.transcript.length,
          duration: Math.floor(end - start),
          absoluteMs: 0,
        };
      });
    }
    return [];
  }

  /**
   * Generic normalization for untracked custom pipelines
   */
  private _parseGeneric(marks: RawGenericMark[]): NormalizedSpeechMark[] {
    if (!Array.isArray(marks)) return [];
    
    return marks.map(m => {
      const type = m.type || "word";
      const value = m.value || m.word || m.text || "";
      const time = m.time !== undefined ? m.time : (m.offset !== undefined ? m.offset : (m.start_ms !== undefined ? m.start_ms : 0));
      const start = m.start !== undefined ? m.start : (m.char_start !== undefined ? m.char_start : 0);
      const end = m.end !== undefined ? m.end : (m.char_end !== undefined ? m.char_end : 0);
      // m.start/end are CHARACTER offsets, not time — never use them as ms duration.
      // Use m.duration if present; otherwise a safe 200ms default.
      const duration = Math.max(50, m.duration !== undefined ? m.duration : 200);

      return {
        type,
        value,
        time,
        start,
        end,
        duration,
        absoluteMs: 0,
      };
    });
  }
}

// ── Singleton ──────────────────────────────────────────────────
export const speechMarksParser = new SpeechMarksParser();
