import { useCallback, useState } from "react";
import type { HttpClient } from "../../api/client";
import { useSession } from "../../app/session";
import { Icon } from "../../shared/components/Icon";
import { Notice } from "../../shared/components/Notice";
import { formatKstWithYear } from "../../shared/format";
import { useAction } from "../../shared/hooks/useAction";
import { usePollingQuery } from "../../shared/hooks/usePollingQuery";
import { batchLink } from "../batches/api";
import { ReportPages } from "../reports/ReportPreview";
import {
  getSchedule,
  listScheduleRuns,
  listSchedules,
  runPageSize,
  scheduleLink,
  schedulePageSize,
  setScheduleEnabled,
  type Schedule,
  type ScheduleRun,
} from "./api";
import { ScheduleChangesPanel } from "./ScheduleChanges";
import { ScheduleForm, weekdays } from "./ScheduleForm";
import "./schedules.css";

const runStatus = {
  RUNNING: "실행 중",
  COMPLETED: "완료",
  PARTIAL: "일부 실패",
  FAILED: "실패",
  SKIPPED: "건너뜀",
};

function recurrence(schedule: Schedule) {
  const period = schedule.weekday === null ? "매일" : `매주 ${weekdays[schedule.weekday]}요일`;
  return `${period} ${schedule.local_time} KST`;
}

export function SchedulePage({ id, create, edit }: { id: string; create: boolean; edit: boolean }) {
  const { api, canWrite, capabilities } = useSession();
  if (!api) return null;
  if (!capabilities?.features.workflow_schedules)
    return <Notice error="서버에서 분석 예약을 사용할 수 없습니다." />;
  if (id) return <ScheduleDetail api={api} id={id} canWrite={canWrite} edit={edit} />;
  if (create && canWrite) return <ScheduleForm api={api} />;
  return <ScheduleList api={api} canWrite={canWrite} />;
}

function ScheduleList({ api, canWrite }: { api: HttpClient; canWrite: boolean }) {
  const [page, setPage] = useState(0);
  const load = useCallback((signal: AbortSignal) => listSchedules(api, page, signal), [api, page]);
  const query = usePollingQuery(load, 15000);
  return (
    <section className="work-card schedule-card" aria-labelledby="schedule-list-title">
      <header className="schedule-heading">
        <h2 id="schedule-list-title">예약 목록</h2>
        <div className="schedule-actions">
          <button
            className="button-link secondary-link schedule-refresh"
            disabled={query.loading}
            onClick={query.refresh}
            aria-label="예약 목록 새로고침"
          >
            <Icon name="refresh" />
          </button>
          {canWrite && (
            <a className="button-link primary-link" href="#/schedules?new=1">
              <Icon name="plus" /> 새 예약
            </a>
          )}
        </div>
      </header>
      <Notice error={query.error} />
      {query.data?.items.length ? (
        <ul className="schedule-list">
          {query.data.items.map((schedule) => (
            <li key={schedule.id}>
              <a href={scheduleLink(schedule.id)}>
                <span className="schedule-row-icon">
                  <Icon name="jobs" />
                </span>
                <span className="schedule-label">
                  <strong>{schedule.name}</strong>
                  <small>{recurrence(schedule)}</small>
                </span>
                <span className="schedule-next">
                  {schedule.next_run_at ? (
                    <>
                      <small>다음 실행</small>
                      <time dateTime={schedule.next_run_at}>
                        {formatKstWithYear(schedule.next_run_at)}
                      </time>
                    </>
                  ) : (
                    <span className="schedule-status paused">일시 중지</span>
                  )}
                </span>
                <Icon name="arrow" />
              </a>
            </li>
          ))}
        </ul>
      ) : (
        !query.error && (
          <p className="schedule-empty" role="status">
            {query.data ? "등록된 분석 예약이 없습니다." : "예약 목록을 불러오는 중…"}
          </p>
        )
      )}
      {(query.data?.total ?? 0) > schedulePageSize && (
        <ReportPages
          label="예약 목록"
          page={page}
          total={query.data!.total}
          size={schedulePageSize}
          setPage={setPage}
        />
      )}
    </section>
  );
}

