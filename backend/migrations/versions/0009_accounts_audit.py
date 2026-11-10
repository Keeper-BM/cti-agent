"""Accounts, sessions, asset grants and immutable audit entries."""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(64), unique=True, nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "login_sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_login_sessions_user_id", "login_sessions", ["user_id"])
    op.create_index("ix_login_sessions_expires_at", "login_sessions", ["expires_at"])
    op.create_table(
        "asset_grants",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("assets.id"), primary_key=True),
    )
    op.create_table(
        "login_throttles",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("assets.id")),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("target_id", sa.String(100)),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("request_id", sa.String(36)),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name in ("actor_id", "asset_id", "action", "created_at"):
        op.create_index("ix_audit_events_" + name, "audit_events", [name])
    if op.get_bind().dialect.name == "sqlite":
        op.execute("ALTER TABLE jobs ADD COLUMN requested_by VARCHAR(36) REFERENCES users(id)")
    else:
        op.add_column("jobs", sa.Column("requested_by", sa.String(36)))
        op.create_foreign_key(
            "fk_jobs_requested_by_users", "jobs", "users", ["requested_by"], ["id"]
        )
    op.create_index("ix_jobs_requested_by", "jobs", ["requested_by"])


def downgrade():
    op.drop_index("ix_jobs_requested_by", table_name="jobs")
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint("fk_jobs_requested_by_users", "jobs", type_="foreignkey")
    op.drop_column("jobs", "requested_by")
    for name in ("actor_id", "asset_id", "action", "created_at"):
        op.drop_index("ix_audit_events_" + name, table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("login_throttles")
    op.drop_table("asset_grants")
    op.drop_index("ix_login_sessions_expires_at", table_name="login_sessions")
    op.drop_index("ix_login_sessions_user_id", table_name="login_sessions")
    op.drop_table("login_sessions")
    op.drop_table("users")
