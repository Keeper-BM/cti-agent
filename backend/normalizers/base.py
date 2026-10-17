"""Source adapters produce frozen, normalized inputs for assessment."""

from datetime import datetime
from typing import Protocol

from backend.models.contracts import FeedSnapshot


class FeedNormalizer(Protocol):
    def normalize(self, raw: bytes, captured_at: datetime) -> FeedSnapshot:
        """Preserve evidence and unknown conditions without inventing a verdict."""
        ...
