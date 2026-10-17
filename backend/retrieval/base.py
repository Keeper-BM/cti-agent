from typing import Protocol
from uuid import UUID

from backend.models.contracts import Evidence


class Retriever(Protocol):
    def search(self, question: str, analysis_ids: list[UUID]) -> list[Evidence]:
        """Search only documents linked to the authorized analysis snapshots."""
        ...
