"""Optional BGE-M3 retrieval over pre-scoped evidence chunks."""

import hashlib
import re
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=2)
def load_model(model_name):
    import torch
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name, device=select_device(torch))


def select_device(torch):
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def cache_path(cache_directory, model_name, text):
    digest = hashlib.sha256((model_name + "\0" + text).encode("utf-8")).hexdigest()
    return Path(cache_directory) / f"{digest}.npy"


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
            except (OSError, ValueError):
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
            path.parent.mkdir(parents=True, exist_ok=True)
            np.save(path, embedding)

    return np.stack(results) if results else np.empty((0, 1024), dtype=np.float32)


def rank_dense(
    question,
    candidates,
    limit=10,
    *,
    model_name="BAAI/bge-m3",
    cache_directory=".data/embedding-cache",
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
        if requested_cves and candidate.get("cve_id") in requested_cves:
            score += 2.0
        scored.append((score, candidate["id"], candidate))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [(candidate, score) for score, _, candidate in scored[:limit]]
