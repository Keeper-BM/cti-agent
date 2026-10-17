from typing import Protocol

from backend.models.contracts import Evidence, Finding


class ExplanationProvider(Protocol):
    def explain(self, question: str, findings: list[Finding], evidence: list[Evidence]) -> str:
        """Generate explanation only. Validate citations and facts outside the model."""
        ...
