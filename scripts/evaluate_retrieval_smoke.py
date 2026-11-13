"""TF-IDF / BGE-M3 / Hybrid retrieval smoke test (synthetic data)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sentence_transformers import SentenceTransformer

from backend.retrieval.search import rank, vector

DOCUMENTS = [
    (
        "ubuntu",
        "CVE-2099-10001",
        "Ubuntu apache2 package has a conditional vulnerability. Update to the fixed version.",
    ),
    ("nvd", "CVE-2099-10001", "NVD describes a synthetic vulnerability affecting a web server."),
    ("kev", "CVE-2099-10001", "Known exploited vulnerabilities require prioritized remediation."),
    (
        "apache",
        "CVE-2099-10002",
        "Apache HTTP Server authentication bypass vulnerability allows unauthorized access.",
    ),
    (
        "oracle",
        "CVE-2099-10003",
        "Oracle MySQL database security update fixes a privilege escalation issue.",
    ),
]

QUESTIONS = [
    "CVE-2099-10001의 수정 버전은?",
    "인증 없이 접근할 수 있는 웹 서버 취약점은?",
    "MySQL 데이터베이스 권한 상승 문제는?",
]


def main():
    model = SentenceTransformer("BAAI/bge-m3", device="mps")
    texts = [f"{cve}\n{text}" for _, cve, text in DOCUMENTS]
    embeddings = model.encode(texts, normalize_embeddings=True)

    candidates = [
        {
            "id": i,
            "cve_id": cve,
            "vector": vector(text),
            "text": text,
            "source": source,
        }
        for i, ((source, cve, _), text) in enumerate(zip(DOCUMENTS, texts, strict=True), 1)
    ]

    for question in QUESTIONS:
        tfidf = rank(question, candidates, len(candidates))
        query_embedding = model.encode([question], normalize_embeddings=True)[0]

        dense = sorted(
            [(c, float(query_embedding @ embeddings[i])) for i, c in enumerate(candidates)],
            key=lambda item: (-item[1], item[0]["id"]),
        )

        tfidf_ranks = {c["id"]: i for i, (c, _) in enumerate(tfidf, 1)}
        dense_ranks = {c["id"]: i for i, (c, _) in enumerate(dense, 1)}

        hybrid = sorted(
            candidates,
            key=lambda c: (
                -(
                    (1 / (60 + tfidf_ranks[c["id"]]) if c["id"] in tfidf_ranks else 0)
                    + 1 / (60 + dense_ranks[c["id"]])
                ),
                c["id"],
            ),
        )

        print(f"\n질문: {question}")
        for name, results in [
            ("TF-IDF", [c for c, _ in tfidf]),
            ("BGE-M3", [c for c, _ in dense]),
            ("Hybrid", hybrid),
        ]:
            top = results[:3]
            print(f"  {name:8}: " + " > ".join(f"{c['source']}({c['cve_id']})" for c in top))


if __name__ == "__main__":
    main()
