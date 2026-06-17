"""
Branch Manager — manages cognitive timeline branches.

Sarasvi is a BRANCHING cognitive timeline engine, not a linear conversation system.
When a student interrupts, a new branch is created from the interruption point.
This enables alternate explanations, confusion tracking, and branch replay.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class Branch:
    """A single cognitive timeline branch."""
    branch_id: str
    parent_branch_id: Optional[str]
    branch_point_sequence: int  # sequence number where branch diverges
    created_at: str
    reason: str  # "interruption", "alternate_explanation", "quiz_branch"
    is_active: bool = True


class BranchManager:
    """
    Manages branching cognitive timelines for a session.

    Example:
        Main timeline: A → B → C → D
        Student interrupts at C:
        New branch:     C → C1 → C2 → C3
    """

    def __init__(self, session_id: str):
        self._session_id = session_id
        self._branches: dict[str, Branch] = {}
        self._active_branch_id: str = "main"

        # Create the main branch
        self._branches["main"] = Branch(
            branch_id="main",
            parent_branch_id=None,
            branch_point_sequence=0,
            created_at=datetime.now(timezone.utc).isoformat(),
            reason="session_start",
            is_active=True,
        )

    @property
    def active_branch_id(self) -> str:
        return self._active_branch_id

    @property
    def active_branch(self) -> Branch:
        return self._branches[self._active_branch_id]

    def create_branch(
        self,
        branch_point_sequence: int,
        reason: str = "interruption",
        parent_branch_id: Optional[str] = None,
    ) -> Branch:
        """
        Create a new cognitive branch from the given sequence point.
        Returns the new branch.
        """
        parent = parent_branch_id or self._active_branch_id
        branch_id = f"branch_{uuid.uuid4().hex[:8]}"

        branch = Branch(
            branch_id=branch_id,
            parent_branch_id=parent,
            branch_point_sequence=branch_point_sequence,
            created_at=datetime.now(timezone.utc).isoformat(),
            reason=reason,
        )

        self._branches[branch_id] = branch

        # Deactivate old branch, activate new
        if self._active_branch_id in self._branches:
            self._branches[self._active_branch_id].is_active = False
        self._active_branch_id = branch_id

        logger.info(
            "branch.created",
            session_id=self._session_id,
            branch_id=branch_id,
            parent=parent,
            branch_point=branch_point_sequence,
            reason=reason,
        )

        return branch

    def switch_branch(self, branch_id: str) -> Branch:
        """Switch active branch (for replay branch switching)."""
        if branch_id not in self._branches:
            raise ValueError(f"Branch {branch_id} does not exist")

        self._active_branch_id = branch_id
        logger.info(
            "branch.switched",
            session_id=self._session_id,
            branch_id=branch_id,
        )
        return self._branches[branch_id]

    def get_branch(self, branch_id: str) -> Optional[Branch]:
        """Get branch by ID."""
        return self._branches.get(branch_id)

    def get_all_branches(self) -> list[Branch]:
        """Get all branches for this session."""
        return list(self._branches.values())

    def get_branch_tree(self) -> dict:
        """Get branch hierarchy as a tree structure."""
        tree = {}
        for branch in self._branches.values():
            tree[branch.branch_id] = {
                "parent": branch.parent_branch_id,
                "branch_point": branch.branch_point_sequence,
                "reason": branch.reason,
                "is_active": branch.is_active,
                "created_at": branch.created_at,
            }
        return tree

    @property
    def branch_count(self) -> int:
        return len(self._branches)

    @property
    def interruption_count(self) -> int:
        """Count branches created by interruptions."""
        return sum(
            1 for b in self._branches.values()
            if b.reason == "interruption"
        )

    # ── Serialization (for durable, externalized session state) ──────
    def to_state(self) -> dict:
        return {
            "active_branch_id": self._active_branch_id,
            "branches": {
                bid: {
                    "branch_id": b.branch_id,
                    "parent_branch_id": b.parent_branch_id,
                    "branch_point_sequence": b.branch_point_sequence,
                    "created_at": b.created_at,
                    "reason": b.reason,
                    "is_active": b.is_active,
                }
                for bid, b in self._branches.items()
            },
        }

    @classmethod
    def from_state(cls, session_id: str, state: dict | None) -> "BranchManager":
        mgr = cls(session_id)
        if state and state.get("branches"):
            mgr._branches = {
                bid: Branch(
                    branch_id=b["branch_id"],
                    parent_branch_id=b.get("parent_branch_id"),
                    branch_point_sequence=int(b.get("branch_point_sequence", 0)),
                    created_at=b.get("created_at", ""),
                    reason=b.get("reason", "session_start"),
                    is_active=bool(b.get("is_active", False)),
                )
                for bid, b in state["branches"].items()
            }
            mgr._active_branch_id = state.get("active_branch_id", "main")
        return mgr
