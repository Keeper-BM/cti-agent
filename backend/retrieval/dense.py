"""Optional BGE-M3 retrieval over pre-scoped evidence chunks."""

import hashlib
import logging
import math
import os
import re
import tempfile
from functools import lru_cache
from pathlib import Path
from threading import Lock

logger = logging.getLogger(__name__)
_model_lock = Lock()


def load_model(model_name):
    # lru_cache alone may invoke its wrapped function concurrently on a miss.
    with _model_lock:
        return _load_model(model_name)


@lru_cache(maxsize=2)
def _load_model(model_name):
    import torch
    from sentence_transformers import SentenceTransformer

    device = select_device(torch)
    logger.info("Loading dense retrieval model %s on %s", model_name, device)
    return SentenceTransformer(model_name, device=device)


def select_device(torch):
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def cache_path(cache_directory, model_name, text):
    digest = hashlib.sha256((model_name + "\0" + text).encode("utf-8")).hexdigest()
    return Path(cache_directory) / f"{digest}.npy"


def write_cache(path, embedding):
    """Publish only complete cache files, including when multiple requests write at once."""
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            np.save(stream, embedding, allow_pickle=False)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def embed_texts(texts, model_name, cache_directory):
    import numpy as np

    results = [None] * len(texts)
    missing = []
    missing_indices = []

    for index, text in enumerate(texts):
        path = cache_path(cache_directory, model_name, text)
        if path.exists():
            try:
                embedding = np.load(path, allow_pickle=False)
                if embedding.shape == (1024,) and np.isfinite(embedding).all():
                    results[index] = embedding.astype(np.float32)
                    continue
            except (EOFError, OSError, ValueError):
                pass
        missing.append(text)
        missing_indices.append(index)

    if missing:
        model = load_model(model_name)
        embeddings = model.encode(
            missing,
            batch_size=8,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        for index, embedding in zip(missing_indices, embeddings, strict=True):
            embedding = np.asarray(embedding, dtype=np.float32)
            results[index] = embedding
            path = cache_path(cache_directory, model_name, texts[index])
            write_cache(path, embedding)

    return np.stack(results) if results else np.empty((0, 1024), dtype=np.float32)


def rank_dense(
    question,
    candidates,
    limit=10,
    *,
    model_name="BAAI/bge-m3",
    cache_directory=".data/embedding-cache",
    min_similarity=0.45,
):
    if not candidates or limit <= 0:
        return []

    texts = [question] + [c["chunk"].text for c in candidates]
    embeddings = embed_texts(texts, model_name, cache_directory)

    query_embedding = embeddings[0]
    document_embeddings = embeddings[1:]
    scores = document_embeddings @ query_embedding

    requested_cves = set(re.findall(r"CVE-\d{4}-\d{4,19}", question.upper()))

    scored = []
    for candidate, similarity in zip(candidates, scores, strict=True):
        score = float(similarity)
        if not math.isfinite(score):
            continue
        exact_cve = bool(requested_cves and candidate.get("cve_id") in requested_cves)
        if not exact_cve and score < min_similarity:
            continue
        if exact_cve:
            score += 2.0
        scored.append((score, candidate["id"], candidate))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [(candidate, score) for score, _, candidate in scored[:limit]]
