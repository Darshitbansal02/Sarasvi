"""
Chemistry verifier — atom-conservation (balance) checking for reaction equations.

Parses 'aA + bB -> cC + dD' (or =, →, \\rightarrow, \\to as the arrow), counts atoms
on each side (handling parentheses/hydrates), and REJECTS unbalanced reactions.
Non-reaction statements → UNVERIFIED.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.verification.base import ClaimVerification, VerificationStatus

_ARROWS = ["\\rightarrow", "\\to", "->", "→", "⟶", "="]
_ELEMENT_RE = re.compile(r"([A-Z][a-z]?)(\d*)")


VALID_ELEMENTS = {
    "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne", "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar",
    "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge", "As", "Se", "Br", "Kr",
    "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn", "Sb", "Te", "I", "Xe",
    "Cs", "Ba", "La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu",
    "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi", "Po", "At", "Rn", "Fr", "Ra",
    "Ac", "Th", "Pa", "U", "Np", "Pu", "Am", "Cm", "Bk", "Cf", "Es", "Fm", "Md", "No", "Lr", "Rf", "Db",
    "Sg", "Bh", "Hs", "Mt", "Ds", "Rg", "Cn", "Nh", "Fl", "Mc", "Lv", "Ts", "Og"
}


def _parse_formula(formula: str) -> Counter:
    """Count atoms in a formula, supporting nested parentheses, e.g. Ca(OH)2.
    Raises ValueError on unexpected/invalid characters or elements to prevent false matching."""
    formula = formula.strip()
    counts: Counter = Counter()
    stack: list[Counter] = [Counter()]
    i = 0
    while i < len(formula):
        ch = formula[i]
        if ch == "(" or ch == "[":
            stack.append(Counter())
            i += 1
        elif ch == ")" or ch == "]":
            i += 1
            num = ""
            while i < len(formula) and formula[i].isdigit():
                num += formula[i]
                i += 1
            mult = int(num) if num else 1
            if not stack:
                raise ValueError("Unmatched closing parenthesis")
            group = stack.pop()
            for el, c in group.items():
                stack[-1][el] += c * mult
        elif ch.isdigit():
            i += 1
        elif ch in "+-·*•^#{}":
            i += 1
        elif ch.isspace():
            i += 1
        else:
            m = _ELEMENT_RE.match(formula, i)
            if m and m.group(1):
                el = m.group(1)
                if el not in VALID_ELEMENTS:
                    raise ValueError(f"Invalid chemical element symbol: {el}")
                cnt = int(m.group(2)) if m.group(2) else 1
                stack[-1][el] += cnt
                i = m.end()
            else:
                raise ValueError(f"Unexpected character in chemical formula: {ch}")
    while len(stack) > 1:
        group = stack.pop()
        stack[-1].update(group)
    counts.update(stack[0])
    return counts


def _parse_side(side: str) -> Counter:
    total: Counter = Counter()
    for term in side.split("+"):
        term = term.strip().replace("\\,", " ")
        if not term:
            continue
        # Strip common state symbols in parentheses
        term = re.sub(r"\((s|l|g|aq)\)", "", term, flags=re.IGNORECASE)
        # Normalize LaTeX subscripts to plain atom counts: H_2 / H_{2} → H2
        term = re.sub(r"_\{(\d+)\}", r"\1", term)
        term = re.sub(r"_(\d+)", r"\1", term)
        # Strip superscript/subscript formatting and charges like ^+, ^-, ^{2-}
        term = re.sub(r"\^\{?[+-]?\d*[+-]?\}?", "", term)
        m = re.match(r"^(\d+)\s*", term)
        coeff = 1
        if m:
            coeff = int(m.group(1))
            term = term[m.end():].strip()
        atoms = _parse_formula(term)
        for el, c in atoms.items():
            total[el] += c * coeff
    return total


def _find_arrow(text: str) -> str | None:
    for a in _ARROWS:
        if a in text:
            return a
    return None


class ChemistryVerifier:
    name = "chemistry"

    def verify(self, teaching_sequence: list[dict[str, Any]], *, query: str = "", **_: Any) -> list[ClaimVerification]:
        results: list[ClaimVerification] = []
        for step in teaching_sequence:
            prim = step.get("visual_primitive") or {}
            if not isinstance(prim, dict):
                continue
            data = prim.get("data") or {}
            text = str(data.get("latex") or data.get("full_latex") or data.get("equation")
                       or data.get("reaction") or data.get("text") or "").strip()
            if not text:
                continue
            arrow = _find_arrow(text)
            if not arrow:
                continue
            # Must look like a reaction (contains an element letter and a '+')
            if not re.search(r"[A-Z][a-z]?\d*", text):
                continue
            left, _, right = text.partition(arrow)
            try:
                lc = _parse_side(left)
                rc = _parse_side(right)
            except Exception as exc:
                results.append(ClaimVerification(text, "chemistry", VerificationStatus.UNVERIFIED,
                                                 0.3, f"parse-skip: {exc}", self.name))
                continue
            if not lc or not rc:
                continue
            if lc == rc:
                results.append(ClaimVerification(text, "chemistry", VerificationStatus.VERIFIED,
                                                 0.95, "atom-balanced", self.name))
            else:
                diff = {el: rc[el] - lc[el] for el in set(lc) | set(rc) if rc[el] != lc[el]}
                # Fail-closed only on a GENUINE reaction arrow. '=' and '\to' are
                # ambiguous (math identities, limits, mappings) — an "imbalance"
                # there usually means the letters are variables, not elements, so
                # it must not block the lesson.
                real_reaction = arrow not in ("=", "\\to")
                status = VerificationStatus.REJECTED if real_reaction else VerificationStatus.UNVERIFIED
                results.append(ClaimVerification(text, "chemistry", status,
                                                 0.9 if real_reaction else 0.3,
                                                 f"unbalanced: {diff}", self.name))
        return results


chemistry_verifier = ChemistryVerifier()
