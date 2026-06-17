# audio_planner.py — Authoritative Narration & Phoneme Alignment Planner
#
# v2: Improved speaking rate model
#   • Base rate closer to natural Indian English speaking pace
#   • Sentence-level breathing pauses (600ms between sentences)
#   • Emphasis detection: slow down for key terms, speed up for filler
#   • Difficulty-aware pacing: harder content → slower speaking rate

from typing import Any, Dict, List
import re


class AudioPlanner:
    """
    Authoritative Speech Timeline Planner:
    Responsible for generating exact timestamps for speech segments,
    word segments, and phonemes to support determinism and lip-syncing.
    """

    # Words that signal emphasis — teacher slows down naturally
    _EMPHASIS_WORDS = frozenset({
        "important", "critical", "key", "note", "remember", "notice",
        "therefore", "hence", "because", "since", "however", "but",
        "equals", "means", "defined", "definition", "formula",
        "theorem", "proof", "result", "conclusion", "answer",
    })

    # Filler/connector words — teacher speeds through naturally
    _FILLER_WORDS = frozenset({
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "in", "on", "at", "to", "for", "of", "and", "or", "so",
        "we", "it", "as", "by", "if", "do", "up", "no", "not",
    })

    def split_syllables(self, word: str) -> List[str]:
        """A simple rule-based syllable splitter for English words."""
        vowels = "aeiouyAEIOUY"
        syllables = []
        current = ""
        for idx, char in enumerate(word):
            current += char
            if char in vowels:
                # If next char is a consonant, split
                if idx < len(word) - 1 and word[idx+1] not in vowels:
                    syllables.append(current)
                    current = ""
        if current:
            if syllables:
                syllables[-1] += current
            else:
                syllables.append(current)
        return syllables

    def _word_duration_ms(self, word: str, pacing_multiplier: float) -> int:
        """
        Compute speaking duration for a single word.
        Adjusted from 150+45/char to 130+40/char for more natural pacing,
        with emphasis/filler word detection.
        """
        word_lower = word.lower().strip(".,!?\"'()[]{}:;")
        char_count = len(word_lower)

        # Base: configurable onset + per-character pace (defaults 130ms + 40ms/char).
        from app.config.settings import get_settings
        _s = get_settings()
        base_ms = _s.tts_word_onset_ms + char_count * _s.tts_per_char_ms

        # Emphasis words: slow down 25%
        if word_lower in self._EMPHASIS_WORDS:
            base_ms = int(base_ms * 1.25)
        # Filler words: speed up 15%
        elif word_lower in self._FILLER_WORDS and char_count <= 3:
            base_ms = int(base_ms * 0.85)
        # Long technical words (>8 chars): slightly slower enunciation
        elif char_count > 8:
            base_ms = int(base_ms * 1.1)

        return int(base_ms * pacing_multiplier)

    def _inter_word_gap_ms(self, word: str) -> int:
        """
        Gap between words — longer pauses for punctuation (teacher breathing),
        short gaps for normal flow.
        """
        # Sentence-ending punctuation → 600ms breathing pause
        if word.endswith(('.', '!', '?')):
            return 600
        # Comma/semicolon → 350ms clause pause
        elif word.endswith((',', ';', ':')):
            return 350
        # Em-dash or parenthetical → 250ms
        elif word.endswith(('—', '–', ')')):
            return 250
        # Normal word gap: 70ms
        else:
            return 70

    def plan_speech_narration(self, text: str, pacing_multiplier: float = 1.0) -> Dict[str, Any]:
        """
        Plans narration timeline. In a production pipeline, this maps speech ticks
        using synthesized TTS outputs. Here, we compute precise phonetic and syllable bounds.
        """
        words = text.split()
        speech_events = []
        current_time_ms = 0
        
        for idx, w in enumerate(words):
            word_clean = w.strip(".,!?\"'")
            duration_ms = self._word_duration_ms(w, pacing_multiplier)
            end_time_ms = current_time_ms + duration_ms
            
            # Formulate syllables
            syl_list = self.split_syllables(word_clean)
            syllables = []
            syl_time = current_time_ms
            total_len = sum(len(s) for s in syl_list) or 1
            for syl in syl_list:
                syl_dur = int(duration_ms * (len(syl) / total_len))
                syllables.append({
                    "text": syl,
                    "start_ms": syl_time,
                    "end_ms": syl_time + syl_dur
                })
                syl_time += syl_dur

            # Formulate phoneme timings (base phoneme duration approximation ~60ms)
            phonemes = []
            num_phonemes = max(1, len(word_clean) // 2)
            for j in range(num_phonemes):
                p_dur = duration_ms // num_phonemes
                phonemes.append({
                    "code": f"PH_{word_clean[j*2:(j+1)*2]}".upper(),
                    "start_ms": current_time_ms + j * p_dur,
                    "end_ms": current_time_ms + (j + 1) * p_dur
                })

            speech_events.append({
                "word": word_clean,
                "start_ms": current_time_ms,
                "end_ms": end_time_ms,
                "syllables": syllables,
                "phonemes": phonemes
            })
            
            # Context-aware inter-word gap
            gap = self._inter_word_gap_ms(w)
            current_time_ms = end_time_ms + gap

        return {
            "total_duration_ms": current_time_ms,
            "speech_events": speech_events
        }

audio_planner = AudioPlanner()
