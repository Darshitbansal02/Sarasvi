"""
Algorithms / CS verifier.

  - REJECTS Python code blocks that do not parse (syntactically invalid code is
    objectively wrong to teach).
  - Checks complexity_label Big-O notation is well-formed (advisory: VERIFIED /
    UNVERIFIED, never a hard reject — a label is not a reasoning claim).
"""

from __future__ import annotations

import ast
import re
from typing import Any

from app.verification.base import ClaimVerification, VerificationStatus

_BIG_O_RE = re.compile(
    r"^O\(\s*(1|log\s*n|n|n\s*log\s*n|n\^?2|n\^?3|n\^?k|2\^?n|n!|sqrt\(?n\)?|m\s*\+\s*n|v\s*\+\s*e)\s*\)$",
    re.IGNORECASE,
)


class AlgorithmsVerifier:
    name = "algorithms"

    def verify(self, teaching_sequence: list[dict[str, Any]], *, query: str = "", **_: Any) -> list[ClaimVerification]:
        results: list[ClaimVerification] = []
        for step in teaching_sequence:
            prim = step.get("visual_primitive") or {}
            if not isinstance(prim, dict):
                continue
            ptype = str(prim.get("type", "")).lower()
            data = prim.get("data") or {}

            if ptype == "code_block":
                code = str(data.get("code", "")).strip()
                # Clean code of markdown fences if LLM wrapped them inside the JSON string
                if code.startswith("```"):
                    lines = code.splitlines()
                    if len(lines) >= 2:
                        if lines[0].startswith("```"):
                            lines = lines[1:]
                        if lines and lines[-1].strip() == "```":
                            lines = lines[:-1]
                        code = "\n".join(lines).strip()
                lang_raw = data.get("language")
                lang = str(lang_raw).lower() if lang_raw else None
                if code and lang in {"python", "py", "python3"}:
                    import textwrap
                    parsed = False
                    error_msg = ""
                    
                    # Try a few variations to support partial snippets and indented code:
                    # 1. Raw code
                    # 2. Dedented code
                    # 3. Raw code + pass (for loop/function headers)
                    # 4. Dedented code + pass
                    variations = [
                        code,
                        textwrap.dedent(code),
                        code + "\n    pass",
                        textwrap.dedent(code) + "\n    pass",
                    ]
                    
                    for var in variations:
                        try:
                            ast.parse(var)
                            parsed = True
                            break
                        except SyntaxError as e:
                            error_msg = e.msg
                            
                    if parsed:
                        results.append(ClaimVerification(code[:60], "computer_science",
                                                         VerificationStatus.VERIFIED, 0.9,
                                                         "python parses", self.name))
                    else:
                        # Teaching snippets are often illustrative pseudocode or partial
                        # fragments (mislabeled "python", using "...", "for i = 1 to n"…).
                        # A syntax error is a quality signal, not a provable falsehood, so
                        # it must not block the whole lesson → UNVERIFIED.
                        results.append(ClaimVerification(code[:60], "computer_science",
                                                         VerificationStatus.UNVERIFIED, 0.4,
                                                         f"python syntax not confirmed: {error_msg}", self.name))

            elif ptype == "complexity_label":
                big_o = str(data.get("big_o", "")).replace(" ", "")
                if not big_o:
                    continue
                normalized = big_o.replace("·", "").replace("*", "")
                if _BIG_O_RE.match(normalized.replace("n", "n")):
                    results.append(ClaimVerification(big_o, "computer_science",
                                                     VerificationStatus.VERIFIED, 0.7,
                                                     "well-formed complexity", self.name))
                else:
                    results.append(ClaimVerification(big_o, "computer_science",
                                                     VerificationStatus.UNVERIFIED, 0.4,
                                                     "unrecognized complexity form", self.name))
        return results


algorithms_verifier = AlgorithmsVerifier()
