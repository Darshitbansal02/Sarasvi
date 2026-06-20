# glyph_compiler.py — Authoritative Math LaTeX Layout & Stroke Compiler

import math
import uuid
import re
from typing import Any, Dict, List, Optional, Tuple
from app.services.vector_glyphs import get_glyph

# --- LaTeX normalizations and parsing rules ---

SYMBOL_MAP = {
    # Operators
    "\\int": "∫", "\\sum": "∑", "\\prod": "∏",
    # Relations
    "\\le": "≤", "\\leq": "≤", "\\ge": "≥", "\\geq": "≥",
    "\\neq": "≠", "\\approx": "≈", "\\in": "∈",
    "\\subset": "⊂", "\\supset": "⊃", "\\perp": "⊥",
    # Arrows
    "\\rightarrow": "→", "\\Rightarrow": "⇒", "\\leftrightarrow": "↔",
    "\\implies": "⇒",
    # Set theory
    "\\cup": "∪", "\\cap": "∩", "\\forall": "∀", "\\exists": "∃",
    # Misc math
    "\\partial": "∂", "\\nabla": "∇", "\\infty": "∞",
    "\\cdot": "·", "\\times": "×", "\\pm": "±", "\\mp": "∓",
    "\\oint": "∮", "\\oiint": "∬", "\\iint": "∬",
    "\\gg": "≫", "\\ll": "≪",
    "\\odot": "⊙", "\\ominus": "⊖", "\\oslash": "⊘",
    # Greek lowercase
    "\\alpha": "α", "\\beta": "β", "\\gamma": "γ",
    "\\delta": "δ", "\\epsilon": "ε", "\\zeta": "ζ",
    "\\eta": "η", "\\theta": "θ", "\\iota": "iota",
    "\\kappa": "κ", "\\lambda": "λ", "\\mu": "μ",
    "\\nu": "nu", "\\xi": "xi", "\\pi": "π",
    "\\rho": "ρ", "\\sigma": "σ", "\\tau": "τ",
    "\\phi": "φ", "\\chi": "chi", "\\psi": "ψ", "\\omega": "ω",
    # Greek uppercase — mapped to dedicated letter-form glyphs
    "\\Gamma": "Γ", "\\Delta": "Δ", "\\Theta": "Θ",
    "\\Lambda": "Λ", "\\Xi": "Ξ", "\\Pi": "Π",
    "\\Sigma": "Σ", "\\Phi": "Φ", "\\Psi": "Ψ", "\\Omega": "Ω",
    "\\Upsilon": "Υ",
    # Braces
    "\\{": "{", "\\}": "}",
    # Degree
    "\\degree": "°", "\\circ": "°",
    # Bracket delimiters (used after \left / \right)
    "\\lfloor": "⌊", "\\rfloor": "⌋",
    "\\lceil": "⌈", "\\rceil": "⌉",
    "\\langle": "⟨", "\\rangle": "⟩",
    "\\lvert": "|", "\\rvert": "|",
    "\\lVert": "∥", "\\rVert": "∥", "\\|": "∥",
    # Relations
    "\\mid": "|", "\\vert": "|", "\\Vert": "∥",
    "\\sim": "∼", "\\cong": "≅", "\\propto": "∝",
    "\\equiv": "≡", "\\simeq": "≃", "\\asymp": "≍",
    "\\doteq": "≐", "\\triangleq": "≜",
    # Arrows (additional)
    "\\leftarrow": "←", "\\gets": "←", "\\Leftarrow": "⇐",
    "\\to": "→", "\\Leftrightarrow": "⟺", "\\iff": "⟺",
    "\\mapsto": "↦", "\\hookrightarrow": "↪", "\\longrightarrow": "→",
    "\\longleftarrow": "←", "\\longleftrightarrow": "↔",
    "\\rightleftharpoons": "⇌", "\\leftrightharpoons": "⇌",
    "\\uparrow": "↑", "\\downarrow": "↓",
    "\\Uparrow": "⇑", "\\Downarrow": "⇓",
    "\\nearrow": "↑", "\\searrow": "↓",  # diagonal — fallback to vertical
    # Sets & Logic
    "\\emptyset": "∅", "\\varnothing": "∅",
    "\\therefore": "∴", "\\because": "∵",
    # Algebraic ops
    "\\oplus": "⊕", "\\otimes": "⊗", "\\ominus": "⊖", "\\oslash": "⊘",
    "\\odot": "⊙", "\\wedge": "∧", "\\vee": "∨", "\\neg": "¬",
    # Ellipsis
    "\\cdots": "⋯", "\\ldots": "…", "\\vdots": "⋮", "\\ddots": "⋱",
    # Misc math
    "\\prime": "′", "\\hbar": "ℏ", "\\ell": "ℓ", "\\wp": "℘", "\\aleph": "ℵ",
    # More Greek
    "\\iota": "ι", "\\kappa": "κ", "\\upsilon": "υ",
    "\\varphi": "φ", "\\varepsilon": "ε", "\\vartheta": "θ",
    "\\varsigma": "ς", "\\varrho": "ρ", "\\varpi": "π",
    "\\Gamma": "Γ", "\\Delta": "Δ", "\\Theta": "Θ",
    "\\Lambda": "Λ", "\\Xi": "Ξ", "\\Pi": "Π",
    "\\Sigma": "Σ", "\\Phi": "Φ", "\\Psi": "Ψ", "\\Omega": "Ω",
    "\\Upsilon": "Υ",
}

# Map JSON-mangled control chars back to their LaTeX symbols.
# When the LLM writes \rightarrow with a single backslash in JSON, Python's
# json.loads converts \r → chr(13), leaving chr(13)+"ightarrow" in the string.
# Same issue for \frac (\f→chr(12)), \beta (\b→chr(8)), \theta (\t→chr(9)),
# \nabla (\n→chr(10)), etc.
_JSON_CTRL_LETTER = {'\r': 'r', '\f': 'f', '\b': 'b', '\t': 't', '\n': 'n'}
_JSON_MANGLE_MAP: Dict[str, str] = {}
for _cmd, _sym in SYMBOL_MAP.items():
    for _ctrl, _letter in _JSON_CTRL_LETTER.items():
        if _cmd.startswith('\\' + _letter):
            _JSON_MANGLE_MAP[_ctrl + _cmd[2:]] = _sym

def _repair_annotation_latex(text: str) -> str:
    """Repair JSON-mangled LaTeX escapes and convert \\command → Unicode."""
    for mangled, sym in _JSON_MANGLE_MAP.items():
        if mangled in text:
            text = text.replace(mangled, sym)
    # Also convert any surviving well-formed \command via SYMBOL_MAP
    text = re.sub(r'\\[A-Za-z]+', lambda m: SYMBOL_MAP.get(m.group(0), m.group(0)), text)
    return text

MULTI_LETTER_OPERATORS = {
    "\\sin": "sin",
    "\\cos": "cos",
    "\\tan": "tan",
    "\\cot": "cot",
    "\\sec": "sec",
    "\\csc": "csc",
    "\\log": "log",
    "\\ln": "ln",
    "\\exp": "exp",
    "\\max": "max",
    "\\min": "min",
    "\\lim": "lim",
    "\\sinh": "sinh",
    "\\cosh": "cosh",
    "\\tanh": "tanh",
    "\\coth": "coth",
    "\\sech": "sech",
    "\\csch": "csch",
    "\\sinc": "sinc",
    "\\tg": "tg",
    "\\ctg": "ctg",
    "\\gcd": "gcd", "\\lcm": "lcm",
    "\\det": "det", "\\dim": "dim", "\\deg": "deg",
    "\\sup": "sup", "\\inf": "inf",
    "\\Pr": "Pr", "\\arg": "arg", "\\ker": "ker",
    "\\mod": "mod", "\\bmod": "mod", "\\pmod": "mod",
    "\\sgn": "sgn", "\\tr": "tr", "\\rank": "rank",
    "\\diag": "diag", "\\hom": "Hom",
    "\\span": "span", "\\Span": "span",
    "\\coker": "coker",
}

# Inverse trig/hyperbolic: rendered as base^{-1} (e.g. sin⁻¹, cos⁻¹, tan⁻¹)
INVERSE_TRIG_OPS: dict[str, str] = {
    "\\arcsin": "sin",   "\\asin": "sin",
    "\\arccos": "cos",   "\\acos": "cos",
    "\\arctan": "tan",   "\\atan": "tan",
    "\\arccot": "cot",
    "\\arcsec": "sec",
    "\\arccsc": "csc",
    "\\arcsinh": "sinh",
    "\\arccosh": "cosh",
    "\\arctanh": "tanh",
    "\\arccoth": "coth",
}

# Extensible "stretchy" arrows: \xrightarrow[under]{over}, \xleftarrow{...}, etc.
# These take an optional [under] and a (nominally mandatory) {over} label that is
# drawn above the arrow, with the shaft stretched to span the label. They are NOT
# in SYMBOL_MAP on purpose: a plain substitution would orphan the {...} label.
# Value = arrowhead style consumed by _build_xarrow_strokes.
XARROW_KINDS: dict[str, str] = {
    "\\xrightarrow": "right",
    "\\xRightarrow": "right",
    "\\xleftarrow": "left",
    "\\xLeftarrow": "left",
    "\\xleftrightarrow": "both",
    "\\xrightleftharpoons": "equilibrium",
    "\\xleftrightharpoons": "equilibrium",
    "\\xmapsto": "right",
    "\\xhookrightarrow": "right",
    "\\xhookleftarrow": "left",
}

# --- Smoothing and handwriting transforms ---

def smooth_path(path: List[Tuple[float, float]], iterations: int = 2) -> List[Tuple[float, float]]:
    if not path or len(path) < 3:
        return path
    current = path
    for _ in range(iterations):
        next_path = [current[0]]
        for j in range(len(current) - 1):
            p0 = current[j]
            p1 = current[j + 1]
            next_path.append((0.75 * p0[0] + 0.25 * p1[0], 0.75 * p0[1] + 0.25 * p1[1]))
            next_path.append((0.25 * p0[0] + 0.75 * p1[0], 0.25 * p0[1] + 0.75 * p1[1]))
        next_path.append(current[-1])
        current = next_path
    return current

def catmull_rom_chain(
    path: List[Tuple[float, float]],
    samples_per_segment: int = 8,
) -> List[Tuple[float, float]]:
    """Catmull-Rom spline interpolation — C1-continuous through every control point.

    Replaces Chaikin subdivision for glyph paths: produces geometrically smooth
    curves even from sparse polyline control points.  samples_per_segment=8 gives
    ~4× more intermediate points than two Chaikin iterations while preserving the
    exact start and end positions of every stroke.
    """
    n = len(path)
    if n < 2:
        return path
    # Phantom endpoints so the spline starts and ends tangent to the first/last segment.
    pts = [path[0]] + list(path) + [path[-1]]
    result: List[Tuple[float, float]] = [path[0]]
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        for k in range(1, samples_per_segment + 1):
            t  = k / samples_per_segment
            t2 = t * t
            t3 = t2 * t
            x = 0.5 * (
                (2 * p1[0])
                + (-p0[0] + p2[0]) * t
                + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3
            )
            y = 0.5 * (
                (2 * p1[1])
                + (-p0[1] + p2[1]) * t
                + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3
            )
            result.append((x, y))
    return result

def round_stroke_corners(path: List[Tuple[float, float]], corner_amount: float = 0.18) -> List[Tuple[float, float]]:
    if not path or len(path) < 3:
        return path

    rounded = [path[0]]
    for i in range(1, len(path) - 1):
        prev_pt = path[i - 1]
        curr_pt = path[i]
        next_pt = path[i + 1]

        in_x = curr_pt[0] - prev_pt[0]
        in_y = curr_pt[1] - prev_pt[1]
        out_x = next_pt[0] - curr_pt[0]
        out_y = next_pt[1] - curr_pt[1]

        in_len = max(0.001, math.hypot(in_x, in_y))
        out_len = max(0.001, math.hypot(out_x, out_y))
        curve = max(0.06, min(corner_amount, min(in_len, out_len) * 0.45))

        rounded.append((
            curr_pt[0] - (in_x / in_len) * curve,
            curr_pt[1] - (in_y / in_len) * curve,
        ))
        rounded.append((
            curr_pt[0] + (out_x / out_len) * curve,
            curr_pt[1] + (out_y / out_len) * curve,
        ))

    rounded.append(path[-1])
    return smooth_path(rounded, 1)

