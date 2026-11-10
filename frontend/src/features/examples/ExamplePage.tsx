import { useCallback } from "react";
import { useSession } from "../../app/session";
import { Icon } from "../../shared/components/Icon";
import { Notice } from "../../shared/components/Notice";
import { usePollingQuery } from "../../shared/hooks/usePollingQuery";
import { getAssessmentExample } from "./api";

const verdicts: Record<string, { label: string; style: string }> = {
  AFFECTED: { label: "영향 있음", style: "affected" },
  FIXED: { label: "수정됨", style: "fixed" },
  NOT_AFFECTED: { label: "영향 없음", style: "not-affected" },
  NEEDS_REVIEW: { label: "추가 확인", style: "needs-review" },
};
const processing: Record<string, string> = {
  EVALUATED: "판정 완료",
  OUT_OF_SCOPE: "범위 밖",
  NOT_INSTALLED: "미설치",
  NO_MATCHING_RECORD: "매칭 자료 없음",
  COLLECTION_FAILED: "수집 실패",
  PARTIAL_COLLECTION: "부분 수집",
};
const reasons: Record<string, string> = {
  MATCHED_AFFECTED_CONDITION: "가상 취약 조건에 해당",
  FIX_CONFIRMED: "가상 수정 버전 충족",
  OFFICIAL_NOT_AFFECTED: "명시적 비영향 근거",
  MISSING_FULL_VERSION: "전체 버전 확인 필요",
  UNKNOWN_ORIGIN: "설치 출처 확인 필요",
  MISSING_CONDITION: "추가 조건 확인 필요",
  UNSUPPORTED_RULE: "지원하지 않는 조건",
  CONFLICTING_EVIDENCE: "근거가 서로 다름",
  NO_OFFICIAL_EVIDENCE: "공식 근거 없음",
};

