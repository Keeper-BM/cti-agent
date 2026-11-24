"""Persist recurring analysis schedules and their execution slots."""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "workflow_schedules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("requested_by", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("local_time", sa.String(5), nullable=False),
        sa.Column("weekday", sa.Integer()),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_workflow_schedules_next_run_at", "workflow_schedules", ["next_run_at"])
    op.create_table(
        "workflow_schedule_assets",
        sa.Column(
            "schedule_id", sa.String(36), sa.ForeignKey("workflow_schedules.id"), primary_key=True
        ),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("assets.id"), primary_key=True),
    )
    op.create_table(
        "workflow_schedule_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "schedule_id", sa.String(36), sa.ForeignKey("workflow_schedules.id"), nullable=False
        ),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("batch_id", sa.String(36), sa.ForeignKey("workflow_batches.id"), unique=True),
        sa.Column("error", sa.String(600)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("schedule_id", "scheduled_for", name="uq_workflow_schedule_slot"),
    )


def downgrade():
    op.drop_table("workflow_schedule_runs")
    op.drop_table("workflow_schedule_assets")
    op.drop_table("workflow_schedules")
