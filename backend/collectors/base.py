from typing import Protocol
from uuid import UUID

from backend.models.contracts import InventorySnapshot


class InventoryCollector(Protocol):
    def collect(self, asset_id: UUID) -> InventorySnapshot:
        """Resolve an approved profile; verify host keys; use fixed read-only commands."""
        ...
