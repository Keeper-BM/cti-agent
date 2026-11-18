import { useCallback, useEffect, useRef, useState } from "react";
import { useSession } from "../../app/session";
import type { HttpClient } from "../../api/client";
import { Icon } from "../../shared/components/Icon";
import { Notice } from "../../shared/components/Notice";
import { usePollingQuery } from "../../shared/hooks/usePollingQuery";
import type { AssetList } from "../assets/api";
import { getAnalysis } from "../findings/api";
import {
  count,
  getWorkspace,
  routeParam,
  shortTime,
  sourceNames,
  startWorkflow,
  type Brief,
  type Workflow,
  type Workspace,
} from "./api";
import { Results } from "./Results";
import { RunRail } from "./RunRail";

const connectionLabels = {
  verified: "SSH 인증 확인",
  configured: "SSH 설정됨",
  failed: "SSH 연결 확인 필요",
  unconfigured: "SSH 미설정",
};
const sourceLabels = {
  UPDATED: "갱신 완료",
  CACHED: "저장본 사용",
  FAILED: "갱신 실패",
  QUEUED: "조회 대기",
  RUNNING: "조회 중",
} as const;

export function WorkflowPage() {
  const { api, isAdmin } = useSession();
  const [chosen, setChosen] = useState(() => routeParam("asset"));
  const [page, setPage] = useState(0);
  const load = useCallback(
    (signal: AbortSignal) =>
      api!.request<AssetList>(`/assets?limit=20&offset=${page * 20}&recent_analysis_first=true`, {
        signal,
      }),
    [api, page],
  );
  const assets = usePollingQuery(api ? load : null, null);
  const assetId = chosen || assets.data?.items[0]?.id || "";
  return (
    <div className="workflow-page">
      <Notice error={assets.error} />
      {assetId && api ? (
        <Console
          key={assetId}
          api={api}
          id={assetId}
          assets={assets.data}
          page={page}
          setPage={(p) => {
            setPage(p);
            setChosen("");
          }}
          choose={(id) => {
            setChosen(id);
            window.history.replaceState(null, "", `#/workspace?asset=${id}`);
          }}
        />
      ) : (
        <section className="work-card welcome">
          <span className="welcome-icon">
            <Icon name="assets" />
          </span>
          <h2>{assets.data ? "첫 자산을 등록하세요" : "자산을 불러오는 중"}</h2>
          {assets.data && (
            <>
              <p>서버를 등록하고 SSH 연결을 설정하면 패키지 수집과 분석을 시작할 수 있습니다.</p>
              {isAdmin && (
                <a className="button-link" href="#/assets?new=1">
                  <Icon name="plus" />
                  자산 등록
                </a>
              )}
            </>
          )}
        </section>
      )}
    </div>
  );
}

