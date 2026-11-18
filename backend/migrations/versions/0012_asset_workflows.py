"""Persist asset workflows and their exact inventory, source and report lineage."""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "asset_workflows",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("requested_by", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("request_key", sa.String(100), nullable=False),
        sa.Column("active_slot", sa.String(36), unique=True),
        sa.Column("mode", sa.String(12), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("inventory_id", sa.String(36), sa.ForeignKey("inventory_snapshots.inventory_id")),
        sa.Column("collection_id", sa.String(36), sa.ForeignKey("collection_runs.id")),
        sa.Column("analysis_id", sa.String(36), sa.ForeignKey("analyses.id")),
        sa.Column("report_id", sa.String(36), sa.ForeignKey("reports.id")),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("enriched", sa.Boolean(), nullable=False),
        sa.Column("timeline", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("error", sa.String(600)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("asset_id", "request_key", name="uq_workflow_request"),
    )
    op.create_index("ix_workflow_asset_created", "asset_workflows", ["asset_id", "created_at"])


def downgrade():
    op.drop_table("asset_workflows")
