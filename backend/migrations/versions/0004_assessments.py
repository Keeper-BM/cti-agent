"""Frozen analysis inputs and immutable package findings."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analyses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=False, unique=True),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column(
            "inventory_id",
            sa.String(36),
            sa.ForeignKey("inventory_snapshots.inventory_id"),
            nullable=False,
        ),
        sa.Column("asset_name", sa.String(100), nullable=False),
        sa.Column("expected_release", sa.String(16)),
        sa.Column("os_release", sa.String(16)),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("ruleset_version", sa.String(60), nullable=False),
        sa.Column("feed_snapshot_id", sa.String(36), nullable=False, unique=True),
        sa.Column("source_snapshot_ids", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON()),
        sa.Column("feed_payload", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_analysis_asset_created", "analyses", ["asset_id", "created_at"])
    op.create_table(
        "findings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("analysis_id", sa.String(36), sa.ForeignKey("analyses.id"), nullable=False),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("package_name", sa.String(200)),
        sa.Column("cve_id", sa.String(32)),
        sa.Column("processing_status", sa.String(32), nullable=False),
        sa.Column("verdict", sa.String(24)),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_finding_analysis_cve", "findings", ["analysis_id", "cve_id"])
    op.create_index("ix_findings_asset_id", "findings", ["asset_id"])


def downgrade() -> None:
    op.drop_index("ix_findings_asset_id", table_name="findings")
    op.drop_index("ix_finding_analysis_cve", table_name="findings")
    op.drop_table("findings")
    op.drop_index("ix_analysis_asset_created", table_name="analyses")
    op.drop_table("analyses")
