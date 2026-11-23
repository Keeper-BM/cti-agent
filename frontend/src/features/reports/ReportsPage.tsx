import { useCallback, useEffect, useRef, useState } from "react";
import { Icon } from "../../shared/components/Icon";
import { routeParam, workspaceLink, reportLink } from "../workflows/api";
import { useSession } from "../../app/session";
import { Notice } from "../../shared/components/Notice";
import { useAction } from "../../shared/hooks/useAction";
import { usePollingQuery } from "../../shared/hooks/usePollingQuery";
import { listAssets } from "../assets/api";
import { getAnalysis, listAnalyses } from "../findings/api";
import { createReport, downloadReport, getReport, listReports } from "./api";
import { ReportPages, ReportPreview, reportTime } from "./ReportPreview";

const states: Record<string, string> = {
  QUEUED: "생성 대기",
  RUNNING: "보고서 생성 중",
  SUCCEEDED: "저장 완료",
  FAILED: "생성 실패",
};

export function ReportsPage() {
  const report = routeParam("report");
  return report ? <ReportReader id={report} /> : <ReportLibrary />;
}

function ReportLibrary() {
  const { api, canWrite } = useSession();
  const [initialId] = useState(
    () => new URLSearchParams(window.location.hash.split("?")[1] ?? "").get("analysis") ?? "",
  );
  const [assetId, setAssetId] = useState("");
  const [assetPage, setAssetPage] = useState(0);
  const [analysisId, setAnalysisId] = useState("");
  const [analysisPage, setAnalysisPage] = useState(0);
  const [includeAI, setIncludeAI] = useState(false);
  const [historyPage, setHistoryPage] = useState(0);
  const action = useAction();
  const key = useRef({ input: "", value: crypto.randomUUID() });
  const seedLoad = useCallback(
    (signal: AbortSignal) => getAnalysis(api!, initialId, signal),
    [api, initialId],
  );
  const seed = usePollingQuery(api && initialId ? seedLoad : null, null);
  useEffect(() => {
    if (seed.data) {
      setAssetId(seed.data.asset_id);
      setAnalysisId(seed.data.id);
    }
  }, [seed.data]);
  const assetsLoad = useCallback(
    (signal: AbortSignal) => listAssets(api!, assetPage * 20, signal),
    [api, assetPage],
  );
  const assets = usePollingQuery(api ? assetsLoad : null, null);
  const analysesLoad = useCallback(
    (signal: AbortSignal) => listAnalyses(api!, assetId, analysisPage, signal),
    [api, assetId, analysisPage],
  );
  const analyses = usePollingQuery(api && assetId ? analysesLoad : null, null);
  const chosenLoad = useCallback(
    (signal: AbortSignal) => getAnalysis(api!, analysisId, signal),
    [api, analysisId],
  );
  const chosen = usePollingQuery(api && analysisId ? chosenLoad : null, null);
  const historyLoad = useCallback(
    (signal: AbortSignal) => listReports(api!, assetId, historyPage, signal),
    [api, assetId, historyPage],
  );
  const history = usePollingQuery(api ? historyLoad : null);
  function chooseAsset(id: string) {
    setAssetId(id);
    setAnalysisId("");
    setAnalysisPage(0);
    setHistoryPage(0);
  }
  async function generate() {
    if (!api) return;
    const input = `${analysisId}:${includeAI}`;
    if (key.current.input !== input) key.current = { input, value: crypto.randomUUID() };
    const ok = await action.run(async () => {
      const result = await createReport(api, analysisId, includeAI, key.current.value);
      window.location.hash = reportLink(result.id);
      setHistoryPage(0);
      history.refresh();
    }, "보고서 생성 요청이 접수되었습니다.");
    if (ok) key.current = { input: "", value: crypto.randomUUID() };
  }
  return (
    <>
      <Notice
        error={
          action.error ||
          assets.error ||
          analyses.error ||
          chosen.error ||
          seed.error ||
          history.error
        }
        success={action.notice}
      />
      <div className="report-asset-filter">
        {" "}
        <label>
          대상 자산
          <select
            value={assetId}
            disabled={!api || action.pending}
            onChange={(e) => chooseAsset(e.target.value)}
          >
            <option value="">전체 자산</option>
            {assetId &&
              !assets.data?.items.some((a) => a.id === assetId) &&
              seed.data?.asset_id === assetId && (
                <option value={assetId}>{seed.data.asset_name}</option>
              )}
            {assets.data?.items.map((a) => (
              <option key={a.id} value={a.id}>
                {a.asset_name}
                {a.is_active ? "" : " (비활성 · 이전 분석 사용)"}
              </option>
            ))}
          </select>
        </label>
        {(assets.data?.total ?? 0) > 20 && (
          <ReportPages
            label="보고서 자산 선택"
            page={assetPage}
            total={assets.data?.total ?? 0}
            size={20}
            setPage={(p) => {
              setAssetPage(p);
              chooseAsset("");
            }}
          />
        )}
      </div>
      {canWrite && (
        <details className="panel create-fold" open={!!initialId || undefined}>
          <summary>
            새 보고서 생성
            <Icon name="chevron" />
          </summary>
          <div className="report-form">
            <label>
              완료된 분석 선택
              <select
                value={analysisId}
                disabled={!assetId || action.pending}
                onChange={(e) => setAnalysisId(e.target.value)}
              >
                <option value="">대상 분석 선택</option>
                {analysisId &&
                  !analyses.data?.items.some((a) => a.id === analysisId) &&
                  seed.data?.id === analysisId && (
                    <option value={analysisId}>
                      {reportTime(seed.data.created_at)} · {analysisId.slice(0, 8)}
                    </option>
                  )}
                {analyses.data?.items.map((a) => (
                  <option key={a.id} value={a.id} disabled={a.job.status !== "SUCCEEDED"}>
                    {reportTime(a.created_at)} · {a.id.slice(0, 8)} ·{" "}
                    {a.job.status === "SUCCEEDED" ? "분석 완료" : a.job.status}
                    {a.is_synthetic ? " · 가상 입력" : ""}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {(analyses.data?.total ?? 0) > 10 && (
            <ReportPages
              label="보고서 분석 선택"
              page={analysisPage}
              total={analyses.data?.total ?? 0}
              size={10}
              setPage={(p) => {
                setAnalysisPage(p);
                setAnalysisId("");
              }}
            />
          )}
          <div className="report-options">
            <label className="report-checkbox">
              <input
                type="checkbox"
                checked={includeAI}
                disabled={action.pending}
                onChange={(e) => setIncludeAI(e.target.checked)}
              />
              <span>
                AI Summary 포함
                <small>저장된 요약을 포함하고, 대표 판정에 요약이 없으면 BAZE로 생성합니다.</small>
              </span>
            </label>
            <button
              className="primary"
              disabled={
                !api ||
                !analysisId ||
                !canWrite ||
                action.pending ||
                chosen.data?.id !== analysisId ||
                chosen.data?.job.status !== "SUCCEEDED"
              }
              onClick={generate}
            >
              {action.pending ? "요청 중…" : "보고서 생성"}
            </button>
          </div>
          {chosen.data && (
            <p className="report-selected-analysis">
              선택한 분석 · {chosen.data.asset_name} · Ubuntu {chosen.data.os_release} · 결과{" "}
              {chosen.data.summary?.TOTAL ?? 0}건{chosen.data.is_synthetic ? " · 가상 입력" : ""}
            </p>
          )}
          {assetId && analyses.data?.total === 0 && (
            <p className="report-selected-analysis">
              완료된 분석이 없습니다. <a href="#/workspace">분석 실행</a>
            </p>
          )}
        </details>
      )}
      <section className="panel report-history">
        <div className="panel-heading">
          <div>
            <h2>보고서 이력</h2>
            <p>자료 고정 시각 기준 내림차순 · 동일 분석의 보고서 개별 보관</p>
          </div>
          <button className="secondary" disabled={!api} onClick={history.refresh}>
            보고서 이력 새로고침
          </button>
        </div>
        <div className="analysis-history">
          {!history.data?.items.length && (
            <p>{history.loading ? "보고서 이력 조회 중…" : "저장된 보고서가 없습니다."}</p>
          )}
          {history.data?.items.map((r) => (
            <button
              className="analysis-history-item"
              key={r.id}
              onClick={() => {
                window.location.hash = reportLink(r.id);
              }}
            >
              <span>
                <strong>
                  {r.asset_name} · {reportTime(r.created_at)}
                </strong>
                <small>
                  {r.id.slice(0, 8)} · 분석 {r.analysis_id.slice(0, 8)} · 결과 {r.finding_count}건 ·{" "}
                  {!r.include_ai_explanations
                    ? "AI 요약 미포함"
                    : r.explanation_count > 0
                      ? "AI Summary " + r.explanation_count + "건"
                      : r.job.status === "SUCCEEDED"
                        ? "저장된 AI 요약 없음"
                        : "AI 요약 요청"}
                  {r.is_synthetic ? " · 가상" : ""}
                </small>
              </span>
              <span className={`badge ${r.job.status.toLowerCase()}`}>
                {states[r.job.status] ?? r.job.status}
              </span>
            </button>
          ))}
        </div>
        {(history.data?.total ?? 0) > 10 && (
          <ReportPages
            label="보고서 이력"
            page={historyPage}
            total={history.data?.total ?? 0}
            size={10}
            setPage={setHistoryPage}
          />
        )}
      </section>
    </>
  );
}

function ReportReader({ id }: { id: string }) {
  const { api } = useSession();
  const downloadAction = useAction();
  const detailLoad = useCallback((signal: AbortSignal) => getReport(api!, id, signal), [api, id]);
  const detail = usePollingQuery(api ? detailLoad : null, null);
  const status = detail.data?.job.status;
  useEffect(() => {
    if (status !== "QUEUED" && status !== "RUNNING") return;
    const timer = window.setInterval(detail.refresh, 3000);
    return () => window.clearInterval(timer);
  }, [status, detail.refresh]);
  async function download() {
    if (!api || !detail.data) return;
    const id = detail.data.id;
    await downloadAction.run(async () => {
      const text = await downloadReport(api, id);
      const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `cti-report-${id}.md`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }, "Markdown 보고서 다운로드 완료");
  }
  return (
    <>
      <div className="reader-navigation">
        <a href="#/reports">
          <Icon name="reports" />
          보고서 목록
        </a>
        {detail.data && (
          <a href={workspaceLink(detail.data.asset_id, detail.data.analysis_id)}>
            이 분석의 결과
            <Icon name="arrow" />
          </a>
        )}
      </div>
      <Notice error={detail.error} />
      {!detail.data && !detail.error && (
        <p className="quiet-empty" role="status">
          보고서를 불러오는 중…
        </p>
      )}
      {detail.data && (
        <section className="panel report-document">
          <header className="panel-heading report-cover">
            <div>
              <h2>{detail.data.asset_name} 대응 보고서</h2>
              <p>
                {states[detail.data.job.status]} · 분석 {detail.data.analysis_id.slice(0, 8)}
              </p>
              {detail.data.content && (
                <p className="report-frozen">
                  Ubuntu {detail.data.content.os.version_id} · 분석 완료{" "}
                  {reportTime(detail.data.content.analysis_completed_at)}
                  <br />
                  자료 고정 {reportTime(detail.data.content.frozen_at)}
                  {detail.data.content.generated_at &&
                    " · 생성 " + reportTime(detail.data.content.generated_at)}
                </p>
              )}
            </div>
            <button
              className="primary"
              disabled={
                detail.data.job.status !== "SUCCEEDED" ||
                !detail.data.content ||
                downloadAction.pending
              }
              onClick={download}
            >
              {downloadAction.pending ? "파일 준비 중…" : "Markdown 다운로드"}
            </button>
          </header>
          <Notice error={downloadAction.error} success={downloadAction.notice} />
          {detail.data.job.status === "FAILED" && (
            <p className="report-job-note" role="alert">
              {String(detail.data.job.result?.message ?? "보고서를 생성하지 못했습니다.")} (
              {detail.data.job.error_code}) 이전 보고서는 이력에서 계속 조회할 수 있습니다.
            </p>
          )}
          {["QUEUED", "RUNNING"].includes(detail.data.job.status) && (
            <p className="report-job-note" role="status">
              {states[detail.data.job.status]} · 진행 상태는 작업 내역에서 확인할 수 있습니다.
            </p>
          )}
          {detail.data.content && (
            <>
              <ReportPreview key={detail.data.id} content={detail.data.content} />
              <details className="report-file-info">
                <summary>보고서 파일 식별 정보</summary>
                <p className="mono">
                  보고서 {detail.data.id}
                  <br />
                  Markdown SHA-256 {detail.data.markdown_sha256}
                  <br />
                  입력 SHA-256 {detail.data.input_sha256}
                </p>
              </details>
            </>
          )}
        </section>
      )}
    </>
  );
}
