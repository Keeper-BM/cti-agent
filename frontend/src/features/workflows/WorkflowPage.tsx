import { useCallback, useEffect, useRef, useState } from "react";
import { useSession } from "../../app/session";
import type { HttpClient } from "../../api/client";
import { Icon } from "../../shared/components/Icon";
import { Notice } from "../../shared/components/Notice";
import { usePollingQuery } from "../../shared/hooks/usePollingQuery";
import type { AssetList } from "../assets/api";
import {
  count,
  getWorkspace,
  reportLink,
  shortTime,
  startWorkflow,
  workspaceLink,
  type Workflow,
} from "./api";
import { Results } from "./Results";
import { RunRail, StageSpotlight, useRunReplay } from "./RunRail";
import { Sources, History } from "./WorkflowContext";

const connectionLabels = {
  verified: "SSH 인증 확인",
  configured: "SSH 설정됨",
  failed: "SSH 확인 실패",
  unconfigured: "SSH 미설정",
};

export function WorkflowPage({ asset, analysis }: { asset: string; analysis: string }) {
  const { api, isAdmin } = useSession();
  const [page, setPage] = useState(0);
  const [focus, setFocus] = useState(false);
  useEffect(() => {
    if (!focus) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFocus(false);
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [focus]);
  const load = useCallback(
    (signal: AbortSignal) =>
      api!.request<AssetList>(`/assets?limit=20&offset=${page * 20}&recent_analysis_first=true`, {
        signal,
      }),
    [api, page],
  );
  const assets = usePollingQuery(api ? load : null, null);
  const assetId = asset || assets.data?.items[0]?.id || "";
  return (
    <div className={focus ? "workflow-page focused-console" : "workflow-page"}>
      <Notice error={assets.error} />
      {api && assetId ? (
        <Console
          key={assetId + ":" + analysis}
          api={api}
          id={assetId}
          pinned={analysis}
          assets={assets.data}
          page={page}
          setPage={(n) => {
            setPage(n);
            window.location.hash = "/workspace";
          }}
          focus={focus}
          toggleFocus={() => setFocus(!focus)}
        />
      ) : (
        <section className="work-card welcome">
          <Icon name="assets" />
          <h2>{assets.data ? "첫 자산을 등록하세요" : "자산을 불러오는 중…"}</h2>
          {assets.data && isAdmin && (
            <a className="button-link primary-link" href="#/assets?new=1">
              <Icon name="plus" />
              자산 등록
            </a>
          )}
        </section>
      )}
    </div>
  );
}

function Console({
  api,
  id,
  pinned,
  assets,
  page,
  setPage,
  focus,
  toggleFocus,
}: {
  api: HttpClient;
  id: string;
  pinned: string;
  assets: AssetList | null;
  page: number;
  setPage: (n: number) => void;
  focus: boolean;
  toggleFocus: () => void;
}) {
  const { canWrite } = useSession();
  const [input, setInput] = useState<"ssh" | "saved" | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [requested, setRequested] = useState<Workflow | null>(null);
  const key = useRef({ input: "", value: "" });
  const load = useCallback(
    (signal: AbortSignal) => getWorkspace(api, id, pinned, signal),
    [api, id, pinned],
  );
  const query = usePollingQuery(load, null);
  const data = query.data;
  const awaiting =
    !pinned &&
    requested &&
    (!data?.latest ||
      (data.latest.id !== requested.id && data.latest.created_at <= requested.created_at));
  const run = awaiting ? requested : (data?.selection.workflow ?? null);
  const selected = awaiting ? null : (data?.selection.analysis ?? null);
  const busy = run?.status === "RUNNING";
  const pollMs = data?.latest?.status === "RUNNING" || busy ? 1800 : 15000;
  const refresh = query.refresh;
  useEffect(() => {
    const timer = window.setInterval(refresh, pollMs);
    return () => window.clearInterval(timer);
  }, [refresh, pollMs]);
  const locked = busy || data?.latest?.status === "RUNNING";
  const mode = input ?? (data?.profile_id ? "ssh" : "saved");
  const available = mode === "saved" ? !!data?.inventory : !!data?.profile_id;
  const assetInfo = data?.asset ?? assets?.items.find((item) => item.id === id);
  const replay = useRunReplay(run);
  const isReplaying = replay.index !== null;
  const showingStage = busy || isReplaying;
  const report = showingStage || sending ? null : selected?.report_id;
  const legacy = !!selected && !run;
  const recovery =
    run?.status === "FAILED"
      ? (data?.history.find((item) => item.id !== selected?.id && item.report_id) ??
        data?.history.find((item) => item.id !== selected?.id))
      : undefined;
  const release = selected
    ? selected.os_release
    : (data?.inventory?.os_release ?? assetInfo?.expected_release);
  async function start() {
    if (!data || locked || sending || !available || !canWrite || !data.asset.is_active) return;
    const inventory = mode === "saved" ? data.inventory!.inventory_id : null;
    const identity = id + ":" + (inventory ?? "ssh");
    if (key.current.input !== identity)
      key.current = { input: identity, value: crypto.randomUUID() };
    setSending(true);
    setError("");
    try {
      const result = await startWorkflow(api, id, inventory, key.current.value);
      setRequested(result);
      key.current = { input: "", value: "" };
      query.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "분석을 시작하지 못했습니다.");
      query.refresh();
    } finally {
      setSending(false);
    }
  }
  return (
    <div className="console">
      <section className="work-card asset-command" aria-label="분석 대상과 실행">
        <div className="asset-line">
          <div className="asset-identity">
            <span className="asset-glyph">
              <Icon name="assets" />
            </span>
            <div className="asset-description">
              <span className="field-caption">분석 대상</span>
              <label className="asset-picker">
                <span aria-hidden="true">{assetInfo?.asset_name ?? "자산 선택"}</span>
                <Icon name="chevron" />
                <select
                  aria-label="분석 대상 자산"
                  value={id}
                  onChange={(e) => {
                    window.location.hash = workspaceLink(e.target.value);
                  }}
                >
                  {assetInfo && !assets?.items.some((a) => a.id === id) && (
                    <option value={id}>{assetInfo.asset_name}</option>
                  )}
                  {assets?.items.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.asset_name}
                      {a.is_active ? "" : " (비활성)"}
                    </option>
                  ))}
                </select>
              </label>
              <div className="asset-meta">
                <span>{release ? "Ubuntu " + release : "OS 미확인"}</span>
                {assetInfo?.host && (
                  <>
                    <i /> <span>{assetInfo.host}</span>
                  </>
                )}
                {selected?.is_synthetic && <span>가상 입력</span>}
                <span className="scope-tag">Apache2 · MySQL 분석</span>
              </div>
            </div>
          </div>
          {!isReplaying && (
            <div className="asset-actions">
              {pinned ? (
                <a className="button-link secondary-link" href={workspaceLink(id)}>
                  {data?.latest?.status === "RUNNING" ? "진행 중인 실행 보기" : "최신 실행 보기"}
                </a>
              ) : (
                canWrite &&
                data &&
                (available ? (
                  <button
                    className={report ? "button-link secondary-link" : "button-link primary-link"}
                    disabled={locked || sending || !assetInfo?.is_active}
                    onClick={start}
                  >
                    <Icon
                      name={
                        locked
                          ? "activity"
                          : selected || run?.status === "FAILED"
                            ? "refresh"
                            : "play"
                      }
                    />
                    {locked
                      ? "분석 진행 중"
                      : sending
                        ? "요청 중…"
                        : selected || run?.status === "FAILED"
                          ? "다시 분석"
                          : "분석 시작"}
                  </button>
                ) : (
                  <a className="button-link secondary-link" href={`#/assets?asset=${id}&setup=ssh`}>
                    수집 설정
                  </a>
                ))
              )}
              {report && (
                <a className="button-link primary-link report-entrance" href={reportLink(report)}>
                  <Icon name="reports" />
                  대응 보고서 보기
                  <Icon name="arrow" />
                </a>
              )}
              {selected && !run && !report && canWrite && (
                <a className="button-link primary-link" href={"#/reports?analysis=" + selected.id}>
                  <Icon name="reports" />
                  보고서 생성
                </a>
              )}
            </div>
          )}
        </div>
        <div className="asset-tools">
          <div className="asset-connection">
            {data && (
              <>
                <span className={"ssh-state " + data.connection_status}>
                  <i />
                  {connectionLabels[data.connection_status]}
                </span>
                {data.connection_checked_at && (
                  <span>
                    마지막 확인{" "}
                    <time dateTime={data.connection_checked_at}>
                      {shortTime(data.connection_checked_at)}
                    </time>
                  </span>
                )}
                <a href={`#/assets?asset=${id}&setup=ssh`}>연결 설정</a>
              </>
            )}
          </div>
          <div className="display-tools">
            {!isReplaying && !pinned && canWrite && data && (
              <label className="input-option">
                <span className="sr-only">분석 입력</span>
                <select
                  value={mode}
                  disabled={locked || sending}
                  onChange={(e) => setInput(e.target.value as "ssh" | "saved")}
                >
                  <option value="ssh" disabled={!data.profile_id}>
                    SSH로 새로 수집
                  </option>
                  <option value="saved" disabled={!data.inventory}>
                    저장된 패키지 기록
                    {data.inventory ? " · " + count(data.inventory.package_count) + "개" : ""}
                    {data.inventory?.is_synthetic ? " · 가상 입력" : ""}
                  </option>
                </select>
              </label>
            )}
            <button className="text-tool" onClick={toggleFocus} aria-pressed={focus}>
              <Icon name={focus ? "close" : "scope"} />
              {focus ? "집중 보기 닫기" : "집중 보기"}
            </button>
          </div>
        </div>
        {assets && assets.total > 20 && (
          <div className="work-pager">
            <button disabled={page === 0} onClick={() => setPage(page - 1)}>
              이전 자산
            </button>
            <span>
              {page + 1} / {Math.ceil(assets.total / 20)}
            </span>
            <button disabled={(page + 1) * 20 >= assets.total} onClick={() => setPage(page + 1)}>
              다음 자산
            </button>
          </div>
        )}
      </section>
      <Notice error={error || query.error} />
      {run?.status === "FAILED" && (
        <section className="work-card workflow-recovery" aria-label="분석 실행 오류">
          <div>
            <strong role="alert">
              <Icon name="alert" /> {run.error || "분석이 중단되었습니다."}
            </strong>
            {recovery && <p>저장된 최근 완료 기록을 열어 판정과 근거를 확인할 수 있습니다.</p>}
          </div>
          {recovery && (
            <a className="button-link primary-link" href={workspaceLink(id, recovery.id)}>
              마지막 정상 분석 보기
              <Icon name="arrow" />
            </a>
          )}
        </section>
      )}
      {!data && query.error && (
        <div className="asset-actions">
          <button className="button-link secondary-link" onClick={query.refresh}>
            다시 불러오기
          </button>
          <a href={workspaceLink(id)}>최신 실행 보기</a>
        </div>
      )}
      {data && (
        <>
          {legacy ? (
            <div className="legacy-note">
              <Icon name="jobs" />
              <strong>개별 분석 기록</strong>
              <span>
                {shortTime(selected!.completed_at)} 저장 · 당시의 판정과 기준 자료를 표시합니다.
              </span>
            </div>
          ) : (
            <RunRail run={run} replay={replay} />
          )}
          <div className="console-grid" data-replaying={isReplaying || undefined}>
            <div className="primary-column">
              {run && showingStage && (
                <StageSpotlight
                  key={run.id}
                  run={run}
                  analysis={selected}
                  replayIndex={replay.index}
                />
              )}
              {selected && (
                <div className="run-outcome" hidden={showingStage}>
                  <Results key={selected.id} api={api} analysis={selected} />
                </div>
              )}
              {!selected && !showingStage && (
                <section className="work-card empty-results" role="status">
                  <span className="empty-symbol">
                    <Icon name={run?.status === "FAILED" ? "alert" : "shield"} />
                  </span>
                  <h2>
                    {run?.status === "FAILED" ? "분석이 중단되었습니다" : "첫 분석을 시작하세요"}
                  </h2>
                  <p>
                    {run?.status === "FAILED"
                      ? "실행 단계와 오류를 확인한 후 다시 요청할 수 있습니다."
                      : available
                        ? "패키지를 수집하고 공식 기준과 대조하면 이곳에 결과가 표시됩니다."
                        : "SSH 연결을 설정하거나 패키지 기록을 등록하세요."}
                  </p>
                </section>
              )}
            </div>
            <aside className="workspace-aside" hidden={isReplaying}>
              <Sources
                key={run?.id ?? selected?.id ?? "idle"}
                api={api}
                run={run}
                selected={selected}
              />
              <History items={data.history} asset={id} selected={selected?.id ?? ""} />
            </aside>
          </div>
        </>
      )}
    </div>
  );
}
