"""
Verification contracts.

A Verifier turns a reasoning claim into one of three outcomes:
  - VERIFIED   : the claim was checked and is correct  → keep.
  - REJECTED   : the claim was checked and is WRONG    → fail closed (stop lesson).
  - UNVERIFIED : the claim could not be checked         → keep, but mark.

Policy (decided 2026-06): fail closed only where a verifier exists. A REJECTED
claim from a formal verifier (math/physics/chemistry/algorithms) stops generation.
Domains without a formal verifier produce UNVERIFIED at best, never REJECTED — the
lesson is taught with a visible "unverified" marker instead of being blocked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    REJECTED = "rejected"
    UNVERIFIED = "unverified"


@dataclass
class ClaimVerification:
    claim: str
    domain: str
    status: VerificationStatus
    confidence: float = 0.0
    reason: str = ""
    verifier: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "domain": self.domain,
            "status": self.status.value,
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "verifier": self.verifier,
        }


@dataclass
class VerificationReport:
    results: list[ClaimVerification] = field(default_factory=list)
    domain: str = "general"
    has_formal_verifier: bool = False

    @property
    def rejected(self) -> list[ClaimVerification]:
        return [r for r in self.results if r.status is VerificationStatus.REJECTED]

    @property
    def unverified(self) -> list[ClaimVerification]:
        return [r for r in self.results if r.status is VerificationStatus.UNVERIFIED]

    @property
    def verified(self) -> list[ClaimVerification]:
        return [r for r in self.results if r.status is VerificationStatus.VERIFIED]

    @property
    def has_rejection(self) -> bool:
        return len(self.rejected) > 0

    @property
    def rejection_reasons(self) -> list[str]:
        return [f"{r.verifier}:{r.reason}" for r in self.rejected]

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "has_formal_verifier": self.has_formal_verifier,
            "verified": len(self.verified),
            "unverified": len(self.unverified),
            "rejected": len(self.rejected),
            "results": [r.to_dict() for r in self.results],
        }
