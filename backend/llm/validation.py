"""Structural and referential validation, not a claim of semantic truth verification."""

import json
import re
import unicodedata

from pydantic import ValidationError

from backend.core.errors import AppError
from backend.llm.contracts import ExplanationContext, ExplanationResult, GeneratedExplanation


def invalid(code="LLM_OUTPUT_INVALID", message="AI 설명의 형식을 검증하지 못했습니다."):
    return AppError(code, message, 502)


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def no_constant(_value):
    raise ValueError()


def validate_output(content: str, context: ExplanationContext) -> ExplanationResult:
    try:
        if len(content.encode("utf-8")) > 24000:
            raise ValueError()
        output = GeneratedExplanation.model_validate(
            json.loads(
                content,
                object_pairs_hook=unique_keys,
                parse_constant=no_constant,
            )
        )
    except (ValueError, ValidationError, RecursionError):
        raise invalid() from None
    if output.facts != context.facts:
        raise invalid(
            "LLM_FACT_MISMATCH", "모델이 저장된 판단·버전 등의 기준값을 변경해 응답을 제외했습니다."
        )
    allowed = {c.id for c in context.citations}
    all_sections = [output.meaning, *output.next_steps]
    if not any(i.startswith("E") for i in output.meaning.evidence_ids):
        raise invalid("LLM_CITATION_INVALID", "취약점 설명에 공식 근거 인용이 없습니다.")
    if not any("A1" in step.evidence_ids for step in output.next_steps):
        raise invalid("LLM_CITATION_INVALID", "확인 사항에 저장된 분석 근거가 없습니다.")
    for section in all_sections:
        ids = section.evidence_ids
        if len(set(ids)) != len(ids) or not set(ids) <= allowed:
            raise invalid(
                "LLM_CITATION_INVALID",
                "제공하지 않은 근거 또는 중복된 인용이 있어 응답을 제외했습니다.",
            )
        text = unicodedata.normalize("NFKC", section.text)
        if (
            not re.search(r"[가-힣]", text)
            or re.search(
                r"https?://|www\.|<|>|`|dcu_llm_|Bearer\s|\d+\.\d+|\[\s*[EA]\d+\s*\]", text, re.I
            )
            or any(unicodedata.category(c) in {"Cf", "Cc"} and c not in "\n\t" for c in text)
        ):
            raise invalid(
                "LLM_TEXT_INVALID",
                "설명문에 허용하지 않은 버전·주소·표현 형식이 포함되어 있습니다.",
            )
        if any(
            cve.upper() != context.facts.cve_id
            for cve in re.findall(r"CVE-\d{4}-\d{4,}", text, re.I)
        ):
            raise invalid("LLM_FACT_MISMATCH", "선택하지 않은 CVE가 설명에 포함되어 있습니다.")
        # Conservative rejection of obvious reassessment claims. This is not semantic proof.
        if re.search(
            r"(?:서버|자산|시스템|패키지).{0,20}"
            r"(?:안전합니다|취약합니다|영향이 없습니다|수정되었습니다)",
            text,
        ):
            raise invalid(
                "LLM_UNSUPPORTED_CLAIM",
                "모델이 자산 상태를 단정한 표현이 있어 응답을 제외했습니다.",
            )
        section.text = text.strip()
    labels = {
        "AFFECTED": "영향 있음",
        "FIXED": "해당 CVE의 수정 기준 충족",
        "NOT_AFFECTED": "공식 조건상 영향 없음",
        "NEEDS_REVIEW": "추가 확인 필요",
    }
    comparisons = {
        "BELOW_FIX": "공식 수정 기준보다 낮음",
        "MEETS_FIX": "공식 수정 기준 이상",
        "UNAVAILABLE": "버전 비교 불가",
    }
    facts = context.facts
    assessment = (
        f"저장된 판단: {labels.get(facts.verdict, facts.verdict)}. "
        f"버전 비교: {comparisons[facts.version_comparison]}."
    )
    warnings = [
        "AI가 작성한 설명입니다. 인용·기준값을 검사했으며 문장 전체의 사실성은 보장하지 않습니다.",
        "내 패키지의 판단·버전·이유는 저장된 분석에서 가져온 값입니다.",
        *context.limitations,
        *context.selection_notes,
    ]
    if facts.is_synthetic:
        warnings.insert(0, "가상 패키지 입력에 대한 설명이며 실제 서버 상태가 아닙니다.")
    used = {"A1", *(i for section in all_sections for i in section.evidence_ids)}
    return ExplanationResult(
        facts=facts,
        meaning=output.meaning,
        assessment_text=assessment,
        assessment_reasons=context.reasons,
        next_steps=output.next_steps,
        citations=[c for c in context.citations if c.id in used],
        warnings=list(dict.fromkeys(warnings)),
    )
