# ruff: noqa: E402
"""Evaluate TF-IDF, BGE-M3 and Hybrid retrieval on labeled CVE questions."""

import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import torch
import torch._dynamo
from sentence_transformers import CrossEncoder, SentenceTransformer

from backend.retrieval.search import vector

DATA_DIR = ROOT / "data/evaluation"
MODEL_NAME = "BAAI/bge-m3"
RERANKER_NAME = "BAAI/bge-reranker-v2-m3"
TOP_K = 20


def build_text(record):
    description = record["text"].split("Description:", 1)[-1]
    description = description.split("\nPackage:", 1)[0].strip()

    packages = sorted({
        item["package"]
        for item in record["affected"]
        if item.get("package")
    })

    return (
        f"CVE: {record['id']}\n"
        f"Description: {description[:1800]}\n"
        f"Packages: {', '.join(packages[:10])}"
    )


def calculate_metrics(ranked_ids, relevant_ids):
    relevant = set(relevant_ids)

    hits = sum(cve in relevant for cve in ranked_ids[:5])
    recall5 = hits / len(relevant)

    reciprocal_rank = 0.0
    for position, cve in enumerate(ranked_ids[:10], 1):
        if cve in relevant:
            reciprocal_rank = 1 / position
            break

    dcg = sum(
        1 / math.log2(position + 1)
        for position, cve in enumerate(ranked_ids[:10], 1)
        if cve in relevant
    )

    ideal_dcg = sum(
        1 / math.log2(position + 1)
        for position in range(1, min(len(relevant), 10) + 1)
    )

    ndcg10 = dcg / ideal_dcg if ideal_dcg else 0.0

    return {
        "Recall@5": recall5,
        "MRR@10": reciprocal_rank,
        "nDCG@10": ndcg10,
    }


def main():
    records = json.loads(
        (DATA_DIR / "ubuntu_osv_balanced_300.json").read_text()
    )
    questions = json.loads(
        (DATA_DIR / "retrieval_questions_20.json").read_text()
    )

    chunks = []
    for record in records:
        text = build_text(record)
        for ordinal, start_offset in enumerate(range(0, len(text), 1000)):
            excerpt = text[start_offset:start_offset + 1200]
            chunks.append({
                "id": len(chunks) + 1,
                "cve_id": record["id"],
                "ordinal": ordinal,
                "text": excerpt,
                "vector": vector(excerpt),
            })

    texts = [chunk["text"] for chunk in chunks]
    candidates = chunks

    device = "mps" if torch.backends.mps.is_available() else "cpu"

    print(f"CVE 문서: {len(records)}건 / 청크: {len(chunks)}개")
    print(f"질문: {len(questions)}개")
    print(f"장치: {device}")

    model = SentenceTransformer(MODEL_NAME, device=device)

    start = time.perf_counter()
    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        batch_size=8,
        show_progress_bar=True,
    )
    embedding_seconds = time.perf_counter() - start

    question_texts = [item["question"] for item in questions]

    start = time.perf_counter()
    query_embeddings = model.encode(
        question_texts,
        normalize_embeddings=True,
        batch_size=8,
        show_progress_bar=True,
    )
    query_embedding_seconds = time.perf_counter() - start

    print("Reranker 모델 로딩 중...")
    reranker = CrossEncoder(RERANKER_NAME, device=device, max_length=512)

    results = {"BGE-M3": [], "BGE-M3+Reranker": []}
    rerank_times = []
    per_question = []

    for question_item, query_embedding in zip(questions, query_embeddings, strict=True):
        question = question_item["question"]
        relevant = question_item["relevant_cve_ids"]

        similarities = embeddings @ query_embedding
        dense_indices = np.argsort(-similarities, kind="stable")

        def unique_cves(indices):
            seen = set()
            result = []
            for index in indices:
                cve_id = candidates[index]["cve_id"]
                if cve_id not in seen:
                    seen.add(cve_id)
                    result.append(cve_id)
            return result

        dense_ids = unique_cves(dense_indices)

        top_indices = dense_indices[:TOP_K]
        pairs = [
            (question, candidates[i]["text"])
            for i in top_indices
        ]

        rerank_start = time.perf_counter()
        scores = reranker.predict(pairs, batch_size=4)
        rerank_times.append(time.perf_counter() - rerank_start)

        reranked_indices = sorted(
            range(len(top_indices)),
            key=lambda i: (-float(scores[i]), i),
        )

        reranked_top = [
            top_indices[i] for i in reranked_indices
        ]
        reranked_ids = unique_cves(
            list(reranked_top) + list(dense_indices[TOP_K:])
        )

        row = {
            "question_id": question_item["question_id"],
            "question": question,
            "relevant_cve_ids": relevant,
        }

        for name, ranked_ids in [
            ("BGE-M3", dense_ids),
            ("BGE-M3+Reranker", reranked_ids),
        ]:
            metrics = calculate_metrics(ranked_ids, relevant)
            results[name].append(metrics)

            row[name] = {
                "rank": (
                    ranked_ids.index(relevant[0]) + 1
                    if relevant[0] in ranked_ids
                    else None
                ),
                "top5": ranked_ids[:5],
                "metrics": metrics,
            }

        per_question.append(row)

    summary = {}

    print("\n=== 검색 성능 평가 결과 ===")
    print(f"{'방식':<12} {'Recall@5':>10} {'MRR@10':>10} {'nDCG@10':>10}")

    for name, values in results.items():
        summary[name] = {
            metric: sum(item[metric] for item in values) / len(values)
            for metric in ("Recall@5", "MRR@10", "nDCG@10")
        }

        scores = summary[name]
        print(
            f"{name:<12} "
            f"{scores['Recall@5']:>10.4f} "
            f"{scores['MRR@10']:>10.4f} "
            f"{scores['nDCG@10']:>10.4f}"
        )

    output = DATA_DIR / "reranker_results.json"
    output.write_text(
        json.dumps(
            {
                "metadata": {
                    "model": MODEL_NAME,
                    "reranker": RERANKER_NAME,
                    "reranker_top_k": TOP_K,
                    "rerank_seconds_total": sum(rerank_times),
                    "rerank_seconds_average": sum(rerank_times) / len(rerank_times),
                    "device": device,
                    "document_count": len(records),
                    "chunk_count": len(chunks),
                    "question_count": len(questions),
                    "label_status": "source_cve_only",
                    "document_embedding_seconds": embedding_seconds,
                    "query_embedding_seconds": query_embedding_seconds,
                },
                "summary": summary,
                "per_question": per_question,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"\n문서 임베딩 시간: {embedding_seconds:.2f}초")
    print(f"질문 임베딩 시간: {query_embedding_seconds:.2f}초")
    print(f"결과 저장: {output}")


if __name__ == "__main__":
    main()