def get_sketch_seed(char: str, stroke_index: int) -> int:
    seed = stroke_index * 131
    for char_val in char:
        seed = (seed * 33 + ord(char_val)) & 0xFFFFFFFF
    return seed

def apply_handwriting_transform(
    points: List[Tuple[float, float]],
    char: str,
    font_size: float,
    stroke_index: int = 0,
    total_strokes: int = 1,
    word_seed: int = 0,
) -> List[Tuple[float, float]]:
    if not points or len(points) < 2:
        return points

    char_seed = get_sketch_seed(char or "?", stroke_index)
    phase_seed = word_seed or char_seed

    is_upper = char.isupper() if char else False
    is_digit = char.isdigit() if char else False
    is_greek = any(c in "αβγδεζηθικλμνξοπρστυφχψωΓΔΘΛΞΠΣΦΨΩ" for c in char) if char else False

    # Italic lean: ~7° for lowercase, ~5° for uppercase/digits.
    slant_coeff = 0.13 if is_upper else 0.09 if is_digit else 0.11 if is_greek else 0.15

    # Organic wobble: scaled down to represent subtle natural variance rather than heavy tremor
    wobble_amp = max(0.4, font_size * 0.015)

    entry_shift = -min(2.4, font_size * 0.045)
    exit_shift  =  min(3.2, font_size * 0.055)

    base_path = points
    out = []
    base_len = len(base_path)

    # Pre-compute constants outside the loop to minimize CPU overhead in tight drawing loops
    wobble_phase = (phase_seed % 17) * 0.38
    wobble_freq = 1.4 if is_upper else 1.1

    y_curve_coeff = math.cos((char_seed % 11) * 0.28) * wobble_amp * (0.12 if is_digit else 0.17)
    baseline_drift_coeff = math.cos((char_seed % 5) * 0.6) * wobble_amp * 0.06
    
    direction = stroke_index / max(1, total_strokes - 1) if total_strokes > 1 else 0.0
    extra_tail = direction * font_size * 0.015
    lean = 0.06 if is_upper else 0.035 if is_digit else 0.0
    
    y_extra_coeff = math.cos((char_seed % 7) * 0.44) * wobble_amp * 0.05

    for i, pt in enumerate(base_path):
        t = i / (base_len - 1) if base_len > 1 else 0.0
        eased = t * t * (3 - 2 * t)

        # Stroke-interior envelope: 0 at endpoints, peaks at midpoint.
        t_pi = t * math.pi
        sin_t_pi = math.sin(t_pi)

        # Primary lateral wobble — organic pen tremor, confined to stroke interior.
        wobble = math.sin(t_pi * wobble_freq + wobble_phase) * wobble_amp * (0.12 + 0.78 * sin_t_pi)

        # Baseline drift — zero at endpoints so joins land cleanly.
        y_curve = math.sin(eased * math.pi) * y_curve_coeff
        baseline_drift = math.sin(t_pi * 1.8) * baseline_drift_coeff

        out.append((
            pt[0]
            + pt[1] * slant_coeff          # italic slant proportional to y-position
            + wobble
            + entry_shift * ((1.0 - t / 0.18) ** 2 if t < 0.18 else 0.0)
            + exit_shift * (((t - 0.82) / 0.18) ** 2 if t > 0.82 else 0.0)
            + extra_tail
            + (t - 0.5) * lean,
            pt[1] + y_curve + baseline_drift + sin_t_pi * y_extra_coeff,
        ))

    # Bypass the redundant second catmull_rom_chain(out, 2) pass.
    # The points are already dense and smoothed by the call site's catmull_rom_chain(..., 4).
    return out

# --- Metrics and Sizing Helpers ---

# Per-character proportional width factors (relative to font_size).
# These match real handwriting proportions so narrow letters (i, l) are
# actually narrow and wide letters (m, w) fill more space.
_CHAR_WIDTH: dict[str, float] = {
    # Extra-narrow
    "i": 0.30, "I": 0.32, "j": 0.32, "l": 0.26, "!": 0.26, "|": 0.20,
    ":": 0.26, ";": 0.26, ".": 0.22, ",": 0.22, "'": 0.22, '"': 0.30,
    "1": 0.36,
    # Narrow
    "f": 0.38, "r": 0.40, "t": 0.40, "J": 0.40, "L": 0.46,
    "7": 0.44,
    # Standard lowercase
    "a": 0.52, "b": 0.54, "c": 0.48, "d": 0.54, "e": 0.50,
    "g": 0.54, "h": 0.54, "k": 0.52, "n": 0.54, "o": 0.52,
    "p": 0.52, "q": 0.52, "s": 0.46, "u": 0.54, "v": 0.50,
    "x": 0.50, "y": 0.50, "z": 0.48,
    # Standard digits
    "0": 0.54, "2": 0.52, "3": 0.52, "4": 0.54, "5": 0.52,
    "6": 0.54, "8": 0.54, "9": 0.54,
    # Standard uppercase
    "A": 0.62, "B": 0.60, "C": 0.60, "D": 0.64, "E": 0.54,
    "F": 0.52, "G": 0.64, "H": 0.64, "K": 0.62, "N": 0.66,
    "O": 0.66, "P": 0.58, "Q": 0.66, "R": 0.62, "S": 0.56,
    "T": 0.58, "U": 0.64, "V": 0.62, "X": 0.62, "Y": 0.60,
    "Z": 0.58,
    # Wide
    "m": 0.76, "w": 0.76, "M": 0.74, "W": 0.78,
    # Math/symbols — most are single-column
    "+": 0.60, "-": 0.44, "=": 0.60, "/": 0.42, "*": 0.48,
    "(": 0.34, ")": 0.34, "[": 0.34, "]": 0.34, "{": 0.38, "}": 0.38,
    "∫": 0.46, "∑": 0.58, "∏": 0.58, "√": 0.54,
    "α": 0.54, "β": 0.50, "γ": 0.48, "δ": 0.52, "θ": 0.54,
    "π": 0.58, "μ": 0.58, "σ": 0.52, "λ": 0.50, "ω": 0.60,
    " ": 0.30,
    # Brackets / delimiters
    "⌊": 0.34, "⌋": 0.34, "⌈": 0.34, "⌉": 0.34,
    "⟨": 0.30, "⟩": 0.30,
    "∅": 0.56, "∼": 0.54, "≅": 0.62, "∝": 0.58, "≡": 0.62,
    "⊕": 0.60, "⊗": 0.60, "⊖": 0.60,
    "⋯": 0.72, "…": 0.72, "⋮": 0.28, "⋱": 0.58,
    "←": 0.72, "⇐": 0.72, "↦": 0.72, "⟺": 0.80,
    "∴": 0.50, "∵": 0.50, "′": 0.28,
    "ι": 0.30, "κ": 0.50, "υ": 0.52, "ℏ": 0.54, "ℓ": 0.36,
    "≃": 0.60, "≐": 0.60,
}
_DEFAULT_WIDTH: float = 0.55

def measure_glyph_width(text: str, font_size: float) -> float:
    """Return total pixel width for a text string at the given font size.

    Each character gets its proportional width factor so narrow letters
    (i, l, f) are narrower than wide ones (m, w, M) — matching real handwriting.
    """
    total = 0.0
    for ch in text:
        total += _CHAR_WIDTH.get(ch, _DEFAULT_WIDTH) * font_size
    return total or font_size * _DEFAULT_WIDTH

# Maps \left / \right delimiter command names → single bracket char
_BRACKET_CONV: dict[str, str] = {
    "\\{": "{", "\\}": "}",
    "\\lfloor": "⌊", "\\rfloor": "⌋",
    "\\lceil": "⌈", "\\rceil": "⌉",
    "\\langle": "⟨", "\\rangle": "⟩",
    "\\vert": "|", "\\lvert": "|", "\\rvert": "|",
    "\\Vert": "∥", "\\lVert": "∥", "\\rVert": "∥", "\\|": "∥",
    ".": "",   # \left. = invisible bracket
}

# --- Tokenizer and AST Nodes ---

class Token:
    def __init__(self, type_str: str, value: str):
        self.type = type_str
        self.value = value

def tokenize(latex: str) -> List[Token]:
    tokens = []
    i = 0
    while i < len(latex):
        char = latex[i]
        if char == ' ':
            tokens.append(Token('SPACE', ' '))
            i += 1
        elif char == '\\':
            if i + 1 < len(latex) and latex[i + 1] == '\\':
                tokens.append(Token('COMMAND', '\\\\'))
                i += 2
            elif i + 1 < len(latex) and latex[i + 1] in ['{', '}']:
                tokens.append(Token('COMMAND', '\\' + latex[i + 1]))
                i += 2
            else:
                cmd = '\\'
                i += 1
                while i < len(latex) and latex[i].isalpha():
                    cmd += latex[i]
                    i += 1
                tokens.append(Token('COMMAND', cmd))
        elif char == '&':
            tokens.append(Token('ALIGN', '&'))
            i += 1
        elif char in ['^', '_', '{', '}']:
            tokens.append(Token('SPECIAL', char))
            i += 1
        else:
            tokens.append(Token('CHAR', char))
            i += 1
    return tokens

class ASTNode:
    def __init__(
        self,
        node_type: str,
        value: Optional[str] = None,
        children: Optional[List['ASTNode']] = None,
        base: Optional['ASTNode'] = None,
        sup: Optional['ASTNode'] = None,
        sub: Optional['ASTNode'] = None,
        num: Optional['ASTNode'] = None,
        den: Optional['ASTNode'] = None,
        content: Optional['ASTNode'] = None,
        left: Optional[str] = None,
        right: Optional[str] = None,
        op: Optional[str] = None,
        matrix_type: Optional[str] = None,
        rows: Optional[List[List['ASTNode']]] = None,
    ):
        self.type = node_type
        self.value = value
        self.children = children or []
        self.base = base
        self.sup = sup
        self.sub = sub
        self.num = num
        self.den = den
        self.content = content
        self.left = left
        self.right = right
        self.op = op
        self.matrix_type = matrix_type
        self.rows = rows or []

