"""add studio settings table

Revision ID: 0002_studio_settings
Revises: 0001_initial
Create Date: 2026-05-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_studio_settings"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "studio_settings",
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("studio_settings")
