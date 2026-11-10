import { useCallback, useEffect, useRef, useState } from "react";
import type { HttpClient } from "../../api/client";
import { useSession } from "../../app/session";
import { Notice } from "../../shared/components/Notice";
import { useAction } from "../../shared/hooks/useAction";
import { usePollingQuery } from "../../shared/hooks/usePollingQuery";
import { listAssets } from "../assets/api";
import type { Asset } from "../assets/api";
import { listInventories } from "../inventories/api";
import { ExplanationPanel } from "../explanations/ExplanationPanel";
import { names } from "../sources/api";
import { createAnalysis, getAnalysis, getFinding, listAnalyses, listFindings } from "./api";
import type { Analysis, Finding } from "./api";
import { ComparisonPanel } from "../comparisons/ComparisonPanel";
import { RemediationPanel } from "../remediation/RemediationPanel";
import { ApacheRuntimeEvidence } from "../verifications/ApacheRuntimeEvidence";

const formatKst = (value: string) =>
  new Date(value).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" });
const metricSummary = (f: Finding) =>
  [
    ...new Set(
      (f.nvd_metrics ?? [])
        .filter((m) => m.score != null)
        .map((m) => `CVSS ${m.version} ${m.score}`),
    ),
  ].join(" · ") || "CVSS 점수 미제공";

const labels: Record<string, string> = {
  AFFECTED: "영향 있음",
  FIXED: "수정 기준 충족",
  NOT_AFFECTED: "영향 없음",
  NEEDS_REVIEW: "추가 확인 필요",
  OUT_OF_SCOPE: "지원 범위 밖",
  NOT_INSTALLED: "입력 목록에 없음",
  NO_MATCHING_RECORD: "대조 자료 없음",
  COLLECTION_FAILED: "수집 실패",
  PARTIAL_COLLECTION: "설치 여부 미확인",
  BELOW_FIX: "수정 기준보다 낮음",
  MEETS_FIX: "수정 기준 이상",
  UNAVAILABLE: "비교 불가",
  QUEUED: "분석 대기",
  RUNNING: "분석 중",
  SUCCEEDED: "분석 완료",
  FAILED: "분석 실패",
  PARTIAL: "일부 완료",
  LISTED: "악용 목록 등재",
  NOT_LISTED: "저장 목록에 미등재",
  NOT_FETCHED: "악용 자료 미수집",
  USER_DECLARED: "사용자 입력 · 미검증",
  UNKNOWN: "미확인",
  UNSUPPORTED: "지원하지 않는 출처",
  SUPPORTED_ORIGIN: "출처 확인됨",
  VERIFIED_LAB: "시험 환경에서 확인됨",
  OFFICIAL_MATCH: "공식 배포본 파일 일치",
};
const verdictClass = (finding: Finding) =>
  finding.verdict === "AFFECTED"
    ? "failed"
    : finding.verdict === "FIXED" || finding.verdict === "NOT_AFFECTED"
      ? "succeeded"
      : "queued";

