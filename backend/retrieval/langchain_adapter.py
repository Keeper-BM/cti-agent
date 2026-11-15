"""LangChain adapter for the existing scoped BGE-M3 retriever."""

from typing import Any

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field

from backend.retrieval.dense import rank_dense


class ScopedBGERetriever(BaseRetriever):
    """Retrieve only pre-authorized evidence candidates."""

    candidates: list[dict[str, Any]] = Field(exclude=True)
    limit: int = 10
    model_name: str = "BAAI/bge-m3"
    cache_directory: str = ".data/embedding-cache"

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _get_relevant_documents(self, query: str, *, run_manager) -> list[Document]:
        ranked = rank_dense(
            query,
            self.candidates,
            self.limit,
            model_name=self.model_name,
            cache_directory=self.cache_directory,
        )

        return [
            Document(
                id=str(candidate["id"]),
                page_content=candidate["chunk"].text,
                metadata={
                    "candidate_id": str(candidate["id"]),
                    "cve_id": candidate.get("cve_id"),
                    "score": score,
                },
            )
            for candidate, score in ranked
        ]
