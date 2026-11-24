"""Persist selected assets, retry lineage and frozen consolidated reports."""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "workflow_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("requested_by", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("request_key", sa.String(100), nullable=False, unique=True),
        sa.Column("parent_id", sa.String(36), sa.ForeignKey("workflow_batches.id"), unique=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("report_summary", sa.JSON()),
        sa.Column("markdown", sa.Text()),
        sa.Column("report_error", sa.String(600)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_workflow_batch_created", "workflow_batches", ["created_at"])
    op.create_table(
        "workflow_batch_assets",
        sa.Column(
            "batch_id", sa.String(36), sa.ForeignKey("workflow_batches.id"), primary_key=True
        ),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("assets.id"), primary_key=True),
        sa.Column("asset_name", sa.String(100), nullable=False),
        sa.Column("workflow_id", sa.String(36), sa.ForeignKey("asset_workflows.id")),
        sa.Column("start_error", sa.String(600)),
        sa.Column("carried", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_workflow_batch_assets_asset_id", "workflow_batch_assets", ["asset_id"])
    op.create_index(
        "ix_workflow_batch_assets_workflow_id", "workflow_batch_assets", ["workflow_id"]
    )


def downgrade():
    op.drop_table("workflow_batch_assets")
    op.drop_table("workflow_batches")
