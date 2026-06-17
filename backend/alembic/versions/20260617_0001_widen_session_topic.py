"""Widen sessions.topic from VARCHAR(500) to VARCHAR(3000)

Revision ID: 20260617_0001
Revises: 20260614_0002
Create Date: 2026-06-17

Image-extracted questions with LaTeX math can easily exceed 500 characters.
Raise the limit to 3000 to accommodate long physics/chemistry problems.
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260617_0001"
down_revision: Union[str, None] = "20260614_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "sessions",
        "topic",
        existing_type=sa.String(500),
        type_=sa.String(3000),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "sessions",
        "topic",
        existing_type=sa.String(3000),
        type_=sa.String(500),
        existing_nullable=False,
    )
