from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    asset_name: Mapped[str] = mapped_column(String(100), unique=True)
    host: Mapped[str | None] = mapped_column(String(253))
    expected_release: Mapped[str | None] = mapped_column(String(16))
    exposure: Mapped[str] = mapped_column(String(16), default="UNKNOWN")
    exposure_source: Mapped[str] = mapped_column(String(200))
    criticality: Mapped[str] = mapped_column(String(16), default="UNKNOWN")
    owner_display_name: Mapped[str | None] = mapped_column(String(100))
    collection_method: Mapped[str] = mapped_column(String(16), default="MANUAL")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(40))
    requested_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"))
    status: Mapped[str] = mapped_column(String(16), default="QUEUED", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InventoryRecord(Base):
    __tablename__ = "inventory_snapshots"
    __table_args__ = (Index("ix_inventory_asset_ingested", "asset_id", "ingested_at"),)

    inventory_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    os_release: Mapped[str] = mapped_column(String(16))
    package_count: Mapped[int] = mapped_column(Integer)
    collection_status: Mapped[str] = mapped_column(String(16))
    is_synthetic: Mapped[bool] = mapped_column(Boolean)
    payload: Mapped[dict] = mapped_column(JSON)


class SourceRun(Base):
    __tablename__ = "source_runs"

    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(16))
    scope_key: Mapped[str] = mapped_column(String(450))
    parameters: Mapped[dict] = mapped_column(JSON)


