import { Icon } from "../../shared/components/Icon";
import { useEffect, useState } from "react";
import { count, sourceCounts, type Workflow } from "./api";

const steps = [
  { key: "inventory", name: "패키지 수집", icon: "package" },
  { key: "sources", name: "보안 자료 갱신", icon: "database" },
  { key: "analysis", name: "취약점 분석", icon: "shield" },
  { key: "report", name: "보고서 생성", icon: "reports" },
] as const;

export function RunRail({ run, loading }: { run: Workflow | null; loading: boolean }) {
  const [replay, setReplay] = useState<number | null>(null);
  const playing = replay !== null && run?.status === "COMPLETED";
  useEffect(() => {
    if (
      !playing ||
      replay === null ||
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    )
      return;
    const timer = window.setTimeout(() => setReplay(replay === 3 ? null : replay + 1), 1900);
    return () => window.clearTimeout(timer);
  }, [replay, playing]);
  const at = playing ? replay! : steps.findIndex((s) => s.key === run?.stage);
  const done = playing ? at : run?.status === "COMPLETED" ? steps.length : Math.max(0, at);
  const sources = run?.sources ?? [];
  const counts = sourceCounts(sources);
  const settled = counts.UPDATED + counts.CACHED + counts.FAILED;
  const stateText = playing
    ? "기록 재생 중"
    : run?.status === "COMPLETED"
      ? "완료"
      : run?.status === "FAILED"
        ? "실행 중단"
        : run
          ? "진행 중"
          : "실행 대기";
  return (
    <section className="work-card run-rail" aria-label="자동 분석 진행 단계">
      <div className="rail-heading">
        <div>
          <h2>실행 단계</h2>
          <span
            className={"rail-status" + (run?.status === "FAILED" ? " failed" : "")}
            aria-live="polite"
          >
            {stateText}
          </span>
        </div>
        {run?.status === "COMPLETED" && (
          <button
            className="text-tool rail-replay"
            onClick={() => setReplay(playing ? (replay === 3 ? null : replay! + 1) : 0)}
          >
            <Icon name={playing ? "arrow" : "play"} />
            {playing ? (replay === 3 ? "재생 종료" : "다음 단계") : "기록 재생"}
          </button>
        )}
      </div>
      <ol className="rail-stops">
        {steps.map((step, i) => {
          const state =
            i < done
              ? "done"
              : i === at
                ? run?.status === "FAILED"
                  ? "failed"
                  : "current"
                : "waiting";
          let detail =
            state === "done"
              ? "완료"
              : state === "current"
                ? "진행 중"
                : state === "failed"
                  ? "실패"
                  : "대기";
          if (state !== "waiting") {
            if (i === 0 && state === "current" && !playing && run?.timeline.verification)
              detail = "공식 파일 대조 중";
            else if (i === 0 && run?.package_count != null)
              detail = "패키지 " + count(run.package_count) + "개";
            if (i === 1 && sources.length)
              detail = "조회 " + settled + "/" + sources.length + "건 처리";
            if (i === 2 && state === "done") detail = "판정 저장";
            if (i === 3 && state === "done") detail = "보고서 저장";
          }
          if (playing && i === at && run?.timeline[step.key])
            detail = new Date(run.timeline[step.key]).toLocaleTimeString("ko-KR", {
              hour12: false,
              timeZone: "Asia/Seoul",
            });
          return (
            <li
              className={"rail-stop " + state}
              key={step.key}
              aria-current={state === "current" ? "step" : undefined}
            >
              <span className="stop-icon">
                <Icon name={step.icon} />
              </span>
              <span className="stop-copy">
                <strong>{i === 0 && run?.mode === "saved" ? "기록 불러오기" : step.name}</strong>
                <small>{loading ? "조회 중" : detail}</small>
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
