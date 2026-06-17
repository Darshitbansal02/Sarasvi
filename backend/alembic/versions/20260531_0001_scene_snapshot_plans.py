"""Add pedagogical and visual plans to scene snapshots.

Revision ID: 20260531_0001
Revises: 89e45903f61a
Create Date: 2026-05-31 00:01:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import app.database.base


revision: str = "20260531_0001"
down_revision: Union[str, None] = "89e45903f61a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("scene_snapshots", sa.Column("pedagogical_plan", app.database.base.JSONType(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("scene_snapshots", sa.Column("visual_plan", app.database.base.JSONType(), nullable=False, server_default=sa.text("'{}'::jsonb")))


def downgrade() -> None:
    op.drop_column("scene_snapshots", "visual_plan")
    op.drop_column("scene_snapshots", "pedagogical_plan")