class ASTParser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> Optional[Token]:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def next_token(self) -> Optional[Token]:
        val = self.peek()
        self.pos += 1
        return val

    def parse(self) -> ASTNode:
        nodes = []
        while self.peek():
            node = self.parse_node()
            if node:
                nodes.append(node)
        return ASTNode('SEQUENCE', children=nodes)

    def parse_node(self) -> Optional[ASTNode]:
        result = self.parse_base_node()
        if not result:
            return None

        # Collect a run of ^/_ scripts and bind BOTH to the SAME base. Each
        # script is a single atom (the next token or a braced group) parsed via
        # parse_base_node — NOT a full parse_node. A full parse_node greedily
        # absorbed a following script into the first one, so `x_i^2` nested as
        # x_(i^2) and `\int_0^1` put the upper limit on top of the lower one.
        sup = None
        sub = None
        saw_script = False
        while self.peek() and self.peek().type == 'SPECIAL' and self.peek().value in ['^', '_']:
            op = self.next_token().value
            script = self.parse_base_node() or ASTNode('SEQUENCE')
            if op == '^':
                sup = script
            else:
                sub = script
            saw_script = True
        if saw_script:
            result = ASTNode('SUP_SUB', base=result, sup=sup, sub=sub)
        return result

    def parse_base_node(self) -> Optional[ASTNode]:
        tok = self.peek()
        if not tok:
            return None

        if tok.type == 'SPECIAL' and tok.value == '{':
            self.next_token()
            children = []
            while self.peek() and not (self.peek().type == 'SPECIAL' and self.peek().value == '}'):
                child = self.parse_node()
                if child:
                    children.append(child)
            self.next_token()
            # Handle {n \choose k} → binomial coefficient
            choose_idx = next(
                (i for i, c in enumerate(children)
                 if c.type == 'SYMBOL' and c.value == '\\choose'), -1
            )
            if choose_idx >= 0:
                return ASTNode('BINOMIAL',
                               num=ASTNode('SEQUENCE', children=children[:choose_idx]),
                               den=ASTNode('SEQUENCE', children=children[choose_idx + 1:]))
            return ASTNode('SEQUENCE', children=children)

        if tok.type == 'SPECIAL' and tok.value == '}':
            self.next_token()
            return None

        if tok.type == 'COMMAND':
            cmd = self.next_token().value

            if cmd in ['\\sum', '\\int', '\\prod', '\\lim']:
                node = ASTNode('LARGE_OPERATOR', op=cmd)
                # Single-atom scripts (parse_base_node) so the upper limit binds
                # to the operator, not to the lower limit. Order-independent: a
                # later ^ does not get swallowed into an earlier _ script.
                while self.peek() and self.peek().type == 'SPECIAL' and self.peek().value in ['^', '_']:
                    op = self.next_token().value
                    script = self.parse_base_node() or ASTNode('SEQUENCE')
                    if op == '^':
                        node.sup = script
                    else:
                        node.sub = script
                return node

            if cmd == '\\begin':
                name_node = self.parse_node()
                matrix_name = "matrix"
                if name_node and name_node.type == 'SEQUENCE' and name_node.children:
                    matrix_name = "".join(c.value for c in name_node.children if c.value)
                elif name_node and name_node.type == 'CHAR' and name_node.value:
                    matrix_name = name_node.value

                matrix_node = self.parse_matrix(matrix_name)
                if matrix_name == 'pmatrix':
                    return ASTNode('BRACKET', left='(', right=')', content=matrix_node)
                elif matrix_name == 'bmatrix':
                    return ASTNode('BRACKET', left='[', right=']', content=matrix_node)
                elif matrix_name == 'vmatrix':
                    return ASTNode('BRACKET', left='|', right='|', content=matrix_node)
                return matrix_node

            if cmd == '\\frac':
                num = self.parse_node() or ASTNode('SEQUENCE')
                den = self.parse_node() or ASTNode('SEQUENCE')
                return ASTNode('FRACTION', num=num, den=den)

            if cmd == '\\sqrt':
                content = self.parse_node() or ASTNode('SEQUENCE')
                return ASTNode('RADICAL', content=content)

            if cmd == '\\left':
                while self.peek() and self.peek().type == 'SPACE':
                    self.next_token()
                left_bracket_tok = self.next_token()
                lbv = left_bracket_tok.value if left_bracket_tok else '('
                left_bracket = _BRACKET_CONV.get(lbv, lbv)
                if not left_bracket:  # \left. → invisible; use placeholder that renders as nothing
                    left_bracket = '\x00'
                children = []

                while self.peek():
                    next_tok = self.peek()
                    if next_tok.type == 'COMMAND' and next_tok.value == '\\right':
                        self.next_token()
                        while self.peek() and self.peek().type == 'SPACE':
                            self.next_token()
                        right_bracket_tok = self.next_token()
                        rbv = right_bracket_tok.value if right_bracket_tok else ')'
                        right_bracket = _BRACKET_CONV.get(rbv, rbv)
                        if not right_bracket:
                            right_bracket = '\x00'
                        return ASTNode('BRACKET', left=left_bracket, right=right_bracket,
                                       content=ASTNode('SEQUENCE', children=children))
                    child = self.parse_node()
                    if child:
                        children.append(child)
                return ASTNode('BRACKET', left=left_bracket, right=')',
                               content=ASTNode('SEQUENCE', children=children))

            # ── Binomial coefficient ──────────────────────────────────────────
            if cmd in ('\\binom', '\\dbinom', '\\tbinom', '\\binom*'):
                top = self.parse_node() or ASTNode('SEQUENCE')
                bot = self.parse_node() or ASTNode('SEQUENCE')
                return ASTNode('BINOMIAL', num=top, den=bot)

            # ── Text-mode / style commands: pass content straight through ────
            if cmd in ('\\text', '\\mathrm', '\\mathbf', '\\mathbb', '\\mathcal',
                       '\\mathit', '\\mathsf', '\\mathtt', '\\operatorname',
                       '\\mbox', '\\hbox', '\\textrm', '\\textbf', '\\textit',
                       '\\textnormal', '\\boldsymbol', '\\mathscr', '\\mathfrak'):
                return self.parse_node() or ASTNode('SEQUENCE')

            # ── Accent marks (narrow, over single char or small group) ───────
            if cmd in ('\\hat', '\\widehat'):
                return ASTNode('ACCENT', content=self.parse_node() or ASTNode('SEQUENCE'), op='hat')
            if cmd in ('\\bar', '\\overline'):
                return ASTNode('ACCENT', content=self.parse_node() or ASTNode('SEQUENCE'), op='bar')
            if cmd == '\\vec':
                return ASTNode('ACCENT', content=self.parse_node() or ASTNode('SEQUENCE'), op='vec')
            if cmd in ('\\tilde', '\\widetilde'):
                return ASTNode('ACCENT', content=self.parse_node() or ASTNode('SEQUENCE'), op='tilde')
            if cmd == '\\dot':
                return ASTNode('ACCENT', content=self.parse_node() or ASTNode('SEQUENCE'), op='dot')
            if cmd == '\\ddot':
                return ASTNode('ACCENT', content=self.parse_node() or ASTNode('SEQUENCE'), op='ddot')
            if cmd == '\\acute':
                return ASTNode('ACCENT', content=self.parse_node() or ASTNode('SEQUENCE'), op='acute')
            if cmd == '\\grave':
                return ASTNode('ACCENT', content=self.parse_node() or ASTNode('SEQUENCE'), op='grave')
            if cmd in ('\\check', '\\breve'):
                return ASTNode('ACCENT', content=self.parse_node() or ASTNode('SEQUENCE'), op='check')
            if cmd == '\\ring':
                return ASTNode('ACCENT', content=self.parse_node() or ASTNode('SEQUENCE'), op='ring')

            # ── Underline ────────────────────────────────────────────────────
            if cmd == '\\underline':
                return ASTNode('UNDERLINE', content=self.parse_node() or ASTNode('SEQUENCE'))

            # ── Strikethrough ────────────────────────────────────────────────
            if cmd in ('\\cancel', '\\xcancel', '\\bcancel', '\\sout'):
                return ASTNode('CANCEL', content=self.parse_node() or ASTNode('SEQUENCE'))

            # ── Negation ─────────────────────────────────────────────────────
            if cmd == '\\not':
                return ASTNode('CANCEL', content=self.parse_base_node() or ASTNode('SEQUENCE'))

            # ── Underbrace / overbrace ────────────────────────────────────────
            if cmd == '\\underbrace':
                node = ASTNode('UNDERBRACE', content=self.parse_node() or ASTNode('SEQUENCE'))
                if self.peek() and self.peek().type == 'SPECIAL' and self.peek().value == '_':
                    self.next_token()
                    node.sub = self.parse_base_node() or ASTNode('SEQUENCE')
                return node
            if cmd == '\\overbrace':
                node = ASTNode('OVERBRACE', content=self.parse_node() or ASTNode('SEQUENCE'))
                if self.peek() and self.peek().type == 'SPECIAL' and self.peek().value == '^':
                    self.next_token()
                    node.sup = self.parse_base_node() or ASTNode('SEQUENCE')
                return node

            # ── Extensible arrows: \xrightarrow[under]{over}, \xleftarrow{…} ──
            if cmd in XARROW_KINDS:
                over = None
                under = None
                # optional [under] label — '[' / ']' tokenize as CHARs
                while self.peek() and self.peek().type == 'SPACE':
                    self.next_token()
                if self.peek() and self.peek().type == 'CHAR' and self.peek().value == '[':
                    self.next_token()  # consume '['
                    kids = []
                    while self.peek() and not (self.peek().type == 'CHAR' and self.peek().value == ']'):
                        child = self.parse_node()
                        if child:
                            kids.append(child)
                    if self.peek():
                        self.next_token()  # consume ']'
                    under = ASTNode('SEQUENCE', children=kids)
                    while self.peek() and self.peek().type == 'SPACE':
                        self.next_token()
                # {over} label — only when explicitly braced, so a bare
                # `\xrightarrow N_2` leaves N_2 as the following product, not a label
                if self.peek() and self.peek().type == 'SPECIAL' and self.peek().value == '{':
                    over = self.parse_node()
                return ASTNode('XARROW', op=cmd, sup=over, sub=under)

            # ── Spacing commands → thin space ────────────────────────────────
            if cmd in ('\\,', '\\;', '\\:', '\\!', '\\enspace', '\\thinspace',
                       '\\medspace', '\\thickspace', '\\negthinspace'):
                return ASTNode('CHAR', value=' ')

            # ── Phantom / smash (absorb silently) ────────────────────────────
            if cmd in ('\\phantom', '\\hphantom', '\\vphantom', '\\smash'):
                self.parse_node()  # consume arg, emit nothing
                return None

            # ── Invisible bracket \left. already handled; \right. too ────────
            # ── Miscellaneous pass-throughs ───────────────────────────────────
            if cmd == '\\choose':
                # Already detected inside {} groups; if seen standalone, skip
                return ASTNode('SYMBOL', value='\\choose')

            return ASTNode('SYMBOL', value=cmd)

        if tok.type == 'SPACE':
            self.next_token()
            return ASTNode('CHAR', value=' ')

        return ASTNode('CHAR', value=self.next_token().value)

    def parse_matrix(self, matrix_name: str) -> ASTNode:
        rows = []
        current_row = []
        current_cell_nodes = []

        def flush_cell():
            nonlocal current_cell_nodes
            current_row.append(ASTNode('SEQUENCE', children=current_cell_nodes))
            current_cell_nodes = []

        def flush_row():
            nonlocal current_row
            flush_cell()
            rows.append(current_row)
            current_row = []

        while self.peek():
            tok = self.peek()
            if tok.type == 'COMMAND' and tok.value == '\\end':
                self.next_token()
                self.parse_node()  # discard ending name
                flush_row()
                return ASTNode('MATRIX', matrix_type=matrix_name, rows=rows)

            if tok.type == 'ALIGN':
                self.next_token()
                flush_cell()
            elif tok.type == 'COMMAND' and tok.value == '\\\\':
                self.next_token()
                flush_row()
            else:
                node = self.parse_node()
                if node:
                    current_cell_nodes.append(node)

        flush_row()
        return ASTNode('MATRIX', matrix_type=matrix_name, rows=rows)

# --- Layout Solver Output Structure ---

class LayoutBox:
    def __init__(self, width: float, height: float, ascent: float, descent: float, glyphs: List[Dict[str, Any]], strokes: List[Dict[str, Any]], sequence: List[Dict[str, Any]]):
        self.width = width
        self.height = height
        self.ascent = ascent
        self.descent = descent
        self.glyphs = glyphs
        self.strokes = strokes
        self.constructionSequence = sequence

# --- AST Layout Engine ---

