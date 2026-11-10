"""Append-only inventory snapshots, with efficient asset history lookup."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_snapshots",
        sa.Column("inventory_id", sa.String(36), primary_key=True),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("os_release", sa.String(16), nullable=False),
        sa.Column("package_count", sa.Integer(), nullable=False),
        sa.Column("collection_status", sa.String(16), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_inventory_asset_ingested", "inventory_snapshots", ["asset_id", "ingested_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_inventory_asset_ingested", table_name="inventory_snapshots")
    op.drop_table("inventory_snapshots")
