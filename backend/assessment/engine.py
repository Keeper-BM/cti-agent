"""Deterministic rules over frozen inputs. Never query a network or call a model."""

from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID, uuid4, uuid5

from backend.assessment.contracts import (
    BINARY_SOURCES,
    MAX_FINDINGS,
    PACKAGES,
    RELEASES,
    RULESET_VERSION,
    AssessmentFinding,
)
from backend.assessment.debian_version import compare_versions
from backend.assessment.runtime import http2_condition_evidence
from backend.core.errors import AppError
from backend.models.contracts import FeedSnapshot, InventorySnapshot
from backend.models.enums import OriginStatus, ProcessingStatus, ReasonCode, Verdict


def source_for(package):
    return package.source_name or BINARY_SOURCES.get(package.binary_name)


class UbuntuAssessmentEngine:
    def assess(
        self,
        inventory: InventorySnapshot,
        feed: FeedSnapshot,
        *,
        analysis_id: UUID | None = None,
        evaluated_at: datetime | None = None,
        expected_release: str | None = None,
        rejected_cves: set[str] | None = None,
    ) -> list[AssessmentFinding]:
        analysis_id = analysis_id or uuid4()
        evaluated_at = evaluated_at or datetime.now(UTC)
        findings = []
        rules = defaultdict(list)
        for advisory in feed.advisories:
            for rule in advisory.rules:
                rules[rule.package_name].append((advisory, rule))

        def append(package=None, source=None, advisory=None, rule=None, status="EVALUATED"):
            if len(findings) >= MAX_FINDINGS:
                raise AppError("ANALYSIS_LIMIT", "분석 결과가 20,000건을 초과합니다.", 422)
            identity = (
                f"{package.package_id if package else source}:{rule.rule_id if rule else status}"
            )
            finding = AssessmentFinding(
                finding_id=uuid5(analysis_id, identity),
                analysis_id=analysis_id,
                asset_id=inventory.asset_id,
                inventory_id=inventory.inventory_id,
                package_ref=package.package_id if package else None,
                package_name=package.binary_name if package else source,
                source_package=source,
                binary_version=package.binary_version if package else None,
                architecture=package.architecture if package else None,
                origin_status=package.origin_status if package else None,
                origin_evidence_ref=package.origin_evidence_ref if package else None,
                installed_version=(
                    package.source_version
                    if rule and rule.package_kind == "SOURCE"
                    else package.binary_version
                    if package
                    else None
                ),
                comparison_basis=rule.package_kind if rule else None,
                cve_id=advisory.cve_id if advisory else None,
                matched_rule_id=rule.rule_id if rule else None,
                processing_status=status,
                verdict=Verdict.NEEDS_REVIEW if status == "EVALUATED" else None,
                fixed_version=rule.fixed_version if rule else None,
                evidence_refs=advisory.evidence_refs if advisory else [],
                evaluated_at=evaluated_at,
                ruleset_version=RULESET_VERSION,
                feed_snapshot_id=feed.feed_snapshot_id,
                limitations=list(rule.limitations) if rule else [],
            )
            findings.append(finding)
            return finding

        if inventory.collection_status == "FAILED":
            result = append(status="COLLECTION_FAILED")
            result.reasons = ["패키지 수집이 실패해 분석할 수 없습니다."]
            return findings

        present = set()
        supported_os = inventory.os.id == "ubuntu" and inventory.os.version_id in RELEASES
        for package in sorted(inventory.packages, key=lambda p: (p.binary_name, str(p.package_id))):
            source = source_for(package)
            installed = package.install_status == "installed"
            if installed and source in PACKAGES:
                present.add(source)
            if not supported_os or source not in PACKAGES or not installed:
                result = append(package, source, status="OUT_OF_SCOPE")
                result.reasons = [
                    "지원 범위는 Ubuntu 22.04·24.04의 설치된 apache2·mysql-8.0 소스 패키지입니다."
                ]
                continue
            matching = [
                (a, r)
                for a, r in rules[source]
                if r.os_id == inventory.os.id and r.release == inventory.os.version_id
            ]
            if not matching:
                result = append(package, source, status="NO_MATCHING_RECORD")
                result.reason_codes = [ReasonCode.NO_OFFICIAL_EVIDENCE]
                result.reasons = [
                    "이 릴리스·패키지에 대조할 Ubuntu 자료가 없습니다. 안전을 뜻하지 않습니다."
                ]
                continue
            for advisory, rule in sorted(
                matching, key=lambda item: (item[0].cve_id, str(item[1].rule_id))
            ):
                result = append(package, source, advisory, rule)
                blockers = []

                def block(code, message, blockers=blockers, result=result):
                    blockers.append(code)
                    result.reasons.append(message)

                if (
                    package.origin_status
                    not in {
                        OriginStatus.SUPPORTED_ORIGIN,
                        OriginStatus.VERIFIED_LAB,
                        OriginStatus.OFFICIAL_MATCH,
                    }
                    or not package.origin_evidence_ref
                ):
                    block(
                        ReasonCode.UNKNOWN_ORIGIN,
                        "Ubuntu 공식 패키지의 설치 출처를 확인하지 못했습니다.",
                    )
                if expected_release and expected_release != inventory.os.version_id:
                    block(
                        ReasonCode.CONFLICTING_EVIDENCE,
                        "자산의 예상 OS와 입력된 OS 릴리스가 다릅니다.",
                    )
                if advisory.cve_id in (rejected_cves or set()):
                    block(ReasonCode.CONFLICTING_EVIDENCE, "고정한 NVD 자료에서 기각된 CVE입니다.")
                expected_source = BINARY_SOURCES.get(package.binary_name)
                if (
                    expected_source
                    and package.source_name
                    and expected_source != package.source_name
                ):
                    block(
                        ReasonCode.CONFLICTING_EVIDENCE,
                        "바이너리와 소스 패키지의 대응이 상충합니다.",
                    )
                if rule.package_kind == "SOURCE" and package.source_name != rule.package_name:
                    block(ReasonCode.MISSING_CONDITION, "소스 패키지명이 확인되지 않았습니다.")
                if rule.package_kind != "SOURCE":
                    block(ReasonCode.UNSUPPORTED_RULE, "현재 엔진은 소스 패키지 규칙만 지원합니다.")
                if rule.architecture and rule.architecture != package.architecture:
                    block(
                        ReasonCode.MISSING_CONDITION,
                        "공식 조건과 설치 아키텍처가 일치하는지 확인해야 합니다.",
                    )

                version_valid = False
                if not result.installed_version:
                    block(
                        ReasonCode.MISSING_FULL_VERSION,
                        "대조에 필요한 전체 패키지 버전이 없습니다.",
                    )
                else:
                    try:
                        compare_versions(result.installed_version, result.installed_version)
                        version_valid = True
                    except ValueError:
                        block(
                            ReasonCode.MISSING_FULL_VERSION,
                            "설치 버전이 Debian 버전 형식에 맞지 않습니다.",
                        )

                candidate = None
                if rule.status == "FIX_RELEASED" and version_valid:
                    try:
                        comparison = compare_versions(result.installed_version, rule.fixed_version)
                        result.version_comparison = "BELOW_FIX" if comparison < 0 else "MEETS_FIX"
                        result.reasons.insert(
                            0,
                            "소스 버전이 공식 수정 기준보다 낮습니다."
                            if comparison < 0
                            else "소스 버전이 공식 수정 기준과 같거나 높습니다.",
                        )
                        candidate = Verdict.AFFECTED if comparison < 0 else Verdict.FIXED
                    except ValueError:
                        block(ReasonCode.UNSUPPORTED_RULE, "공식 수정 버전을 비교할 수 없습니다.")
                elif rule.status == "NOT_AFFECTED":
                    candidate = Verdict.NOT_AFFECTED
                elif rule.status == "AFFECTED":
                    candidate = Verdict.AFFECTED
                elif rule.status == "UNKNOWN":
                    block(
                        ReasonCode.UNSUPPORTED_RULE,
                        "철회·복잡한 범위·수정 정보 부족으로 자동 판정할 수 없습니다.",
                    )
                # A source package range alone does not verify enabled components/configuration.
                if rule.runtime_condition and candidate != Verdict.FIXED:
                    runtime = http2_condition_evidence(inventory, package, advisory, rule)
                    if runtime and candidate == Verdict.AFFECTED:
                        result.runtime_evidence = runtime
                        result.reasons.append(
                            "공식 apache2-bin 파일과 연결된 실행 프로세스에서 HTTP/2 모듈과 "
                            "루프백 HTTP/2 응답을 확인해 이 CVE의 적용 조건을 충족했습니다."
                        )
                        result.limitations.append(
                            "관측 시점의 로컬 서비스 적용 판단입니다. "
                            "서비스 거부 공격이나 외부 네트워크 노출은 시험하지 않았습니다."
                        )
                    else:
                        block(
                            ReasonCode.MISSING_CONDITION,
                            "이 CVE의 실행 파일·HTTP/2 모듈·응답 조건을 확인하지 못했습니다.",
                        )
                if rule.limitations and candidate != Verdict.FIXED:
                    block(
                        ReasonCode.MISSING_CONDITION,
                        "제품의 컴포넌트·설정 등 추가 영향 조건을 확인해야 합니다.",
                    )
                same_cve_rules = [r for a, r in matching if a.cve_id == advisory.cve_id]
                if len({(r.status, r.fixed_version, r.package_kind) for r in same_cve_rules}) > 1:
                    block(
                        ReasonCode.CONFLICTING_EVIDENCE, "동일 CVE의 공식 패키지 규칙이 상충합니다."
                    )
                result.reason_codes = list(dict.fromkeys(blockers))
                if not blockers and candidate:
                    result.verdict = candidate
                    result.reason_codes = [
                        {
                            Verdict.FIXED: ReasonCode.FIX_CONFIRMED,
                            Verdict.AFFECTED: ReasonCode.MATCHED_AFFECTED_CONDITION,
                            Verdict.NOT_AFFECTED: ReasonCode.OFFICIAL_NOT_AFFECTED,
                        }[candidate]
                    ]
                result.model_validate(result.model_dump())

        if supported_os:
            for source in sorted(PACKAGES - present):
                identities_known = all(
                    p.install_status == "not-installed"
                    or (p.install_status == "installed" and source_for(p) is not None)
                    for p in inventory.packages
                )
                complete = inventory.coverage.package_list_complete and identities_known
                result = append(
                    source=source,
                    status=(
                        ProcessingStatus.NOT_INSTALLED
                        if complete
                        else ProcessingStatus.PARTIAL_COLLECTION
                    ),
                )
                result.reasons = [
                    "완전한 것으로 선언된 입력 목록에 해당 대상이 없습니다."
                    if complete
                    else "목록·패키지 식별 정보가 부족해 설치 여부를 판단할 수 없습니다."
                ]
        return findings
