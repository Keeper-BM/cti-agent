import { useCallback, useRef, useState } from "react";
import type { HttpClient } from "../../api/client";
import { useSession } from "../../app/session";
import { Icon } from "../../shared/components/Icon";
import { Notice } from "../../shared/components/Notice";
import { useAction } from "../../shared/hooks/useAction";
import { usePollingQuery } from "../../shared/hooks/usePollingQuery";
import { listAssets, type AssetList } from "../assets/api";
import { batchLink, startBatch } from "../batches/api";
import { count, getWorkspace, startWorkflow, workspaceLink } from "./api";

const pageSize = 20;
const selectionLimit = 20;
type Asset = AssetList["items"][number];
type InputMode = "ssh" | "saved";

export function TargetSelection({ api }: { api: HttpClient }) {
  const { canWrite, capabilities } = useSession();
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<Asset[]>([]);
  const [input, setInput] = useState<{ asset: string; mode: InputMode }>();
  const action = useAction();
  const requestKey = useRef<{ input: string; key: string } | null>(null);
  const loadAssets = useCallback(
    (signal: AbortSignal) => listAssets(api, page * pageSize, signal),
    [api, page],
  );
  const assets = usePollingQuery(loadAssets, null);
  const pageAssets = assets.data?.items ?? [];
  const selectedIds = new Set(selected.map((asset) => asset.id));
  const activePageAssets = pageAssets.filter((asset) => asset.is_active);
  const remainingPageAssets = activePageAssets.filter((asset) => !selectedIds.has(asset.id));
  const allPageSelected = activePageAssets.length > 0 && remainingPageAssets.length === 0;
  const somePageSelected = !allPageSelected && remainingPageAssets.length < activePageAssets.length;
  const pageWouldExceedLimit = selected.length + remainingPageAssets.length > selectionLimit;
  const assetId = selected.length === 1 ? selected[0].id : "";
  const loadSingle = useCallback(
    (signal: AbortSignal) => getWorkspace(api, assetId, "", signal),
    [api, assetId],
  );
  const single = usePollingQuery(assetId ? loadSingle : null, null);
  const target = single.data?.asset.id === assetId ? single.data : null;
  const wantsSaved = input?.asset === assetId && input.mode === "saved";
  const mode = target?.profile_id && !(wantsSaved && target.inventory) ? "ssh" : "saved";
  const hasInput = !!(target?.profile_id || target?.inventory);
  const running = target?.latest?.status === "RUNNING";
  const isBatch = selected.length > 1;
  const canStart =
    canWrite && !action.pending && (isBatch || (target?.asset.is_active && !running && hasInput));
  const needsSetup = isBatch ? selected.filter((asset) => !asset.ssh_configured).length : 0;

  function selectPage(checked: boolean) {
    if (checked) {
      if (!pageWouldExceedLimit) setSelected([...selected, ...remainingPageAssets]);
    } else {
      const pageIds = new Set(pageAssets.map((asset) => asset.id));
      setSelected(selected.filter((asset) => !pageIds.has(asset.id)));
    }
  }

  async function submit() {
    if (!canStart) return;
    const ids = selected.map((asset) => asset.id).sort();
    const inventory = mode === "saved" ? (target?.inventory?.inventory_id ?? null) : null;
    const identity = isBatch ? ids.join(",") : assetId + ":" + (inventory ?? "ssh");
    if (requestKey.current?.input !== identity) {
      requestKey.current = { input: identity, key: crypto.randomUUID() };
    }
    const { key } = requestKey.current;
    await action.run(async () => {
      if (isBatch) {
        const batch = await startBatch(api, ids, key);
        window.location.hash = batchLink(batch.id);
      } else {
        const run = await startWorkflow(api, assetId, inventory, key);
        window.location.hash = workspaceLink(run.asset_id);
      }
    }, "선택한 자산의 분석을 요청했습니다.");
  }

  return (
    <section className="target-selection" aria-labelledby="target-selection-title">
      <div className="target-heading">
        <div>
          <h2 id="target-selection-title">{canWrite ? "분석 대상 선택" : "자산별 분석"}</h2>
          {canWrite && <p>점검할 자산을 최대 {selectionLimit}대까지 선택하세요.</p>}
        </div>
        <div className="schedule-actions">
          {assets.data && <span className="target-total">등록 자산 {assets.data.total}대</span>}
          {canWrite && capabilities?.features.workflow_schedules && (
            <a href="#/schedules" className="button-link secondary-link">
              <Icon name="jobs" /> 분석 예약
            </a>
          )}
        </div>
      </div>
      <Notice error={assets.error} />
      {pageAssets.length ? (
        <div>
          {canWrite && (
            <div className="target-list-toolbar">
              <label>
                <input
                  type="checkbox"
                  className="target-check"
                  checked={allPageSelected}
                  disabled={
                    action.pending ||
                    assets.loading ||
                    !activePageAssets.length ||
                    pageWouldExceedLimit
                  }
                  aria-controls="target-asset-list"
                  aria-describedby={pageWouldExceedLimit ? "target-selection-limit" : undefined}
                  ref={(checkbox) => {
                    if (checkbox) checkbox.indeterminate = somePageSelected;
                  }}
                  onChange={(event) => selectPage(event.currentTarget.checked)}
                />
                {(assets.data?.total ?? 0) > pageSize ? "현재 페이지 모두 선택" : "모두 선택"}
              </label>
              {pageWouldExceedLimit && (
                <span id="target-selection-limit">
                  최대 {selectionLimit}대까지 선택할 수 있습니다. 일부 선택을 해제하세요.
                </span>
              )}
            </div>
          )}
          <ul
            id="target-asset-list"
            className="target-rows"
            aria-labelledby="target-selection-title"
          >
            {pageAssets.map((asset) => {
              const checked = selectedIds.has(asset.id);
              const name = (
                <span className="target-name">
                  <strong>{asset.asset_name}</strong>
                  {(asset.expected_release || asset.host) && (
                    <small>
                      {[asset.expected_release && `Ubuntu ${asset.expected_release}`, asset.host]
                        .filter(Boolean)
                        .join(" · ")}
                    </small>
                  )}
                </span>
              );
              return (
                <li key={asset.id} className={checked ? "chosen" : undefined}>
                  {canWrite ? (
                    <label className="target-option">
                      <input
                        type="checkbox"
                        className="target-check"
                        aria-label={`${asset.asset_name} 분석 대상 선택`}
                        checked={checked}
                        disabled={
                          action.pending ||
                          (!checked && (!asset.is_active || selected.length >= selectionLimit))
                        }
                        onChange={(event) => {
                          const next = event.currentTarget.checked;
                          setSelected((items) =>
                            next ? [...items, asset] : items.filter((item) => item.id !== asset.id),
                          );
                        }}
                      />
                      {name}
                    </label>
                  ) : (
                    <a className="target-option" href={workspaceLink(asset.id)}>
                      {name}
                    </a>
                  )}
                  <div className="target-row-actions">
                    <span
                      className={
                        asset.is_active && asset.ssh_configured ? "batch-state" : "batch-review"
                      }
                    >
                      {!asset.is_active
                        ? "비활성"
                        : asset.ssh_configured
                          ? "SSH 설정됨"
                          : "SSH 미설정"}
                    </span>
                    {canWrite && asset.is_active && !asset.ssh_configured && (
                      <a
                        href={`#/assets?asset=${asset.id}&setup=ssh`}
                        aria-label={`${asset.asset_name} SSH 설정`}
                      >
                        연결 설정
                      </a>
                    )}
                    {canWrite && asset.last_analysis_at && (
                      <a
                        href={workspaceLink(asset.id)}
                        aria-label={`${asset.asset_name} 분석 보기`}
                      >
                        분석 보기
                      </a>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      ) : assets.error ? (
        <button
          className="button-link secondary-link"
          disabled={assets.loading}
          onClick={assets.refresh}
        >
          <Icon name="refresh" /> {assets.loading ? "다시 불러오는 중…" : "다시 불러오기"}
        </button>
      ) : (
        <p className="target-note" role="status">
          {assets.data ? "등록된 자산이 없습니다." : "자산 목록을 불러오는 중…"}
        </p>
      )}
      {assets.data && assets.data.total > pageSize && (
        <div className="work-pager" aria-label="분석 대상 자산 페이지">
          <button disabled={page === 0 || action.pending} onClick={() => setPage(page - 1)}>
            이전 자산
          </button>
          <span>
            {page + 1} / {Math.ceil(assets.data.total / pageSize)}
          </span>
          <button
            disabled={(page + 1) * pageSize >= assets.data.total || action.pending}
            onClick={() => setPage(page + 1)}
          >
            다음 자산
          </button>
        </div>
      )}
      {canWrite && (assets.data?.total || selected.length) > 0 && (
        <>
          <Notice error={action.error || single.error} />
          {needsSetup > 0 && (
            <p className="target-note target-warning" role="status">
              SSH가 미설정된 {needsSetup}대는 보고서에 수집 실패로 기록됩니다.
            </p>
          )}
          <div className="target-bar">
            <div className="target-count">
              <strong aria-live="polite">선택 {selected.length}대</strong>
              {selected.length > 0 && (
                <button
                  className="text-button"
                  disabled={action.pending}
                  onClick={() => setSelected([])}
                >
                  선택 해제
                </button>
              )}
            </div>
            <div className="target-execute">
              {assetId &&
                !target &&
                (single.error ? (
                  <button
                    className="button-link secondary-link"
                    disabled={single.loading}
                    onClick={single.refresh}
                  >
                    다시 불러오기
                  </button>
                ) : (
                  <span className="activity-status" data-moving="true" role="status">
                    수집 방식 확인 중…
                  </span>
                ))}
              {target &&
                (!target.asset.is_active ? (
                  <span>비활성 자산</span>
                ) : running ? (
                  <a className="asset-open-link" href={workspaceLink(assetId)}>
                    진행 중인 분석 보기
                  </a>
                ) : hasInput ? (
                  <label className="input-option">
                    <span className="sr-only">분석 입력</span>
                    <select
                      value={mode}
                      disabled={action.pending}
                      onChange={(event) =>
                        setInput({ asset: assetId, mode: event.target.value as InputMode })
                      }
                    >
                      <option value="ssh" disabled={!target.profile_id}>
                        SSH로 새로 수집
                      </option>
                      <option value="saved" disabled={!target.inventory}>
                        저장된 패키지 기록
                        {target.inventory
                          ? " · " + count(target.inventory.package_count) + "개"
                          : ""}
                        {target.inventory?.is_synthetic ? " · 가상 입력" : ""}
                      </option>
                    </select>
                  </label>
                ) : (
                  <a className="asset-open-link" href={`#/assets?asset=${assetId}&setup=ssh`}>
                    수집 설정
                  </a>
                ))}
              {isBatch && <span>SSH로 새로 수집 · 통합 보고서</span>}
              <button className="button-link primary-link" disabled={!canStart} onClick={submit}>
                <Icon name="play" />
                {action.pending ? "요청 중…" : isBatch ? "일괄 분석 실행" : "분석 실행"}
              </button>
            </div>
          </div>
        </>
      )}
    </section>
  );
}
