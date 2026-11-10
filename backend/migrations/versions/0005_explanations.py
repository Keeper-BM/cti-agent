"""Persist bounded CVE explanation inputs, validated output and model provenance."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "explanations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=False, unique=True),
        sa.Column("active_slot", sa.String(16), unique=True),
        sa.Column("finding_id", sa.String(36), sa.ForeignKey("findings.id"), nullable=False),
        sa.Column("analysis_id", sa.String(36), sa.ForeignKey("analyses.id"), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("base_url", sa.String(200), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("prompt_version", sa.String(60), nullable=False),
        sa.Column("context_sha256", sa.String(64), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.Column("usage", sa.JSON()),
        sa.Column("reported_model", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_explanation_finding_created", "explanations", ["finding_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_explanation_finding_created", table_name="explanations")
    op.drop_table("explanations")
