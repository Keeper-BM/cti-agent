import { useCallback } from "react";
import { useSession } from "../../app/session";
import { Notice } from "../../shared/components/Notice";
import { usePollingQuery } from "../../shared/hooks/usePollingQuery";
import { getAssessmentExample } from "./api";

const verdicts: Record<string, string> = {
  AFFECTED: "영향 있음",
  FIXED: "수정됨",
  NOT_AFFECTED: "영향 없음",
  NEEDS_REVIEW: "추가 확인",
};

const reasons: Record<string, string> = {
  MATCHED_AFFECTED_CONDITION: "시험 영향 조건과 일치",
  FIX_CONFIRMED: "시험 수정 조건 충족",
};

export function ExamplePage() {
  const { api } = useSession();
  const load = useCallback((signal: AbortSignal) => getAssessmentExample(api!, signal), [api]);
  const query = usePollingQuery(api ? load : null, null);
  const example = query.data;
  const packages = new Map(example?.inventory.packages.map((item) => [item.package_id, item]));

  return (
    <>
      <div className="scope-note example-note" role="note">
        <strong>시험 데이터</strong>
        <span>
          패키지·CVE·공지는 모두 가상이며 결과와 설명은 고정된 예제입니다. 실제 자산의 보안 상태를
          나타내지 않습니다.
        </span>
      </div>
      <Notice error={query.error} />
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>입력과 기대 판정</h2>
            <p>같은 CVE의 결과도 대상 패키지와 설치 버전을 구분해 표시합니다.</p>
          </div>
          <button className="secondary" disabled={!api || query.loading} onClick={query.refresh}>
            {query.loading ? "불러오는 중…" : "예제 다시 읽기"}
          </button>
        </div>
        {example ? (
          <>
            <dl className="example-meta">
              <div>
                <dt>환경</dt>
                <dd>
                  {example.inventory.os.id} {example.inventory.os.version_id} ·{" "}
                  {example.inventory.os.architecture}
                </dd>
              </div>
              <div>
                <dt>설치 패키지</dt>
                <dd>{example.inventory.packages.length}개</dd>
              </div>
              <div>
                <dt>정규화된 자료</dt>
                <dd>{example.feed.advisories.length}개 가상 공지</dd>
              </div>
            </dl>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>패키지 / CVE</th>
                    <th>설치 버전 / 수정 버전</th>
                    <th>기대 판정</th>
                    <th>비교 기준</th>
                  </tr>
                </thead>
                <tbody>
                  {example.expected_findings.map((finding) => (
                    <tr key={finding.finding_id}>
                      <td>
                        <strong>{packages.get(finding.package_ref ?? "")?.binary_name}</strong>
                        <small className="cell-sub">{finding.cve_id}</small>
                      </td>
                      <td className="mono">
                        {finding.installed_version ?? "미확인"}
                        <small className="cell-sub">
                          수정: {finding.fixed_version ?? "미제공"}
                        </small>
                      </td>
                      <td>
                        <span
                          className={`badge ${finding.verdict === "FIXED" ? "succeeded" : "failed"}`}
                        >
                          {verdicts[finding.verdict ?? ""] ?? finding.processing_status}
                        </span>
                        <small className="cell-sub">
                          {finding.reason_codes?.map((code) => reasons[code] ?? code).join(", ")}
                        </small>
                      </td>
                      <td>
                        {finding.comparison_basis === "BINARY" ? "바이너리 패키지" : "소스 패키지"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <div className="empty">
            <strong>
              {!api
                ? "API에 연결하면 시험 예제를 볼 수 있습니다"
                : query.loading
                  ? "예제를 불러오는 중입니다"
                  : "예제를 불러오지 못했습니다"}
            </strong>
            <p>외부 서버, GPU와 Worker가 없어도 확인할 수 있습니다.</p>
          </div>
        )}
      </section>
      {example && (
        <>
          <section className="panel example-panel">
            <div className="panel-heading">
              <div>
                <h2>설명과 근거 예제</h2>
                <p>고정된 기대 설명이며 AI가 생성한 응답이 아닙니다.</p>
              </div>
              <span className="badge">가상 근거</span>
            </div>
            <div className="example-content">
              <p>{example.expected_answer.answer}</p>
              {example.expected_answer.citations.map((citation) => (
                <blockquote key={citation.document_version_id}>
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
                <h2>예제 데이터</h2>
                <p>입력, 정규화 자료, 기대 결과의 연결을 확인합니다.</p>
              </div>
            </div>
            <div className="example-content">
              {[
                ["자산·패키지 입력", example.inventory],
                ["정규화된 보안 자료", example.feed],
                ["기대 판정 결과", example.expected_findings],
                ["기대 설명", example.expected_answer],
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
