"""initial voice studio schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-01
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "voices",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("avatar", sa.String(length=255), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "contents",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("translations", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "stt_jobs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("source_audio_path", sa.Text(), nullable=False),
        sa.Column("normalized_audio_path", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "conversion_jobs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("model_id", sa.String(length=80), nullable=False),
        sa.Column("source_audio_path", sa.Text(), nullable=False),
        sa.Column("target_voice_id", sa.String(length=64), nullable=True),
        sa.Column("output_audio_url", sa.Text(), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "voice_samples",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("voice_id", sa.String(length=64), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("audio_path", sa.Text(), nullable=False),
        sa.Column("audio_url", sa.Text(), nullable=False),
        sa.Column("source_audio_path", sa.Text(), nullable=True),
        sa.Column("source_audio_url", sa.Text(), nullable=True),
        sa.Column("trim_start", sa.Float(), nullable=True),
        sa.Column("trim_end", sa.Float(), nullable=True),
        sa.Column("sample_rate", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["voice_id"], ["voices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_voice_samples_voice_id"), "voice_samples", ["voice_id"], unique=False)
    op.create_table(
        "generation_results",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("content_id", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("voice_id", sa.String(length=64), nullable=True),
        sa.Column("voice_name", sa.String(length=255), nullable=True),
        sa.Column("model_id", sa.String(length=80), nullable=True),
        sa.Column("audio_url", sa.Text(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("tone_prompt", sa.Text(), nullable=True),
        sa.Column("style_prompt", sa.Text(), nullable=True),
        sa.Column("effective_instruct", sa.Text(), nullable=True),
        sa.Column("language_hint", sa.String(length=80), nullable=True),
        sa.Column("accent_hint", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["content_id"], ["contents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_generation_results_content_id"), "generation_results", ["content_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_generation_results_content_id"), table_name="generation_results")
    op.drop_table("generation_results")
    op.drop_index(op.f("ix_voice_samples_voice_id"), table_name="voice_samples")
    op.drop_table("voice_samples")
    op.drop_table("conversion_jobs")
    op.drop_table("stt_jobs")
    op.drop_table("contents")
    op.drop_table("voices")
