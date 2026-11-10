import { useState } from "react";
import type { ReactNode } from "react";
import type { ReportContent } from "./api";
import { VerificationBody } from "../verifications/VerificationPanel";
import { RemediationPanel } from "../remediation/RemediationPanel";
import { ApacheRuntimeEvidence } from "../verifications/ApacheRuntimeEvidence";

export const reportTime = (value: string) =>
  new Date(value).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" });
const verdicts: Record<string, string> = {
  AFFECTED: "영향 있음",
  FIXED: "해당 CVE의 수정 기준 충족",
  NOT_AFFECTED: "공식 조건상 영향 없음",
  NEEDS_REVIEW: "추가 확인 필요",
};
const processing: Record<string, string> = {
  EVALUATED: "평가됨",
  OUT_OF_SCOPE: "지원 범위 밖",
  NOT_INSTALLED: "입력 목록에 없음",
  NO_MATCHING_RECORD: "대조 자료 없음",
  COLLECTION_FAILED: "수집 실패",
  PARTIAL_COLLECTION: "설치 여부 미확인",
};
const comparisons: Record<string, string> = {
  BELOW_FIX: "수정 기준보다 낮음",
  MEETS_FIX: "수정 기준 이상",
  UNAVAILABLE: "비교 불가",
};
const kev: Record<string, string> = {
  LISTED: "악용 목록 등재",
  NOT_LISTED: "저장 목록에 미등재",
  NOT_FETCHED: "악용 자료 미수집",
};
const origins: Record<string, string> = {
  USER_DECLARED: "사용자 입력 · 미검증",
  UNKNOWN: "미확인",
  UNSUPPORTED: "지원하지 않는 출처",
  SUPPORTED_ORIGIN: "출처 확인됨",
  VERIFIED_LAB: "시험 환경에서 확인됨",
  OFFICIAL_MATCH: "공식 배포본 파일 일치",
};

function SafeLink({ url, children }: { url: string | null; children: ReactNode }) {
  let safe = false;
  try {
    const target = new URL(url ?? "");
    safe = ["https:", "http:"].includes(target.protocol) && !target.username && !target.password;
  } catch {
    /* Render an unavailable address as text. */
  }
  return safe ? (
    <a href={url!} target="_blank" rel="noreferrer">
      {children}
    </a>
  ) : (
    <span>{children} (주소 미제공)</span>
  );
}

export function ReportPages({
  page,
  total,
  size,
  setPage,
  label,
}: {
  page: number;
  total: number;
  size: number;
  setPage: (page: number) => void;
  label: string;
}) {
  return (
    <div className="analysis-pages" aria-label={label}>
      <button
        className="secondary"
        disabled={page === 0}
        onClick={() => setPage(page - 1)}
        aria-label={`${label} 이전`}
      >
        이전
      </button>
      <span>
        {page + 1} / {Math.max(1, Math.ceil(total / size))}
      </span>
      <button
        className="secondary"
        disabled={(page + 1) * size >= total}
        onClick={() => setPage(page + 1)}
        aria-label={`${label} 다음`}
      >
        다음
      </button>
    </div>
  );
}