function Console({
  api,
  id,
  assets,
  choose,
  page,
  setPage,
}: {
  api: HttpClient;
  id: string;
  assets: AssetList | null;
  choose: (id: string) => void;
  page: number;
  setPage: (n: number) => void;
}) {
  const { canWrite } = useSession();
  const [input, setInput] = useState<"ssh" | "saved" | null>(null);
  const [sending, setSending] = useState(false),
    [error, setError] = useState("");
  const [requested, setRequested] = useState<Workflow | null>(null);
  const [selectedHistory, setSelectedHistory] = useState("");
  const [focus, setFocus] = useState(false);
  const key = useRef({ input: "", value: "" });
  const load = useCallback((signal: AbortSignal) => getWorkspace(api, id, signal), [api, id]);
  const query = usePollingQuery(load, 1800);
  const data = query.data;
  const run =
    requested && (!data?.latest || requested.created_at > data.latest.created_at)
      ? requested
      : (data?.latest ?? null);
  const busy = run?.status === "RUNNING";
  const mode = input ?? (data?.profile_id ? "ssh" : "saved");
  const available = mode === "saved" ? !!data?.inventory : !!data?.profile_id;
  const history = data?.history ?? [];
  const selected = history.find((a) => a.id === selectedHistory) ?? history[0];
  const info = assets?.items.find((a) => a.id === id) ?? data?.asset;
  useEffect(() => {
    if (!focus) return;
    const close = (e: KeyboardEvent) => {
      if (e.key === "Escape") setFocus(false);
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [focus]);
  async function start() {
    if (!data || busy || sending || !available || !canWrite) return;
    const inventory = mode === "saved" ? data.inventory!.inventory_id : null;
    const identity = `${id}:${inventory ?? "ssh"}`;
    if (key.current.input !== identity)
      key.current = { input: identity, value: crypto.randomUUID() };
    setSending(true);
    setError("");
    try {
      const result = await startWorkflow(api, id, inventory, key.current.value);
      setRequested(result);
      setSelectedHistory("");
      key.current = { input: "", value: "" };
    } catch (e) {
      setError(e instanceof Error ? e.message : "분석을 시작하지 못했습니다.");
    } finally {
      setSending(false);
      query.refresh();
    }
  }
  return (
    <div className={focus ? "console focused-console" : "console"}>
      <div className="asset-command">
        <div className="command-top">
          <div className="command-label">
            <span className="target-cross">
              <Icon name="scope" />
            </span>
            분석 대상
          </div>
          <button className="focus-tool" onClick={() => setFocus(!focus)} aria-pressed={focus}>
            <Icon name={focus ? "close" : "scope"} />
            {focus ? "집중 보기 닫기" : "집중 보기"}
          </button>
        </div>
        <div className="command-body">
          <div className="asset-block">
            <label className="asset-picker">
              <span className="sr-only">분석 대상 자산</span>
              <span aria-hidden="true">{info?.asset_name ?? "자산 선택"}</span>
              <Icon name="chevron" />
              <select
                aria-label="분석 대상 자산"
                value={id}
                onChange={(e) => choose(e.target.value)}
              >
                {info && !assets?.items.some((a) => a.id === id) && (
                  <option value={id}>{info.asset_name}</option>
                )}
                {assets?.items.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.asset_name}
                    {a.is_active ? "" : " (비활성)"}
                  </option>
                ))}
              </select>
            </label>
            {!!assets && assets.total > 20 && (
              <div className="asset-pages">
                <button disabled={page === 0} onClick={() => setPage(page - 1)}>
                  이전 자산
                </button>
                <span>
                  {page + 1}/{Math.ceil(assets.total / 20)}
                </span>
                <button
                  disabled={(page + 1) * 20 >= assets.total}
                  onClick={() => setPage(page + 1)}
                >
                  다음 자산
                </button>
              </div>
            )}
            <div className="asset-meta">
              <span>
                <Icon name="assets" />
                {data?.inventory?.os_release || info?.expected_release
                  ? `Ubuntu ${data?.inventory?.os_release ?? info?.expected_release}`
                  : "OS 미확인"}
              </span>
              <span className="host-name">{info?.host ?? "호스트 미등록"}</span>
            </div>
            <div className="connection-controls">
              {data && (
                <span
                  className={`asset-state ${data.connection_status}`}
                  title={
                    data.connection_checked_at ? shortTime(data.connection_checked_at) : undefined
                  }
                >
                  <i />
                  {connectionLabels[data.connection_status]}
                </span>
              )}
              <a href={`#/assets?asset=${id}&setup=ssh`}>
                연결 설정 <Icon name="external" />
              </a>
            </div>
          </div>
          <RunRail run={run} loading={!data} />
        </div>
        <div className="command-bottom">
          <div className="input-choice">
            <label>
              분석 입력
              <select
                value={mode}
                disabled={busy || sending || !data}
                onChange={(e) => {
                  setInput(e.target.value as "ssh" | "saved");
                  setError("");
                }}
              >
                <option value="ssh" disabled={!data?.profile_id}>
                  SSH로 새로 수집
                </option>
                <option value="saved" disabled={!data?.inventory}>
                  저장된 패키지 기록
                </option>
              </select>
            </label>
            <span>
              {data?.inventory && mode === "saved"
                ? `${shortTime(data.inventory.collected_at)} · ${count(data.inventory.package_count)}개${data.inventory.is_synthetic ? " · 가상 입력" : ""}`
                : mode === "ssh"
                  ? "설치 패키지 수집 및 공식 파일 대조"
                  : data
                    ? "패키지 입력이 필요합니다."
                    : "정보를 확인하고 있습니다."}
            </span>
          </div>
          {data && !available && canWrite ? (
            <a className="start-button" href={`#/assets?asset=${id}&setup=ssh`}>
              수집 설정 <Icon name="arrow" />
            </a>
          ) : (
            <button
              className="start-button"
              onClick={start}
              disabled={!available || !data?.asset.is_active || busy || sending || !canWrite}
            >
              <Icon name={busy ? "activity" : "play"} />
              {busy
                ? "분석 진행 중"
                : sending
                  ? "요청 중…"
                  : run?.status === "FAILED"
                    ? "다시 분석"
                    : "분석 시작"}
            </button>
          )}
        </div>
      </div>
      <Notice error={error || query.error || run?.error || ""} />
      {!data && query.error && (
        <button className="secondary" onClick={query.refresh}>
          다시 불러오기
        </button>
      )}
      {data && (
        <div className="console-grid">
          <div className="primary-column">
            {selected ? (
              <Results
                key={selected.id}
                api={api}
                analysis={selected}
                previous={
                  selected.id !== history[0]?.id || !!(run && run.analysis_id !== selected.id)
                }
              />
            ) : (
              <section className="work-card empty-results">
                <Icon name="shield" />
                <h2>{busy ? "분석 결과를 기다리고 있습니다" : "완료된 분석이 없습니다"}</h2>
                <p>
                  {busy
                    ? "패키지와 공식 자료를 대조하면 이곳에 판정과 권고 조치가 표시됩니다."
                    : available
                      ? "분석을 시작하면 패키지별 판정과 대응 보고서가 이곳에 표시됩니다."
                      : "SSH 연결을 설정하거나 패키지 기록을 입력하세요."}
                </p>
              </section>
            )}
          </div>
          <aside className="workspace-aside">
            <Sources api={api} run={run} selected={selected} />
            <History items={history} selected={selected?.id ?? ""} choose={setSelectedHistory} />
          </aside>
        </div>
      )}
    </div>
  );
}

