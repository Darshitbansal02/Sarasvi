"""
Math verifier — universal, subject-agnostic symbolic checking.

There is NO per-subject logic, NO operation/keyword detection, and NO hardcoded
examples. Every equation the lesson asserts is judged purely on whether it is
mathematically true: both sides are parsed and compared symbolically, evaluating
integrals / derivatives / limits / sums via .doit(). The same rule covers
algebra, calculus, physics relations, chemistry rate laws — anything expressed as
an equation, in any subject.

Per-equation verdicts:
  VERIFIED    the relation holds (including after .doit())
  REJECTED    a provably FALSE numeric identity (e.g. 2 + 2 = 5)
  UNVERIFIED  unparseable, approximate, or not a provable identity (safe default —
              a definitional relation between independent symbols is never rejected)
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any

import sympy as sp

from app.verification.base import ClaimVerification, VerificationStatus
from app.verification.latex_sympy import (
    contains_unsupported_latex,
    is_approximate,
    latex_to_sympy,
    split_equation,
)

# ─── Constants ────────────────────────────────────────────────────────────────

# Bounds for symbolic verification, settings-driven so they can be tuned in prod
# without a redeploy. Pathological trig/radical simplifications would otherwise
# stall generation for minutes. _EQ_TIMEOUT caps ONE equality check;
# _VERIFY_BUDGET_SEC caps the whole math pass. Over-budget claims degrade to
# UNVERIFIED — a safe, non-fatal verdict surfaced to the UI.
try:
    from app.config.settings import get_settings as _get_settings
    _vs = _get_settings()
    _EQ_TIMEOUT = float(getattr(_vs, "verify_eq_timeout_sec", 2.0))
    _VERIFY_BUDGET_SEC = float(getattr(_vs, "verify_budget_sec", 15.0))
except Exception:
    _EQ_TIMEOUT = 2.0
    _VERIFY_BUDGET_SEC = 15.0

# Numeric-identity tolerances. The relative tolerance is deliberately loose so
# legitimately rounded teaching values (e.g. 3.14159 for π) still verify.
_NUMERIC_ABS_TOL = 1e-06
_NUMERIC_REL_TOL = 0.005

# LaTeX greek command → SymPy symbol name (e.g. "\theta" → Symbol('theta')).
_GREEK_CMD_TO_SYM = {
    'theta': 'theta', 'vartheta': 'theta', 'phi': 'phi', 'varphi': 'phi',
    'alpha': 'alpha', 'beta': 'beta', 'gamma': 'gamma', 'Gamma': 'Gamma',
    'delta': 'delta', 'Delta': 'Delta', 'epsilon': 'epsilon', 'varepsilon': 'epsilon',
    'zeta': 'zeta', 'eta': 'eta', 'iota': 'iota', 'kappa': 'kappa',
    'lambda': 'lamda', 'Lambda': 'Lambda', 'mu': 'mu', 'nu': 'nu', 'xi': 'xi',
    'Xi': 'Xi', 'rho': 'rho', 'sigma': 'sigma', 'Sigma': 'Sigma', 'tau': 'tau',
    'upsilon': 'upsilon', 'chi': 'chi', 'psi': 'psi', 'Psi': 'Psi',
    'omega': 'omega', 'Omega': 'Omega',
}

# Identifiers that are mathematical functions / reserved constants, never symbols.
_NON_VAR_NAMES = {
    'asec', 'acsc', 'arccot', 'arcsin', 'arctan', 'exp', 'arccsc', 'csc', 'sinh',
    'sec', 'arccos', 'tanh', 'sin', 'cot', 'atan', 'pi', 'arcsec', 'cos', 'cosh',
    'ln', 'log', 'sqrt', 'acot', 'asin', 'tan', 'acos', 'oo', 'abs',
}

# Reserved single letters that map to SymPy constants rather than free symbols.
_RESERVED = {'e': sp.E, 'i': sp.I, 'pi': sp.pi, 'oo': sp.oo}


# ─── Numeric / parsing helpers ────────────────────────────────────────────────

def _numeric_equal_tol(a: sp.Expr, b: sp.Expr) -> bool | None:
    """
    Compare two constant expressions with tolerance.
    Returns True (equal), False (clearly different), or None (cannot evaluate →
    caller must treat as UNVERIFIED, never reject).
    """
    try:
        av = complex(a.evalf())
        bv = complex(b.evalf())
    except Exception:
        return None
    if not (abs(av.imag) < 1e-09 and abs(bv.imag) < 1e-09):
        return None
    av, bv = av.real, bv.real
    diff = abs(av - bv)
    if diff <= _NUMERIC_ABS_TOL:
        return True
    scale = max(abs(av), abs(bv), 1.0)
    return diff / scale <= _NUMERIC_REL_TOL


def _is_unsafe_to_reject(latex: str) -> bool:
    """An equation we cannot faithfully parse or that is explicitly approximate
    must never be hard-rejected (→ UNVERIFIED instead)."""
    return contains_unsupported_latex(latex) or is_approximate(latex)


def _build_symbols(text: str) -> dict[str, Any]:
    """
    Auto-create SymPy symbols for every variable identifier found in cleaned `text`.

    Handles single-letter and multi-character/subscript variables, greek LaTeX
    commands (\\theta → Symbol('theta')), and reserved names (e → E, i → I, …).
    Multi-letter names that are mathematical functions (sin, cos, …) are left to
    SymPy's parser and excluded from the symbol table.
    """
    _FUNCS_SET = {
        'sqrt', 'Limit', 'exp', 'sin', 'asin', 'tanh', 'csc', 'acos', 'cos',
        'tan', 'cot', 'limit', 'cosh', 'ln', 'log', 'sinh', 'sec', 'atan', 'abs',
        # SymPy operator constructors emitted by the LaTeX converters — must NOT
        # become free symbols (that would shadow the real callables at parse time).
        'integral', 'derivative', 'sum', 'product',
    }
    table: dict[str, Any] = {}

    # Match variables even when preceded by digits (like 3x, 2y, etc.)
    for word in re.findall(r"(?<![a-zA-Z_])([a-zA-Z][a-zA-Z0-9_]*)\b", text):
        word_lower = word.lower()
        if word_lower in _FUNCS_SET or word_lower in _NON_VAR_NAMES:
            continue
        if word in _RESERVED:
            table[word] = _RESERVED[word]
        elif word not in table:
            table[word] = sp.Symbol(word, real=True)

    for cmd in re.findall(r"\\([a-zA-Z]+)", text):
        sym_name = _GREEK_CMD_TO_SYM.get(cmd)
        if sym_name and sym_name not in table and sym_name not in _NON_VAR_NAMES:
            table[sym_name] = sp.Symbol(sym_name, real=True)

    return table


def _parse(latex: str, extra: dict[str, Any] | None = None) -> sp.Expr:
    """Parse one side of an equation into a SymPy expression."""
    from app.verification.latex_sympy import _strip_latex
    cleaned = _strip_latex(latex)
    syms = _build_symbols(cleaned)
    if extra:
        syms.update(extra)
    return latex_to_sympy(latex, syms)


# ─── Symbolic equality ────────────────────────────────────────────────────────

def _timed(fn, timeout: float):
    """Run fn() in a daemon thread; return result or None on timeout/error."""
    result = [None]
    exc = [None]

    def _worker():
        try:
            result[0] = fn()
        except Exception as e:
            exc[0] = e

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout)
    if exc[0] is not None:
        raise exc[0]
    return result[0]


def _numeric_sample_zero(expr: sp.Expr, n: int = 8) -> bool:
    """Spot-check expr == 0 by substituting random real values for free symbols."""
    free = list(expr.free_symbols)
    if not free:
        try:
            return abs(complex(expr.evalf())) < 1e-8
        except Exception:
            return False
    import random
    rng = random.Random(0)
    for _ in range(n):
        subs = {s: rng.uniform(0.7, 3.5) for s in free}
        try:
            val = complex(expr.subs(subs).evalf())
            if abs(val) > 1e-6:
                return False
        except Exception:
            return False
    return True


def _symbolically_equal(a: sp.Expr, b: sp.Expr) -> bool:
    """
    Check a == b using a cascade of simplification strategies (cheapest first),
    evaluating limits/integrals/derivatives via .doit() first.

    The ENTIRE cascade (including .doit()) runs inside ONE worker thread under a
    single timeout. Python cannot kill a thread, so running all heavy symbolic
    operations inside the timed wrapper prevents blocking the verifier's execution
    indefinitely if SymPy encounters a pathological or misparsed expression.
    Returns False on timeout/error — safe default: never reject when uncertain.
    """
    def _cascade() -> bool:
        # Fast path: if there are no free symbols, try evaluating numerically first.
        # This resolves definite integrals, limits, and sums quickly if they are constants.
        if not (a.free_symbols or b.free_symbols):
            try:
                av = a.evalf()
                bv = b.evalf()
                diff = abs(av - bv)
                if diff <= _NUMERIC_ABS_TOL:
                    return True
                scale = max(abs(av), abs(bv), 1.0)
                if diff / scale <= _NUMERIC_REL_TOL:
                    return True
            except Exception:
                pass

        try:
            expr_a = a.doit()
        except Exception:
            expr_a = a
        try:
            expr_b = b.doit()
        except Exception:
            expr_b = b

        diff = expr_a - expr_b
        strategies = (
            lambda d: sp.cancel(d) == 0,                 # fast: rational/polynomial
            lambda d: sp.simplify(d) == 0,
            lambda d: sp.trigsimp(d) == 0,
            lambda d: sp.expand(sp.trigsimp(sp.expand(d))) == 0,
            lambda d: sp.nsimplify(d) == 0,
            lambda d: _numeric_sample_zero(d),           # sampling, not a proof
        )

        for strategy in strategies:
            try:
                if strategy(diff) is True:
                    return True
            except Exception:
                continue
        return False

    try:
        # Give a slightly higher timeout budget for pure constant expressions to allow
        # numerical evaluation of complex definite integrals/sums.
        timeout = _EQ_TIMEOUT
        if not (a.free_symbols or b.free_symbols):
            timeout = max(timeout, 5.0)
        return _timed(_cascade, timeout) is True
    except Exception:
        return False





# ─── Equation step extraction ─────────────────────────────────────────────────

def _equation_steps(teaching_sequence: list[dict[str, Any]]) -> list[str]:
    """Return all equation LaTeX strings (containing '=') from visual primitives."""
    out: list[str] = []
    for step in teaching_sequence:
        prim = step.get("visual_primitive") or {}
        if not isinstance(prim, dict):
            continue
        if str(prim.get("type", "")).lower() not in {
            "equation", "equation_write", "equation_highlight"
        }:
            continue
        data = prim.get("data") or {}
        latex = str(
            data.get("full_latex") or data.get("latex") or data.get("append_latex") or ""
        ).strip()
        if latex and "=" in latex:
            out.append(latex)
    return out


# ─── Main verifier ────────────────────────────────────────────────────────────

class MathVerifier:
    name = "math"

    def verify(
        self,
        teaching_sequence: list[dict[str, Any]],
        **_: Any,
    ) -> list[ClaimVerification]:
        """
        Universal, subject-agnostic symbolic verification. For every equation the
        lesson asserts, parse both sides and test whether the relation actually
        holds — evaluating integrals / derivatives / limits / sums via .doit()
        (inside _symbolically_equal). This works for ANY operation in ANY subject
        with NO keyword/operation detection and NO query parsing: an equation is
        judged purely on whether it is mathematically true.
          • relation holds (incl. after .doit())  → VERIFIED
          • provably false numeric identity        → REJECTED
          • unparseable / not a provable identity  → UNVERIFIED  (safe, non-fatal)
        """
        results: list[ClaimVerification] = []
        _deadline = time.monotonic() + _VERIFY_BUDGET_SEC

        for latex in _equation_steps(teaching_sequence):
            parts = split_equation(latex)
            if not parts:
                continue

            # Once the time budget is spent, stop expensive symbolic work and mark
            # the rest UNVERIFIED rather than stalling generation.
            if time.monotonic() > _deadline:
                results.append(ClaimVerification(
                    latex, "mathematics", VerificationStatus.UNVERIFIED,
                    0.3, "skipped (verification time budget exceeded)", self.name,
                ))
                continue

            lhs_s, rhs_s = parts
            try:
                # Build a unified symbol table for the entire equation (LHS + RHS) to avoid
                # assumptions mismatch (e.g. Symbol('x', real=True) vs Symbol('x'))
                from app.verification.latex_sympy import _strip_latex
                cleaned_lhs = _strip_latex(lhs_s)
                cleaned_rhs = _strip_latex(rhs_s)
                syms = _build_symbols(cleaned_lhs + " + " + cleaned_rhs)
                
                lhs = latex_to_sympy(lhs_s, syms)
                rhs = latex_to_sympy(rhs_s, syms)
            except Exception:
                results.append(ClaimVerification(
                    latex, "mathematics", VerificationStatus.UNVERIFIED,
                    0.3, "unparseable equation", self.name,
                ))
                continue

            # A bound-variable construct (Limit/Integral/Sum/Product/Derivative)
            # reports no free symbols but is NOT a numeric literal — route it to the
            # symbolic (.doit()-based) check so e.g. an integral or limit equation
            # verifies instead of being mistaken for a numeric mismatch.
            _has_operator = any(
                e.has(sp.Limit, sp.Integral, sp.Sum, sp.Product, sp.Derivative)
                for e in (lhs, rhs)
            )

            # ── Pure numeric identity (concrete numbers on both sides) ─────────
            if not _has_operator and not (lhs.free_symbols or rhs.free_symbols):
                # Approximate (≈) or unfaithfully-parseable (\pm, \binom, …)
                # equations must not be hard-rejected — we can't trust the parse.
                if _is_unsafe_to_reject(latex):
                    results.append(ClaimVerification(
                        latex, "mathematics", VerificationStatus.UNVERIFIED,
                        0.3, "numeric (approx/unsupported notation) — not verifiable", self.name,
                    ))
                    continue
                tol = _numeric_equal_tol(lhs, rhs)
                ok = _symbolically_equal(lhs, rhs) if tol is None else tol
                if tol is None and not ok:
                    results.append(ClaimVerification(
                        latex, "mathematics", VerificationStatus.UNVERIFIED,
                        0.3, "numeric identity not evaluable", self.name,
                    ))
                    continue
                results.append(ClaimVerification(
                    latex, "mathematics",
                    VerificationStatus.VERIFIED if ok else VerificationStatus.REJECTED,
                    0.99,
                    "numeric identity" if ok else "false numeric identity",
                    self.name,
                ))
                continue

            # ── Symbolic / operational identity (holds for all values) ────────
            if _symbolically_equal(lhs, rhs):
                results.append(ClaimVerification(
                    latex, "mathematics", VerificationStatus.VERIFIED,
                    0.9, "symbolic identity", self.name,
                ))
                continue

            # ── Has free symbols, not a provable identity → definitional ──────
            # A defining relation between independent symbols is legitimate and is
            # never rejected — only a provably FALSE numeric identity rejects.
            results.append(ClaimVerification(
                latex, "mathematics", VerificationStatus.UNVERIFIED,
                0.4, "definitional / not a provable identity", self.name,
            ))

        return results


math_verifier = MathVerifier()
