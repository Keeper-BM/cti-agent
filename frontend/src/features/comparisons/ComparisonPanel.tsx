import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSession } from "../../app/session";
import { Notice } from "../../shared/components/Notice";
import { formatKst } from "../../shared/format";
import { useAction } from "../../shared/hooks/useAction";
import { usePollingQuery } from "../../shared/hooks/usePollingQuery";
import { listInventories } from "../inventories/api";
import type { Analysis } from "../findings/api";
import { createComparison, getComparison, listComparisons } from "./api";
import type { ComparisonResult } from "./api";
const labels: Record<string, string> = {
  ADDED: "입력에 추가",
  REMOVED: "입력에서 사라짐",
  CHANGED: "변경",
  UNCHANGED: "동일",
  FIXED: "수정 기준 충족",
  NEEDS_REVIEW: "추가 확인",
  AFFECTED: "영향 있음",
  NOT_AFFECTED: "비영향",
  OUT_OF_SCOPE: "지원 범위 밖",
  NOT_INSTALLED: "목록에 없음",
  PARTIAL_COLLECTION: "설치 여부 미확인",
  NO_MATCHING_RECORD: "대조 자료 없음",
  QUEUED: "대기",
  RUNNING: "비교 중",
  SUCCEEDED: "완료",
  FAILED: "실패",
};
export function ComparisonPanel({ analysis }: { analysis: Analysis }) {
  const { api, canWrite } = useSession();
  const [target, setTarget] = useState("");
  const [invPage, setInvPage] = useState(0);
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState("");
  const [poll, setPoll] = useState(true);
  const action = useAction();
  const key = useRef({ target: "", value: crypto.randomUUID() });
  const load = useCallback(
    (signal: AbortSignal) => listInventories(api!, analysis.asset_id, invPage, signal),
    [api, analysis.asset_id, invPage],
  );
  const inventories = usePollingQuery(api ? load : null, null);
  const historyLoad = useCallback(
    (signal: AbortSignal) => listComparisons(api!, analysis.asset_id, page, signal),
    [api, analysis.asset_id, page],
  );
  const history = usePollingQuery(api ? historyLoad : null);
  const detailLoad = useCallback(
    (signal: AbortSignal) => getComparison(api!, selected, signal),
    [api, selected],
  );
  const detail = usePollingQuery(api && selected ? detailLoad : null, poll ? 4000 : null);
  useEffect(() => {
    if (detail.data && ["SUCCEEDED", "FAILED"].includes(detail.data.job.status)) {
      setPoll(false);
      history.refresh();
    }
  }, [detail.data?.job.status, history.refresh]);
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <h2>분석 전후 비교</h2>
          <p>동일 보안 자료 기준의 패키지 버전·검증 상태·판정 변화</p>
        </div>
      </div>
      <div className="inventory-content">
        <Notice
          error={action.error || inventories.error || history.error || detail.error}
          success={action.notice}
        />
        <div className="collection-toolbar">
          <label>
            비교할 패키지 기록{" "}
            <select value={target} onChange={(e) => setTarget(e.target.value)}>
              <option value="">다른 기록 선택</option>
              {inventories.data?.items
                .filter((i) => i.inventory_id !== analysis.inventory_id)
                .map((i) => (
                  <option value={i.inventory_id} key={i.inventory_id}>
                    {formatKst(i.collected_at)} · {i.package_count}개 · {i.inventory_id.slice(0, 8)}
                  </option>
                ))}
            </select>
          </label>
          <button
            className="primary"
            disabled={!canWrite || !target || action.pending}
            onClick={async () => {
              if (!api) return;
              if (key.current.target !== target)
                key.current = { target, value: crypto.randomUUID() };
              if (
                await action.run(async () => {
                  const r = await createComparison(api, analysis.id, target, key.current.value);
                  setSelected(r.id);
                  setPoll(true);
                  setPage(0);
                  history.refresh();
                }, "같은 자료 기준의 비교를 요청했습니다.")
              )
                key.current = { target: "", value: crypto.randomUUID() };
            }}
          >
            비교 실행
          </button>
        </div>
        {(inventories.data?.total ?? 0) > 10 && (
          <div className="pagination">
            <span>패키지 기록 {invPage + 1}페이지</span>
            <div>
              <button disabled={!invPage} onClick={() => setInvPage(invPage - 1)}>
                이전
              </button>
              <button
                disabled={(invPage + 1) * 10 >= (inventories.data?.total ?? 0)}
                onClick={() => setInvPage(invPage + 1)}
              >
                다음
              </button>
            </div>
          </div>
        )}
        {detail.data && (
          <div aria-live="polite">
            <p>
              {labels[detail.data.job.status]} ·{" "}
              {String(detail.data.job.result?.message ?? "처리 중입니다.")}
            </p>
            {detail.data.result && <ComparisonBody result={detail.data.result} />}
          </div>
        )}
        {!!history.data?.total && (
          <details className="inventory-format">
            <summary>자산 비교 이력 {history.data.total}건</summary>
            <div className="ai-history-list">
              {history.data.items.map((r) => (
                <button
                  className="ai-history-item"
                  key={r.id}
                  onClick={() => {
                    setSelected(r.id);
                    setPoll(true);
                  }}
                >
                  <span>
                    {formatKst(r.created_at)}
                    <small>기준 분석 {r.baseline_analysis_id.slice(0, 8)}</small>
                  </span>
                  <span>{labels[r.job.status]}</span>
                </button>
              ))}
            </div>
            <div className="pagination">
              <span>{page + 1}페이지</span>
              <div>
                <button disabled={!page} onClick={() => setPage(page - 1)}>
                  이전
                </button>
                <button
                  disabled={(page + 1) * 10 >= history.data.total}
                  onClick={() => setPage(page + 1)}
                >
                  다음
                </button>
              </div>
            </div>
          </details>
        )}
      </div>
    </section>
  );
}
function ComparisonBody({ result }: { result: ComparisonResult }) {
  const [onlyChanged, setOnlyChanged] = useState(true);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const rows = useMemo(
    () =>
      result.rows.filter(
        (r) =>
          (!onlyChanged || r.change !== "UNCHANGED") &&
          `${r.package_name} ${r.cve_id ?? ""}`.toLowerCase().includes(search.toLowerCase()),
      ),
    [result, onlyChanged, search],
  );
  return (
    <div>
      <ul>
        {result.warnings?.map((w) => (
          <li key={w}>{w}</li>
        ))}
      </ul>
      <p>
        이전 {formatKst(result.before_collected_at)} → 이후 {formatKst(result.after_collected_at)}
      </p>
      <p>
        {Object.entries(result.summary)
          .map(([k, v]) => `${labels[k]} ${v}건`)
          .join(" · ")}
      </p>
      <div className="collection-toolbar">
        <label>
          <input
            type="checkbox"
            checked={onlyChanged}
            onChange={(e) => {
              setOnlyChanged(e.target.checked);
              setPage(0);
            }}
          />{" "}
          변경된 결과만
        </label>
        <input
          aria-label="비교 결과 검색"
          value={search}
          maxLength={200}
          placeholder="패키지 또는 CVE 검색"
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(0);
          }}
        />
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>패키지 / CVE</th>
              <th>변화</th>
              <th>이전</th>
              <th>이후</th>
            </tr>
          </thead>
          <tbody>
            {rows.slice(page * 20, (page + 1) * 20).map((r, i) => (
              <tr key={i}>
                <td>
                  {r.package_name}
                  <small className="cell-sub">{r.cve_id ?? r.architecture ?? "처리 상태"}</small>
                </td>
                <td>{labels[r.change]}</td>
                {[r.before, r.after].map((side, index) => (
                  <td key={index}>
                    {side.length
                      ? side.map((f) => (
                          <div key={f.finding_id}>
                            {labels[f.verdict ?? f.processing_status] ?? f.processing_status}
                            <small className="cell-sub">{f.installed_version ?? "버전 없음"}</small>
                            <details>
                              <summary>이유</summary>
                              <ul>
                                {f.reasons?.map((reason) => (
                                  <li key={reason}>{reason}</li>
                                ))}
                              </ul>
                            </details>
                          </div>
                        ))
                      : "해당 입력 결과 없음"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!rows.length && <p>현재 조건에서 표시할 차이가 없습니다.</p>}
      <div className="pagination">
        <span>{rows.length}건</span>
        <div>
          <button disabled={!page} onClick={() => setPage(page - 1)}>
            이전
          </button>
          <button disabled={(page + 1) * 20 >= rows.length} onClick={() => setPage(page + 1)}>
            다음
          </button>
        </div>
      </div>
    </div>
  );
}