export function ExamplePage() {
  const { api } = useSession();
  const load = useCallback((signal: AbortSignal) => getAssessmentExample(api!, signal), [api]);
  const query = usePollingQuery(api ? load : null, null);
  const example = query.data;
  const packages = new Map(example?.inventory.packages.map((item) => [item.package_id, item]));

  return (
    <>
      <div className="example-banner" role="note">
        <span className="example-banner-label">가상 예제</span>
        <p>
          가상 패키지와 보안 자료로 구성된 예시입니다. 실제 자산을 수집하거나 취약점을 판정하지
          않습니다.
        </p>
      </div>
      <Notice error={query.error} />
      <section className="panel comparison-panel">
        <div className="panel-heading">
          <div>
            <div className="section-title">
              <h2>패키지별 판정 예시</h2>
              <span className="count">{example?.expected_findings.length ?? "—"}</span>
            </div>
            <p>가상 패키지·설치 버전별 판정 결과 및 근거</p>
          </div>
          <button className="secondary" disabled={!api || query.loading} onClick={query.refresh}>
            <Icon name="refresh" />
            {query.loading ? "불러오는 중…" : "새로고침"}
          </button>
        </div>
        {example ? (
          <>
            <dl className="example-meta">
              <div>
                <dt>예제 환경</dt>
                <dd>
                  {example.inventory.os.id} {example.inventory.os.version_id}{" "}
                  <span>{example.inventory.os.architecture}</span>
                </dd>
              </div>
              <div>
                <dt>패키지</dt>
                <dd>{example.inventory.packages.length}개</dd>
              </div>
              <div>
                <dt>보안 자료</dt>
                <dd>가상 공지 {example.feed.advisories.length}개</dd>
              </div>
            </dl>
            <div className="finding-grid">
              {example.expected_findings.map((finding) => {
                const verdict = finding.verdict ? verdicts[finding.verdict] : undefined;
                const label =
                  verdict?.label ??
                  (finding.verdict ||
                    processing[finding.processing_status] ||
                    finding.processing_status);
                const basis =
                  finding.comparison_basis === "BINARY"
                    ? "바이너리 패키지"
                    : finding.comparison_basis === "SOURCE"
                      ? "소스 패키지"
                      : "미확인";
                return (
                  <article className="finding-card" key={finding.finding_id}>
                    <div className="finding-top">
                      <span className="eyebrow">판정 예시</span>
                      <span className={`badge ${verdict?.style ?? "processing"}`}>
                        <i />
                        {label}
                      </span>
                    </div>
                    <h3>
                      {packages.get(finding.package_ref ?? "")?.binary_name ?? "패키지 미확인"}
                    </h3>
                    <p className="finding-cve mono">{finding.cve_id ?? "CVE 미확인"}</p>
                    <dl className="version-grid">
                      <div>
                        <dt>설치 버전</dt>
                        <dd className="mono">{finding.installed_version ?? "미확인"}</dd>
                      </div>
                      <div>
                        <dt>수정 버전</dt>
                        <dd className="mono">{finding.fixed_version ?? "미제공"}</dd>
                      </div>
                    </dl>
                    <div className="finding-reason">
                      <span>판정 사유</span>
                      <strong>
                        {finding.reason_codes?.map((code) => reasons[code] ?? code).join(", ") ||
                          "제공되지 않음"}
                      </strong>
                    </div>
                    <div className="finding-basis">
                      비교 기준 <span>{basis}</span>
                    </div>
                    <details className="evidence-details">
                      <summary>가상 근거 보기</summary>
                      <div>
                        {finding.evidence_refs?.map((evidence) => (
                          <blockquote key={evidence.document_version_id}>
                            <strong>{evidence.title}</strong>
                            <p>{evidence.excerpt}</p>
                            <small className="mono">{evidence.url}</small>
                          </blockquote>
                        ))}
                        {finding.limitations?.map((limit) => (
                          <p className="example-warning" key={limit}>
                            {limit}
                          </p>
                        ))}
                      </div>
                    </details>
                  </article>
                );
              })}
            </div>
          </>
        ) : (
          <div className="empty">
            <div className="empty-icon">
              <Icon name="example" />
            </div>
            <strong>
              {!api
                ? "API에 연결하면 시험 예제를 볼 수 있습니다"
                : query.loading
                  ? "예제를 불러오는 중입니다"
                  : "예제를 불러오지 못했습니다"}
            </strong>
            <p>
              {!api
                ? "서비스 연결이 필요합니다."
                : query.loading
                  ? "예제 조회 중…"
                  : "잠시 후 다시 시도해 주세요."}
            </p>
          </div>
        )}
      </section>
      {example && (
        <>
          <section className="panel example-panel">
            <div className="panel-heading">
              <div>
                <h2>응답 및 근거 예제</h2>
                <p>고정된 예시 설명이며 AI가 생성한 응답이 아닙니다.</p>
              </div>
              <span className="badge unavailable">가상 근거</span>
            </div>
            <div className="example-content">
              <p>{example.expected_answer.answer}</p>
              {example.expected_answer.citations.map((citation) => (
                <blockquote key={citation.document_version_id}>
                  <span className="eyebrow">인용 예시</span>
                  <strong>{citation.title}</strong>
                  <p>{citation.excerpt}</p>
                  <small className="mono">{citation.url}</small>
                </blockquote>
              ))}
              {example.expected_answer.warnings?.map((warning) => (
                <p key={warning} className="example-warning">
                  {warning}
                </p>
              ))}
            </div>
          </section>
          <section className="panel example-panel">
            <div className="panel-heading">
              <div>
                <h2>예제 원본 데이터</h2>
                <p>예제 입력 및 기대 결과</p>
              </div>
            </div>
            <div className="example-content data-details">
              {[
                ["자산 및 패키지 정보", example.inventory],
                ["보안 자료", example.feed],
                ["판정 예시", example.expected_findings],
                ["설명 예시", example.expected_answer],
              ].map(([title, value]) => (
                <details key={String(title)}>
                  <summary>{String(title)}</summary>
                  <pre>{JSON.stringify(value, null, 2)}</pre>
                </details>
              ))}
            </div>
          </section>
        </>
      )}
    </>
  );
}
