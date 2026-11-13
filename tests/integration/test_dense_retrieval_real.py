"""Real BGE-M3 retrieval integration test."""

import pytest
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.models.tables import AnalysisRun, QuestionRun, TextChunk
from tests.integration import test_questions as questions
from tests.integration import test_sources as sources

source_wire = sources.source_wire
wire = questions.wire


def test_real_bge_m3_question_api(
    client, headers, engine, source_wire, wire, monkeypatch, tmp_path
):
    pytest.importorskip("numpy")
    pytest.importorskip("sentence_transformers")

    monkeypatch.setenv("RETRIEVAL_MODE", "dense")
    monkeypatch.setenv("EMBEDDING_MODEL", "BAAI/bge-m3")
    monkeypatch.setenv(
        "EMBEDDING_CACHE_DIRECTORY",
        str(tmp_path / "bge-cache"),
    )
    get_settings.cache_clear()

    sources.execute(client, headers, engine, "ubuntu")
    baseline = questions.analysis(client, headers, engine)

    response = questions.ask(
        client,
        headers,
        [baseline["id"]],
        question="이 분석에서 발견된 취약점과 공식 보안 근거를 설명해줘",
    )
    assert response.status_code == 202, response.text

    with Session(engine) as db:
        run = db.get(QuestionRun, response.json()["id"])
        context = run.input_payload
        snapshots = set(db.get(AnalysisRun, baseline["id"]).source_snapshot_ids)

        assert context["retrieval_version"] == "dense/BAAI/bge-m3"
        assert context["facts"]
        assert not context["insufficient_evidence"]

        evidence = [citation for citation in context["citations"] if citation["id"].startswith("E")]
        assert evidence

        for citation in evidence:
            assert citation["snapshot_id"] in snapshots
            chunk = db.get(TextChunk, citation["chunk_id"])
            assert chunk.text == citation["excerpt"]
            assert chunk.end_offset - chunk.start_offset == len(chunk.text)

    assert list((tmp_path / "bge-cache").rglob("*.npy"))
    get_settings.cache_clear()
