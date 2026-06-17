"""
SYMBOL_WORD_MAP — data, not logic.

Maps LaTeX/math glyphs to the spoken words a TTS engine emits for them, used to
align handwritten stroke reveals to word-boundary timestamps. Kept as a standalone
data module (rather than inline in the generation pipeline) so it is a single,
overridable source — e.g. swap/extend it for non-English narration without
touching pipeline code.
"""

from __future__ import annotations

SYMBOL_WORD_MAP: dict[str, list[str]] = {
    "=": ["equals", "equal", "is", "gives", "yields", "to", "बराबर", "barabar"],
    "+": ["plus", "add", "addition", "धन", "dhan", "प्लस"],
    "-": ["minus", "subtract", "difference", "ऋण", "rin", "माइनस"],
    "*": ["times", "multiply", "multiplied", "गुणा", "guna", "गुना"],
    "/": ["divided", "over", "fraction", "भाग", "bhag", "बटा", "bata"],
    "∫": ["integral", "integrate", "integration", "समाकलन", "samakalan"],
    "∑": ["sum", "summation", "sigma", "योग", "yog"],
    "sin": ["sine", "sin", "साइन"],
    "cos": ["cosine", "cos", "कॉस"],
    "tan": ["tangent", "tan", "टैन"],
}
