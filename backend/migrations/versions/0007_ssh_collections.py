"""SSH connection profiles, collection jobs and bounded collection evidence."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ssh_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("host", sa.String(45), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(32), nullable=False),
        sa.Column("key_alias", sa.String(80), nullable=False),
        sa.Column("host_fingerprint", sa.String(60), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ssh_profile_asset_created", "ssh_profiles", ["asset_id", "created_at"])
    op.create_table(
        "collection_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), unique=True, nullable=False),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("profile_id", sa.String(36), sa.ForeignKey("ssh_profiles.id"), nullable=False),
        sa.Column("active_slot", sa.String(36), unique=True),
        sa.Column("inventory_id", sa.String(36), sa.ForeignKey("inventory_snapshots.inventory_id")),
        sa.Column("collector_version", sa.String(60), nullable=False),
        sa.Column("evidence", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_collection_asset_created", "collection_runs", ["asset_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_collection_asset_created", table_name="collection_runs")
    op.drop_table("collection_runs")
    op.drop_index("ix_ssh_profile_asset_created", table_name="ssh_profiles")
    op.drop_table("ssh_profiles")
