import { useCallback, useEffect, useRef, useState } from "react";
import { useSession } from "../../app/session";
import { Icon } from "../../shared/components/Icon";
import { Notice } from "../../shared/components/Notice";
import { formatKst } from "../../shared/format";
import { useAction } from "../../shared/hooks/useAction";
import { usePollingQuery } from "../../shared/hooks/usePollingQuery";
import { findingLink } from "../findings/api";
import { saveMarkdown } from "../reports/download";
import { ReportPages } from "../reports/ReportPreview";
import { count, reportLink, workspaceLink } from "../workflows/api";
import { SourceRefresh } from "../workflows/SourceRefresh";
import { BatchComparison } from "./BatchComparison";
import {
  batchLink,
  coverageLabels,
  downloadBatch,
  getBatch,
  listBatches,
  retryBatch,
  retryBatchReport,
  type Batch,
} from "./api";

const batchStates = {
  RUNNING: "분석 진행 중",
  COMPLETED: "분석 완료",
  PARTIAL: "일부 분석 실패",
  FAILED: "분석 실패",
};

function batchState(batch: Batch) {
  if (batch.status === "COMPLETED") {
    if (!batch.evaluated_cve_count) return "평가 결과 없음";
    if (batch.assets.some((asset) => asset.coverage !== "EVALUATED")) return "일부 미평가";
  }
  return batchStates[batch.status];
}

const stages = {
  inventory: "패키지 수집",
  sources: "공식 자료 갱신",
  analysis: "취약점 분석",
  report: "보고서 생성",
};

export function BatchHistory() {
  const { api, canWrite } = useSession();
  const [page, setPage] = useState(0);
  const load = useCallback((signal: AbortSignal) => listBatches(api!, page, signal), [api, page]);
  const query = usePollingQuery(api ? load : null);
  if (!query.data?.items.length && !query.error) return null;
  return (
    <section className="panel batch-panel" aria-labelledby="batch-history-title">
      <div className="panel-heading">
        <h2 id="batch-history-title">통합 대응 보고서</h2>
        {canWrite && (
          <a className="button-link secondary-link" href={workspaceLink()}>
            자산 선택 <Icon name="arrow" />
          </a>
        )}
      </div>
      <Notice error={query.error} />
      <ul className="batch-history">
        {query.data?.items.map((batch) => (
          <li key={batch.id}>
            <div>
              <a href={batchLink(batch.id)}>
                {batch.assets.length}대 일괄 분석 <Icon name="arrow" />
              </a>
              <p>{batch.assets.map((asset) => asset.asset_name).join(", ")}</p>
            </div>
            <span>
              {batchState(batch)} · {formatKst(batch.created_at)}
            </span>
          </li>
        ))}
      </ul>
      {(query.data?.total ?? 0) > 5 && (
        <ReportPages
          label="일괄 분석 기록"
          page={page}
          total={query.data?.total ?? 0}
          size={5}
          setPage={setPage}
        />
      )}
    </section>
  );
}

