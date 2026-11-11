"""Dense retrieval API integration without heavyweight model dependencies."""

import sys
from types import ModuleType

from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.models.tables import AnalysisRun, QuestionRun, TextChunk
from tests.integration import test_questions as questions
from tests.integration import test_sources as sources

source_wire = sources.source_wire
wire = questions.wire


def test_dense_retrieval_preserves_evidence_scope(
    client, headers, engine, source_wire, wire, monkeypatch
):
    calls = []

    def fake_rank_dense(question, candidates, limit=10, **kwargs):
        calls.append({
            "question": question,
            "candidate_snapshot_ids": [
                candidate["record"].snapshot_id
                for candidate in candidates
            ],
            "limit": limit,
            "kwargs": kwargs,
        })
        return [(candidate, 0.9) for candidate in candidates[:limit]]

    fake_module = ModuleType("backend.retrieval.dense")
    fake_module.rank_dense = fake_rank_dense
    monkeypatch.setitem(sys.modules, "backend.retrieval.dense", fake_module)

    monkeypatch.setenv("RETRIEVAL_MODE", "dense")
    get_settings.cache_clear()

    sources.execute(client, headers, engine, "ubuntu")
    baseline = questions.analysis(client, headers, engine)

    response = questions.ask(client, headers, [baseline["id"]])
    assert response.status_code == 202, response.text
    assert calls, "Dense 검색 함수가 호출되지 않았습니다."

    with Session(engine) as db:
        run = db.get(QuestionRun, response.json()["id"])
        context = run.input_payload
        snapshots = set(
            db.get(AnalysisRun, baseline["id"]).source_snapshot_ids
        )

        assert context["retrieval_version"] == "dense/BAAI/bge-m3"
        assert context["facts"]
        assert not context["insufficient_evidence"]

        evidence = [
            citation for citation in context["citations"]
            if citation["id"].startswith("E")
        ]
        assert evidence

        for citation in evidence:
            assert citation["snapshot_id"] in snapshots
            chunk = db.get(TextChunk, citation["chunk_id"])
            assert chunk.text == citation["excerpt"]
            assert chunk.end_offset - chunk.start_offset == len(chunk.text)

        assert calls[0]["limit"] == 10
        assert all(
            snapshot_id in snapshots
            for snapshot_id in calls[0]["candidate_snapshot_ids"]
        )

    get_settings.cache_clear()
