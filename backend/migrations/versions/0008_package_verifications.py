"""Immutable official-package verification evidence and resulting inventory."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "verification_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), unique=True, nullable=False),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column(
            "inventory_id",
            sa.String(36),
            sa.ForeignKey("inventory_snapshots.inventory_id"),
            nullable=False,
        ),
        sa.Column("profile_id", sa.String(36), sa.ForeignKey("ssh_profiles.id"), nullable=False),
        sa.Column(
            "verified_inventory_id",
            sa.String(36),
            sa.ForeignKey("inventory_snapshots.inventory_id"),
        ),
        sa.Column("active_slot", sa.String(36), unique=True),
        sa.Column("verifier_version", sa.String(60), nullable=False),
        sa.Column("evidence", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_verification_asset_created", "verification_runs", ["asset_id", "created_at"]
    )


def downgrade():
    op.drop_index("ix_verification_asset_created", table_name="verification_runs")
    op.drop_table("verification_runs")
