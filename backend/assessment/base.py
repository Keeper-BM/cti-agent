from typing import Protocol

from backend.models.contracts import FeedSnapshot, Finding, InventorySnapshot


class AssessmentEngine(Protocol):
    def assess(self, inventory: InventorySnapshot, feed: FeedSnapshot) -> list[Finding]:
        """Use frozen evidence, Debian version semantics and explicit coverage checks."""
        ...
