import { useCallback, useState, Fragment } from "react";
import { Icon } from "../../shared/components/Icon";
import { Notice } from "../../shared/components/Notice";
import { usePollingQuery } from "../../shared/hooks/usePollingQuery";
import { useAction } from "../../shared/hooks/useAction";
import type { HttpClient } from "../../api/client";
import { listFindings, type Finding } from "../findings/api";
import { downloadReport } from "../reports/api";
import { count, shortTime, type Brief } from "./api";

const verdicts: Record<string, string> = {
  AFFECTED: "영향 있음",
  NEEDS_REVIEW: "추가 확인 필요",
  FIXED: "수정 기준 충족",
  NOT_AFFECTED: "영향 없음",
  OUT_OF_SCOPE: "지원 범위 밖",
  NO_MATCHING_RECORD: "대조 자료 없음",
  NOT_INSTALLED: "입력 목록에 없음",
  PARTIAL_COLLECTION: "일부 수집",
  COLLECTION_FAILED: "수집 실패",
};
const metrics = [
  { key: "AFFECTED", icon: "alert", tone: "red" },
  { key: "NEEDS_REVIEW", icon: "scope", tone: "amber" },
  { key: "FIXED", icon: "shield", tone: "teal" },
] as const;

export function FindingsList({
  api,
  analysisId,
  filter,
}: {
  api: HttpClient;
  analysisId: string;
  filter: string;
}) {
  const [page, setPage] = useState(0);
  const [open, setOpen] = useState("");
  const load = useCallback(
    (signal: AbortSignal) =>
      listFindings(
        api,
        {
          analysis_id: analysisId,
          limit: "5",
          offset: String(page * 5),
          ...(filter === "actionable"
            ? { actionable: "true" }
            : filter === "outside"
              ? { processing_status: "OUT_OF_SCOPE" }
              : filter === "all"
                ? { processing_status: "EVALUATED" }
                : { verdict: filter }),
        },
        signal,
      ),
    [api, analysisId, page, filter],
  );
  const result = usePollingQuery(load, null);
  return (
    <div className="find-list">
      <Notice error={result.error} />
      <div className="work-table" role="table" aria-label="패키지별 판정 결과">
        <div className="work-tr work-th" role="row">
          <span role="columnheader">패키지 / CVE</span>
          <span role="columnheader">대조 버전</span>
          <span role="columnheader">최종 판단</span>
          <span role="columnheader" className="sr-only">
            상세 근거
          </span>
        </div>
        {result.data?.items.map((f) => (
          <Fragment key={f.finding_id}>
            <div role="row" className={`work-tr ${open === f.finding_id ? "expanded" : ""}`}>
              <span role="cell">
                <b>{f.package_name ?? "패키지 미확인"}</b>
                <small>{f.cve_id ?? "CVE 미지정"}</small>
              </span>
              <span role="cell" className="version-cell">
                <samp>{f.installed_version ?? f.binary_version ?? "미확인"}</samp>
                <small>수정 {f.fixed_version ?? "기준 없음"}</small>
              </span>
              <span role="cell">
                <span className={`decision ${f.verdict?.toLowerCase() ?? "neutral"}`}>
                  {verdicts[f.verdict ?? f.processing_status] ?? f.processing_status}
                </span>
              </span>
              <span role="cell">
                <button
                  className="row-toggle"
                  aria-expanded={open === f.finding_id}
                  aria-label={`${f.package_name} ${f.cve_id ?? ""} 근거 ${open === f.finding_id ? "닫기" : "보기"}`}
                  onClick={() => setOpen(open === f.finding_id ? "" : f.finding_id)}
                >
                  <Icon name="chevron" />
                </button>
              </span>
            </div>
            {open === f.finding_id && (
              <div role="row">
                <div role="cell" className="row-evidence">
                  <Evidence finding={f} />
                </div>
              </div>
            )}
          </Fragment>
        ))}
      </div>
      {result.data?.items.length === 0 && (
        <p className="quiet-empty">이 분류에 해당하는 결과가 없습니다.</p>
      )}
      {!result.data && !result.error && (
        <p className="quiet-empty" role="status">
          판정 결과를 불러오는 중…
        </p>
      )}
      {result.data && result.data.total > 5 && (
        <div className="work-pager">
          <span>
            전체 {count(result.data.total)}건 · {page + 1} / {Math.ceil(result.data.total / 5)}
          </span>
          <button
            disabled={!page}
            onClick={() => {
              setPage(page - 1);
              setOpen("");
            }}
          >
            이전
          </button>
          <button
            disabled={(page + 1) * 5 >= result.data.total}
            onClick={() => {
              setPage(page + 1);
              setOpen("");
            }}
          >
            다음
          </button>
        </div>
      )}
    </div>
  );
}
function Evidence({ finding: f }: { finding: Finding }) {
  return (
    <>
      <strong>판정 근거</strong>
      {f.reasons?.map((reason) => (
        <p key={reason}>{reason}</p>
      ))}
      {f.remediation && (
        <>
          <strong>권고 조치</strong>
          {f.remediation.steps.slice(0, 2).map((s) => (
            <p key={s.title}>
              {s.title} · {s.description}
            </p>
          ))}
        </>
      )}
      {(f.evidence_refs ?? []).map((e) => (
        <a key={e.document_version_id} href={e.url} target="_blank" rel="noreferrer">
          {e.source} 공식 근거 <Icon name="external" />
        </a>
      ))}
    </>
  );
}
export function Results({
  api,
  analysis,
  previous,
}: {
  api: HttpClient;
  analysis: Brief;
  previous: boolean;
}) {
  const [filter, setFilter] = useState("actionable");
  const [outside, setOutside] = useState(false);
  const action = useAction();
  const totals = analysis.summary;
  const out = totals.OUT_OF_SCOPE ?? 0;
  async function download() {
    if (!analysis.report_id) return;
    const id = analysis.report_id;
    await action.run(async () => {
      const text = await downloadReport(api, id);
      const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `cti-report-${id}.md`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }, "보고서 다운로드를 요청했습니다.");
  }
  return (
    <>
      <div className="result-heading">
        <div>
          <h2>{previous ? "이전 분석 결과" : "분석 결과"}</h2>
          <span>
            {shortTime(analysis.completed_at)} 기준 · 패키지와 CVE 조합별 집계
            {analysis.is_synthetic ? " · 가상 입력" : ""}
          </span>
        </div>
        {analysis.report_id && (
          <button
            className="button-link download-link"
            disabled={action.pending}
            onClick={download}
          >
            <Icon name="download" />
            보고서 다운로드
          </button>
        )}
      </div>
      <Notice error={action.error} success={action.notice} />
      <div className="result-metrics">
        {metrics.map((m) => (
          <button
            className={`metric-tile ${m.tone}`}
            key={m.key}
            aria-pressed={filter === m.key}
            onClick={() => setFilter(filter === m.key ? "actionable" : m.key)}
          >
            <span>
              <i>
                <Icon name={m.icon} />
              </i>
              {verdicts[m.key]}
            </span>
            <b>
              {count(totals[m.key] ?? 0)}
              <small>건</small>
            </b>
          </button>
        ))}
      </div>
      <section className="work-card priority-card">
        <div className="card-top">
          <h3>우선 조치 항목</h3>
          <label className="filter-select">
            <span className="sr-only">결과 분류</span>
            <select value={filter} onChange={(e) => setFilter(e.target.value)}>
              <option value="actionable">조치 대상</option>
              {metrics.map((m) => (
                <option key={m.key} value={m.key}>
                  {verdicts[m.key]}
                </option>
              ))}
              <option value="all">평가된 결과 전체</option>
            </select>
          </label>
        </div>
        <FindingsList key={filter} api={api} analysisId={analysis.id} filter={filter} />
        {out > 0 && (
          <div className="outside-block">
            <button aria-expanded={outside} onClick={() => setOutside(!outside)}>
              지원 범위 밖 <b>{count(out)}건</b>
              <Icon name="chevron" />
            </button>
            {outside && <FindingsList api={api} analysisId={analysis.id} filter="outside" />}
          </div>
        )}
        <div className="result-links">
          <a href={`#/findings?analysis=${analysis.id}`}>
            <Icon name="findings" />
            전체 분석 근거
          </a>
          <a href={`#/questions?analysis=${analysis.id}`}>
            <Icon name="insights" />이 분석에 질문
          </a>
          {analysis.report_id && (
            <a href={`#/reports?analysis=${analysis.id}&report=${analysis.report_id}`}>
              <Icon name="reports" />
              보고서 보기
            </a>
          )}
        </div>
      </section>
    </>
  );
}