function Pages({
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

export function FindingsPage() {
  const { api } = useSession();
  const [asset, setAsset] = useState<Asset | null>(null);
  const [page, setPage] = useState(0);
  const load = useCallback(
    (signal: AbortSignal) => listAssets(api!, page * 20, signal),
    [api, page],
  );
  const assets = usePollingQuery(api ? load : null, null);
  return (
    <>
      <div className="inline-info">
        <span className="info-icon">i</span>
        <span>
          Ubuntu 22.04·24.04의 Apache2·MySQL 패키지를 공식 기준과 대조합니다. 버전 비교와 최종
          판단은 구분됩니다.
        </span>
      </div>
      <Notice error={assets.error} />
      <section className="panel analysis-select">
        <div>
          <h2>분석 대상 자산</h2>
          <p>저장한 패키지 입력 이력을 선택해 분석합니다.</p>
        </div>
        <label>
          자산 선택
          <select
            value={asset?.id ?? ""}
            disabled={!api}
            onChange={(e) =>
              setAsset(assets.data?.items.find((a) => a.id === e.target.value) ?? null)
            }
          >
            <option value="">자산을 선택하세요</option>
            {assets.data?.items.map((a) => (
              <option key={a.id} value={a.id}>
                {a.asset_name}
                {!a.is_active ? " (비활성)" : ""}
              </option>
            ))}
          </select>
        </label>
        {(assets.data?.total ?? 0) > 20 && (
          <Pages
            label="자산 목록"
            page={page}
            total={assets.data?.total ?? 0}
            size={20}
            setPage={(p) => {
              setAsset(null);
              setPage(p);
            }}
          />
        )}
        {!assets.loading && assets.data?.total === 0 && (
          <p>
            <a href="#/assets">자산 현황</a>에서 자산을 등록하고 SSH로 패키지를 가져오거나 JSON
            파일을 입력하세요.
          </p>
        )}
      </section>
      {api && asset && <AnalysisWorkspace key={asset.id} api={api} asset={asset} />}
    </>
  );
}

function AnalysisWorkspace({ api, asset }: { api: HttpClient; asset: Asset }) {
  const { canWrite } = useSession();
  const [inventoryId, setInventoryId] = useState("");
  const [inventoryPage, setInventoryPage] = useState(0);
  const [historyPage, setHistoryPage] = useState(0);
  const [analysisId, setAnalysisId] = useState("");
  const action = useAction();
  const requestKey = useRef({ inventory: "", key: crypto.randomUUID() });
  const inventoryLoad = useCallback(
    (signal: AbortSignal) => listInventories(api, asset.id, inventoryPage, signal),
    [api, asset.id, inventoryPage],
  );
  const inventories = usePollingQuery(inventoryLoad, null);
  const historyLoad = useCallback(
    (signal: AbortSignal) => listAnalyses(api, asset.id, historyPage, signal),
    [api, asset.id, historyPage],
  );
  const history = usePollingQuery(historyLoad);
  const detailLoad = useCallback(
    (signal: AbortSignal) => getAnalysis(api, analysisId, signal),
    [api, analysisId],
  );
  const selected = usePollingQuery(analysisId ? detailLoad : null);
  const chosenInventory = inventories.data?.items.find((i) => i.inventory_id === inventoryId);
  async function analyse() {
    if (requestKey.current.inventory !== inventoryId)
      requestKey.current = { inventory: inventoryId, key: crypto.randomUUID() };
    const succeeded = await action.run(async () => {
      const result = await createAnalysis(api, inventoryId, requestKey.current.key);
      setAnalysisId(result.id);
      setHistoryPage(0);
      history.refresh();
    }, "분석 요청이 접수되었습니다.");
    if (succeeded) requestKey.current = { inventory: "", key: crypto.randomUUID() };
  }
  return (
    <>
      <Notice
        error={action.error || inventories.error || history.error || selected.error}
        success={action.notice}
      />
      <section className="panel analysis-select">
        <div>
          <h2>패키지 정보 선택</h2>
          <p>요청 시점의 저장된 보안 자료로 분석하며, 외부 자료를 자동 수집하지 않습니다.</p>
        </div>
        <label>
          패키지 입력 이력
          <select value={inventoryId} onChange={(e) => setInventoryId(e.target.value)}>
            <option value="">분석 대상 입력 선택</option>
            {inventories.data?.items.map((i) => (
              <option key={i.inventory_id} value={i.inventory_id}>
                {formatKst(i.collected_at)} · Ubuntu {i.os_release} · {i.package_count}개 ·{" "}
                {i.inventory_id.slice(0, 8)}
                {i.is_synthetic ? " · 가상 입력" : ""}
              </option>
            ))}
          </select>
        </label>
        <button
          className="primary"
          disabled={!chosenInventory || action.pending || !asset.is_active || !canWrite}
          onClick={analyse}
        >
          {action.pending ? "요청 중…" : "분석 실행"}
        </button>
        {(inventories.data?.total ?? 0) > 10 && (
          <Pages
            label="패키지 입력"
            page={inventoryPage}
            total={inventories.data?.total ?? 0}
            size={10}
            setPage={(p) => {
              setInventoryPage(p);
              setInventoryId("");
            }}
          />
        )}
        {chosenInventory && (
          <p className="analysis-input-note">
            입력 시각 {formatKst(chosenInventory.ingested_at)} ·{" "}
            {chosenInventory.collection_status === "COMPLETE" ? "전체 목록으로 선언" : "부분 입력"}
            {chosenInventory.is_synthetic ? " · 가상 데이터는 실제 서버 결과와 구분됩니다." : ""}
          </p>
        )}
        {!asset.is_active && (
          <p className="analysis-input-note">비활성 자산은 이전 결과만 조회할 수 있습니다.</p>
        )}
        {inventories.data?.total === 0 && (
          <p>
            <a href="#/assets">자산 현황</a>에서 이 자산의 패키지를 SSH로 가져오거나 JSON 파일을
            입력하세요.
          </p>
        )}
      </section>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>분석 이력</h2>
            <p>이전 결과는 당시 패키지·보안 자료·규칙을 유지합니다.</p>
          </div>
          <button className="secondary" onClick={history.refresh}>
            이력 새로고침
          </button>
        </div>
        <div className="analysis-history">
          {!history.data?.items.length && (
            <p>
              {history.loading ? "분석 이력을 확인하고 있습니다." : "아직 실행한 분석이 없습니다."}
            </p>
          )}
          {history.data?.items.map((a) => (
            <button
              key={a.id}
              className={`analysis-history-item ${analysisId === a.id ? "selected" : ""}`}
              onClick={() => setAnalysisId(a.id)}
              aria-pressed={analysisId === a.id}
            >
              <span>
                <strong>{formatKst(a.created_at)}</strong>
                <small>
                  {a.id.slice(0, 8)} · 입력 {a.inventory_id.slice(0, 8)}
                  {a.is_synthetic ? " · 가상" : ""}
                </small>
              </span>
              <span className={`badge ${a.job.status.toLowerCase()}`}>{labels[a.job.status]}</span>
            </button>
          ))}
        </div>
        {(history.data?.total ?? 0) > 10 && (
          <Pages
            label="분석 이력"
            page={historyPage}
            total={history.data?.total ?? 0}
            size={10}
            setPage={setHistoryPage}
          />
        )}
      </section>
      {selected.data && (
        <AnalysisResults key={selected.data.id} api={api} analysis={selected.data} />
      )}
      {selected.data?.job.status === "SUCCEEDED" && (
        <ComparisonPanel key={`compare-${selected.data.id}`} analysis={selected.data} />
      )}
    </>
  );
}

function AnalysisResults({ api, analysis }: { api: HttpClient; analysis: Analysis }) {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("");
  const [page, setPage] = useState(0);
  const [findingId, setFindingId] = useState("");
  const completed = analysis.job.status === "SUCCEEDED";
  const load = useCallback(
    (signal: AbortSignal) =>
      listFindings(
        api,
        {
          analysis_id: analysis.id,
          search,
          limit: "20",
          offset: String(page * 20),
          ...(filter
            ? ["AFFECTED", "FIXED", "NOT_AFFECTED", "NEEDS_REVIEW"].includes(filter)
              ? { verdict: filter }
              : { processing_status: filter }
            : {}),
        },
        signal,
      ),
    [api, analysis.id, search, filter, page],
  );
  const results = usePollingQuery(completed ? load : null, null);
  function reset() {
    setPage(0);
    setFindingId("");
  }
  return (
    <>
      <section className="panel analysis-overview">
        <div className="panel-heading">
          <div>
            <h2>{analysis.asset_name} 분석 결과</h2>
            <p>
              Ubuntu {analysis.os_release ?? "미확인"} · {formatKst(analysis.created_at)} ·{" "}
              {analysis.id.slice(0, 8)}
            </p>
          </div>
          <span className={`badge ${analysis.job.status.toLowerCase()}`}>
            {labels[analysis.job.status]}
          </span>
          {completed && (
            <a className="report-shortcut" href={`#/reports?analysis=${analysis.id}`}>
              보고서 생성
            </a>
          )}
        </div>
        {analysis.is_synthetic && (
          <div className="analysis-synthetic">
            가상 입력 분석 · 실제 서버의 보안 상태를 나타내지 않습니다.
          </div>
        )}
        {analysis.job.status === "QUEUED" && (
          <p className="analysis-message" role="status">
            분석 대기 중입니다. 작업 처리기가 실행되면 결과가 표시됩니다.
          </p>
        )}
        {analysis.job.status === "RUNNING" && (
          <p className="analysis-message" role="status">
            고정한 패키지와 공식 자료를 대조하고 있습니다.
          </p>
        )}
        {analysis.job.status === "FAILED" && (
          <p className="analysis-message" role="alert">
            {String(analysis.job.result?.message ?? "분석에 실패했습니다.")} (
            {analysis.job.error_code}) 이전 분석 결과는 이력에서 계속 조회할 수 있습니다.
          </p>
        )}
        {completed && (
          <div className="analysis-stats">
            {["TOTAL", "BELOW_FIX", "MEETS_FIX", "NEEDS_REVIEW"].map((k) => (
              <div key={k}>
                <span>
                  {k === "TOTAL"
                    ? "전체 결과"
                    : k === "NEEDS_REVIEW"
                      ? "최종 판단: 추가 확인"
                      : `버전: ${labels[k]}`}
                </span>
                <strong>
                  {analysis.summary?.[k] ?? 0}
                  <small>건</small>
                </strong>
              </div>
            ))}
          </div>
        )}
        <details className="analysis-context">
          <summary>분석 범위 및 제한 사항 · {analysis.warnings.length}개</summary>
          <ul>
            {analysis.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </details>
        <details className="analysis-context">
          <summary>참조 보안 자료 · {analysis.sources.length}개 기준본</summary>
          <p>
            분석 시점의 자료와 규칙 {analysis.ruleset_version}을 적용했습니다. 출처별 수집 시각은
            다음과 같습니다.
          </p>
          <ul>
            {analysis.sources.map((s) => (
              <li key={s.id}>
                {names[s.source_id]} / {s.scope_key} · {formatKst(s.captured_at)} ·{" "}
                <span className="mono">{s.id.slice(0, 8)}</span>
              </li>
            ))}
          </ul>
          <p>
            입력 ID: <span className="mono">{analysis.inventory_id}</span>
            <br />
            대조 기준 ID: <span className="mono">{analysis.feed_snapshot_id}</span>
          </p>
        </details>
      </section>
      {completed && (
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>CVE별 패키지 결과</h2>
              <p>
                동일 CVE라도 설치 패키지별로 구분합니다. 검색 결과가 없다는 뜻이 안전을 의미하지는
                않습니다.
              </p>
              {!filter && (
                <p>
                  영향 있음 → 추가 확인 필요 → 수정 기준 충족 → 영향 없음 순으로 표시합니다. 지원
                  범위 밖은 맨 아래에 표시합니다.
                </p>
              )}
            </div>
          </div>
          <div className="source-filters">
            <label>
              패키지·CVE 검색
              <input
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  reset();
                }}
                placeholder="apache2 또는 CVE 번호"
                maxLength={200}
              />
            </label>
            <label>
              최종 판단·처리 상태
              <select
                value={filter}
                onChange={(e) => {
                  setFilter(e.target.value);
                  reset();
                }}
              >
                <option value="">전체 결과</option>
                {[
                  "AFFECTED",
                  "NEEDS_REVIEW",
                  "FIXED",
                  "NOT_AFFECTED",
                  "COLLECTION_FAILED",
                  "PARTIAL_COLLECTION",
                  "NO_MATCHING_RECORD",
                  "NOT_INSTALLED",
                  "OUT_OF_SCOPE",
                ].map((k) => (
                  <option value={k} key={k}>
                    {labels[k]}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <Notice error={results.error} />
          <div className="table-wrap">
            <table className="analysis-table">
              <thead>
                <tr>
                  <th>패키지 / CVE</th>
                  <th>버전 비교</th>
                  <th>최종 판단</th>
                  <th>위험 정보</th>
                  <th>근거</th>
                </tr>
              </thead>
              <tbody>
                {results.data?.items.map((f) => (
                  <tr
                    key={f.finding_id}
                    className={findingId === f.finding_id ? "analysis-selected-row" : ""}
                  >
                    <td>
                      <strong>{f.package_name ?? "전체 입력"}</strong>
                      <span className="mono">{f.cve_id ?? "패키지 처리 상태"}</span>
                    </td>
                    <td>
                      <strong>{labels[f.version_comparison]}</strong>
                      <small>
                        소스 설치:{" "}
                        {f.comparison_basis === "SOURCE"
                          ? (f.installed_version ?? "미제공")
                          : "대조 없음"}
                      </small>
                      <small>공식 수정: {f.fixed_version ?? "미제공"}</small>
                    </td>
                    <td>
                      <span className={`badge ${verdictClass(f)}`}>
                        {labels[f.verdict ?? f.processing_status]}
                      </span>
                    </td>
                    <td>
                      {f.cve_id ? (
                        <>
                          <small>{labels[f.kev_status]}</small>
                          <small>{metricSummary(f)}</small>
                        </>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>
                      <button
                        className="secondary"
                        onClick={() => setFindingId(f.finding_id)}
                        aria-label={`${f.package_name ?? "입력"} ${f.cve_id ?? f.processing_status} 근거 보기`}
                      >
                        근거 보기
                      </button>
                    </td>
                  </tr>
                ))}
                {!results.data?.items.length && (
                  <tr>
                    <td colSpan={5}>
                      {results.loading
                        ? "결과를 불러오고 있습니다."
                        : results.error
                          ? "결과를 불러오지 못했습니다."
                          : "조건에 맞는 결과가 없습니다."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <Pages
            label="분석 결과"
            page={page}
            total={results.data?.total ?? 0}
            size={20}
            setPage={(p) => {
              setPage(p);
              setFindingId("");
            }}
          />
        </section>
      )}
      {findingId && (
        <FindingEvidence key={findingId} api={api} id={findingId} close={() => setFindingId("")} />
      )}
    </>
  );
}

function FindingEvidence({ api, id, close }: { api: HttpClient; id: string; close: () => void }) {
  const load = useCallback((signal: AbortSignal) => getFinding(api, id, signal), [api, id]);
  const query = usePollingQuery(load, null);
  const heading = useRef<HTMLDivElement>(null);
  const [documentId, setDocumentId] = useState("");
  useEffect(() => {
    if (query.data) heading.current?.focus({ preventScroll: true });
  }, [query.data]);
  const f = query.data;
  return (
    <section className="panel" aria-label="분석 근거 상세" ref={heading} tabIndex={-1}>
      <div className="panel-heading">
        <div>
          <h2>
            {f?.cve_id ?? "분석 근거"} · {f?.package_name}
          </h2>
          <p>분석 시점의 공식 자료 및 판정 근거</p>
        </div>
        <button className="secondary" onClick={close}>
          근거 닫기
        </button>
      </div>
      <Notice error={query.error} />
      {!f && <p className="analysis-message">근거를 불러오고 있습니다.</p>}
      {f && (
        <div className="analysis-detail">
          <div className="analysis-decision">
            <span className={`badge ${verdictClass(f)}`}>
              {labels[f.verdict ?? f.processing_status]}
            </span>
            <strong>버전 비교: {labels[f.version_comparison]}</strong>
          </div>
          <ul>
            {(f.reasons ?? []).map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
          <dl className="analysis-facts">
            <div>
              <dt>바이너리 설치 버전</dt>
              <dd>{f.binary_version ?? "미제공"}</dd>
            </div>
            <div>
              <dt>대조한 소스 패키지 / 버전</dt>
              <dd>
                {f.source_package ?? "미확인"} /{" "}
                {f.comparison_basis === "SOURCE" ? (f.installed_version ?? "미제공") : "대조 없음"}
              </dd>
            </div>
            <div>
              <dt>Ubuntu 공식 수정 기준</dt>
              <dd>{f.fixed_version ?? "미제공"}</dd>
            </div>
            <div>
              <dt>설치 출처</dt>
              <dd>{f.origin_status ? labels[f.origin_status] : "미확인"}</dd>
            </div>
          </dl>
          {(f.limitations ?? []).map((l) => (
            <p className="source-caution" key={l}>
              {l}
            </p>
          ))}
          {f.cve_id && (
            <p>
              CISA KEV: {labels[f.kev_status]}
              {f.kev_snapshot ? ` · 기준 ${formatKst(f.kev_snapshot.captured_at)}` : ""}. 미등재는
              악용이 없다는 뜻이 아닙니다.
            </p>
          )}
          {!!(f.nvd_metrics ?? []).length && (
            <div className="analysis-metrics">
              <h3>NVD에 저장된 CVSS</h3>
              {(f.nvd_metrics ?? []).map((m, i) => (
                <p key={i}>
                  CVSS {m.version} · {m.score ?? "점수 미제공"} · {m.provider ?? "공급자 미제공"}
                  <br />
                  <span className="mono">{m.vector}</span>
                </p>
              ))}
            </div>
          )}
          {f.cve_id && f.verdict && (
            <ExplanationPanel key={f.finding_id} api={api} findingId={f.finding_id} />
          )}
          {f.remediation && <RemediationPanel value={f.remediation} />}
          {f.runtime_evidence && <ApacheRuntimeEvidence evidence={f.runtime_evidence} />}
          <h3>공식 근거와 원문</h3>
          {!f.related_records.length && (
            <p>
              대조할 공식 기록이 없습니다. <a href="#/sources">보안 자료</a>에서 해당 릴리스·패키지
              자료를 확인하세요.
            </p>
          )}
          {f.related_records.map((r) => (
            <article className="analysis-evidence" key={r.id}>
              <div className="source-evidence-heading">
                <h3>
                  {names[r.source_id]} <small>{r.scope_key}</small>
                </h3>
                <button className="secondary" onClick={() => setDocumentId(r.document.id)}>
                  저장 원문 보기
                </button>
              </div>
              <p className="analysis-excerpt">{r.data.description || "설명 미제공"}</p>
              {r.data.upstream_fixed_version && (
                <p>
                  제품 자체 수정 버전: {r.data.upstream_fixed_version} · Ubuntu 수정 버전과 별도로
                  해석합니다.
                </p>
              )}
              {!!Object.keys(r.data.attributes ?? {}).length && (
                <dl className="source-attributes">
                  {Object.entries(r.data.attributes ?? {}).map(([k, v]) => (
                    <div key={k}>
                      <dt>{k}</dt>
                      <dd>{v}</dd>
                    </div>
                  ))}
                </dl>
              )}
              <p>
                수집 {formatKst(r.document.captured_at)} · 기준본 {r.snapshot_id.slice(0, 8)}
              </p>
              <details>
                <summary>공식 링크·해시·규칙 자료</summary>
                <ul className="source-links">
                  <li>
                    <a href={r.document.url} target="_blank" rel="noreferrer">
                      수집 출처
                    </a>
                  </li>
                  {(r.data.references ?? []).map((url) => (
                    <li key={url}>
                      <a href={url} target="_blank" rel="noreferrer">
                        {url}
                      </a>
                    </li>
                  ))}
                </ul>
                <p className="mono">SHA-256: {r.document.sha256}</p>
                {r.source_id === "ubuntu" && (
                  <pre>
                    {JSON.stringify(
                      {
                        status: r.data.status,
                        fixed_version: r.data.fixed_version,
                        ranges: r.data.ranges,
                      },
                      null,
                      2,
                    )}
                  </pre>
                )}
              </details>
            </article>
          ))}
          {documentId && (
            <StoredDocument
              key={documentId}
              api={api}
              id={documentId}
              close={() => setDocumentId("")}
            />
          )}
          <details>
            <summary>분석 식별 정보</summary>
            <p className="mono">
              규칙 {f.ruleset_version}
              <br />
              규칙 ID {f.matched_rule_id ?? "없음"}
              <br />
              분석 {f.analysis_id}
              <br />
              판정 시각 {formatKst(f.evaluated_at)}
            </p>
          </details>
        </div>
      )}
    </section>
  );
}

function StoredDocument({ api, id, close }: { api: HttpClient; id: string; close: () => void }) {
  const load = useCallback(
    (signal: AbortSignal) =>
      api.request<{ raw_text: string; sha256: string }>(`/sources/documents/${id}`, { signal }),
    [api, id],
  );
  const query = usePollingQuery(load, null);
  function download() {
    if (!query.data) return;
    const url = URL.createObjectURL(
      new Blob([query.data.raw_text], { type: "text/plain;charset=utf-8" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = `source-${id}.txt`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <div className="source-evidence">
      <div className="source-evidence-heading">
        <h3>저장 원문</h3>
        <button className="secondary" onClick={close}>
          원문 닫기
        </button>
      </div>
      <Notice error={query.error} />
      {query.data ? (
        <>
          <p>화면에는 처음 30,000자까지 표시합니다. 원문 전체는 내려받을 수 있습니다.</p>
          <button className="secondary" onClick={download}>
            전체 원문 내려받기
          </button>
          <pre>{query.data.raw_text.slice(0, 30000)}</pre>
        </>
      ) : (
        <p>원문을 불러오고 있습니다.</p>
      )}
    </div>
  );
}