function Counts({
  title,
  labels,
  values,
}: {
  title: string;
  labels: Record<string, string>;
  values: Record<string, number>;
}) {
  return (
    <div className="report-count-group">
      <h4>{title}</h4>
      <dl>
        {Object.entries(labels).map(([key, label]) => (
          <div key={key}>
            <dt>{label}</dt>
            <dd>{values[key] ?? 0}건</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function ReportPreview({ content }: { content: ReportContent }) {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [packagePage, setPackagePage] = useState(0);
  const [aiPage, setAIPage] = useState(0);
  const [findingId, setFindingId] = useState("");
  const matches = content.findings.filter((f) =>
    `${f.cve_id ?? ""} ${f.package_name ?? ""}`.toLowerCase().includes(search.trim().toLowerCase()),
  );
  const finding = content.findings.find((f) => f.finding_id === findingId);
  return (
    <div className="report-preview" aria-label="저장된 보고서 미리보기">
      <header className="report-cover">
        <span className="report-eyebrow">CTI AGENT · 대응 보고서</span>
        <h2>{content.asset_name}</h2>
        <p>
          Ubuntu {content.os.version_id} · 분석 완료 {reportTime(content.analysis_completed_at)}
        </p>
        <p className="report-frozen">
          자료 고정 {reportTime(content.frozen_at)} · 생성{" "}
          {content.generated_at ? reportTime(content.generated_at) : "처리 중"}
        </p>
      </header>
      {content.is_synthetic && (
        <div className="report-synthetic">가상 입력 보고서 · 실제 서버의 보안 상태가 아닙니다.</div>
      )}
      <div className="report-intro">
        <p>
          버전 비교와 영향 판정은 별도 항목입니다. 최종 판단에는 적용 조건과 추가 확인 사유가
          반영됩니다.
        </p>
        <p>
          보고서 전체를 저장했습니다. 아래 검색·페이지 이동은 미리보기에만 적용되며 다운로드
          파일에는 전체 내용이 포함됩니다.
        </p>
      </div>
      <section className="report-section">
        <h3>분석 요약</h3>
        <div className="report-stats">
          {[
            ["입력 패키지", content.summary.package_count],
            ["패키지별 결과", content.summary.finding_count],
            ["CVE (중복 제외)", content.summary.cve_count],
            ["KEV 등재 CVE", content.summary.kev_listed_cve_count],
          ].map(([name, n]) => (
            <div key={String(name)}>
              <span>{name}</span>
              <strong>
                {n}
                <small>건</small>
              </strong>
            </div>
          ))}
        </div>
        <div className="report-counts">
          <Counts
            title="버전 비교"
            labels={comparisons}
            values={content.summary.comparison_counts}
          />
          <Counts title="최종 판단" labels={verdicts} values={content.summary.verdict_counts} />
          <Counts
            title="처리 상태"
            labels={processing}
            values={content.summary.processing_counts}
          />
        </div>
        <p className="report-caption">
          동일 CVE가 여러 패키지에 연결되면 결과 수와 CVE 수는 다릅니다. ‘대조 자료 없음’ 등의 처리
          상태에는 취약 여부 판정값이 없습니다.
        </p>
      </section>
      <section className="report-section">
        <h3>분석 범위 및 제한 사항</h3>
        <ul>
          {content.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      </section>
      <section className="report-section">
        <h3>입력 패키지</h3>
        <p>
          패키지 확인 {reportTime(content.collected_at)} · 입력 {reportTime(content.ingested_at)} ·{" "}
          {content.package_list_complete ? "전체 목록으로 선언" : "부분 입력"} ·{" "}
          {content.os.architecture ?? "아키텍처 미확인"}
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>바이너리 / 설치 버전</th>
                <th>소스 / 버전</th>
                <th>출처 확인 수준</th>
              </tr>
            </thead>
            <tbody>
              {content.packages.slice(packagePage * 20, (packagePage + 1) * 20).map((p) => (
                <tr key={p.package_id}>
                  <td>
                    {p.binary_name}
                    <small>{p.binary_version ?? "미제공"}</small>
                  </td>
                  <td>
                    {p.source_name ?? "미확인"}
                    <small>{p.source_version ?? "미제공"}</small>
                  </td>
                  <td>
                    {origins[p.origin_status]}
                    <small>{p.architecture ?? "아키텍처 미제공"}</small>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {content.packages.length > 20 && (
          <ReportPages
            label="보고서 패키지"
            page={packagePage}
            total={content.packages.length}
            size={20}
            setPage={setPackagePage}
          />
        )}
      </section>
      <section className="report-section">
        {content.verification && (
          <>
            <h3>공식 패키지 파일 검증</h3>
            <VerificationBody evidence={content.verification} />
          </>
        )}
        <h3>CVE별 결과와 근거</h3>
        <label className="report-search">
          보고서 내 패키지·CVE 검색
          <input
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(0);
              setFindingId("");
            }}
            placeholder="패키지명 또는 CVE 번호"
            maxLength={200}
          />
        </label>
        <div className="table-wrap">
          <table className="report-findings">
            <thead>
              <tr>
                <th>패키지 / CVE</th>
                <th>버전 비교</th>
                <th>최종 판단·처리 상태</th>
                <th>위험 정보</th>
                <th>상세</th>
              </tr>
            </thead>
            <tbody>
              {matches.slice(page * 20, (page + 1) * 20).map((f) => (
                <tr key={f.finding_id}>
                  <td>
                    {f.package_name ?? "전체 입력"}
                    <small>{f.cve_id ?? "패키지 처리 상태"}</small>
                  </td>
                  <td>
                    {comparisons[f.version_comparison]}
                    <small>대조: {f.installed_version ?? "미제공"}</small>
                    <small>수정: {f.fixed_version ?? "미제공"}</small>
                  </td>
                  <td>{f.verdict ? verdicts[f.verdict] : processing[f.processing_status]}</td>
                  <td>
                    {f.cve_id ? kev[f.kev_status] : "해당 없음"}
                    <small>
                      {[
                        ...new Set(
                          (f.nvd_metrics ?? [])
                            .filter((m) => m.score != null)
                            .map((m) => `CVSS ${m.version}: ${m.score}`),
                        ),
                      ].join(" · ") || "CVSS 점수 미제공"}
                    </small>
                  </td>
                  <td>
                    <button
                      className="secondary"
                      aria-label={`${f.package_name ?? "입력"} ${f.cve_id ?? f.processing_status} 보고서 근거`}
                      onClick={() => setFindingId(f.finding_id)}
                    >
                      근거
                    </button>
                  </td>
                </tr>
              ))}
              {!matches.length && (
                <tr>
                  <td colSpan={5}>
                    검색 조건에 맞는 결과가 없습니다. 다운로드는 전체 결과를 포함합니다.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <ReportPages
          label="보고서 결과"
          page={page}
          total={matches.length}
          size={20}
          setPage={(p) => {
            setPage(p);
            setFindingId("");
          }}
        />
        {finding && (
          <div className="report-finding-detail" role="region" aria-label="보고서에 고정된 근거">
            <div className="source-evidence-heading">
              <h4>
                {finding.cve_id ?? "처리 상태"} · {finding.package_name}
              </h4>
              <button className="secondary" onClick={() => setFindingId("")}>
                근거 닫기
              </button>
            </div>
            <p>
              {finding.verdict ? verdicts[finding.verdict] : processing[finding.processing_status]}{" "}
              · {comparisons[finding.version_comparison]}
            </p>
            <p>
              바이너리: {finding.binary_version ?? "미제공"} · 소스:{" "}
              {finding.source_package ?? "미확인"} · 대조: {finding.installed_version ?? "미제공"} (
              {finding.comparison_basis ?? "대조 없음"}) · 수정: {finding.fixed_version ?? "미제공"}
            </p>
            <p>출처: {finding.origin_status ? origins[finding.origin_status] : "미확인"}</p>
            <ul>
              {[...(finding.reasons ?? []), ...(finding.limitations ?? [])].map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
            {finding.remediation && <RemediationPanel value={finding.remediation} />}
            {finding.runtime_evidence && (
              <ApacheRuntimeEvidence evidence={finding.runtime_evidence} />
            )}
            {(finding.nvd_metrics ?? []).map((m, i) => (
              <p key={i}>
                CVSS {m.version} · {m.score ?? "점수 미제공"} · {m.provider ?? "공급자 미제공"}
                <br />
                {m.vector}
              </p>
            ))}
            {(finding.evidence_refs ?? []).map((e, i) => (
              <div key={i} className="report-evidence">
                <SafeLink url={e.url}>
                  {e.source} · {e.title}
                </SafeLink>
                <p>{e.excerpt}</p>
                <small>원문 {e.document_version_id}</small>
              </div>
            ))}
            {!finding.evidence_refs?.length && (
              <p>대조할 공식 근거가 없습니다. 안전을 의미하지 않습니다.</p>
            )}
            <details>
              <summary>규칙·결과 식별 정보</summary>
              <p>
                규칙 {finding.matched_rule_id ?? "없음"} · {finding.ruleset_version}
                <br />
                결과 {finding.finding_id}
              </p>
            </details>
          </div>
        )}
      </section>
      <section className="report-section">
        <h3>AI Summary · {content.explanations.length}건</h3>
        <p>
          {content.include_ai_explanations
            ? "자료 고정 시점의 최신 저장 요약입니다. 보고서 생성 시 추가 요약은 생성하지 않습니다."
            : "AI Summary 미포함 보고서입니다."}
        </p>
        {content.include_ai_explanations && !content.explanations.length && (
          <p>자료 고정 시점에 생성 완료된 AI Summary가 없습니다.</p>
        )}
        {content.explanations.slice(aiPage * 5, (aiPage + 1) * 5).map((e) => (
          <details className="report-ai" key={e.id}>
            <summary>
              {e.result.facts.package_name} · {e.result.facts.cve_id} · {reportTime(e.completed_at)}
            </summary>
            <p>
              {e.model} · 생성 규칙 {e.prompt_version} · 요약 {e.id}
            </p>
            <h4>취약점 개요 (AI 생성)</h4>
            <p>{e.result.meaning.text}</p>
            <small>인용 {e.result.meaning.evidence_ids.join(", ")}</small>
            <h4>패키지 분석 결과 (분석 원본)</h4>
            <p>{e.result.assessment_text}</p>
            <ul>
              {e.result.assessment_reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
            <h4>권고 조치 (AI 생성)</h4>
            <ul>
              {e.result.next_steps.map((s, i) => (
                <li key={i}>
                  {s.text} <small>인용 {s.evidence_ids.join(", ")}</small>
                </li>
              ))}
            </ul>
            <h4>제한 사항</h4>
            <ul>
              {e.result.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
            <h4>참조 근거</h4>
            {e.result.citations.map((c) => (
              <details key={c.id}>
                <summary>
                  {c.id} · {c.title}
                </summary>
                <p>
                  기준 {reportTime(c.captured_at)}
                  {c.truncated ? " · 일부 발췌" : ""}
                </p>
                <pre>{c.excerpt}</pre>
                {c.url && <SafeLink url={c.url}>공식 출처</SafeLink>}
                <p className="mono">
                  원문 {c.document_id ?? "분석 자체"}
                  <br />
                  SHA-256 {c.sha256 ?? "해당 없음"}
                </p>
              </details>
            ))}
            <p className="mono">요약 입력 SHA-256 {e.context_sha256}</p>
          </details>
        ))}
        {content.explanations.length > 5 && (
          <ReportPages
            label="보고서 AI Summary"
            page={aiPage}
            total={content.explanations.length}
            size={5}
            setPage={setAIPage}
          />
        )}
      </section>
      <section className="report-section">
        <h3>공식 자료와 재현 정보</h3>
        <p>
          아래는 이 보고서에 고정된 출처입니다. 외부 링크의 현재 내용은 저장 당시와 다를 수
          있습니다.
        </p>
        <details>
          <summary>
            출처 기준본 {content.sources.length}개 · 원문 {content.documents.length}개
          </summary>
          {content.sources.map((s) => (
            <div className="report-source" key={s.id}>
              <strong>
                {s.source_id} / {s.scope_key}
              </strong>
              <p>
                수집 {reportTime(s.captured_at)} · 해석 버전 {s.adapter_version}
              </p>
              <small>기준본 {s.id}</small>
              {content.documents
                .filter((d) => d.snapshot_id === s.id)
                .map((d) => (
                  <div key={d.id}>
                    <SafeLink url={d.url}>공식 수집 출처</SafeLink>
                    <p className="mono">
                      원문 {d.id}
                      <br />
                      수집 {reportTime(d.captured_at)}
                      <br />
                      SHA-256 {d.sha256}
                    </p>
                  </div>
                ))}
            </div>
          ))}
        </details>
        <dl className="report-identifiers">
          <div>
            <dt>분석</dt>
            <dd>{content.analysis_id}</dd>
          </div>
          <div>
            <dt>패키지 입력</dt>
            <dd>{content.inventory_id}</dd>
          </div>
          <div>
            <dt>판정용 자료</dt>
            <dd>{content.feed_snapshot_id}</dd>
          </div>
          <div>
            <dt>규칙·보고서 양식</dt>
            <dd>
              {content.ruleset_version} / {content.template_version}
            </dd>
          </div>
        </dl>
      </section>
    </div>
  );
}
