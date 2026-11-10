from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from backend.api.schemas.common import TimestampResponse
from backend.api.schemas.jobs import JobResponse
from backend.models.contracts import Contract
from backend.verification.contracts import VerificationEvidence


class VerificationRequest(Contract):
    inventory_id: UUID


class VerificationResponse(TimestampResponse):
    id: UUID
    asset_id: UUID
    inventory_id: UUID
    verified_inventory_id: UUID | None
    job: JobResponse
    verifier_version: str
    created_at: datetime
    completed_at: datetime | None


class VerificationDetail(VerificationResponse):
    evidence: VerificationEvidence | None


class VerificationList(BaseModel):
    items: list[VerificationResponse]
    total: int
