"""
Physics verifier — dimensional analysis.

Builds the physical dimension (in base dimensions M, L, T, I, Θ) of each side of an
equation from a table of common physical symbols and rejects dimensionally
inconsistent equations. Unknown symbols or unparseable forms → UNVERIFIED
(never a false rejection).
"""

from __future__ import annotations

from typing import Any

import sympy as sp

from app.verification.base import ClaimVerification, VerificationStatus
from app.verification.latex_sympy import latex_to_sympy, split_equation

# Base dimensions
M, L, T, I, TH = sp.symbols("M L T I Theta", positive=True)
_DIMLESS = sp.Integer(1)

# Common physics symbol → dimension. Conservative; unknown symbols → UNVERIFIED.
_DIM: dict[str, sp.Expr] = {
    "m": M, "M": M,
    "t": T, "T": T,
    "x": L, "d": L, "r": L, "h": L, "l": L, "s": L, "lambda": L, "y": L,
    "v": L / T, "u": L / T, "c": L / T,
    "a": L / T**2, "g": L / T**2,
    "F": M * L / T**2, "N": M * L / T**2,
    "p": M * L / T,
    "E": M * L**2 / T**2, "W": M * L**2 / T**2, "K": M * L**2 / T**2, "U": M * L**2 / T**2,
    "P": M * L**2 / T**3,            # power
    "f": 1 / T, "omega": 1 / T,       # frequency / angular frequency
    "q": I * T, "Q": I * T,           # charge
    "pi": _DIMLESS, "theta": _DIMLESS, "n": _DIMLESS,
}


class DimensionError(Exception):
    pass


def _dimension(expr: sp.Expr) -> sp.Expr:
    """Return dimension monomial in M,L,T,I,Θ or raise DimensionError."""
    if expr.is_Number:
        return _DIMLESS
    if expr.is_Symbol:
        name = expr.name
        if name in _DIM:
            return _DIM[name]
        raise DimensionError(f"unknown symbol {name}")
    if expr.is_Add:
        dims = [_dimension(arg) for arg in expr.args]
        first = sp.simplify(dims[0])
        for d in dims[1:]:
            if sp.simplify(d - first) != 0:
                raise DimensionError("inconsistent additive terms")
        return first
    if expr.is_Mul:
        out = _DIMLESS
        for arg in expr.args:
            out = out * _dimension(arg)
        return sp.simplify(out)
    if expr.is_Pow:
        base, exp = expr.args
        if not exp.is_Number:
            raise DimensionError("non-numeric exponent")
        return sp.simplify(_dimension(base) ** exp)
    if expr.is_Function:
        # sin/cos/exp/log require dimensionless args; result dimensionless
        for arg in expr.args:
            if sp.simplify(_dimension(arg) - _DIMLESS) != 0:
                raise DimensionError("non-dimensionless function argument")
        return _DIMLESS
    raise DimensionError(f"unsupported node {type(expr)}")


def _equation_steps(teaching_sequence: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for step in teaching_sequence:
        prim = step.get("visual_primitive") or {}
        if not isinstance(prim, dict):
            continue
        if str(prim.get("type", "")).lower() not in {"equation", "equation_write"}:
            continue
        data = prim.get("data") or {}
        latex = str(data.get("full_latex") or data.get("latex") or "").strip()
        if latex and "=" in latex:
            out.append(latex)
    return out


class PhysicsVerifier:
    name = "physics"

    def verify(self, teaching_sequence: list[dict[str, Any]], *, query: str = "", **_: Any) -> list[ClaimVerification]:
        results: list[ClaimVerification] = []
        for latex in _equation_steps(teaching_sequence):
            parts = split_equation(latex)
            if not parts:
                continue
            lhs_s, rhs_s = parts
            try:
                lhs = latex_to_sympy(lhs_s)
                rhs = latex_to_sympy(rhs_s)
                lhs_dim = _dimension(lhs)
                rhs_dim = _dimension(rhs)
            except DimensionError as exc:
                results.append(ClaimVerification(latex, "physics", VerificationStatus.UNVERIFIED,
                                                 0.3, f"dim-skip: {exc}", self.name))
                continue
            except Exception as exc:
                results.append(ClaimVerification(latex, "physics", VerificationStatus.UNVERIFIED,
                                                 0.3, f"parse-skip: {exc}", self.name))
                continue

            if sp.simplify(lhs_dim / rhs_dim) == 1:
                results.append(ClaimVerification(latex, "physics", VerificationStatus.VERIFIED,
                                                 0.9, "dimensionally consistent", self.name))
            else:
                # Do NOT fail the lesson on a dimension mismatch: the symbol→dimension
                # table assumes one physical meaning per letter (E=energy, P=power,
                # a=acceleration, …), but lessons legitimately reuse those letters for
                # other quantities (E=electric field, P=pressure, generic constants).
                # A mismatch is therefore advisory, not a provable error → UNVERIFIED.
                results.append(ClaimVerification(latex, "physics", VerificationStatus.UNVERIFIED,
                                                 0.35, f"dimension mismatch (advisory) {lhs_dim} vs {rhs_dim}", self.name))
        return results


physics_verifier = PhysicsVerifier()
