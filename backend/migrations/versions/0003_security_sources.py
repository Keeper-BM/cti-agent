"""Preserve official source documents, revisions and CVE records independently."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_runs",
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), primary_key=True),
        sa.Column("source_id", sa.String(16), nullable=False),
        sa.Column("scope_key", sa.String(450), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
    )
    op.create_table(
        "security_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=False, unique=True),
        sa.Column("source_id", sa.String(16), nullable=False),
        sa.Column("scope_key", sa.String(450), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("adapter_version", sa.String(60), nullable=False),
        sa.Column("document_count", sa.Integer(), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_security_source_scope_time",
        "security_snapshots",
        ["source_id", "scope_key", "captured_at"],
    )
    op.create_table(
        "source_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "snapshot_id", sa.String(36), sa.ForeignKey("security_snapshots.id"), nullable=False
        ),
        sa.Column("url", sa.String(2000), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("content_type", sa.String(200), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
    )
    op.create_index("ix_source_documents_snapshot_id", "source_documents", ["snapshot_id"])
    op.create_table(
        "source_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "snapshot_id", sa.String(36), sa.ForeignKey("security_snapshots.id"), nullable=False
        ),
        sa.Column(
            "document_id", sa.String(36), sa.ForeignKey("source_documents.id"), nullable=False
        ),
        sa.Column("source_id", sa.String(16), nullable=False),
        sa.Column("cve_id", sa.String(32), nullable=False),
        sa.Column("package_name", sa.String(200)),
        sa.Column("release", sa.String(16)),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_source_records_snapshot_id", "source_records", ["snapshot_id"])
    op.create_index("ix_source_record_cve_snapshot", "source_records", ["cve_id", "snapshot_id"])


def downgrade() -> None:
    op.drop_index("ix_source_record_cve_snapshot", table_name="source_records")
    op.drop_index("ix_source_records_snapshot_id", table_name="source_records")
    op.drop_table("source_records")
    op.drop_index("ix_source_documents_snapshot_id", table_name="source_documents")
    op.drop_table("source_documents")
    op.drop_index("ix_security_source_scope_time", table_name="security_snapshots")
    op.drop_table("security_snapshots")
    op.drop_table("source_runs")