function Sources({
  api,
  run,
  selected,
}: {
  api: HttpClient;
  run: Workflow | null;
  selected?: Brief;
}) {
  const active =
    run?.status === "RUNNING" ||
    run?.status === "FAILED" ||
    !!(run?.analysis_id && run.analysis_id === selected?.id);
  const id = active ? "" : (selected?.id ?? "");
  const load = useCallback((signal: AbortSignal) => getAnalysis(api, id, signal), [api, id]);
  const query = usePollingQuery(id ? load : null, null);
  const sources = active
    ? (run?.sources ?? [])
    : (query.data?.sources ?? []).map((s) => ({
        source: s.source_id,
        scope: s.scope_key,
        job_id: s.job_id,
        status: "PINNED" as const,
        records: s.record_count,
        captured_at: s.captured_at,
      }));
  const warnings = active ? (run?.warnings ?? []) : (query.data?.warnings ?? []);
  const [expanded, setExpanded] = useState(false);
  const groups = new Set(sources.map((s) => s.source));
  return (
    <section className="work-card source-card">
      <div className="card-top">
        <h3>
          <Icon name="database" />
          {active ? "이번 실행 자료" : "분석 기준 자료"}
        </h3>
        <span className="quiet-count">{groups.size}개 출처</span>
      </div>
      {active && run?.verification_note && (
        <p className="proof-summary">
          <Icon name="package" />
          {run.verification_note}
        </p>
      )}
      <Notice error={query.error} />
      {!sources.length ? (
        <p className="aside-empty">
          {active && run?.stage === "inventory"
            ? "패키지 확인 후 출처를 선택합니다."
            : "표시할 자료가 없습니다."}
        </p>
      ) : (
        <ul className="source-list">
          {[...groups].map((source) => {
            const items = sources.filter((s) => s.source === source);
            const bad = items.find((s) => ["FAILED", "CACHED"].includes(s.status));
            const live = items.find((s) => ["RUNNING", "QUEUED"].includes(s.status));
            const state = (bad ?? live ?? items[0]).status;
            const title = state === "PINNED" ? "기준본" : sourceLabels[state];
            const n = items.reduce((a, s) => a + (s.records ?? 0), 0);
            return (
              <li key={source}>
                <span className={`source-glyph sg-${source}`}>
                  {(
                    { ubuntu: "U", kev: "K", nvd: "N", apache: "A", oracle: "O" } as Record<
                      string,
                      string
                    >
                  )[source] ?? "·"}
                </span>
                <span>
                  <b>{sourceNames[source] ?? source}</b>
                  <small>
                    {items.length}개 기준 · {count(n)}건
                  </small>
                </span>
                <span className={`source-state st-${state.toLowerCase()}`}>{title}</span>
              </li>
            );
          })}
        </ul>
      )}
      {(sources.length > 0 || warnings.length > 0) && (
        <div className="source-details">
          <button onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>
            자료 시각 및 제한 사항 <Icon name="chevron" />
          </button>
          {expanded && (
            <div>
              {sources.map((s) => (
                <p key={s.job_id}>
                  <strong>
                    {sourceNames[s.source]} · {s.scope}
                  </strong>
                  {s.captured_at ? shortTime(s.captured_at) : "기준 시각 미확정"}
                </p>
              ))}
              {warnings.map((w) => (
                <p key={w}>{w}</p>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
function History({
  items,
  selected,
  choose,
}: {
  items: Workspace["history"];
  selected: string;
  choose: (id: string) => void;
}) {
  return (
    <section className="work-card history-card">
      <div className="card-top">
        <h3>
          <Icon name="jobs" />
          최근 분석
        </h3>
      </div>
      {items.length ? (
        <ul>
          {items.slice(0, 4).map((h) => (
            <li key={h.id}>
              <button aria-pressed={selected === h.id} onClick={() => choose(h.id)}>
                <i />
                <span>
                  <b>{shortTime(h.completed_at)}</b>
                  <small>평가 결과 {count(h.summary.TOTAL ?? 0)}건</small>
                </span>
                <Icon name="arrow" />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="aside-empty">완료된 분석이 여기에 쌓입니다.</p>
      )}
    </section>
  );
}