def _build_xarrow_strokes(style: str, length: float, font_size: float) -> List[Dict[str, Any]]:
    """Strokes for a stretchy arrow of the given pixel `length`, shaft on y=0.

    Mirrors the proportions of the fixed "→"/"⇌" vector glyphs but with the
    shaft stretched to span an arbitrary length so a label can sit above it.
    """
    th = max(2.0, font_size * 0.05)
    hh = font_size * 0.13   # arrowhead half-height
    hl = font_size * 0.20   # arrowhead length along the shaft

    def stroke(pts: List[Tuple[float, float]]) -> Dict[str, Any]:
        return {
            "strokeId": f"xar_{uuid.uuid4().hex[:5]}",
            "x1": pts[0][0], "y1": pts[0][1],
            "x2": pts[-1][0], "y2": pts[-1][1],
            "points": pts, "thickness": th,
        }

    if style == "left":
        return [
            stroke([(length, 0.0), (0.0, 0.0)]),
            stroke([(hl, -hh), (0.0, 0.0), (hl, hh)]),
        ]
    if style == "both":
        return [
            stroke([(0.0, 0.0), (length, 0.0)]),
            stroke([(hl, -hh), (0.0, 0.0), (hl, hh)]),
            stroke([(length - hl, -hh), (length, 0.0), (length - hl, hh)]),
        ]
    if style == "equilibrium":
        dy = font_size * 0.08
        return [
            stroke([(0.0, -dy), (length, -dy)]),                       # top shaft →
            stroke([(length - hl, -dy - hh * 0.85), (length, -dy)]),   # top harpoon hook
            stroke([(length, dy), (0.0, dy)]),                         # bottom shaft ←
            stroke([(hl, dy + hh * 0.85), (0.0, dy)]),                 # bottom harpoon hook
        ]
    # default: rightward arrow
    return [
        stroke([(0.0, 0.0), (length, 0.0)]),
        stroke([(length - hl, -hh), (length, 0.0), (length - hl, hh)]),
    ]


