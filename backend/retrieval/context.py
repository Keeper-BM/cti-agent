import hashlib
import json
import re
from datetime import UTC

from sqlalchemy import select

from backend.assessment.contracts import AssessmentFinding
from backend.core.errors import AppError
from backend.llm.contracts import Citation
from backend.models.tables import FindingRecord, SourceDocument, SourceRecord, TextChunk
from backend.retrieval.contracts import QuestionContext, QuestionFact
from backend.retrieval.search import VERSION, rank, vector
from backend.sources.contracts import SecurityRecord

SOURCE_STAGE_NOTE = "Ubuntu 패키지 기준 자료입니다. 자산의 영향 판정은 아직 실행하지 않았습니다."


def sha(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def aware(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def prepare(db, question, analyses):
    summaries = []
    all_findings = []
    snapshots = set()
    citations = []
    facts = []
    warnings = []
    asked = set(re.findall(r"CVE-\d{4}-\d{4,19}", question.upper()))
    named_sources = set()
    if re.search(r"apache|httpd|아파치", question, re.I):
        named_sources.add("apache2")
    if re.search(r"mysql|my sql|마이에스큐엘", question, re.I):
        named_sources.add("mysql-8.0")
    for index, analysis in enumerate(analyses, 1):
        ref = f"A{index}"
        summary = {
            "asset_ref": ref,
            "analysis_id": analysis.id,
            "analysis_completed": True,
            "os_release": analysis.os_release,
            "counts": analysis.summary or {},
            "is_synthetic": analysis.is_synthetic,
            "warnings": analysis.warnings,
        }
        summaries.append(summary)
        snapshots.update(analysis.source_snapshot_ids)
        citations.append(
            Citation(
                id=ref,
                source_id="assessment",
                title=f"{ref} 저장된 분석 요약",
                document_id=None,
                record_id=None,
                snapshot_id=None,
                captured_at=aware(analysis.created_at),
                sha256=None,
                url=None,
                excerpt=json.dumps(summary, ensure_ascii=False),
            )
        )
        records = db.scalars(
            select(FindingRecord)
            .where(FindingRecord.analysis_id == analysis.id, FindingRecord.cve_id.is_not(None))
            .order_by(FindingRecord.id)
        )
        for row in records:
            value = AssessmentFinding.model_validate(row.payload)
            if asked and value.cve_id not in asked:
                continue
            if named_sources and value.source_package not in named_sources:
                continue
            priority = (
                int(value.verdict == "AFFECTED") * 8
                + int(value.kev_status == "LISTED") * 4
                + int(value.version_comparison == "BELOW_FIX") * 2
                + int(value.verdict == "NEEDS_REVIEW")
            )
            all_findings.append((priority, ref, analysis, value))
    all_findings.sort(key=lambda x: (-x[0], x[1], x[3].cve_id or "", x[3].package_name or ""))
    selected = []
    seen = set()
    for _, ref, analysis, f in all_findings:
        identity = (analysis.id, f.cve_id)
        if identity in seen:
            continue
        seen.add(identity)
        selected.append((ref, analysis, f))
        if len(selected) >= 12:
            break
    cves = {f.cve_id for _, _, f in selected}
    candidates = []
    documents = {}
    for ref, analysis, f in selected:
        fact = QuestionFact(
            asset_ref=ref,
            analysis_id=analysis.id,
            finding_id=str(f.finding_id),
            package_name=f.package_name,
            cve_id=f.cve_id,
            installed_version=f.installed_version,
            fixed_version=f.fixed_version,
            verdict=f.verdict,
            version_comparison=f.version_comparison,
            origin_status=f.origin_status,
            reasons=f.reasons,
        )
        facts.append(fact)
    facts_wire = [f.model_dump() for f in facts]
    # Full facts are backend-controlled and displayed separately from model prose.
    for citation in citations:
        related = [f.model_dump() for f in facts if f.asset_ref == citation.id]
        citation.excerpt += "\n" + json.dumps(related, ensure_ascii=False)
        citation.sha256 = hashlib.sha256(citation.excerpt.encode()).hexdigest()
    if snapshots and cves:
        rows = db.execute(
            select(SourceRecord, SourceDocument)
            .join(SourceDocument, SourceDocument.id == SourceRecord.document_id)
            .where(SourceRecord.snapshot_id.in_(snapshots), SourceRecord.cve_id.in_(cves))
            .order_by(SourceRecord.id)
            .limit(400)
        )
        for record, document in rows:
            data = SecurityRecord.model_validate(record.payload)
            if record.source_id == "ubuntu" and not any(
                a.os_release == data.release
                and f.source_package == data.package_name
                and f.cve_id == data.cve_id
                for _, a, f in selected
            ):
                continue
            text = f"{data.cve_id}\n{data.title}\n{data.description}\n" + json.dumps(
                {
                    "status": data.status,
                    "fixed_version": data.fixed_version,
                    "notes": [note for note in data.notes if note != SOURCE_STAGE_NOTE],
                    "attributes": data.attributes,
                },
                ensure_ascii=False,
            )
            text = text[:8000]
            chunks = list(
                db.scalars(
                    select(TextChunk)
                    .where(TextChunk.record_id == record.id, TextChunk.index_version == VERSION)
                    .order_by(TextChunk.ordinal)
                )
            )
            if not chunks:
                for ordinal, start in enumerate(range(0, len(text), 1000)):
                    excerpt = text[start : start + 1200]
                    chunk = TextChunk(
                        record_id=record.id,
                        document_id=document.id,
                        index_version=VERSION,
                        ordinal=ordinal,
                        start_offset=start,
                        end_offset=start + len(excerpt),
                        text=excerpt,
                        vector=vector(excerpt),
                    )
                    db.add(chunk)
                    chunks.append(chunk)
                db.flush()
            documents[document.id] = document
            for chunk in chunks:
                candidates.append(
                    {
                        "id": chunk.id,
                        "chunk": chunk,
                        "record": record,
                        "document": document,
                        "vector": chunk.vector,
                        "cve_id": record.cve_id,
                    }
                )
    for candidate, _score in rank(question, candidates, 10):
        chunk = candidate["chunk"]
        record = candidate["record"]
        document = candidate["document"]
        citations.append(
            Citation(
                id=f"E{len([c for c in citations if c.id.startswith('E')]) + 1}",
                source_id=record.source_id,
                title=record.cve_id + " " + record.source_id,
                document_id=document.id,
                record_id=record.id,
                snapshot_id=record.snapshot_id,
                captured_at=aware(document.captured_at),
                sha256=document.sha256,
                url=document.url,
                excerpt=chunk.text,
                truncated=True,
                chunk_id=chunk.id,
                chunk_start=chunk.start_offset,
                chunk_end=chunk.end_offset,
            )
        )
    if len(all_findings) > len(selected):
        warnings.append(
            "질문 문맥에는 최대 12개 CVE 대표 결과를 포함했습니다. "
            "전체 결과는 분석 화면에서 확인하세요."
        )
    warnings.extend(
        [
            "질문과 선택한 분석의 패키지·판단·공식 근거 발췌를 학교 API에 전달합니다.",
            "인용 존재·입력 범위를 검사하지만 모든 생성 문장의 사실성을 자동 보장하지 않습니다.",
        ]
    )
    context = QuestionContext(
        question=question,
        analysis_ids=[a.id for a in analyses],
        asset_ids=[a.asset_id for a in analyses],
        summaries=summaries,
        facts=facts,
        citations=citations,
        retrieval_version=VERSION,
        facts_digest=sha({"facts": facts_wire, "summaries": summaries}),
        warnings=warnings,
        insufficient_evidence=not facts or not any(c.id.startswith("E") for c in citations),
    )
    if len(context.model_dump_json().encode()) > 96 * 1024:
        raise AppError(
            "QUESTION_CONTEXT_LIMIT", "질문 범위를 줄이거나 분석을 더 적게 선택하세요.", 422
        )
    return context
