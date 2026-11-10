"""Local sparse TF-IDF retrieval with exact CVE boosts and source-scoped candidates."""

import math
import re
from collections import Counter

VERSION = "local-tfidf/1.1"
EXPANSIONS = {
    "확인": "affected fixed vulnerability",
    "먼저": "exploited critical vulnerability",
    "조치": "fixed patch update",
    "분석": "vulnerability affected",
    "취약": "vulnerability",
    "원격": "remote",
    "인증": "authentication",
    "업데이트": "update patch fix",
    "수정": "fixed patch",
    "우선": "exploited critical",
    "악용": "exploited",
    "설정": "configuration",
    "영향": "affected",
}


def terms(text):
    words = re.findall(r"[a-z0-9][a-z0-9.+:_-]*|[가-힣]+", text.lower())
    result = []
    for word in words[:1600]:
        result.append(word)
        if re.search("[가-힣]", word):
            result.extend(word[i : i + 2] for i in range(len(word) - 1))
    return Counter(result)


def vector(text):
    return {term: 1 + math.log(count) for term, count in terms(text).most_common(256)}


def rank(question, candidates, limit=10):
    query = question + " " + " ".join(value for key, value in EXPANSIONS.items() if key in question)
    q = vector(query)
    df = Counter(t for c in candidates for t in c["vector"])
    n = len(candidates)

    def weight(t):
        return math.log((1 + n) / (1 + df[t])) + 1

    qv = {t: v * weight(t) for t, v in q.items()}
    qn = math.sqrt(sum(v * v for v in qv.values())) or 1
    cves = set(re.findall(r"CVE-\d{4}-\d{4,19}", question.upper()))
    scored = []
    for candidate in candidates:
        v = {t: value * weight(t) for t, value in candidate["vector"].items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1
        score = sum(value * v.get(t, 0) for t, value in qv.items()) / (qn * norm)
        if cves and candidate.get("cve_id") in cves:
            score += 2
        scored.append((score, candidate["id"], candidate))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [(candidate, score) for score, _, candidate in scored[:limit] if score > 0]
