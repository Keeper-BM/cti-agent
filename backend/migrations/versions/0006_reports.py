"""Frozen single-analysis reports and immutable Markdown exports."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=False, unique=True),
        sa.Column("analysis_id", sa.String(36), sa.ForeignKey("analyses.id"), nullable=False),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("asset_name", sa.String(100), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("include_ai_explanations", sa.Boolean(), nullable=False),
        sa.Column("explanation_count", sa.Integer(), nullable=False),
        sa.Column("finding_count", sa.Integer(), nullable=False),
        sa.Column("template_version", sa.String(60), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        sa.Column("content", sa.JSON()),
        sa.Column("markdown", sa.Text()),
        sa.Column("markdown_sha256", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_report_asset_created", "reports", ["asset_id", "created_at"])
    op.create_index("ix_reports_analysis_id", "reports", ["analysis_id"])


def downgrade() -> None:
    op.drop_index("ix_reports_analysis_id", table_name="reports")
    op.drop_index("ix_report_asset_created", table_name="reports")
    op.drop_table("reports")
