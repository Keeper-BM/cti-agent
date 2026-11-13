# ruff: noqa: E402
"""Compare TF-IDF, BGE-M3 and Hybrid on real Ubuntu OSV records."""

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import torch
import torch._dynamo
from sentence_transformers import SentenceTransformer

from backend.retrieval.search import rank, vector

DATA_PATH = ROOT / "data/evaluation/ubuntu_osv_300.json"
MODEL_NAME = "BAAI/bge-m3"
TOP_K = 5


def build_text(record):
    description = record["text"].split("Description:", 1)[-1]
    description = description.split("\nPackage:", 1)[0].strip()

    packages = sorted({item["package"] for item in record["affected"] if item.get("package")})

    return (
        f"CVE: {record['id']}\n"
        f"Description: {description[:1800]}\n"
        f"Packages: {', '.join(packages[:10])}"
    )


def main():
    records = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    texts = [build_text(record) for record in records]

    candidates = [
        {
            "id": i,
            "cve_id": record["id"],
            "vector": vector(text),
            "text": text,
            "source": record["source"],
        }
        for i, (record, text) in enumerate(zip(records, texts, strict=True), 1)
    ]

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"문서 수: {len(candidates)}")
    print(f"임베딩 장치: {device}")

    model = SentenceTransformer(MODEL_NAME, device=device)

    start = time.perf_counter()
    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        batch_size=8,
        show_progress_bar=True,
    )
    print(f"문서 임베딩 시간: {time.perf_counter() - start:.2f}초")

    # The first question tests exact CVE identification.
    # The other questions test semantic retrieval without CVE IDs.
    first = records[0]
    questions = [
        f"{first['id']} 취약점은 무엇인가?",
        "Linux kernel logical CPU ID validation vulnerability",
        "Java certificate X.509 name constraints validation vulnerability",
        "원격 코드 실행이 가능한 메모리 손상 취약점",
        "Ubuntu에서 인증 없이 접근 가능한 보안 취약점",
    ]

    for question in questions:
        print(f"\n질문: {question}")

        start = time.perf_counter()
        tfidf = rank(question, candidates, len(candidates))
        tfidf_time = time.perf_counter() - start

        start = time.perf_counter()
        query_embedding = model.encode([question], normalize_embeddings=True)[0]
        similarities = embeddings @ query_embedding
        dense = sorted(
            zip(candidates, similarities, strict=True),
            key=lambda item: (-float(item[1]), item[0]["id"]),
        )
        dense_time = time.perf_counter() - start

        start = time.perf_counter()
        tfidf_ranks = {candidate["id"]: i for i, (candidate, _) in enumerate(tfidf, 1)}
        dense_ranks = {candidate["id"]: i for i, (candidate, _) in enumerate(dense, 1)}

        hybrid = sorted(
            candidates,
            key=lambda candidate: (
                -(
                    (
                        1 / (60 + tfidf_ranks[candidate["id"]])
                        if candidate["id"] in tfidf_ranks
                        else 0
                    )
                    + 1 / (60 + dense_ranks[candidate["id"]])
                ),
                candidate["id"],
            ),
        )
        hybrid_time = time.perf_counter() - start

        for name, results, elapsed in [
            ("TF-IDF", [c for c, _ in tfidf], tfidf_time),
            ("BGE-M3", [c for c, _ in dense], dense_time),
            ("Hybrid", hybrid, hybrid_time),
        ]:
            print(f"  {name} ({elapsed * 1000:.1f}ms)")
            for candidate in results[:TOP_K]:
                description = re.search(
                    r"Description: (.*)",
                    candidate["text"],
                )
                snippet = description.group(1)[:100] if description else ""
                print(f"    {candidate['cve_id']}: {snippet}")


if __name__ == "__main__":
    main()
