"""Conservative, deterministic follow-up guidance tied to saved assessment facts."""

from pydantic import BaseModel


class ResponseStep(BaseModel):
    title: str
    description: str
    evidence_urls: list[str]


class Remediation(BaseModel):
    priority: str
    priority_reason: str
    target_version: str | None
    steps: list[ResponseStep]
    limitations: list[str]


def guidance(finding):
    if finding.cve_id is None:
        return None
    urls = list(dict.fromkeys(e.url for e in finding.evidence_refs))
    scores = [m.score for m in finding.nvd_metrics if m.score is not None]
    score = max(scores) if scores else None
    if finding.verdict in {"FIXED", "NOT_AFFECTED"}:
        priority, reason = "ROUTINE", "현재 저장된 패키지 판단 기준으로 정기 확인 대상입니다."
    elif finding.kev_status == "LISTED":
        priority, reason = (
            "URGENT_REVIEW",
            "CISA 악용 목록에 있어 이 자산의 적용 조건을 우선 확인해야 합니다.",
        )
    elif finding.version_comparison == "BELOW_FIX" or (score is not None and score >= 9):
        priority, reason = (
            "HIGH_REVIEW",
            "수정 기준보다 낮은 버전 또는 높은 CVSS가 있어 우선 검토가 필요합니다.",
        )
    else:
        priority, reason = "REVIEW", "확인되지 않은 출처·적용 조건·자료를 검토해야 합니다."
    steps = []
    if finding.origin_status not in {"OFFICIAL_MATCH", "SUPPORTED_ORIGIN", "VERIFIED_LAB"}:
        steps.append(
            ResponseStep(
                title="설치 파일과 공식 패키지 확인",
                description="공식 패키지 파일 검증을 실행하고 출처·버전·누락 자료를 확인하세요.",
                evidence_urls=urls,
            )
        )
    if finding.version_comparison == "BELOW_FIX" and finding.fixed_version:
        steps.append(
            ResponseStep(
                title="공식 수정 패키지 검토",
                description=(
                    f"{finding.source_package} 소스 수정 기준은 {finding.fixed_version}입니다. "
                    "같은 Ubuntu 릴리스의 바이너리 업데이트와 호환성·백업·일정을 검토하세요."
                ),
                evidence_urls=urls,
            )
        )
    elif finding.version_comparison == "MEETS_FIX":
        steps.append(
            ResponseStep(
                title="수정 기준과 적용 상태 구분",
                description=(
                    "저장된 소스 버전은 수정 기준 이상입니다. "
                    "최종 판단, 파일 검증과 서비스 재시작 여부를 확인하세요."
                ),
                evidence_urls=urls,
            )
        )
    else:
        steps.append(
            ResponseStep(
                title="공식 수정 정보 재확인",
                description=(
                    "자동 비교할 수정 기준이 충분하지 않습니다. "
                    "공식 공지의 릴리스·패키지 조건을 확인하세요."
                ),
                evidence_urls=urls,
            )
        )
    if finding.verdict == "NEEDS_REVIEW":
        steps.append(
            ResponseStep(
                title="실제 적용 조건 확인",
                description=(
                    "공식 공지의 모듈·기능·구성 조건이 서버에 해당하는지 확인하세요. "
                    "추가 확인 상태는 확정 취약 또는 안전을 뜻하지 않습니다."
                ),
                evidence_urls=urls,
            )
        )
    steps.append(
        ResponseStep(
            title="조치 후 다시 수집·비교",
            description=(
                "조치 후 패키지를 다시 수집하고 검증하세요. "
                "동일한 자료 기준으로 전후 분석을 비교해 변경 내용을 확인합니다."
            ),
            evidence_urls=urls,
        )
    )
    return Remediation(
        priority=priority,
        priority_reason=reason,
        target_version=finding.fixed_version,
        steps=steps,
        limitations=[
            "대응 우선순위는 검토 순서이며 취약 여부를 확정하지 않습니다.",
            "자동 패치·설정 변경·서비스 재시작은 실행하지 않습니다.",
            "공식 근거에 없는 특정 완화 명령을 생성하지 않습니다.",
        ],
    )