function ScheduleDetail({
  api,
  id,
  canWrite,
  edit,
}: {
  api: HttpClient;
  id: string;
  canWrite: boolean;
  edit: boolean;
}) {
  const load = useCallback((signal: AbortSignal) => getSchedule(api, id, signal), [api, id]);
  const query = usePollingQuery(load, edit ? null : 8000);
  const action = useAction();
  const schedule = query.data;
  const enabled = !!schedule?.next_run_at;
  if (schedule && edit && canWrite) return <ScheduleForm api={api} schedule={schedule} />;

  async function toggle() {
    if (!schedule || !canWrite || action.pending) return;
    await action.run(
      async () => {
        await setScheduleEnabled(api, id, !enabled);
        query.refresh();
      },
      enabled ? "다음 예약부터 일시 중지했습니다." : "예약을 다시 활성화했습니다.",
    );
  }

  return (
    <div className="schedule-layout">
      <a className="run-back" href="#/schedules">
        <Icon name="arrow" /> 예약 목록
      </a>
      <Notice error={query.error || action.error} success={action.notice} />
      {schedule ? (
        <>
          <section className="work-card schedule-card" aria-labelledby="schedule-title">
            <header className="schedule-heading">
              <div>
                <div className="schedule-title">
                  <h2 id="schedule-title">{schedule.name}</h2>
                  <span className={`schedule-status ${enabled ? "enabled" : "paused"}`}>
                    {enabled ? "활성" : "일시 중지"}
                  </span>
                </div>
                <p>{recurrence(schedule)}</p>
              </div>
              {canWrite && (
                <div className="schedule-actions">
                  <a className="button-link secondary-link" href={scheduleLink(id, true)}>
                    예약 수정
                  </a>
                  <button
                    className="button-link secondary-link"
                    disabled={action.pending || query.loading}
                    onClick={toggle}
                  >
                    <Icon name={enabled ? "pause" : "play"} />
                    {enabled ? "일시 중지" : "다시 활성화"}
                  </button>
                </div>
              )}
            </header>
            <dl className="schedule-meta">
              <div>
                <dt>다음 실행</dt>
                <dd>
                  {schedule.next_run_at ? (
                    <time dateTime={schedule.next_run_at}>
                      {formatKstWithYear(schedule.next_run_at)}
                    </time>
                  ) : (
                    "일시 중지됨"
                  )}
                </dd>
              </div>
              <div>
                <dt>분석 대상</dt>
                <dd>
                  <ul className="schedule-chips">
                    {schedule.assets.map((asset) => (
                      <li key={asset.id}>{asset.asset_name}</li>
                    ))}
                    {schedule.inaccessible_asset_count > 0 && (
                      <li>접근 불가 {schedule.inaccessible_asset_count}대</li>
                    )}
                  </ul>
                </dd>
              </div>
            </dl>
          </section>
          <RunHistory api={api} id={id} />
        </>
      ) : (
        <section className="work-card schedule-card">
          {query.error ? (
            <button className="button-link secondary-link" onClick={query.refresh}>
              <Icon name="refresh" /> 다시 불러오기
            </button>
          ) : (
            <p className="schedule-empty" role="status">
              예약을 불러오는 중…
            </p>
          )}
        </section>
      )}
    </div>
  );
}

function RunHistory({ api, id }: { api: HttpClient; id: string }) {
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState("");
  const load = useCallback(
    (signal: AbortSignal) => listScheduleRuns(api, id, page, signal),
    [api, id, page],
  );
  const query = usePollingQuery(load, 5000);
  const runs = query.data?.items ?? [];
  const run = runs.find((item) => item.id === selected) ?? runs[0];
  return (
    <>
      <section className="work-card schedule-card" aria-labelledby="schedule-runs-title">
        <header className="schedule-heading">
          <h2 id="schedule-runs-title">실행 이력</h2>
          <button
            className="button-link secondary-link schedule-refresh"
            disabled={query.loading}
            onClick={query.refresh}
            aria-label="실행 이력 새로고침"
          >
            <Icon name="refresh" />
          </button>
        </header>
        <Notice error={query.error} />
        {runs.length ? (
          <ul className="schedule-runs">
            {runs.map((entry) => (
              <li key={entry.id}>
                <button
                  type="button"
                  aria-pressed={entry.id === run?.id}
                  onClick={() => setSelected(entry.id)}
                >
                  <time dateTime={entry.scheduled_for}>
                    {formatKstWithYear(entry.scheduled_for)} 예정
                  </time>
                  <span className={`schedule-status ${entry.status.toLowerCase()}`}>
                    {runStatus[entry.status]}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          !query.error && (
            <p className="schedule-empty" role="status">
              {query.data ? "아직 실행 기록이 없습니다." : "실행 이력을 불러오는 중…"}
            </p>
          )
        )}
        {(query.data?.total ?? 0) > runPageSize && (
          <ReportPages
            label="예약 실행 이력"
            page={page}
            total={query.data!.total}
            size={runPageSize}
            setPage={(next) => {
              setSelected("");
              setPage(next);
            }}
          />
        )}
      </section>
      {run && <RunResult key={run.id} api={api} id={id} run={run} />}
    </>
  );
}

function RunResult({ api, id, run }: { api: HttpClient; id: string; run: ScheduleRun }) {
  return (
    <section className="work-card schedule-card" aria-labelledby="schedule-changes-title">
      <header className="schedule-heading">
        <div>
          <h2 id="schedule-changes-title">판정 변경 내역</h2>
          <p>
            <time dateTime={run.created_at}>{formatKstWithYear(run.created_at)}</time> 접수
            {run.finished_at && run.batch_id && (
              <>
                {" · "}
                <time dateTime={run.finished_at}>{formatKstWithYear(run.finished_at)}</time> 완료
              </>
            )}
          </p>
        </div>
        {run.batch_id && (
          <a className="button-link secondary-link" href={batchLink(run.batch_id)}>
            <Icon name={run.status === "RUNNING" ? "activity" : "reports"} />
            {run.status === "RUNNING" ? "진행 상황 보기" : "분석·보고서 보기"}
          </a>
        )}
      </header>
      {run.error ? (
        <p role="status" className="schedule-empty">
          {run.error}
        </p>
      ) : run.status === "RUNNING" ? (
        <p className="schedule-empty activity-status" data-moving="true" role="status">
          분석이 끝나면 지난 결과와 비교합니다.
        </p>
      ) : (
        <ScheduleChangesPanel api={api} id={id} run={run} />
      )}
    </section>
  );
}
