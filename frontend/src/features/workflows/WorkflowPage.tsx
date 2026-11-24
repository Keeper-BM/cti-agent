import { useCallback, useEffect, useState } from "react";
import { useSession } from "../../app/session";
import type { HttpClient } from "../../api/client";
import { Icon } from "../../shared/components/Icon";
import { Notice } from "../../shared/components/Notice";
import { usePollingQuery } from "../../shared/hooks/usePollingQuery";
import { getWorkspace, reportLink, shortTime, workspaceLink } from "./api";
import { Results } from "./Results";
import { RunRail, useRunReplay } from "./RunRail";
import { StageSpotlight } from "./StageSpotlight";
import { Sources, History } from "./WorkflowContext";
import { SourceRefresh } from "./SourceRefresh";
import { TargetSelection } from "./TargetSelection";

const connectionLabels = {
  verified: "SSH 인증 확인",
  configured: "SSH 설정됨",
  failed: "SSH 확인 실패",
  unconfigured: "SSH 미설정",
};

export function WorkflowPage({ asset, analysis }: { asset: string; analysis: string }) {
  const { api } = useSession();
  if (!api) return null;
  return asset ? (
    <AnalysisView key={asset + ":" + analysis} api={api} id={asset} pinned={analysis} />
  ) : (
    <TargetSelection api={api} />
  );
}

function WorkspaceStatus({
  title,
  detail,
  loading,
  retry,
  latest,
}: {
  title: string;
  detail: string;
  loading: boolean;
  retry?: () => void;
  latest?: string;
}) {
  return (
    <section className="work-card workspace-load">
      <div role={retry && !loading ? "alert" : "status"}>
        <Icon name={retry && !loading ? "alert" : "activity"} />
        <div>
          <h2>{title}</h2>
          <p>{detail}</p>
        </div>
      </div>
      {retry && (
        <div className="toolbar-actions">
          <button className="button-link secondary-link" disabled={loading} onClick={retry}>
            <Icon name="refresh" /> {loading ? "다시 불러오는 중…" : "다시 불러오기"}
          </button>
          {latest && (
            <a className="text-tool" href={latest}>
              최신 실행 보기
            </a>
          )}
        </div>
      )}
      {(!retry || loading) && <div className="activity-track" aria-hidden="true" />}
    </section>
  );
}

function AnalysisView({ api, id, pinned }: { api: HttpClient; id: string; pinned: string }) {
  const { canWrite } = useSession();
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
    (signal: AbortSignal) => getWorkspace(api, id, pinned, signal),
    [api, id, pinned],
  );
  const query = usePollingQuery(load, null);
  const data = query.data;
  const run = data?.selection.workflow ?? null;
  const selected = data?.selection.analysis ?? null;
  const busy = run?.status === "RUNNING";
  const pollMs = data?.latest?.status === "RUNNING" || busy ? 1800 : 15000;
  const refresh = query.refresh;
  useEffect(() => {
    const timer = window.setInterval(refresh, pollMs);
    return () => window.clearInterval(timer);
  }, [refresh, pollMs]);
  const replay = useRunReplay(run);
  const isReplaying = replay.index !== null;
  const showingStage = busy || isReplaying;
  const report = showingStage ? null : selected?.report_id;
  const legacy = !!selected && !run;
  const recovery =
    run?.status === "FAILED"
      ? (data?.history.find((item) => item.id !== selected?.id && item.report_id) ??
        data?.history.find((item) => item.id !== selected?.id))
      : undefined;
  const release = selected
    ? selected.os_release
    : (data?.inventory?.os_release ?? data?.asset.expected_release);
  return (
    <div className={focus ? "console focused-console" : "console"}>
      <header className="run-header">
        <div className="run-identity">
          {!focus && !isReplaying && (
            <a className="run-back" href={workspaceLink()}>
              <Icon name="arrow" /> 분석 대상 선택
            </a>
          )}
          <h2>{data?.asset.asset_name ?? "자산 분석"}</h2>
          {data && (
            <div className="asset-meta">
              {release && <span>Ubuntu {release}</span>}
              {data.asset.host && <span>{data.asset.host}</span>}
              {selected?.is_synthetic && <span>가상 입력</span>}
              <span className={"ssh-state " + data.connection_status}>
                <i />
                {data.connection_status === "verified" &&
                data.connection_check_scope === "PACKAGE_READ"
                  ? "SSH 패키지 조회 확인"
                  : connectionLabels[data.connection_status]}
              </span>
              {data.connection_checked_at && (
                <time dateTime={data.connection_checked_at}>
                  확인 {shortTime(data.connection_checked_at)}
                </time>
              )}
              {canWrite && !focus && <a href={`#/assets?asset=${id}&setup=ssh`}>연결 설정</a>}
            </div>
          )}
        </div>
        <div className="asset-actions">
          {!isReplaying && pinned && (
            <a className="button-link secondary-link" href={workspaceLink(id)}>
              {data?.latest?.status === "RUNNING" ? "진행 중인 실행 보기" : "최신 실행 보기"}
            </a>
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
          {data && (
            <button className="text-tool" onClick={() => setFocus(!focus)} aria-pressed={focus}>
              <Icon name={focus ? "close" : "scope"} />
              {focus ? "집중 보기 닫기" : "집중 보기"}
            </button>
          )}
        </div>
      </header>
      <Notice error={data ? query.error : ""} />
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
      {!data && (
        <WorkspaceStatus
          title={query.error ? "분석 정보를 불러오지 못했습니다" : "분석 정보를 불러오는 중…"}
          detail={query.error || "SSH 연결 설정과 최근 분석 기록을 조회하고 있습니다."}
          loading={query.loading}
          retry={query.error ? query.refresh : undefined}
          latest={pinned ? workspaceLink(id) : undefined}
        />
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
          {run && showingStage && (
            <StageSpotlight
              key={run.id}
              run={run}
              analysis={selected}
              replayIndex={replay.index}
              advancing={replay.advancing}
            />
          )}
          {run && !showingStage && (
            <div className="work-card workflow-refresh">
              <SourceRefresh sources={run.sources} />
            </div>
          )}
          <div className="console-grid" hidden={showingStage}>
            <div className="primary-column">
              {selected && (
                <div className="run-outcome">
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
                      : data.inventory || data.profile_id
                        ? "패키지를 수집하고 공식 기준과 대조하면 이곳에 결과가 표시됩니다."
                        : "SSH 연결을 설정하거나 패키지 기록을 등록하세요."}
                  </p>
                </section>
              )}
            </div>
            <aside className="workspace-aside">
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