def layout_node(node: ASTNode, font_size: float) -> LayoutBox:
    # Inverse trig/hyperbolic: render as func^{-1}  (e.g. \arctan → tan⁻¹)
    if node.type == 'SYMBOL' and node.value in INVERSE_TRIG_OPS:
        base_name = INVERSE_TRIG_OPS[node.value]
        base_node = ASTNode('SEQUENCE', children=[ASTNode('CHAR', value=c) for c in base_name])
        sup_node  = ASTNode('SEQUENCE', children=[ASTNode('CHAR', value='-'), ASTNode('CHAR', value='1')])
        return layout_node(ASTNode('SUP_SUB', base=base_node, sup=sup_node), font_size)

    # Handle multi-character LaTeX operators
    if node.type == 'SYMBOL' and node.value in MULTI_LETTER_OPERATORS:
        expanded_str = MULTI_LETTER_OPERATORS[node.value]
        children = [ASTNode('CHAR', value=char) for char in expanded_str]
        return layout_node(ASTNode('SEQUENCE', children=children), font_size)

    if node.type in ['CHAR', 'SYMBOL']:
        char = node.value or ""
        if node.type == 'SYMBOL' and node.value:
            mapped = SYMBOL_MAP.get(node.value)
            if mapped is not None:
                char = mapped
            elif node.value.startswith('\\') and len(node.value) > 2 and node.value[1:].isalpha():
                # Unknown alphabetic LaTeX command (any subject) that wasn't
                # caught by SYMBOL_MAP / operators / XARROW etc. Degrade to its
                # handwritten letters instead of leaking literal "\command" text
                # (get_glyph has no stroke for "\command", so it would render as
                # raw styled text). Universal graceful fallback, not per-symbol.
                letters = [ASTNode('CHAR', value=c) for c in node.value[1:]]
                return layout_node(ASTNode('SEQUENCE', children=letters), font_size)
            else:
                char = node.value

        is_large_op = char in ["∫", "∑"]
        char_font_size = font_size * 1.3 if is_large_op else font_size

        w = measure_glyph_width(char, char_font_size)
        ascent = char_font_size * 0.75
        descent = char_font_size * 0.25
        y_offset = -font_size * 0.1 if is_large_op else 0.0

        glyph_strokes_list = get_glyph(char)
        strokes = []
        sequence = []
        glyphs = [{"char": char, "scaledX": 0.0, "scaledY": 0.0, "width": w, "fontSize": char_font_size}]

        for stroke_idx, pts in enumerate(glyph_strokes_list):
            if not pts or len(pts) < 2:
                continue
            scaled_points = [(p[0] * w, p[1] * char_font_size + y_offset) for p in pts]
            # Catmull-Rom pre-smoothing: turns sparse control points into a smooth
            # base curve before the handwriting wobble/slant pass.
            path_points = apply_handwriting_transform(
                catmull_rom_chain(scaled_points, 4), char, char_font_size, len(strokes), len(glyph_strokes_list)
            )

            strokes.append({
                "strokeId": f"char_stroke_{uuid.uuid4().hex[:5]}",
                "x1": path_points[0][0],
                "y1": path_points[0][1],
                "x2": path_points[-1][0],
                "y2": path_points[-1][1],
                "points": path_points,
                "thickness": max(2.0, char_font_size * 0.06),
                "charIndex": len(glyphs) - 1
            })
            sequence.append({"type": "stroke", "index": len(strokes) - 1})

        return LayoutBox(w, ascent + descent, ascent - y_offset, descent + y_offset, glyphs, strokes, sequence)

    if node.type == 'SEQUENCE':
        glyphs = []
        strokes = []
        sequence = []
        current_x = 0.0
        max_ascent = 0.0
        max_descent = 0.0

        for child in node.children:
            child_layout = layout_node(child, font_size)

            start_glyph_index = len(glyphs)
            for g in child_layout.glyphs:
                glyphs.append({**g, "scaledX": g["scaledX"] + current_x})

            start_stroke_index = len(strokes)
            for s in child_layout.strokes:
                strokes.append({
                    **s,
                    "x1": s["x1"] + current_x,
                    "x2": s["x2"] + current_x,
                    "points": [(pt[0] + current_x, pt[1]) for pt in s["points"]] if "points" in s else None,
                    "charIndex": s["charIndex"] + start_glyph_index if s.get("charIndex") is not None else None,
                })

            if child_layout.constructionSequence:
                for step in child_layout.constructionSequence:
                    sequence.append({
                        "type": step["type"],
                        "index": (step["index"] + start_glyph_index
                                  if step["type"] == "glyph"
                                  else step["index"] + start_stroke_index),
                    })

            current_x += child_layout.width
            max_ascent = max(max_ascent, child_layout.ascent)
            max_descent = max(max_descent, child_layout.descent)

        return LayoutBox(current_x, max_ascent + max_descent, max_ascent, max_descent, glyphs, strokes, sequence)

    if node.type == 'SUP_SUB' and node.base:
        base_layout = layout_node(node.base, font_size)
        glyphs = list(base_layout.glyphs)
        strokes = list(base_layout.strokes)
        sequence = list(base_layout.constructionSequence or [])

        sup_layout = None
        sub_layout = None
        sup_width = 0.0
        sub_width = 0.0

        if node.sup:
            sup_layout = layout_node(node.sup, font_size * 0.60)
            sup_width = sup_layout.width
        if node.sub:
            sub_layout = layout_node(node.sub, font_size * 0.60)
            sub_width = sub_layout.width

        is_base_large_op = len(base_layout.glyphs) > 0 and base_layout.glyphs[0]["char"] in ["∫", "∑"]

        sup_y = 0.0
        sub_y = 0.0
        script_x = base_layout.width

        if is_base_large_op:
            script_x = base_layout.width - (font_size * 0.15 if base_layout.glyphs[0]["char"] == "∫" else 0.0)
            if sup_layout:
                sup_y = -base_layout.ascent - sup_layout.descent - font_size * 0.05
            if sub_layout:
                sub_y = base_layout.descent + sub_layout.ascent + font_size * 0.05
        else:
            if sup_layout:
                sup_y = -font_size * 0.35
                # Tall exponent (nested power, fraction, multi-line): lift its
                # baseline further up so its body clears the base instead of
                # cutting through it. One-line exponents (x^2, e^{x+x\sin x})
                # are unaffected — their ascent ≈ a single small glyph's ascent.
                normal_sup_ascent = font_size * 0.60 * 0.75
                if sup_layout.ascent > normal_sup_ascent * 1.25:
                    sup_y -= (sup_layout.ascent - normal_sup_ascent)
            if sub_layout:
                sub_y = font_size * 0.25
                # Mirror for a deep subscript so it clears the base downward.
                normal_sub_descent = font_size * 0.60 * 0.25
                if sub_layout.descent > normal_sub_descent * 1.25:
                    sub_y += (sub_layout.descent - normal_sub_descent)

        start_glyph_index_sub = len(glyphs)
        start_stroke_index_sub = len(strokes)
        if sub_layout:
            for g in sub_layout.glyphs:
                glyphs.append({
                    **g,
                    "scaledX": g["scaledX"] + script_x,
                    "scaledY": g["scaledY"] + sub_y,
                })
            for s in sub_layout.strokes:
                strokes.append({
                    **s,
                    "x1": s["x1"] + script_x,
                    "y1": s["y1"] + sub_y,
                    "x2": s["x2"] + script_x,
                    "y2": s["y2"] + sub_y,
                    "points": [(pt[0] + script_x, pt[1] + sub_y) for pt in s["points"]] if s.get("points") else None,
                    "charIndex": s["charIndex"] + start_glyph_index_sub if s.get("charIndex") is not None else None
                })

        start_glyph_index_sup = len(glyphs)
        start_stroke_index_sup = len(strokes)
        if sup_layout:
            for g in sup_layout.glyphs:
                glyphs.append({
                    **g,
                    "scaledX": g["scaledX"] + script_x,
                    "scaledY": g["scaledY"] + sup_y,
                })
            for s in sup_layout.strokes:
                strokes.append({
                    **s,
                    "x1": s["x1"] + script_x,
                    "y1": s["y1"] + sup_y,
                    "x2": s["x2"] + script_x,
                    "y2": s["y2"] + sup_y,
                    "points": [(pt[0] + script_x, pt[1] + sup_y) for pt in s["points"]] if s.get("points") else None,
                    "charIndex": s["charIndex"] + start_glyph_index_sup if s.get("charIndex") is not None else None
                })

        if sub_layout and sub_layout.constructionSequence:
            for step in sub_layout.constructionSequence:
                sequence.append({
                    "type": step["type"],
                    "index": step["index"] + start_glyph_index_sub if step["type"] == "glyph" else step["index"] + start_stroke_index_sub
                })
        if sup_layout and sup_layout.constructionSequence:
            for step in sup_layout.constructionSequence:
                sequence.append({
                    "type": step["type"],
                    "index": step["index"] + start_glyph_index_sup if step["type"] == "glyph" else step["index"] + start_stroke_index_sup
                })

        total_w = script_x + max(sup_width, sub_width)
        total_ascent = max(base_layout.ascent, -sup_y + sup_layout.ascent if sup_layout else 0.0)
        total_descent = max(base_layout.descent, sub_y + sub_layout.descent if sub_layout else 0.0)

        return LayoutBox(total_w, total_ascent + total_descent, total_ascent, total_descent, glyphs, strokes, sequence)

    if node.type == 'FRACTION' and node.num and node.den:
        num_layout = layout_node(node.num, font_size)
        den_layout = layout_node(node.den, font_size)

        w = max(num_layout.width, den_layout.width) + font_size * 0.2
        num_x = (w - num_layout.width) / 2
        den_x = (w - den_layout.width) / 2

        axis_y = -font_size * 0.25
        gap = font_size * 0.08

        num_y = axis_y - num_layout.descent - gap
        den_y = axis_y + den_layout.ascent + gap

        glyphs = []
        strokes = []
        sequence = []

        start_glyph_index_num = len(glyphs)
        start_stroke_index_num = len(strokes)
        for g in num_layout.glyphs:
            glyphs.append({
                **g,
                "scaledX": g["scaledX"] + num_x,
                "scaledY": g["scaledY"] + num_y
            })
        for s in num_layout.strokes:
            strokes.append({
                **s,
                "x1": s["x1"] + num_x,
                "y1": s["y1"] + num_y,
                "x2": s["x2"] + num_x,
                "y2": s["y2"] + num_y,
                "points": [(pt[0] + num_x, pt[1] + num_y) for pt in s["points"]] if s.get("points") else None,
                "charIndex": s["charIndex"] + start_glyph_index_num if s.get("charIndex") is not None else None
            })

        bar_stroke_index = len(strokes)
        bar_thickness = max(1.5, font_size * 0.05)
        strokes.append({
            "strokeId": f"frac_{uuid.uuid4().hex[:5]}",
            "x1": 0.0,
            "y1": axis_y,
            "x2": w,
            "y2": axis_y,
            "points": [(0.0, axis_y), (w, axis_y)],
            "thickness": bar_thickness
        })

        start_glyph_index_den = len(glyphs)
        start_stroke_index_den = len(strokes)
        for g in den_layout.glyphs:
            glyphs.append({
                **g,
                "scaledX": g["scaledX"] + den_x,
                "scaledY": g["scaledY"] + den_y
            })
        for s in den_layout.strokes:
            strokes.append({
                **s,
                "x1": s["x1"] + den_x,
                "y1": s["y1"] + den_y,
                "x2": s["x2"] + den_x,
                "y2": s["y2"] + den_y,
                "points": [(pt[0] + den_x, pt[1] + den_y) for pt in s["points"]] if s.get("points") else None,
                "charIndex": s["charIndex"] + start_glyph_index_den if s.get("charIndex") is not None else None
            })

        if num_layout.constructionSequence:
            for step in num_layout.constructionSequence:
                sequence.append({
                    "type": step["type"],
                    "index": step["index"] + start_glyph_index_num if step["type"] == "glyph" else step["index"] + start_stroke_index_num
                })

        sequence.append({"type": "stroke", "index": bar_stroke_index})

        if den_layout.constructionSequence:
            for step in den_layout.constructionSequence:
                sequence.append({
                    "type": step["type"],
                    "index": step["index"] + start_glyph_index_den if step["type"] == "glyph" else step["index"] + start_stroke_index_den
                })

        total_ascent = -num_y + num_layout.ascent
        total_descent = den_y + den_layout.descent

        return LayoutBox(w, total_ascent + total_descent, total_ascent, total_descent, glyphs, strokes, sequence)

    if node.type == 'RADICAL' and node.content:
        content_layout = layout_node(node.content, font_size)
        rad_w = font_size * 0.5
        y_top = -content_layout.ascent - font_size * 0.08
        y_bottom = content_layout.descent + font_size * 0.08
        y_mid = (y_top + y_bottom) / 2
        thickness = max(1.5, font_size * 0.05)

        glyphs = [{"char": "√", "scaledX": 0.0, "scaledY": y_mid, "width": rad_w, "fontSize": font_size}]
        strokes = [
            {
                "strokeId": f"rad_hook_{uuid.uuid4().hex[:5]}",
                "x1": 0.0,
                "y1": y_mid - font_size * 0.1,
                "x2": rad_w * 0.2,
                "y2": y_mid,
                "points": [(0.0, y_mid - font_size * 0.1), (rad_w * 0.2, y_mid)],
                "thickness": thickness,
                "charIndex": 0
            },
            {
                "strokeId": f"rad_desc_{uuid.uuid4().hex[:5]}",
                "x1": rad_w * 0.2,
                "y1": y_mid,
                "x2": rad_w * 0.5,
                "y2": y_bottom,
                "points": [(rad_w * 0.2, y_mid), (rad_w * 0.5, y_bottom)],
                "thickness": thickness,
                "charIndex": 0
            },
            {
                "strokeId": f"rad_asc_{uuid.uuid4().hex[:5]}",
                "x1": rad_w * 0.5,
                "y1": y_bottom,
                "x2": rad_w,
                "y2": y_top,
                "points": [(rad_w * 0.5, y_bottom), (rad_w, y_top)],
                "thickness": thickness,
                "charIndex": 0
            },
            {
                "strokeId": f"rad_roof_{uuid.uuid4().hex[:5]}",
                "x1": rad_w,
                "y1": y_top,
                "x2": rad_w + content_layout.width,
                "y2": y_top,
                "points": [(rad_w, y_top), (rad_w + content_layout.width, y_top)],
                "thickness": thickness,
                "charIndex": 0
            }
        ]

        start_glyph_index = len(glyphs)
        start_stroke_index = len(strokes)
        content_x = rad_w

        for g in content_layout.glyphs:
            glyphs.append({
                **g,
                "scaledX": g["scaledX"] + content_x
            })
        for s in content_layout.strokes:
            strokes.append({
                **s,
                "x1": s["x1"] + content_x,
                "y1": s["y1"],
                "x2": s["x2"] + content_x,
                "y2": s["y2"],
                "points": [(pt[0] + content_x, pt[1]) for pt in s["points"]] if s.get("points") else None,
                "charIndex": s["charIndex"] + start_glyph_index if s.get("charIndex") is not None else None
            })

        sequence = [
            {"type": "stroke", "index": 0},
            {"type": "stroke", "index": 1},
            {"type": "stroke", "index": 2}
        ]

        if content_layout.constructionSequence:
            for step in content_layout.constructionSequence:
                sequence.append({
                    "type": step["type"],
                    "index": step["index"] + start_glyph_index if step["type"] == "glyph" else step["index"] + start_stroke_index
                })

        sequence.append({"type": "stroke", "index": 3})

        total_w = rad_w + content_layout.width
        total_ascent = max(-y_top, content_layout.ascent)
        total_descent = max(y_bottom, content_layout.descent)

        return LayoutBox(total_w, total_ascent + total_descent, total_ascent, total_descent, glyphs, strokes, sequence)

    if node.type == 'BRACKET' and node.content and node.left and node.right:
        content_layout = layout_node(node.content, font_size)
        content_h = content_layout.ascent + content_layout.descent
        bracket_font_size = max(font_size, content_h * 1.05)
        
        left_w = measure_glyph_width(node.left, bracket_font_size)
        right_w = measure_glyph_width(node.right, bracket_font_size)
        
        left_layout = layout_node(ASTNode('CHAR', value=node.left), bracket_font_size)
        right_layout = layout_node(ASTNode('CHAR', value=node.right), bracket_font_size)
        
        content_midline = (content_layout.descent - content_layout.ascent) / 2.0
        left_midline = (left_layout.descent - left_layout.ascent) / 2.0
        right_midline = (right_layout.descent - right_layout.ascent) / 2.0
        left_y_offset = content_midline - left_midline
        right_y_offset = content_midline - right_midline
        
        glyphs = []
        strokes = []
        sequence = []
        
        # Left bracket
        start_stroke_index_left = len(strokes)
        for s in left_layout.strokes:
            strokes.append({
                **s,
                "y1": s["y1"] + left_y_offset,
                "y2": s["y2"] + left_y_offset,
                "points": [(pt[0], pt[1] + left_y_offset) for pt in s["points"]] if s.get("points") else None,
            })
        for g in left_layout.glyphs:
            glyphs.append({
                **g,
                "scaledY": g["scaledY"] + left_y_offset
            })
            
        # Content
        start_stroke_index_content = len(strokes)
        start_glyph_index_content = len(glyphs)
        content_x = left_w
        for g in content_layout.glyphs:
            glyphs.append({
                **g,
                "scaledX": g["scaledX"] + content_x
            })
        for s in content_layout.strokes:
            strokes.append({
                **s,
                "x1": s["x1"] + content_x,
                "x2": s["x2"] + content_x,
                "points": [(pt[0] + content_x, pt[1]) for pt in s["points"]] if s.get("points") else None,
                "charIndex": s["charIndex"] + start_glyph_index_content if s.get("charIndex") is not None else None
            })
            
        # Right bracket
        start_stroke_index_right = len(strokes)
        right_x = left_w + content_layout.width
        start_glyph_index_right = len(glyphs)
        for s in right_layout.strokes:
            strokes.append({
                **s,
                "x1": s["x1"] + right_x,
                "y1": s["y1"] + right_y_offset,
                "x2": s["x2"] + right_x,
                "y2": s["y2"] + right_y_offset,
                "points": [(pt[0] + right_x, pt[1] + right_y_offset) for pt in s["points"]] if s.get("points") else None,
                "charIndex": s["charIndex"] + start_glyph_index_right if s.get("charIndex") is not None else None
            })
        for g in right_layout.glyphs:
            glyphs.append({
                **g,
                "scaledX": g["scaledX"] + right_x,
                "scaledY": g["scaledY"] + right_y_offset
            })
            
        if left_layout.constructionSequence:
            for step in left_layout.constructionSequence:
                sequence.append({
                    "type": step["type"],
                    "index": step["index"] if step["type"] == "glyph" else step["index"] + start_stroke_index_left
                })
        if content_layout.constructionSequence:
            for step in content_layout.constructionSequence:
                sequence.append({
                    "type": step["type"],
                    "index": step["index"] + start_glyph_index_content if step["type"] == "glyph" else step["index"] + start_stroke_index_content
                })
        if right_layout.constructionSequence:
            for step in right_layout.constructionSequence:
                sequence.append({
                    "type": step["type"],
                    "index": step["index"] + start_glyph_index_right if step["type"] == "glyph" else step["index"] + start_stroke_index_right
                })
                
        total_w = left_w + content_layout.width + right_w
        total_ascent = max(content_layout.ascent, left_layout.ascent - left_y_offset, right_layout.ascent - right_y_offset)
        total_descent = max(content_layout.descent, left_layout.descent + left_y_offset, right_layout.descent + right_y_offset)
        
        return LayoutBox(total_w, total_ascent + total_descent, total_ascent, total_descent, glyphs, strokes, sequence)

    if node.type == 'LARGE_OPERATOR' and node.op:
        char = "∑"
        if node.op == "\\sum": char = "∑"
        elif node.op == "\\int": char = "∫"
        elif node.op == "\\prod": char = "∏"
        elif node.op == "\\lim": char = "lim"
        else:
            symbol_map = {"\\int": "∫", "\\sum": "∑", "\\prod": "∏", "\\lim": "lim"}
            char = symbol_map.get(node.op, node.op)

        op_font_size = font_size * 1.5
        w_op = measure_glyph_width(char, op_font_size)
        op_ascent = op_font_size * 0.75
        op_descent = op_font_size * 0.25

        is_sum_limit = char in ["∑", "∏", "lim"]

        sup_layout = None
        sub_layout = None
        if node.sup: sup_layout = layout_node(node.sup, font_size * 0.6)
        if node.sub: sub_layout = layout_node(node.sub, font_size * 0.6)

        glyphs = []
        strokes = []
        sequence = []

        total_w = w_op
        total_ascent = op_ascent
        total_descent = op_descent
        axis_y = -font_size * 0.15

        if is_sum_limit:
            gap_scale = font_size * 0.12
            is_lim = char == 'lim'
            lim_layout = None
            
            if is_lim:
                lim_layout = layout_node(ASTNode('SEQUENCE', children=[ASTNode('CHAR', value='l'), ASTNode('CHAR', value='i'), ASTNode('CHAR', value='m')]), font_size)
                for g in lim_layout.glyphs: glyphs.append(g)
                for s in lim_layout.strokes: strokes.append(s)
                if lim_layout.constructionSequence: sequence.extend(lim_layout.constructionSequence)
                total_w = lim_layout.width

            max_w = max(w_op, sup_layout.width if sup_layout else 0.0, sub_layout.width if sub_layout else 0.0, lim_layout.width if lim_layout else 0.0)
            total_w = max_w

            op_x = (max_w - w_op) / 2.0
            op_y = axis_y

            if not is_lim:
                op_layout = layout_node(ASTNode('CHAR', value=char), op_font_size)
                start_stroke_index_op = len(strokes)
                op_index_start = len(glyphs)
                for s in op_layout.strokes:
                    strokes.append({
                        **s,
                        "x1": s["x1"] + op_x,
                        "y1": s["y1"] + op_y,
                        "x2": s["x2"] + op_x,
                        "y2": s["y2"] + op_y,
                        "points": [(pt[0] + op_x, pt[1] + op_y) for pt in s["points"]] if s.get("points") else None,
                        "charIndex": s["charIndex"] + op_index_start if s.get("charIndex") is not None else None
                    })
                if op_layout.constructionSequence:
                    for step in op_layout.constructionSequence:
                        sequence.append({
                            "type": step["type"],
                            "index": step["index"] if step["type"] == "glyph" else step["index"] + start_stroke_index_op
                        })

            sub_index_start = len(glyphs)
            sub_stroke_start = len(strokes)
            if sub_layout:
                sub_x = (max_w - sub_layout.width) / 2.0
                sub_y = (axis_y + op_descent) + sub_layout.ascent + gap_scale

                for g in sub_layout.glyphs:
                    glyphs.append({
                        **g,
                        "scaledX": g["scaledX"] + sub_x,
                        "scaledY": g["scaledY"] + sub_y
                    })
                for s in sub_layout.strokes:
                    strokes.append({
                        **s,
                        "x1": s["x1"] + sub_x,
                        "y1": s["y1"] + sub_y,
                        "x2": s["x2"] + sub_x,
                        "y2": s["y2"] + sub_y,
                        "points": [(pt[0] + sub_x, pt[1] + sub_y) for pt in s["points"]] if s.get("points") else None,
                        "charIndex": s["charIndex"] + sub_index_start if s.get("charIndex") is not None else None
                    })

                if sub_layout.constructionSequence:
                    for step in sub_layout.constructionSequence:
                        sequence.append({
                            "type": step["type"],
                            "index": step["index"] + sub_index_start if step["type"] == "glyph" else step["index"] + sub_stroke_start
                        })
                total_descent = max(total_descent, sub_y + sub_layout.descent)

            sup_index_start = len(glyphs)
            sup_stroke_start = len(strokes)
            if sup_layout:
                sup_x = (max_w - sup_layout.width) / 2.0
                sup_y = (axis_y - op_ascent) - sup_layout.descent - gap_scale

                for g in sup_layout.glyphs:
                    glyphs.append({
                        **g,
                        "scaledX": g["scaledX"] + sup_x,
                        "scaledY": g["scaledY"] + sup_y
                    })
                for s in sup_layout.strokes:
                    strokes.append({
                        **s,
                        "x1": s["x1"] + sup_x,
                        "y1": s["y1"] + sup_y,
                        "x2": s["x2"] + sup_x,
                        "y2": s["y2"] + sup_y,
                        "points": [(pt[0] + sup_x, pt[1] + sup_y) for pt in s["points"]] if s.get("points") else None,
                        "charIndex": s["charIndex"] + sup_index_start if s.get("charIndex") is not None else None
                    })

                if sup_layout.constructionSequence:
                    for step in sup_layout.constructionSequence:
                        sequence.append({
                            "type": step["type"],
                            "index": step["index"] + sup_index_start if step["type"] == "glyph" else step["index"] + sup_stroke_start
                        })
                total_ascent = max(total_ascent, -(sup_y - sup_layout.ascent))
            
        else:
            op_layout = layout_node(ASTNode('CHAR', value=char), op_font_size)
            start_stroke_index_op = len(strokes)
            for s in op_layout.strokes:
                strokes.append({
                    **s,
                    "y1": s["y1"] + axis_y,
                    "y2": s["y2"] + axis_y,
                    "points": [(pt[0], pt[1] + axis_y) for pt in s["points"]] if s.get("points") else None,
                })
            if op_layout.constructionSequence:
                for step in op_layout.constructionSequence:
                    sequence.append({
                        "type": step["type"],
                        "index": step["index"] if step["type"] == "glyph" else step["index"] + start_stroke_index_op
                    })

            sup_y = 0.0
            sub_y = 0.0
            
            # Professional kerning offsets for definite integrals to prevent limit-hook overlap
            if char == "∫":
                sup_script_x = w_op + font_size * 0.05
                sub_script_x = w_op - font_size * 0.10
            else:
                sup_script_x = w_op
                sub_script_x = w_op

            sub_index_start = len(glyphs)
            sub_stroke_start = len(strokes)
            if sub_layout:
                sub_y = font_size * 0.35
                for g in sub_layout.glyphs:
                    glyphs.append({
                        **g,
                        "scaledX": g["scaledX"] + sub_script_x,
                        "scaledY": g["scaledY"] + sub_y
                    })
                for s in sub_layout.strokes:
                    strokes.append({
                        **s,
                        "x1": s["x1"] + sub_script_x,
                        "y1": s["y1"] + sub_y,
                        "x2": s["x2"] + sub_script_x,
                        "y2": s["y2"] + sub_y,
                        "points": [(pt[0] + sub_script_x, pt[1] + sub_y) for pt in s["points"]] if s.get("points") else None,
                        "charIndex": s["charIndex"] + sub_index_start if s.get("charIndex") is not None else None
                    })
                
                if sub_layout.constructionSequence:
                    for step in sub_layout.constructionSequence:
                        sequence.append({
                            "type": step["type"],
                            "index": step["index"] + sub_index_start if step["type"] == "glyph" else step["index"] + sub_stroke_start
                        })

            sup_index_start = len(glyphs)
            sup_stroke_start = len(strokes)
            if sup_layout:
                sup_y = -font_size * 0.45
                for g in sup_layout.glyphs:
                    glyphs.append({
                        **g,
                        "scaledX": g["scaledX"] + sup_script_x,
                        "scaledY": g["scaledY"] + sup_y
                    })
                for s in sup_layout.strokes:
                    strokes.append({
                        **s,
                        "x1": s["x1"] + sup_script_x,
                        "y1": s["y1"] + sup_y,
                        "x2": s["x2"] + sup_script_x,
                        "y2": s["y2"] + sup_y,
                        "points": [(pt[0] + sup_script_x, pt[1] + sup_y) for pt in s["points"]] if s.get("points") else None,
                        "charIndex": s["charIndex"] + sup_index_start if s.get("charIndex") is not None else None
                    })
                
                if sup_layout.constructionSequence:
                    for step in sup_layout.constructionSequence:
                        sequence.append({
                            "type": step["type"],
                            "index": step["index"] + sup_index_start if step["type"] == "glyph" else step["index"] + sup_stroke_start
                        })

            script_width = max(
                ((sup_layout.width if sup_layout else 0.0) + (sup_script_x - w_op)),
                ((sub_layout.width if sub_layout else 0.0) + (sub_script_x - w_op))
            )
            total_w = w_op + max(0.0, script_width)
            total_ascent = max(op_ascent - axis_y, -sup_y + sup_layout.ascent if sup_layout else 0.0)
            total_descent = max(op_descent + axis_y, sub_y + sub_layout.descent if sub_layout else 0.0)

        return LayoutBox(total_w, total_ascent + total_descent, total_ascent, total_descent, glyphs, strokes, sequence)

    if node.type == 'MATRIX' and node.rows:
        row_count = len(node.rows)
        col_count = max(len(row) for row in node.rows) if node.rows else 0
        
        grid = []
        col_widths = [0.0] * col_count
        row_ascents = [0.0] * row_count
        row_descents = [0.0] * row_count
        row_heights = [0.0] * row_count
        
        for r in range(row_count):
            row_layouts = []
            for c in range(col_count):
                row = node.rows[r]
                cell_node = row[c] if c < len(row) else ASTNode('SEQUENCE', children=[])
                cell_layout = layout_node(cell_node, font_size)
                row_layouts.append(cell_layout)
                
                col_widths[c] = max(col_widths[c], cell_layout.width)
                row_ascents[r] = max(row_ascents[r], cell_layout.ascent)
                row_descents[r] = max(row_descents[r], cell_layout.descent)
            grid.append(row_layouts)
            row_heights[r] = row_ascents[r] + row_descents[r]
            
        col_gap = font_size * 0.4
        row_gap = font_size * 0.3
        
        total_w = sum(col_widths) + (col_count - 1) * col_gap
        total_h = sum(row_heights) + (row_count - 1) * row_gap
        matrix_top = -font_size * 0.25 - total_h / 2.0
        
        glyphs = []
        strokes = []
        sequence = []
        
        current_baseline_y = matrix_top
        
        for r in range(row_count):
            row_baseline = current_baseline_y + row_ascents[r]
            current_col_x = 0.0
            
            for c in range(col_count):
                cell = grid[r][c]
                cell_x = current_col_x + (col_widths[c] - cell.width) / 2.0
                
                start_glyph_index = len(glyphs)
                start_stroke_index = len(strokes)
                
                for g in cell.glyphs:
                    glyphs.append({
                        **g,
                        "scaledX": g["scaledX"] + cell_x,
                        "scaledY": g["scaledY"] + row_baseline
                    })
                for s in cell.strokes:
                    strokes.append({
                        **s,
                        "x1": s["x1"] + cell_x,
                        "y1": s["y1"] + row_baseline,
                        "x2": s["x2"] + cell_x,
                        "y2": s["y2"] + row_baseline,
                        "points": [(pt[0] + cell_x, pt[1] + row_baseline) for pt in s["points"]] if s.get("points") else None,
                        "charIndex": s["charIndex"] + start_glyph_index if s.get("charIndex") is not None else None
                    })
                
                if cell.constructionSequence:
                    for step in cell.constructionSequence:
                        sequence.append({
                            "type": step["type"],
                            "index": step["index"] + start_glyph_index if step["type"] == "glyph" else step["index"] + start_stroke_index
                        })
                current_col_x += col_widths[c] + col_gap
            current_baseline_y += row_heights[r] + row_gap
            
        return LayoutBox(total_w, total_h, -matrix_top, matrix_top + total_h, glyphs, strokes, sequence)

    # ── BINOMIAL: \binom{n}{k} — stacked n/k in auto-sized parentheses ──────
    if node.type == 'BINOMIAL' and node.num is not None and node.den is not None:
        binom_fs = font_size * 0.85
        n_lay = layout_node(node.num, binom_fs)
        k_lay = layout_node(node.den, binom_fs)
        gap = font_size * 0.10
        content_w = max(n_lay.width, k_lay.width) + font_size * 0.06
        n_y = -(gap / 2.0 + n_lay.descent)
        k_y  =  gap / 2.0 + k_lay.ascent
        total_asc  = gap / 2.0 + n_lay.descent + n_lay.ascent
        total_desc = gap / 2.0 + k_lay.ascent  + k_lay.descent

        ig: List[Dict[str, Any]] = []
        ist: List[Dict[str, Any]] = []
        iseq: List[Dict[str, Any]] = []

        def _offset_layout(lay: 'LayoutBox', ox: float, oy: float,
                           gi: List, si: List, sq: List) -> None:
            g0, s0 = len(gi), len(si)
            for g in lay.glyphs:
                gi.append({**g, "scaledX": g["scaledX"] + ox, "scaledY": g["scaledY"] + oy})
            for s in lay.strokes:
                si.append({**s,
                    "x1": s["x1"] + ox, "y1": s["y1"] + oy,
                    "x2": s["x2"] + ox, "y2": s["y2"] + oy,
                    "points": [(p[0] + ox, p[1] + oy) for p in s["points"]] if s.get("points") else None,
                    "charIndex": s["charIndex"] + g0 if s.get("charIndex") is not None else None,
                })
            for step in (lay.constructionSequence or []):
                sq.append({"type": step["type"],
                           "index": step["index"] + g0 if step["type"] == "glyph" else step["index"] + s0})

        nx = (content_w - n_lay.width) / 2.0
        kx = (content_w - k_lay.width) / 2.0
        _offset_layout(n_lay, nx, n_y, ig, ist, iseq)
        _offset_layout(k_lay, kx, k_y, ig, ist, iseq)

        # Auto-size parentheses to match stacked content height
        content_h = total_asc + total_desc
        pfs = max(font_size, content_h * 1.08)
        lp_lay = layout_node(ASTNode('CHAR', value='('), pfs)
        rp_lay = layout_node(ASTNode('CHAR', value=')'), pfs)
        lw, rw = lp_lay.width, rp_lay.width
        cmid  = (total_desc - total_asc) / 2.0
        ly_off = cmid - (lp_lay.descent - lp_lay.ascent) / 2.0
        ry_off = cmid - (rp_lay.descent - rp_lay.ascent) / 2.0

        all_g: List[Dict[str, Any]] = []
        all_s: List[Dict[str, Any]] = []
        all_sq: List[Dict[str, Any]] = []

        _offset_layout(lp_lay, 0.0, ly_off, all_g, all_s, all_sq)
        _offset_layout(LayoutBox(content_w, content_h, total_asc, total_desc, ig, ist, iseq),
                       lw, 0.0, all_g, all_s, all_sq)
        _offset_layout(rp_lay, lw + content_w, ry_off, all_g, all_s, all_sq)

        tot_w  = lw + content_w + rw
        fin_asc  = max(total_asc,  lp_lay.ascent - ly_off, rp_lay.ascent - ry_off)
        fin_desc = max(total_desc, lp_lay.descent + ly_off, rp_lay.descent + ry_off)
        return LayoutBox(tot_w, fin_asc + fin_desc, fin_asc, fin_desc, all_g, all_s, all_sq)

    # ── ACCENT: \hat \bar \vec \tilde \dot \ddot \acute \grave \check ────────
    if node.type == 'ACCENT' and node.content is not None:
        c_lay = layout_node(node.content, font_size)
        w = c_lay.width
        acc = node.op or 'hat'
        ay = -(c_lay.ascent + font_size * 0.10)   # accent sits above ascent
        th = max(1.4, font_size * 0.048)
        glyphs = list(c_lay.glyphs)
        strokes = list(c_lay.strokes)
        seq = list(c_lay.constructionSequence or [])
        acc_i = len(strokes)

        def _dot_stroke(x: float, y: float) -> Dict[str, Any]:
            return {"strokeId": f"acc_{uuid.uuid4().hex[:5]}", "x1": x, "y1": y,
                    "x2": x + 0.01, "y2": y, "points": [(x, y), (x + 0.01, y)],
                    "thickness": th * 2.2}

        if acc in ('hat', 'widehat'):
            pts = [(0.05 * w, ay + font_size * 0.09), (0.5 * w, ay), (0.95 * w, ay + font_size * 0.09)]
            strokes.append({"strokeId": f"acc_{uuid.uuid4().hex[:5]}", "x1": pts[0][0], "y1": pts[0][1],
                            "x2": pts[-1][0], "y2": pts[-1][1], "points": pts, "thickness": th})
        elif acc in ('bar',):
            strokes.append({"strokeId": f"acc_{uuid.uuid4().hex[:5]}", "x1": 0.0, "y1": ay,
                            "x2": w, "y2": ay, "points": [(0.0, ay), (w, ay)], "thickness": th})
        elif acc == 'vec':
            hy = font_size * 0.07
            strokes.append({"strokeId": f"acc_{uuid.uuid4().hex[:5]}", "x1": 0.1*w, "y1": ay,
                            "x2": 0.9*w, "y2": ay, "points": [(0.1*w, ay), (0.9*w, ay)], "thickness": th})
            strokes.append({"strokeId": f"acc_{uuid.uuid4().hex[:5]}",
                            "x1": 0.7*w, "y1": ay - hy, "x2": 0.7*w, "y2": ay + hy,
                            "points": [(0.7*w, ay - hy), (0.9*w, ay), (0.7*w, ay + hy)], "thickness": th})
        elif acc in ('tilde', 'widetilde'):
            pts = [(0.05*w, ay+font_size*0.04), (0.25*w, ay), (0.5*w, ay+font_size*0.05),
                   (0.75*w, ay), (0.95*w, ay+font_size*0.04)]
            strokes.append({"strokeId": f"acc_{uuid.uuid4().hex[:5]}", "x1": pts[0][0], "y1": pts[0][1],
                            "x2": pts[-1][0], "y2": pts[-1][1], "points": pts, "thickness": th})
        elif acc == 'dot':
            strokes.append(_dot_stroke(w * 0.5, ay))
        elif acc == 'ddot':
            strokes.append(_dot_stroke(w * 0.3, ay))
            strokes.append(_dot_stroke(w * 0.7, ay))
        elif acc == 'acute':
            pts = [(0.35*w, ay + font_size*0.07), (0.65*w, ay)]
            strokes.append({"strokeId": f"acc_{uuid.uuid4().hex[:5]}", "x1": pts[0][0], "y1": pts[0][1],
                            "x2": pts[-1][0], "y2": pts[-1][1], "points": pts, "thickness": th})
        elif acc == 'grave':
            pts = [(0.35*w, ay), (0.65*w, ay + font_size*0.07)]
            strokes.append({"strokeId": f"acc_{uuid.uuid4().hex[:5]}", "x1": pts[0][0], "y1": pts[0][1],
                            "x2": pts[-1][0], "y2": pts[-1][1], "points": pts, "thickness": th})
        elif acc in ('check', 'breve'):
            pts = [(0.05*w, ay), (0.5*w, ay + font_size*0.09), (0.95*w, ay)]
            strokes.append({"strokeId": f"acc_{uuid.uuid4().hex[:5]}", "x1": pts[0][0], "y1": pts[0][1],
                            "x2": pts[-1][0], "y2": pts[-1][1], "points": pts, "thickness": th})
        elif acc == 'ring':
            # Small circle above
            r = font_size * 0.06
            cy = ay - r
            pts = [(w*0.5, cy-r), (w*0.5+r, cy), (w*0.5, cy+r), (w*0.5-r, cy), (w*0.5, cy-r)]
            strokes.append({"strokeId": f"acc_{uuid.uuid4().hex[:5]}", "x1": pts[0][0], "y1": pts[0][1],
                            "x2": pts[-1][0], "y2": pts[-1][1], "points": pts, "thickness": th * 0.8})

        for idx in range(acc_i, len(strokes)):
            seq.append({"type": "stroke", "index": idx})

        tot_asc = c_lay.ascent + font_size * 0.20
        return LayoutBox(w, tot_asc + c_lay.descent, tot_asc, c_lay.descent, glyphs, strokes, seq)

    # ── UNDERLINE: line below content ─────────────────────────────────────────
    if node.type == 'UNDERLINE' and node.content is not None:
        c_lay = layout_node(node.content, font_size)
        w = c_lay.width
        uy = c_lay.descent + font_size * 0.07
        th = max(1.4, font_size * 0.048)
        strokes = list(c_lay.strokes)
        ul_i = len(strokes)
        strokes.append({"strokeId": f"ul_{uuid.uuid4().hex[:5]}", "x1": 0.0, "y1": uy,
                        "x2": w, "y2": uy, "points": [(0.0, uy), (w, uy)], "thickness": th})
        seq = list(c_lay.constructionSequence or []) + [{"type": "stroke", "index": ul_i}]
        tot_desc = c_lay.descent + font_size * 0.13
        return LayoutBox(w, c_lay.ascent + tot_desc, c_lay.ascent, tot_desc,
                         list(c_lay.glyphs), strokes, seq)

    # ── CANCEL: diagonal slash through content ────────────────────────────────
    if node.type == 'CANCEL' and node.content is not None:
        c_lay = layout_node(node.content, font_size)
        w = c_lay.width
        strokes = list(c_lay.strokes)
        sl_i = len(strokes)
        strokes.append({"strokeId": f"sl_{uuid.uuid4().hex[:5]}",
                        "x1": 0.0, "y1": c_lay.descent,
                        "x2": w,   "y2": -c_lay.ascent,
                        "points": [(0.0, c_lay.descent), (w, -c_lay.ascent)],
                        "thickness": max(1.4, font_size * 0.05)})
        seq = list(c_lay.constructionSequence or []) + [{"type": "stroke", "index": sl_i}]
        return LayoutBox(w, c_lay.height, c_lay.ascent, c_lay.descent,
                         list(c_lay.glyphs), strokes, seq)

    # ── UNDERBRACE: curly brace below content with optional sub-label ─────────
    if node.type == 'UNDERBRACE' and node.content is not None:
        c_lay = layout_node(node.content, font_size)
        w = c_lay.width
        bt = c_lay.descent + font_size * 0.06   # brace top y
        bh = font_size * 0.18                   # brace height
        bc = bt + bh * 0.5                       # brace mid (horizontal arms)
        bb = bt + bh                             # brace bottom point
        th = max(1.4, font_size * 0.048)
        brace_pts = [
            (0.0, bt), (0.0, bc), (w * 0.22, bc), (w * 0.45, bb),
            (w * 0.5, bb), (w * 0.55, bb), (w * 0.78, bc), (w, bc), (w, bt),
        ]
        strokes = list(c_lay.strokes)
        br_i = len(strokes)
        strokes.append({"strokeId": f"ub_{uuid.uuid4().hex[:5]}",
                        "x1": brace_pts[0][0], "y1": brace_pts[0][1],
                        "x2": brace_pts[-1][0], "y2": brace_pts[-1][1],
                        "points": brace_pts, "thickness": th})
        seq = list(c_lay.constructionSequence or []) + [{"type": "stroke", "index": br_i}]
        glyphs = list(c_lay.glyphs)
        tot_desc = bb
        if node.sub:
            lbl = layout_node(node.sub, font_size * 0.62)
            ly = bb + font_size * 0.08 + lbl.ascent
            lx = (w - lbl.width) / 2.0
            g0, s0 = len(glyphs), len(strokes)
            for g in lbl.glyphs:
                glyphs.append({**g, "scaledX": g["scaledX"] + lx, "scaledY": g["scaledY"] + ly})
            for s in lbl.strokes:
                strokes.append({**s, "x1": s["x1"]+lx, "y1": s["y1"]+ly,
                                "x2": s["x2"]+lx, "y2": s["y2"]+ly,
                                "points": [(p[0]+lx, p[1]+ly) for p in s["points"]] if s.get("points") else None,
                                "charIndex": s["charIndex"]+g0 if s.get("charIndex") is not None else None})
            for step in (lbl.constructionSequence or []):
                seq.append({"type": step["type"],
                            "index": step["index"]+g0 if step["type"]=="glyph" else step["index"]+s0})
            tot_desc = ly + lbl.descent
        return LayoutBox(w, c_lay.ascent + tot_desc, c_lay.ascent, tot_desc, glyphs, strokes, seq)

    # ── OVERBRACE: curly brace above content with optional sup-label ──────────
    if node.type == 'OVERBRACE' and node.content is not None:
        c_lay = layout_node(node.content, font_size)
        w = c_lay.width
        bt = -(c_lay.ascent + font_size * 0.06)
        bh = font_size * 0.18
        bc = bt - bh * 0.5
        bb = bt - bh
        th = max(1.4, font_size * 0.048)
        brace_pts = [
            (0.0, bt), (0.0, bc), (w * 0.22, bc), (w * 0.45, bb),
            (w * 0.5, bb), (w * 0.55, bb), (w * 0.78, bc), (w, bc), (w, bt),
        ]
        strokes = list(c_lay.strokes)
        br_i = len(strokes)
        strokes.append({"strokeId": f"ob_{uuid.uuid4().hex[:5]}",
                        "x1": brace_pts[0][0], "y1": brace_pts[0][1],
                        "x2": brace_pts[-1][0], "y2": brace_pts[-1][1],
                        "points": brace_pts, "thickness": th})
        seq = list(c_lay.constructionSequence or []) + [{"type": "stroke", "index": br_i}]
        glyphs = list(c_lay.glyphs)
        tot_asc = -bb
        if node.sup:
            lbl = layout_node(node.sup, font_size * 0.62)
            ly = bb - font_size * 0.08 - lbl.descent
            lx = (w - lbl.width) / 2.0
            g0, s0 = len(glyphs), len(strokes)
            for g in lbl.glyphs:
                glyphs.append({**g, "scaledX": g["scaledX"] + lx, "scaledY": g["scaledY"] + ly})
            for s in lbl.strokes:
                strokes.append({**s, "x1": s["x1"]+lx, "y1": s["y1"]+ly,
                                "x2": s["x2"]+lx, "y2": s["y2"]+ly,
                                "points": [(p[0]+lx, p[1]+ly) for p in s["points"]] if s.get("points") else None,
                                "charIndex": s["charIndex"]+g0 if s.get("charIndex") is not None else None})
            for step in (lbl.constructionSequence or []):
                seq.append({"type": step["type"],
                            "index": step["index"]+g0 if step["type"]=="glyph" else step["index"]+s0})
            tot_asc = -(ly - lbl.ascent)
        return LayoutBox(w, tot_asc + c_lay.descent, tot_asc, c_lay.descent, glyphs, strokes, seq)

    # ── XARROW: stretchy arrow with optional over/under labels ───────────────
    if node.type == 'XARROW':
        style = XARROW_KINDS.get(node.op or "", "right")
        lbl_fs = font_size * 0.55
        over = layout_node(node.sup, lbl_fs) if node.sup else None
        under = layout_node(node.sub, lbl_fs) if node.sub else None
        side_pad = font_size * 0.30
        lbl_w = max(over.width if over else 0.0, under.width if under else 0.0)
        length = max(font_size * 1.7, lbl_w + 2 * side_pad)

        strokes = _build_xarrow_strokes(style, length, font_size)
        glyphs: List[Dict[str, Any]] = []
        seq: List[Dict[str, Any]] = [{"type": "stroke", "index": i} for i in range(len(strokes))]
        shaft_extent = font_size * 0.21  # half-height of arrowhead + equilibrium offset
        asc = shaft_extent
        desc = shaft_extent

        def _merge(sub: LayoutBox, dx: float, dy: float) -> None:
            g0, s0 = len(glyphs), len(strokes)
            for g in sub.glyphs:
                glyphs.append({**g, "scaledX": g["scaledX"] + dx, "scaledY": g["scaledY"] + dy})
            for s in sub.strokes:
                strokes.append({
                    **s,
                    "x1": s["x1"] + dx, "y1": s["y1"] + dy,
                    "x2": s["x2"] + dx, "y2": s["y2"] + dy,
                    "points": [(p[0] + dx, p[1] + dy) for p in s["points"]] if s.get("points") else None,
                    "charIndex": s["charIndex"] + g0 if s.get("charIndex") is not None else None,
                })
            for step in (sub.constructionSequence or []):
                strokes_off = g0 if step["type"] == "glyph" else s0
                seq.append({"type": step["type"], "index": step["index"] + strokes_off})

        if over:
            oy = -shaft_extent - font_size * 0.10 - over.descent
            _merge(over, (length - over.width) / 2.0, oy)
            asc = max(asc, -(oy - over.ascent))
        if under:
            uy = shaft_extent + font_size * 0.10 + under.ascent
            _merge(under, (length - under.width) / 2.0, uy)
            desc = max(desc, uy + under.descent)

        return LayoutBox(length, asc + desc, asc, desc, glyphs, strokes, seq)

    # ── Invisible bracket sentinel (from \left. / \right.) ───────────────────
    if node.type == 'CHAR' and node.value == '\x00':
        return LayoutBox(0.0, font_size, font_size * 0.75, font_size * 0.25, [], [], [])

    # Return empty layout for unrecognized nodes
    return LayoutBox(0.0, 0.0, 0.0, 0.0, [], [], [])

