import numpy as np

from backend.retrieval import dense


def test_exact_cve_match_gets_priority(monkeypatch):
    candidates = [
        {"id": "a", "cve_id": "CVE-2025-11111", "chunk": type("Chunk", (), {"text": "first"})()},
        {"id": "b", "cve_id": "CVE-2025-12345", "chunk": type("Chunk", (), {"text": "second"})()},
    ]

    def fake_embed_texts(texts, model_name, cache_directory):
        return np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32)

    monkeypatch.setattr(dense, "embed_texts", fake_embed_texts)

    ranked = dense.rank_dense("CVE-2025-12345 취약점 알려줘", candidates)

    assert ranked[0][0]["cve_id"] == "CVE-2025-12345"
    assert ranked[0][1] == 2.0


def test_embedding_cache_key_uses_null_separator(tmp_path):
    actual = dense.cache_path(tmp_path, "model", "text")
    import hashlib

    expected = hashlib.sha256(b"model\x00text").hexdigest()
    assert actual.name == f"{expected}.npy"
