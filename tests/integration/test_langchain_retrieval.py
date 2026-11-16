"""LangChain retrieval integration with scoped Ubuntu OSV evidence."""

import pytest
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.models.tables import AnalysisRun, QuestionRun, TextChunk
from tests.integration import test_questions as questions
from tests.integration import test_sources as sources

source_wire = sources.source_wire
wire = questions.wire


def test_langchain_retrieval_preserves_evidence_scope(
    client, headers, engine, source_wire, wire, monkeypatch
):
    pytest.importorskip("langchain_core")
    from backend.retrieval import langchain_adapter

    calls = []

    def fake_rank_dense(question, candidates, limit=10, **kwargs):
        calls.append(
            {
                "question": question,
                "candidate_snapshot_ids": [
                    candidate["record"].snapshot_id for candidate in candidates
                ],
                "limit": limit,
                "kwargs": kwargs,
            }
        )
        return [(candidate, 0.9) for candidate in candidates[:limit]]

    monkeypatch.setattr(langchain_adapter, "rank_dense", fake_rank_dense)
    monkeypatch.setenv("RETRIEVAL_MODE", "langchain")
    monkeypatch.setenv("DENSE_MIN_SIMILARITY", "0.67")
    get_settings.cache_clear()

    try:
        sources.execute(client, headers, engine, "ubuntu")
        baseline = questions.analysis(client, headers, engine)

        response = questions.ask(client, headers, [baseline["id"]])
        assert response.status_code == 202, response.text
        assert calls, "LangChain을 통한 Dense 검색이 호출되지 않았습니다."

        with Session(engine) as db:
            run = db.get(QuestionRun, response.json()["id"])
            context = run.input_payload
            snapshots = set(db.get(AnalysisRun, baseline["id"]).source_snapshot_ids)

            assert context["retrieval_version"] == "langchain/dense/BAAI/bge-m3"
            assert context["facts"]
            assert not context["insufficient_evidence"]

            evidence = [
                citation for citation in context["citations"] if citation["id"].startswith("E")
            ]
            assert evidence

            for citation in evidence:
                assert citation["snapshot_id"] in snapshots
                chunk = db.get(TextChunk, citation["chunk_id"])
                assert chunk.text == citation["excerpt"]
                assert chunk.end_offset - chunk.start_offset == len(chunk.text)

            assert calls[0]["limit"] == 10
            assert calls[0]["kwargs"]["min_similarity"] == 0.67
            assert all(
                snapshot_id in snapshots for snapshot_id in calls[0]["candidate_snapshot_ids"]
            )
    finally:
        get_settings.cache_clear()


def test_langchain_irrelevant_evidence_does_not_call_llm(
    client, headers, engine, source_wire, wire, monkeypatch
):
    pytest.importorskip("langchain_core")
    np = pytest.importorskip("numpy")
    from backend.retrieval import dense
    from backend.worker.runner import run_once

    def unrelated_embeddings(texts, _model, _directory):
        return np.array([[1.0]] + [[-1.0]] * (len(texts) - 1), dtype=np.float32)

    monkeypatch.setattr(dense, "embed_texts", unrelated_embeddings)
    monkeypatch.setenv("RETRIEVAL_MODE", "langchain")
    get_settings.cache_clear()
    try:
        sources.execute(client, headers, engine, "ubuntu")
        baseline = questions.analysis(client, headers, engine)
        response = questions.ask(
            client, headers, [baseline["id"]], question="banana moonlight recipe"
        )
        assert response.status_code == 202, response.text
        with Session(engine) as db:
            context = db.get(QuestionRun, response.json()["id"]).input_payload
            assert context["insufficient_evidence"]
            assert not any(citation["id"].startswith("E") for citation in context["citations"])

        run_once(engine)
        result = client.get("/api/v1/questions/" + response.json()["id"], headers=headers).json()
        assert result["result"]["status"] == "INSUFFICIENT_EVIDENCE"
        assert wire["calls"] == []
    finally:
        get_settings.cache_clear()
