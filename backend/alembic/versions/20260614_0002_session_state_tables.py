"""externalized session + student-profile state tables

Revision ID: 20260614_0002
Revises: 20260614_0001
Create Date: 2026-06-14

Adds session_state and student_profile_state so per-session coordination state
(page lock, whiteboard cursor, generation/branch snapshots) and the student
cognitive profile are durable instead of in-process.
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

from app.database.base import GUID, JSONType

# revision identifiers, used by Alembic.
revision: str = "20260614_0002"
down_revision: Union[str, None] = "20260614_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "session_state",
        sa.Column("session_id", GUID(), sa.ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("page_lock", JSONType(), nullable=False),
        sa.Column("whiteboard_state", JSONType(), nullable=False),
        sa.Column("generation_state", JSONType(), nullable=False),
        sa.Column("branch_state", JSONType(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "student_profile_state",
        sa.Column("session_id", GUID(), sa.ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("profile", JSONType(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("student_profile_state")
    op.drop_table("session_state")