class SecuritySnapshot(Base):
    __tablename__ = "security_snapshots"
    __table_args__ = (
        Index("ix_security_source_scope_time", "source_id", "scope_key", "captured_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), unique=True)
    source_id: Mapped[str] = mapped_column(String(16))
    scope_key: Mapped[str] = mapped_column(String(450))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    adapter_version: Mapped[str] = mapped_column(String(60))
    document_count: Mapped[int] = mapped_column(Integer)
    record_count: Mapped[int] = mapped_column(Integer)


class SourceDocument(Base):
    __tablename__ = "source_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("security_snapshots.id"), index=True)
    url: Mapped[str] = mapped_column(String(2000))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sha256: Mapped[str] = mapped_column(String(64))
    content_type: Mapped[str] = mapped_column(String(200))
    raw_text: Mapped[str] = mapped_column(Text)


class SourceRecord(Base):
    __tablename__ = "source_records"
    __table_args__ = (Index("ix_source_record_cve_snapshot", "cve_id", "snapshot_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("security_snapshots.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"))
    source_id: Mapped[str] = mapped_column(String(16))
    cve_id: Mapped[str] = mapped_column(String(32))
    package_name: Mapped[str | None] = mapped_column(String(200))
    release: Mapped[str | None] = mapped_column(String(16))
    payload: Mapped[dict] = mapped_column(JSON)


class AnalysisRun(Base):
    __tablename__ = "analyses"
    __table_args__ = (Index("ix_analysis_asset_created", "asset_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), unique=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"))
    inventory_id: Mapped[str] = mapped_column(ForeignKey("inventory_snapshots.inventory_id"))
    asset_name: Mapped[str] = mapped_column(String(100))
    expected_release: Mapped[str | None] = mapped_column(String(16))
    os_release: Mapped[str | None] = mapped_column(String(16))
    is_synthetic: Mapped[bool] = mapped_column(Boolean)
    ruleset_version: Mapped[str] = mapped_column(String(60))
    feed_snapshot_id: Mapped[str] = mapped_column(String(36), unique=True)
    source_snapshot_ids: Mapped[list] = mapped_column(JSON)
    warnings: Mapped[list] = mapped_column(JSON)
    summary: Mapped[dict | None] = mapped_column(JSON)
    feed_payload: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FindingRecord(Base):
    __tablename__ = "findings"
    __table_args__ = (Index("ix_finding_analysis_cve", "analysis_id", "cve_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id"))
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), index=True)
    package_name: Mapped[str | None] = mapped_column(String(200))
    cve_id: Mapped[str | None] = mapped_column(String(32))
    processing_status: Mapped[str] = mapped_column(String(32))
    verdict: Mapped[str | None] = mapped_column(String(24))
    payload: Mapped[dict] = mapped_column(JSON)


class ExplanationRun(Base):
    __tablename__ = "explanations"
    __table_args__ = (Index("ix_explanation_finding_created", "finding_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), unique=True)
    active_slot: Mapped[str | None] = mapped_column(String(16), unique=True)
    finding_id: Mapped[str] = mapped_column(ForeignKey("findings.id"))
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id"))
    provider: Mapped[str] = mapped_column(String(30))
    base_url: Mapped[str] = mapped_column(String(200))
    model: Mapped[str] = mapped_column(String(200))
    prompt_version: Mapped[str] = mapped_column(String(60))
    context_sha256: Mapped[str] = mapped_column(String(64))
    input_payload: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    usage: Mapped[dict | None] = mapped_column(JSON)
    reported_model: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReportRun(Base):
    __tablename__ = "reports"
    __table_args__ = (Index("ix_report_asset_created", "asset_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), unique=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id"), index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"))
    asset_name: Mapped[str] = mapped_column(String(100))
    is_synthetic: Mapped[bool] = mapped_column(Boolean)
    include_ai_explanations: Mapped[bool] = mapped_column(Boolean)
    explanation_count: Mapped[int] = mapped_column(Integer)
    finding_count: Mapped[int] = mapped_column(Integer)
    template_version: Mapped[str] = mapped_column(String(60))
    input_sha256: Mapped[str] = mapped_column(String(64))
    input_payload: Mapped[dict] = mapped_column(JSON)
    content: Mapped[dict | None] = mapped_column(JSON)
    markdown: Mapped[str | None] = mapped_column(Text)
    markdown_sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SSHProfile(Base):
    __tablename__ = "ssh_profiles"
    __table_args__ = (Index("ix_ssh_profile_asset_created", "asset_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"))
    host: Mapped[str] = mapped_column(String(45))
    port: Mapped[int] = mapped_column(Integer)
    username: Mapped[str] = mapped_column(String(32))
    key_alias: Mapped[str] = mapped_column(String(80))
    host_fingerprint: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CollectionRun(Base):
    __tablename__ = "collection_runs"
    __table_args__ = (Index("ix_collection_asset_created", "asset_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), unique=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"))
    profile_id: Mapped[str] = mapped_column(ForeignKey("ssh_profiles.id"))
    active_slot: Mapped[str | None] = mapped_column(String(36), unique=True)
    inventory_id: Mapped[str | None] = mapped_column(ForeignKey("inventory_snapshots.inventory_id"))
    collector_version: Mapped[str] = mapped_column(String(60))
    evidence: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VerificationRun(Base):
    __tablename__ = "verification_runs"
    __table_args__ = (Index("ix_verification_asset_created", "asset_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), unique=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"))
    inventory_id: Mapped[str] = mapped_column(ForeignKey("inventory_snapshots.inventory_id"))
    profile_id: Mapped[str] = mapped_column(ForeignKey("ssh_profiles.id"))
    verified_inventory_id: Mapped[str | None] = mapped_column(
        ForeignKey("inventory_snapshots.inventory_id")
    )
    active_slot: Mapped[str | None] = mapped_column(String(36), unique=True)
    verifier_version: Mapped[str] = mapped_column(String(60))
    evidence: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(16), default="VIEWER")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LoginSession(Base):
    __tablename__ = "login_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AssetGrant(Base):
    __tablename__ = "asset_grants"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), primary_key=True)


class LoginThrottle(Base):
    __tablename__ = "login_throttles"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"), index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    target_id: Mapped[str | None] = mapped_column(String(100))
    outcome: Mapped[str] = mapped_column(String(16), default="SUCCESS")
    request_id: Mapped[str | None] = mapped_column(String(36))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class ComparisonRun(Base):
    __tablename__ = "comparisons"
    __table_args__ = (Index("ix_comparison_asset_created", "asset_id", "created_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), unique=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"))
    baseline_analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id"))
    target_inventory_id: Mapped[str] = mapped_column(ForeignKey("inventory_snapshots.inventory_id"))
    version: Mapped[str] = mapped_column(String(60))
    input_sha256: Mapped[str] = mapped_column(String(64))
    input_payload: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TextChunk(Base):
    __tablename__ = "text_chunks"
    __table_args__ = (
        UniqueConstraint(
            "record_id", "index_version", "ordinal", name="uq_chunk_record_version_ordinal"
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    record_id: Mapped[str] = mapped_column(ForeignKey("source_records.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"))
    index_version: Mapped[str] = mapped_column(String(60))
    ordinal: Mapped[int] = mapped_column(Integer)
    start_offset: Mapped[int] = mapped_column(Integer)
    end_offset: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    vector: Mapped[dict] = mapped_column(JSON)


class QuestionRun(Base):
    __tablename__ = "questions"
    __table_args__ = (Index("ix_question_asset_created", "asset_id", "created_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), unique=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"))
    question: Mapped[str] = mapped_column(Text)
    analysis_ids: Mapped[list] = mapped_column(JSON)
    active_slot: Mapped[str | None] = mapped_column(String(16), unique=True)
    model: Mapped[str] = mapped_column(String(200))
    prompt_version: Mapped[str] = mapped_column(String(60))
    context_sha256: Mapped[str] = mapped_column(String(64))
    input_payload: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    usage: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QuestionAsset(Base):
    __tablename__ = "question_assets"
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"), primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), primary_key=True)
