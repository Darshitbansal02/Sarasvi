"""
Lightweight LaTeX → SymPy conversion (no antlr dependency).

sympy.parsing.latex.parse_latex requires antlr4 runtime which is not installed,
so we do a pragmatic transform that covers the equation forms our lessons emit.
Returns a sympy expression or raises on failure (caller treats failure as
'cannot verify' → UNVERIFIED, never a false rejection).
"""

from __future__ import annotations

import re
from typing import Any

import sympy as sp
from sympy.parsing.sympy_parser import (
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

_TRANSFORMS = standard_transformations + (implicit_multiplication_application,)


# Greek letters that SymPy can use as symbol names.
# \lambda → "lamda" because "lambda" is a Python keyword.
_GREEK_LATEX: dict[str, str] = {
    "theta": "theta", "vartheta": "theta",
    "phi": "phi", "varphi": "phi",
    "alpha": "alpha", "beta": "beta",
    "gamma": "gamma", "Gamma": "Gamma",
    "delta": "delta", "Delta": "Delta",
    "epsilon": "epsilon", "varepsilon": "epsilon",
    "zeta": "zeta", "eta": "eta",
    "iota": "iota", "kappa": "kappa",
    "lambda": "lamda", "Lambda": "Lambda",  # 'lamda' avoids Python keyword clash
    "mu": "mu", "nu": "nu",
    "xi": "xi", "Xi": "Xi",
    "rho": "rho", "sigma": "sigma", "Sigma": "Sigma",
    "tau": "tau", "upsilon": "upsilon",
    "chi": "chi", "psi": "psi", "Psi": "Psi",
    "omega": "omega", "Omega": "Omega",
    "infty": "oo",   # \infty → sympy's oo
}

# Trig / math functions sympy's parser understands (LaTeX backslash form)
_TRIG_FUNCS = re.compile(
    r"\\(sin|cos|tan|cot|sec|csc|arcsin|arccos|arctan|arccot|arcsec|arccsc|asin|acos|atan|acot|asec|acsc|sinh|cosh|tanh|log|ln|exp|sqrt)\b"
)

# Bare trig/math functions without a LaTeX backslash and without parentheses.
# Longer alternatives (sinh, cosh, arcsin …) must come before their prefixes (sin, cos …)
# so that "sinh" is never misread as "sin" + leftover "h".
# Uses (?<![a-zA-Z]) not \b because \b treats digits as word chars — "5sinx" has no
# \b before "s" since "5" is \w, so the lookbehind is more precise.
# Matches: sinx → sin(x), 5sinx → 5sin(x), sin x → sin(x), cosx → cos(x), etc.
# Does NOT match: sin(x) (already parenthesised), asin (preceded by letter).
_BARE_TRIG_RE = re.compile(
    r"(?<![a-zA-Z])(sinh|cosh|tanh|arcsin|arccos|arctan|arccot|arcsec|arccsc|asin|acos|atan|acot|asec|acsc|sin|cos|tan|cot|sec|csc|log|ln|exp)"
    r"(?!\s*\()\s*([a-zA-Z][a-zA-Z0-9_]*)",
    re.I,
)


def _convert_limits(s: str) -> str:
    # Match \lim_{var \to point}
    lim_re = re.compile(
        r"\\lim\s*_\s*\{\s*([a-zA-Z]+)\s*(?:\\to|->|\\rightarrow)\s*([^\}]+)\s*\}"
    )
    while True:
        match = lim_re.search(s)
        if not match:
            break
        start, end = match.span()
        var = match.group(1)
        point = match.group(2)
        rem = s[end:]
        limit_expr_len = len(rem)
        stack = []
        for i, char in enumerate(rem):
            if char in "{[(":
                stack.append(char)
            elif char in "}])":
                if not stack:
                    limit_expr_len = i
                    break
                else:
                    stack.pop()
            elif char == '=':
                if not stack:
                    limit_expr_len = i
                    break
        limit_expr = rem[:limit_expr_len]
        converted = f"Limit({limit_expr}, {var}, {point})"
        s = s[:start] + converted + rem[limit_expr_len:]
    return s


def _convert_derivatives(s: str) -> str:
    """
    Convert Leibniz operator notation to a SymPy Derivative BEFORE _convert_fractions
    consumes the \\frac. The operator applies to the rest of the (single) equation
    side, which is the dominant teaching form:
        \\frac{d}{dx} x^3        → Derivative(x^3, x)
        \\frac{d^2}{dx^2}(x^3)   → Derivative((x^3), x, 2)
    Ordinary fractions (numerator ≠ d / d^n) are left untouched for _convert_fractions.
    """
    m = re.search(
        r"\\frac\s*\{\s*d(?:\^\{?(\d+)\}?)?\s*\}\s*\{\s*d\s*([a-zA-Z])(?:\^\{?\d+\}?)?\s*\}",
        s,
    )
    if not m:
        return s
    order = m.group(1)
    var = m.group(2)
    operand = s[m.end():].strip()
    if not operand:
        return s
    if order and int(order) > 1:
        repl = f"Derivative({operand}, {var}, {order})"
    else:
        repl = f"Derivative({operand}, {var})"
    return s[:m.start()] + repl


def _convert_integrals(s: str) -> str:
    """
    Convert integral notation to a SymPy Integral, capturing optional bounds and the
    d<var> measure. Runs on a single equation side, so the integrand is everything
    between the (optional) bounds and the measure:
        \\int 3x^2 dx              → Integral(3x^2, x)
        \\int_{0}^{1} x \\, dx      → Integral(x, (x, 0, 1))
    Handles multiple integrals in the same expression using an iterative search loop.
    If the measure can't be located the string is returned unchanged (→ UNVERIFIED,
    never a false rejection).
    """
    start_pos = 0
    while True:
        idx = s.find("\\int", start_pos)
        if idx == -1:
            break
        rest = s[idx + 4:]

        lower = upper = None
        bm = re.match(r"\s*_\s*\{([^}]*)\}\s*\^\s*\{([^}]*)\}", rest)
        if not bm:
            bm = re.match(r"\s*_\s*([A-Za-z0-9])\s*\^\s*([A-Za-z0-9])", rest)
        if bm:
            lower, upper = bm.group(1), bm.group(2)
            rest = rest[bm.end():]

        # Prevent searching into a subsequent integral's domain
        next_int = rest.find("\\int")
        search_limit = len(rest) if next_int == -1 else next_int
        search_area = rest[:search_limit]

        # Prefer a measure anchored at the end of the search area; fall back to the first d<var>
        mm = re.search(r"(?:\\,|\s)*d\s*([a-zA-Z])\s*$", search_area)
        if not mm:
            mm = re.search(r"(?:\\,|\s)*d\s*([a-zA-Z])(?![a-zA-Z])", search_area)
        if not mm:
            # Move start_pos past this \int to avoid infinite loop
            start_pos = idx + 4
            continue

        var = mm.group(1)
        integrand = search_area[:mm.start()].strip() or "1"

        if lower is not None:
            repl = f"Integral({integrand}, ({var}, {lower}, {upper}))"
        else:
            repl = f"Integral({integrand}, {var})"
        
        s = s[:idx] + repl + rest[mm.end():]
        start_pos = idx + len(repl)
    return s


def _convert_fractions(s: str) -> str:
    # Match \frac{A}{B} recursively using balanced braces
    frac_re = re.compile(r"\\frac\b")
    while True:
        match = frac_re.search(s)
        if not match:
            break
        start = match.start()
        rem = s[match.end():]
        first_open = rem.find('{')
        if first_open == -1:
            break
        stack = []
        first_close = -1
        for i in range(first_open, len(rem)):
            char = rem[i]
            if char == '{':
                stack.append('{')
            elif char == '}':
                stack.pop()
                if not stack:
                    first_close = i
                    break
        if first_close == -1:
            break
        arg1 = rem[first_open + 1:first_close]
        rem2 = rem[first_close + 1:]
        second_open = rem2.find('{')
        if second_open == -1:
            break
        stack = []
        second_close = -1
        for i in range(second_open, len(rem2)):
            char = rem2[i]
            if char == '{':
                stack.append('{')
            elif char == '}':
                stack.pop()
                if not stack:
                    second_close = i
                    break
        if second_close == -1:
            break
        arg2 = rem2[second_open + 1:second_close]
        arg1 = _convert_fractions(arg1)
        arg2 = _convert_fractions(arg2)
        end_idx = match.end() + first_close + 1 + second_close + 1
        s = s[:start] + f"(({arg1})/({arg2}))" + s[end_idx:]
    return s


def _convert_subscripts(s: str) -> str:
    # Subscripts: a_{bc} -> a_bc
    s = re.sub(r"([a-zA-Z0-9_]+)_\{([a-zA-Z0-9_]+)\}", r"\1_\2", s)
    return s


def _strip_latex(s: str) -> str:
    s = s.strip()
    s = _convert_limits(s)
    # Derivatives must run before _convert_fractions (they share the \frac form);
    # integrals before the d<var> measure is disturbed by later replacements.
    s = _convert_derivatives(s)
    s = _convert_integrals(s)
    s = _convert_fractions(s)
    s = _convert_subscripts(s)

    # Replace arc* trig functions with standard a* trig functions (SymPy compatible)
    s = s.replace("arcsin", "asin").replace("arccos", "acos").replace("arctan", "atan")
    s = s.replace("arccot", "acot").replace("arcsec", "asec").replace("arccsc", "acsc")

    # Clean up \operatorname{atan} -> \atan
    s = re.sub(r"\\operatorname\{([a-zA-Z0-9_]+)\}", r"\\\1", s)

    s = s.replace("\\left", "").replace("\\right", "")
    s = s.replace("\\,", " ").replace("\\;", " ").replace("\\!", "")
    s = s.replace("\\cdot", "*").replace("\\times", "*").replace("\\div", "/")
    s = s.replace("\\pm", "")   # ±: strip rather than misparse
    s = s.replace("\\mp", "")

    # Map LaTeX absolute value symbols to standard |
    s = s.replace("\\lvert", "|").replace("\\rvert", "|").replace("\\vert", "|")

    # Replace |expr| with (abs(expr)) before function cleaning
    s = re.sub(r"\|([^|]+)\|", r"(abs(\1))", s)

    s = re.sub(r"\\sqrt\{([^{}]*)\}", r"sqrt(\1)", s)
    s = re.sub(r"\\sqrt\s*([0-9a-zA-Z])", r"sqrt(\1)", s)
    s = s.replace("^", "**")

    # \pi, trig functions, ln
    s = s.replace("\\pi", "pi")
    s = _TRIG_FUNCS.sub(r"\1", s)
    # Bare function names without parens: sinx → sin(x), cos x → cos(x).
    # Runs AFTER backslash-trig strip so \sin(x) → sin(x) is already correct
    # and doesn't re-enter this path.
    s = _BARE_TRIG_RE.sub(lambda m: f"{m.group(1)}({m.group(2)})", s)
    s = s.replace("ln(", "log(")

    # Greek letters → their SymPy-compatible ASCII names (before the catch-all stripper)
    def _greek_sub(m: re.Match) -> str:
        cmd = m.group(1)
        return _GREEK_LATEX.get(cmd, "")   # unknown commands → empty string

    s = re.sub(r"\\([a-zA-Z]+)", _greek_sub, s)

    s = s.replace("{", "(").replace("}", ")")
    return s.strip()


def latex_to_sympy(latex: str, symbols: dict[str, Any] | None = None) -> sp.Expr:
    cleaned = _strip_latex(latex)
    if not cleaned:
        raise ValueError("empty expression")
    local = dict(symbols or {})
    local.setdefault("abs", sp.Abs)

    # Dynamically inject all SymPy callables of length >= 2
    for name in dir(sp):
        attr = getattr(sp, name)
        if callable(attr) and len(name) >= 2:
            local.setdefault(name, attr)

    return parse_expr(cleaned, transformations=_TRANSFORMS, local_dict=local, evaluate=True)


# LaTeX commands we faithfully convert. Anything outside this set is silently
# dropped by _strip_latex (unknown → ""), which would corrupt the expression —
# so the verifier must NOT issue a hard REJECT for equations that contain them.
_KNOWN_LATEX_CMDS: set[str] = (
    set(_GREEK_LATEX)
    | {
        "sin", "cos", "tan", "cot", "sec", "csc",
        "arcsin", "arccos", "arctan", "arccot", "arcsec", "arccsc",
        "asin", "acos", "atan", "acot", "asec", "acsc",
        "sinh", "cosh", "tanh",
        "frac", "sqrt", "left", "right", "cdot", "times", "div",
        "int", "iint", "iiint", "oint", "partial",
        "pi", "ln", "log", "exp", "lim", "to", "rightarrow", "longrightarrow",
        "leq", "geq", "neq", "infty", "operatorname",
        "lvert", "rvert", "vert", "quad", "qquad",
    }
)

# Approximation markers — when present, an equation is intentionally inexact and
# must never be hard-rejected as a false identity.
_APPROX_MARKERS = ("\\approx", "≈", "\\sim", "\\simeq", "\\cong", "\\propto", "~")


def contains_unsupported_latex(latex: str) -> bool:
    """True if `latex` uses a command we don't faithfully parse (→ skip hard reject)."""
    for cmd in re.findall(r"\\([a-zA-Z]+)", latex):
        if cmd not in _KNOWN_LATEX_CMDS and cmd.lower() not in _KNOWN_LATEX_CMDS:
            return True
    return False


def is_approximate(latex: str) -> bool:
    """True if the equation is an approximation (≈, ∼, ∝, …) rather than an identity."""
    return any(m in latex for m in _APPROX_MARKERS)


def split_equation(latex: str) -> tuple[str, str] | None:
    """Split 'lhs = rhs' on the top-level single '='. Ignores >=, <=, ==, !=."""
    s = latex.replace("\\leq", "≤").replace("\\geq", "≥").replace("\\neq", "≠")
    # find a single '=' not part of a comparison
    candidates = [m.start() for m in re.finditer(r"=", s)]
    for idx in candidates:
        before = s[idx - 1] if idx > 0 else ""
        after = s[idx + 1] if idx + 1 < len(s) else ""
        if before in "<>!=≤≥≠" or after == "=":
            continue
        return s[:idx].strip(), s[idx + 1 :].strip()
    return None