export function BatchReportReader({ id }: { id: string }) {
  const { api, canWrite } = useSession();
  const downloadAction = useAction();
  const retryAction = useAction();
  const reportAction = useAction();
  const retryKey = useRef<string | null>(null);
  const load = useCallback((signal: AbortSignal) => getBatch(api!, id, signal), [api, id]);
  const query = usePollingQuery(api ? load : null, null);
  const batch = query.data;
  const running = batch?.status === "RUNNING";
  const regenerating = batch?.report_status === "QUEUED";
  const { refresh } = query;
  useEffect(() => {
    if (!running && !regenerating) return;
    const timer = window.setInterval(refresh, 2500);
    return () => window.clearInterval(timer);
  }, [running, regenerating, refresh]);

  const assets = batch?.assets ?? [];
  const done = assets.filter((asset) => asset.status === "COMPLETED").length;
  const failed = assets.filter((asset) => asset.status === "FAILED").length;
  const assessed = assets.filter((asset) => asset.coverage === "EVALUATED").length;
  const needsReview = assets.reduce(
    (total, asset) => total + (asset.verdict_counts.NEEDS_REVIEW ?? 0),
    0,
  );
  const unassessed = assets.filter(
    (asset) => asset.status === "COMPLETED" && asset.coverage !== "EVALUATED",
  ).length;
  const remaining = assets.length - done - failed;
  const summary = batch?.report_summary;

  async function download() {
    if (!api) return;
    await downloadAction.run(async () => {
      saveMarkdown(await downloadBatch(api, id), `cti-batch-report-${id}.md`);
    }, "통합 보고서를 내려받았습니다.");
  }

  async function retry() {
    if (!api || !canWrite || !batch || retryAction.pending) return;
    retryKey.current ??= crypto.randomUUID();
    const key = retryKey.current;
    await retryAction.run(async () => {
      const next = await retryBatch(api, id, key);
      window.location.hash = batchLink(next.id);
    }, "실패한 자산의 분석을 다시 요청했습니다.");
  }

  async function rebuildReport() {
    if (!api || !canWrite || reportAction.pending) return;
    await reportAction.run(async () => {
      await retryBatchReport(api, id);
      refresh();
    }, "저장된 판정으로 통합 보고서 재생성을 요청했습니다.");
  }

  return (
    <>
      <div className="reader-navigation">
        <a href="#/reports">← 보고서 목록</a>
        {batch?.parent_id && <a href={batchLink(batch.parent_id)}>이전 실행 보기</a>}
      </div>
      <Notice
        error={
          query.error ||
          reportAction.error ||
          batch?.report_error ||
          retryAction.error ||
          downloadAction.error
        }
        success={downloadAction.notice || reportAction.notice}
      />
      {!batch ? (
        <section className="panel empty">
          <strong
            className={query.error ? undefined : "activity-status"}
            data-moving={!query.error || undefined}
            role={query.error ? undefined : "status"}
          >
            {query.error ? "일괄 분석 기록을 불러오지 못했습니다" : "일괄 분석 불러오는 중…"}
          </strong>
          {query.error && (
            <button className="secondary" onClick={refresh}>
              다시 불러오기
            </button>
          )}
        </section>
      ) : (
        <>
          <section
            className="panel batch-panel batch-overview"
            aria-labelledby="batch-summary-title"
          >
            <div className="panel-heading">
              <div>
                <h2 id="batch-summary-title">통합 대응 보고서</h2>
                <p>
                  {batchState(batch)} · 시작 {formatKst(batch.created_at)}
                </p>
              </div>
              <div className="toolbar-actions">
                {batch.retry_id ? (
                  <a className="button-link secondary-link" href={batchLink(batch.retry_id)}>
                    재시도 결과 보기
                  </a>
                ) : (
                  canWrite &&
                  !running &&
                  failed > 0 && (
                    <button className="secondary" disabled={retryAction.pending} onClick={retry}>
                      <Icon name="refresh" />{" "}
                      {retryAction.pending ? "요청 중…" : "실패 자산만 재시도"}
                    </button>
                  )
                )}
                {canWrite && batch.report_status === "FAILED" && (
                  <button
                    className="primary"
                    disabled={reportAction.pending}
                    onClick={rebuildReport}
                  >
                    <Icon name="refresh" />{" "}
                    {reportAction.pending ? "요청 중…" : "통합 보고서 다시 생성"}
                  </button>
                )}
                {batch.report_status === "READY" && (
                  <button className="primary" disabled={downloadAction.pending} onClick={download}>
                    <Icon name="reports" />{" "}
                    {downloadAction.pending ? "파일 준비 중…" : "Markdown 다운로드"}
                  </button>
                )}
              </div>
            </div>
            <dl className="batch-metrics" aria-live="polite">
              <div>
                <dt>선택 자산</dt>
                <dd>
                  {assets.length}
                  <small>대</small>
                </dd>
              </div>
              <div>
                <dt>평가 결과 있음</dt>
                <dd>
                  {assessed}
                  <small>대</small>
                </dd>
              </div>
              <div>
                <dt>미평가</dt>
                <dd>
                  {unassessed}
                  <small>대</small>
                </dd>
              </div>
              <div>
                <dt>분석 실패</dt>
                <dd>
                  {failed}
                  <small>대</small>
                </dd>
              </div>
              <div>
                <dt>평가한 CVE</dt>
                <dd>
                  {batch.evaluated_cve_count == null ? "—" : count(batch.evaluated_cve_count)}
                  {batch.evaluated_cve_count != null && <small>개</small>}
                </dd>
              </div>
              <div>
                <dt>영향 확인 CVE</dt>
                <dd>
                  {batch.evaluated_cve_count && batch.affected_cve_count != null ? (
                    <>
                      {count(batch.affected_cve_count)}
                      <small>개</small>
                    </>
                  ) : (
                    "—"
                  )}
                </dd>
              </div>
            </dl>
            {!running && (
              <p className="batch-outcome-note">
                {batch.evaluated_cve_count
                  ? "CVE 수는 평가 결과가 있는 자산에서 중복을 제거한 값입니다."
                  : "영향을 집계할 수 있는 CVE 판정이 없습니다."}
                {needsReview > 0 && ` 추가 확인 필요 ${count(needsReview)}건 (패키지·CVE 조합).`}
              </p>
            )}
            {regenerating && (
              <p className="batch-outcome-note activity-status" data-moving="true" role="status">
                저장된 판정으로 통합 보고서를 생성하고 있습니다.
              </p>
            )}
            {running && (
              <div className="batch-progress" data-moving="true">
                <progress
                  aria-label="일괄 분석 처리 현황"
                  value={done + failed}
                  max={assets.length}
                />
                <span className="activity-status">
                  {remaining ? remaining + "대 처리 중" : "통합 보고서 생성 중"}
                </span>
              </div>
            )}
            {!running && <SourceRefresh sources={batch.sources} />}
          </section>
          {api && !running && !!batch.evaluated_cve_count && (
            <BatchComparison api={api} batch={batch} />
          )}
          {summary && summary.priorities.length > 0 && (
            <section className="panel batch-panel" aria-labelledby="batch-priority-title">
              <div className="panel-heading">
                <div>
                  <h2 id="batch-priority-title">우선 대응</h2>
                  <p>
                    {summary.attention_asset_count}대에서 조치 또는 추가 확인이 필요합니다.
                    {summary.priority_total > summary.priorities.length &&
                      ` 상위 ${summary.priorities.length}건을 표시합니다.`}
                  </p>
                  <p>
                    {summary.priorities.every((item) => !!item.finding_id)
                      ? "영향 있음, KEV 등재, 확인된 CVSS 점수 순으로 우선 표시합니다."
                      : "보고서 생성 당시 저장한 우선 대응 목록입니다."}
                  </p>
                </div>
              </div>
              <ul className="batch-priorities">
                {summary.priorities.map((item) => {
                  const asset = assets.find((entry) => entry.asset_id === item.asset_id);
                  return (
                    <li key={item.asset_id + item.cve_id}>
                      <span
                        className={item.verdict === "AFFECTED" ? "batch-affected" : "batch-review"}
                      >
                        {item.verdict === "AFFECTED" ? "영향 있음" : "추가 확인 필요"}
                      </span>
                      <div>
                        <a
                          href={
                            item.finding_id
                              ? findingLink(item.finding_id, batch.id, item.cve_id)
                              : batchLink(batch.id, item.cve_id)
                          }
                        >
                          {asset?.asset_name} · {item.cve_id} · {item.package_name}
                        </a>
                        {item.finding_id && (
                          <p className="batch-priority-basis">
                            {item.kev_listed && "KEV 등재 · "}
                            {item.cvss_score != null ? "CVSS " + item.cvss_score : "CVSS 점수 없음"}
                            {item.priority_reason && " · " + item.priority_reason}
                          </p>
                        )}
                        {item.next_step && <p>{item.next_step}</p>}
                      </div>
                    </li>
                  );
                })}
              </ul>
            </section>
          )}
          <section className="panel batch-panel" aria-labelledby="batch-assets-title">
            <div className="panel-heading">
              <div>
                <h2 id="batch-assets-title">{running ? "자산별 분석 진행" : "자산별 분석 결과"}</h2>
                {!running && <p>자산별 건수는 설치 패키지·CVE 조합 기준입니다.</p>}
              </div>
            </div>
            <ul className="batch-assets">
              {assets.map((asset) => (
                <li key={asset.asset_id}>
                  <div className="batch-asset-head">
                    <div>
                      <strong>{asset.asset_name}</strong>
                      <p>
                        {asset.status === "FAILED"
                          ? asset.error || "분석 결과를 확보하지 못했습니다."
                          : asset.status === "RUNNING"
                            ? `${stages[asset.stage]} 진행 중`
                            : asset.coverage === "EVALUATED"
                              ? `조합 ${count(asset.evaluated_pairs)}건 평가 · 영향 있음 ${count(asset.verdict_counts.AFFECTED ?? 0)}건 · 추가 확인 필요 ${count(asset.verdict_counts.NEEDS_REVIEW ?? 0)}건`
                              : asset.coverage === "NO_EVIDENCE"
                                ? "설치 정보 또는 공식 자료가 부족해 CVE를 평가하지 못했습니다."
                                : "지원 범위에 해당하는 설치 패키지·CVE 조합이 없습니다."}
                      </p>
                      {asset.collected_at && (
                        <p>
                          {asset.collection_status === "PARTIAL" ? "일부 수집" : "패키지 수집"}{" "}
                          {count(asset.package_count ?? 0)}개 ·{" "}
                          <time dateTime={asset.collected_at}>{formatKst(asset.collected_at)}</time>
                          {(asset.verdict_counts.OUT_OF_SCOPE ?? 0) > 0 &&
                            " · 지원 범위 밖 " + count(asset.verdict_counts.OUT_OF_SCOPE) + "개"}
                          {(asset.verdict_counts.NO_MATCHING_RECORD ?? 0) > 0 &&
                            " · 대조 자료 없음 " +
                              count(asset.verdict_counts.NO_MATCHING_RECORD) +
                              "개"}
                        </p>
                      )}
                      {(asset.carried || asset.is_synthetic || asset.report_note) && (
                        <p>
                          {[
                            asset.carried && "이전 실행 결과 사용",
                            asset.is_synthetic && "가상 입력",
                            asset.report_note,
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                        </p>
                      )}
                    </div>
                    <span
                      className={
                        asset.status === "FAILED" ||
                        (asset.coverage !== null && asset.coverage !== "EVALUATED")
                          ? "batch-review"
                          : "batch-state"
                      }
                    >
                      {asset.status === "COMPLETED" && asset.coverage
                        ? coverageLabels[asset.coverage]
                        : batchStates[asset.status]}
                    </span>
                  </div>
                  {asset.analysis_id && (
                    <div className="batch-asset-links">
                      <a href={workspaceLink(asset.asset_id, asset.analysis_id)}>
                        판정과 근거 보기 <Icon name="arrow" />
                      </a>
                      {asset.report_id && <a href={reportLink(asset.report_id)}>개별 보고서</a>}
                    </div>
                  )}
                  {canWrite && asset.status === "FAILED" && (
                    <a
                      className="batch-setup-link"
                      href={`#/assets?asset=${asset.asset_id}&setup=ssh`}
                    >
                      자산 연결 설정
                    </a>
                  )}
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </>
  );
}
