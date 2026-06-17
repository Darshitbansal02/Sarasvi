"""add users.password_hash for JWT auth

Revision ID: 20260614_0001
Revises: 20260531_0001
Create Date: 2026-06-14

Additive, non-destructive: adds a nullable password_hash column so existing
rows remain valid. New accounts always populate it via /api/auth/register.
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260614_0001"
down_revision: Union[str, None] = "20260531_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "password_hash")
