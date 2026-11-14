import pytest

from backend.retrieval import dense


def test_exact_cve_match_gets_priority(monkeypatch):
    np = pytest.importorskip("numpy")
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


def test_dense_ranking_filters_irrelevant_and_nonfinite_scores(monkeypatch):
    np = pytest.importorskip("numpy")
    candidates = [
        {"id": "a", "cve_id": "CVE-2025-11111", "chunk": type("Chunk", (), {"text": "a"})()},
        {"id": "b", "cve_id": "CVE-2025-22222", "chunk": type("Chunk", (), {"text": "b"})()},
        {"id": "c", "cve_id": "CVE-2025-33333", "chunk": type("Chunk", (), {"text": "c"})()},
    ]
    monkeypatch.setattr(
        dense,
        "embed_texts",
        lambda *_: np.array([[1.0], [0.44], [0.46], [float("nan")]], dtype=np.float32),
    )

    assert [candidate["id"] for candidate, _ in dense.rank_dense("question", candidates)] == ["b"]
    assert dense.rank_dense("question", candidates, min_similarity=0.5) == []
    assert [candidate["id"] for candidate, _ in dense.rank_dense("CVE-2025-11111", candidates)] == [
        "a",
        "b",
    ]


def test_corrupted_cache_is_rebuilt_and_used(monkeypatch, tmp_path):
    np = pytest.importorskip("numpy")
    cache = dense.cache_path(tmp_path, "test-model", "text")
    cache.write_bytes(b"")
    calls = []

    class Model:
        def encode(self, texts, **kwargs):
            calls.append(texts)
            return np.full((len(texts), 1024), 0.25, dtype=np.float32)

    monkeypatch.setattr(dense, "load_model", lambda _: Model())
    first = dense.embed_texts(["text"], "test-model", tmp_path)
    second = dense.embed_texts(["text"], "test-model", tmp_path)

    assert calls == [["text"]]
    np.testing.assert_array_equal(first, second)
    np.testing.assert_array_equal(np.load(cache, allow_pickle=False), first[0])


def test_failed_cache_write_does_not_destroy_previous_entry(monkeypatch, tmp_path):
    np = pytest.importorskip("numpy")
    cache = tmp_path / "embedding.npy"
    original = np.array([1.0, 2.0], dtype=np.float32)
    np.save(cache, original, allow_pickle=False)

    def fail_after_partial_write(stream, *_args, **_kwargs):
        stream.write(b"incomplete")
        raise OSError("simulated interrupted write")

    monkeypatch.setattr(np, "save", fail_after_partial_write)
    with pytest.raises(OSError, match="simulated interrupted write"):
        dense.write_cache(cache, np.array([3.0]))

    np.testing.assert_array_equal(np.load(cache, allow_pickle=False), original)
    assert list(tmp_path.iterdir()) == [cache]
