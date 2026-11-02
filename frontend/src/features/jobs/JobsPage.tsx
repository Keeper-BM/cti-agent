// 작업 상태 조회와 Worker 연결 확인 화면.
import { useCallback } from "react";
import { useSession } from "../../app/session";
import { Icon } from "../../shared/components/Icon";
import { Notice } from "../../shared/components/Notice";
import { formatKst } from "../../shared/format";
import { useAction } from "../../shared/hooks/useAction";
import { usePollingQuery } from "../../shared/hooks/usePollingQuery";
import { checkWorker, listJobs } from "./api";
import type { Job } from "./api";

const labels: Record<Job["status"], string> = {
  QUEUED: "대기 중",
  RUNNING: "실행 중",
  SUCCEEDED: "완료",
  PARTIAL: "부분 완료",
  FAILED: "실패",
};

export function JobsPage() {
  const { api } = useSession();
  const load = useCallback((signal: AbortSignal) => listJobs(api!, signal), [api]);
  const query = usePollingQuery(api ? load : null);
  const action = useAction();
  const jobs = query.data?.items ?? [];
  return (
    <>
      <Notice error={action.error || query.error} success={action.notice} />
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>최근 작업</h2>
            <p>최근 20건을 표시합니다. 연결 확인은 작업 처리 상태만 점검합니다.</p>
          </div>
          <button
            className="secondary"
            disabled={!api || action.pending}
            onClick={async () => {
              if (
                api &&
                (await action.run(
                  () => checkWorker(api),
                  "연결 확인 작업을 등록했습니다. Worker가 실행 중이면 곧 완료됩니다.",
                ))
              )
                query.refresh();
            }}
          >
            Worker 연결 확인
          </button>
        </div>
        {jobs.length === 0 ? (
          <div className="empty compact">
            <strong>
              {!api
                ? "연결 후 작업을 확인할 수 있습니다"
                : query.error
                  ? "작업 목록을 불러오지 못했습니다"
                  : query.loading
                    ? "작업을 불러오는 중입니다"
                    : "아직 실행한 작업이 없습니다"}
            </strong>
            <p>
              {!api
                ? "먼저 서비스에 연결해 주세요."
                : query.error
                  ? "잠시 후 다시 시도해 주세요."
                  : query.loading
                    ? "잠시만 기다려 주세요."
                    : "Worker가 실행 중인 상태에서 연결 확인을 요청하세요."}
            </p>
          </div>
        ) : (
          <ul className="job-list">
            {jobs.map((job) => (
              <li key={job.id}>
                <div className="job-icon">
                  <Icon name="jobs" />
                </div>
                <div className="job-detail">
                  <strong>{job.kind === "SYSTEM_CHECK" ? "Worker 연결 확인" : job.kind}</strong>
                  <span className="mono">
                    {job.id.slice(0, 8)} · {formatKst(job.created_at)}
                  </span>
                  {job.error_code && <span className="job-error">{job.error_code}</span>}
                </div>
                <span className={`badge ${job.status.toLowerCase()}`}>{labels[job.status]}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
