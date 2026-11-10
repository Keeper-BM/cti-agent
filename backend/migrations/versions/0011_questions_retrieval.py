"""Scoped questions, frozen answers and local document vectors."""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "text_chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("record_id", sa.String(36), sa.ForeignKey("source_records.id"), nullable=False),
        sa.Column(
            "document_id", sa.String(36), sa.ForeignKey("source_documents.id"), nullable=False
        ),
        sa.Column("index_version", sa.String(60), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("vector", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "record_id", "index_version", "ordinal", name="uq_chunk_record_version_ordinal"
        ),
    )
    op.create_index("ix_text_chunks_record_id", "text_chunks", ["record_id"])
    op.create_table(
        "questions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=False, unique=True),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("analysis_ids", sa.JSON(), nullable=False),
        sa.Column("active_slot", sa.String(16), unique=True),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("prompt_version", sa.String(60), nullable=False),
        sa.Column("context_sha256", sa.String(64), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.Column("usage", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_question_asset_created", "questions", ["asset_id", "created_at"])
    op.create_table(
        "question_assets",
        sa.Column("question_id", sa.String(36), sa.ForeignKey("questions.id"), primary_key=True),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("assets.id"), primary_key=True),
    )


def downgrade():
    op.drop_table("question_assets")
    op.drop_index("ix_question_asset_created", table_name="questions")
    op.drop_table("questions")
    op.drop_index("ix_text_chunks_record_id", table_name="text_chunks")
    op.drop_table("text_chunks")
