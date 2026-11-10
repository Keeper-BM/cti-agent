"""Frozen same-baseline inventory comparisons."""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "comparisons",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), unique=True, nullable=False),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column(
            "baseline_analysis_id", sa.String(36), sa.ForeignKey("analyses.id"), nullable=False
        ),
        sa.Column(
            "target_inventory_id",
            sa.String(36),
            sa.ForeignKey("inventory_snapshots.inventory_id"),
            nullable=False,
        ),
        sa.Column("version", sa.String(60), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_comparison_asset_created", "comparisons", ["asset_id", "created_at"])


def downgrade():
    op.drop_index("ix_comparison_asset_created", table_name="comparisons")
    op.drop_table("comparisons")
