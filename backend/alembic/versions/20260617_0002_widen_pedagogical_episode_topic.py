"""Widen sql_pedagogical_episodes.topic from VARCHAR(200) to VARCHAR(3000)

Revision ID: 20260617_0002
Revises: 20260617_0001
Create Date: 2026-06-17

Image-extracted questions exceed VARCHAR(200). Align with sessions.topic at 3000.
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260617_0002"
down_revision: Union[str, None] = "20260617_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "sql_pedagogical_episodes",
        "topic",
        existing_type=sa.String(200),
        type_=sa.String(3000),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "sql_pedagogical_episodes",
        "topic",
        existing_type=sa.String(3000),
        type_=sa.String(200),
        existing_nullable=False,
    )