# --- Autoritative Entrypoint ---

def compile_latex_to_layout(latex_str: str, font_size: float = 32.0) -> Dict[str, Any]:
    # ── Preprocessing ──────────────────────────────────────────────────────
    cleaned = _repair_annotation_latex(latex_str)

    # Strip display-math delimiters ($$...$$, \[...\])
    cleaned = re.sub(r'^\$\$(.+?)\$\$$', r'\1', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'^\\\[(.+?)\\\]$', r'\1', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'^\$(.+?)\$$', r'\1', cleaned, flags=re.DOTALL)

    # {n \choose k}  →  \binom{n}{k}  (simple single-token n/k)
    cleaned = re.sub(
        r'\{([^{}]+?)\\choose\s+([^{}]+?)\}',
        lambda m: r'\binom{' + m.group(1).strip() + '}{' + m.group(2).strip() + '}',
        cleaned,
    )

    # Spacing commands → single space
    cleaned = re.sub(r'\\,|\\;|\\:|\\!|\\quad\b|\\qquad\b|\\enspace\b|\\thinspace\b', ' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    tokens = tokenize(cleaned)
    parser = ASTParser(tokens)
    ast = parser.parse()
    layout = layout_node(ast, font_size)

    half_w = layout.width / 2.0
    shift_y = (layout.descent - layout.ascent) / 2.0
    centered_glyphs = []
    for g in layout.glyphs:
        centered_glyphs.append({
            **g,
            "scaledX": g["scaledX"] - half_w,
            "scaledY": g["scaledY"] - shift_y
        })

    centered_strokes = []
    for s in layout.strokes:
        centered_strokes.append({
            **s,
            "x1": s["x1"] - half_w,
            "x2": s["x2"] - half_w,
            "y1": s["y1"] - shift_y,
            "y2": s["y2"] - shift_y,
            "points": [(pt[0] - half_w, pt[1] - shift_y) for pt in s["points"]] if s.get("points") else None
        })

    return {
        "width": layout.width,
        "height": layout.height,
        "ascent": layout.ascent,
        "descent": layout.descent,
        "glyphs": centered_glyphs,
        "strokes": centered_strokes,
        "constructionSequence": layout.constructionSequence
    }

def split_text_into_runs(text: str) -> List[Dict[str, Any]]:
    runs = []
    current_text = ""
    is_super = False
    i = 0
    while i < len(text):
        char = text[i]
        if char == '^':
            if current_text:
                runs.append({"text": current_text, "is_superscript": is_super})
                current_text = ""
            if i + 1 < len(text) and text[i + 1] == '{':
                j = i + 2
                brace_count = 1
                super_text = ""
                while j < len(text) and brace_count > 0:
                    if text[j] == '{':
                        brace_count += 1
                    elif text[j] == '}':
                        brace_count -= 1
                    if brace_count > 0:
                        super_text += text[j]
                    j += 1
                if super_text:
                    runs.append({"text": super_text, "is_superscript": True})
                i = j - 1
            else:
                if i + 1 < len(text):
                    runs.append({"text": text[i + 1], "is_superscript": True})
                    i += 1
        else:
            if is_super:
                runs.append({"text": current_text, "is_superscript": True})
                current_text = char
                is_super = False
            else:
                current_text += char
        i += 1
    if current_text:
        runs.append({"text": current_text, "is_superscript": is_super})
    return runs

def compile_text_to_layout(text: str, font_size: float = 32.0) -> Dict[str, Any]:
    text = _repair_annotation_latex(text)
    runs = split_text_into_runs(text)
    glyphs_layout = []
    strokes = []
    construction_sequence = []
    current_scaled_start_x = 0.0

    for run in runs:
        run_font_size = font_size * 0.65 if run["is_superscript"] else font_size
        run_text = run["text"]

        sub_widths = []
        for length in range(1, len(run_text) + 1):
            sub_str = run_text[:length]
            sub_widths.append(measure_glyph_width(sub_str, run_font_size))

        parts = []
        current_word = []
        for i, char in enumerate(run_text):
            if char.isalpha():
                current_word.append({"char": char, "index": i})
            else:
                if current_word:
                    parts.append({"type": "word", "items": current_word})
                    current_word = []
                parts.append({"type": "other", "char": char, "index": i})
        if current_word:
            parts.append({"type": "word", "items": current_word})

        for part in parts:
            if part["type"] == "other":
                char = part["char"]
                i = part["index"]
                prev_width = sub_widths[i - 1] if i > 0 else 0.0
                cur_width = sub_widths[i]
                char_width = cur_width - prev_width

                char_x = current_scaled_start_x + prev_width
                char_y = -font_size * 0.35 if run["is_superscript"] else 0.0
                char_font_size = run_font_size

                glyphs_layout.append({
                    "char": char,
                    "width": char_width,
                    "isSuperscript": run["is_superscript"],
                    "scaledX": char_x,
                    "scaledY": char_y,
                    "fontSize": char_font_size
                })

                glyph_strokes_list = get_glyph(char)
                for s_idx, pts in enumerate(glyph_strokes_list):
                    if len(pts) < 2:
                        continue
                    scaled_points = [
                        (char_x + p[0] * char_width, char_y + p[1] * char_font_size)
                        for p in pts
                    ]
                    # Match the handwriting quality of word-body strokes: Catmull-Rom
                    # smoothing + slant/wobble so digits and operators look hand-drawn,
                    # not geometrically clean amid cursive letters.
                    path_points = apply_handwriting_transform(
                        catmull_rom_chain(scaled_points, 4),
                        char, char_font_size, s_idx, len(glyph_strokes_list),
                    )
                    strokes.append({
                        "strokeId": f"char_stroke_{uuid.uuid4().hex[:5]}",
                        "charIndex": len(glyphs_layout) - 1,
                        "x1": path_points[0][0],
                        "y1": path_points[0][1],
                        "x2": path_points[-1][0],
                        "y2": path_points[-1][1],
                        "points": path_points,
                        "thickness": max(2.0, char_font_size * 0.06)
                    })
                    construction_sequence.append({"type": "stroke", "index": len(strokes) - 1})

            else:
                items = part["items"]
                word_seed = get_sketch_seed(items[0]["char"], 0) if items else 0
                word_len = len(items)
                drift_amp = 0.0 if run["is_superscript"] else min(2.0, font_size * 0.045)
                drift_phase = (word_seed % 100) * 0.0628
                drift_freq = 0.7 + (word_seed % 7) * 0.05

                for k, item in enumerate(items):
                    char = item["char"]
                    i = item["index"]
                    prev_width = sub_widths[i - 1] if i > 0 else 0.0
                    char_width = sub_widths[i] - prev_width
                    char_x = current_scaled_start_x + prev_width
                    drift_t = k / (word_len - 1) if word_len > 1 else 0.0
                    drift_y = drift_amp * math.sin(drift_phase + drift_t * math.pi * 2 * drift_freq)
                    char_y = (-font_size * 0.35 if run["is_superscript"] else 0.0) + drift_y
                    char_font_size = run_font_size

                    glyphs_layout.append({
                        "char": char,
                        "width": char_width,
                        "isSuperscript": run["is_superscript"],
                        "scaledX": char_x,
                        "scaledY": char_y,
                        "fontSize": char_font_size
                    })

                    glyph_strokes_list = get_glyph(char)
                    if not glyph_strokes_list:
                        continue
                    for s_idx, pts in enumerate(glyph_strokes_list):
                        if not pts or len(pts) < 2:
                            continue
                        scaled_points = [
                            (char_x + p[0] * char_width, char_y + p[1] * char_font_size)
                            for p in pts
                        ]
                        path_points = apply_handwriting_transform(
                            catmull_rom_chain(scaled_points, 4), char, char_font_size, s_idx, len(glyph_strokes_list), word_seed
                        )
                        strokes.append({
                            "strokeId": f"char_stroke_{uuid.uuid4().hex[:5]}",
                            "charIndex": len(glyphs_layout) - 1,
                            "x1": path_points[0][0],
                            "y1": path_points[0][1],
                            "x2": path_points[-1][0],
                            "y2": path_points[-1][1],
                            "points": path_points,
                            "thickness": max(2.0, char_font_size * 0.06)
                        })
                        construction_sequence.append({"type": "stroke", "index": len(strokes) - 1})

        current_scaled_start_x += sub_widths[-1] if sub_widths else 0.0

    half_w = current_scaled_start_x / 2.0
    ascent = font_size * 0.75
    descent = font_size * 0.25
    shift_y = (descent - ascent) / 2.0
    centered_glyphs = []
    for g in glyphs_layout:
        centered_glyphs.append({
            **g,
            "scaledX": g["scaledX"] - half_w,
            "scaledY": g["scaledY"] - shift_y
        })

    centered_strokes = []
    for s in strokes:
        centered_strokes.append({
            **s,
            "x1": s["x1"] - half_w,
            "x2": s["x2"] - half_w,
            "y1": s["y1"] - shift_y,
            "y2": s["y2"] - shift_y,
            "points": [(pt[0] - half_w, pt[1] - shift_y) for pt in s["points"]] if s.get("points") else None
        })

    return {
        "width": current_scaled_start_x,
        "height": font_size,
        "ascent": font_size * 0.75,
        "descent": font_size * 0.25,
        "glyphs": centered_glyphs,
        "strokes": centered_strokes,
        "constructionSequence": construction_sequence
    }

