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
from sentence_transformers import SentenceTransformer

from backend.retrieval.search import rank, vector

DATA_DIR = ROOT / "data/evaluation"
MODEL_NAME = "BAAI/bge-m3"


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

    texts = [build_text(record) for record in records]

    candidates = [
        {
            "id": i,
            "cve_id": record["id"],
            "vector": vector(text),
        }
        for i, (record, text) in enumerate(zip(records, texts, strict=True), 1)
    ]

    device = "mps" if torch.backends.mps.is_available() else "cpu"

    print(f"문서: {len(records)}건")
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

    results = {
        f"RRF_{w:.1f}_{1.0-w:.1f}": []
        for w in (0.5, 0.3, 0.2, 0.0)
    }
    per_question = []

    for question_item, query_embedding in zip(questions, query_embeddings, strict=True):
        question = question_item["question"]
        relevant = question_item["relevant_cve_ids"]

        tfidf = rank(question, candidates, len(candidates))
        tfidf_ids = [candidate["cve_id"] for candidate, _ in tfidf]

        similarities = embeddings @ query_embedding
        dense_indices = np.argsort(-similarities, kind="stable")
        dense_ids = [candidates[i]["cve_id"] for i in dense_indices]

        tfidf_ranks = {
            cve: position
            for position, cve in enumerate(tfidf_ids, 1)
        }
        dense_ranks = {
            cve: position
            for position, cve in enumerate(dense_ids, 1)
        }

        row = {
            "question_id": question_item["question_id"],
            "question": question,
            "relevant_cve_ids": relevant,
        }

        for tfidf_weight in (0.5, 0.3, 0.2, 0.0):
            dense_weight = 1.0 - tfidf_weight
            name = f"RRF_{tfidf_weight:.1f}_{dense_weight:.1f}"

            weighted_ids = sorted(
                dense_ids,
                key=lambda cve: (
                    -(
                        (
                            tfidf_weight / (60 + tfidf_ranks[cve])
                            if cve in tfidf_ranks
                            else 0
                        )
                        + dense_weight / (60 + dense_ranks[cve])
                    ),
                    cve,
                ),
            )

            metrics = calculate_metrics(weighted_ids, relevant)
            results[name].append(metrics)

            row[name] = {
                "rank": weighted_ids.index(relevant[0]) + 1,
                "top5": weighted_ids[:5],
                "metrics": metrics,
            }

        per_question.append(row)

    summary = {}

    print("\n=== Weighted RRF 평가 결과 ===")
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

    output = DATA_DIR / "weighted_rrf_results.json"
    output.write_text(
        json.dumps(
            {
                "metadata": {
                    "model": MODEL_NAME,
                    "device": device,
                    "document_count": len(records),
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
