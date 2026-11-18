import { Icon } from "../../shared/components/Icon";
import { useEffect, useState } from "react";
import { count, type Workflow } from "./api";

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
    setReplay(null);
  }, [run?.id]);
  useEffect(() => {
    if (
      !playing ||
      replay === null ||
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    )
      return;
    const timer = window.setTimeout(() => setReplay(replay === 3 ? null : replay + 1), 1500);
    return () => window.clearTimeout(timer);
  }, [replay, playing]);
  const at = playing ? replay! : steps.findIndex((s) => s.key === run?.stage);
  const done = playing ? at : run?.status === "COMPLETED" ? 4 : Math.max(0, at);
  const sources = run?.sources ?? [];
  const settled = sources.filter((s) => ["UPDATED", "CACHED", "FAILED"].includes(s.status)).length;
  return (
    <section className="run-rail" aria-label="자동 분석 진행 단계">
      <div className="rail-heading">
        <span>
          <Icon name="activity" />
          실행 단계
        </span>
        <div className="rail-tools">
          {run?.status === "COMPLETED" && (
            <button
              className="rail-replay"
              onClick={() => setReplay(playing ? (replay === 3 ? null : replay! + 1) : 0)}
            >
              <Icon name={playing ? "arrow" : "play"} />
              {playing ? (replay === 3 ? "재생 종료" : "다음 단계") : "기록 재생"}
            </button>
          )}
          <strong aria-live="polite">
            {playing
              ? "기록 재생 중"
              : run?.status === "FAILED"
                ? "실행 중단"
                : run?.status === "COMPLETED"
                  ? "보고서 준비 완료"
                  : run
                    ? "실행 중"
                    : loading
                      ? "기록 조회 중"
                      : "실행 대기"}
            <b>{loading && !run ? "—" : done} / 4</b>
          </strong>
        </div>
      </div>
      <ol className="rail-stops">
        {steps.map((s, i) => {
          const state =
            i < done
              ? "done"
              : i === at
                ? run?.status === "FAILED"
                  ? "failed"
                  : "current"
                : "waiting";
          const label =
            state === "done"
              ? "완료"
              : state === "current"
                ? "진행 중"
                : state === "failed"
                  ? "실패"
                  : "대기";
          const value =
            i === 0 && state === "current" && !playing && run?.timeline.verification
              ? "공식 파일 대조 중"
              : i === 0 && run?.package_count != null
                ? `${count(run.package_count)}개 패키지`
                : i === 1 && sources.length
                  ? `${settled} / ${sources.length}개 자료`
                  : label;
          return (
            <li
              className={`rail-stop ${state}`}
              key={s.key}
              aria-current={state === "current" ? "step" : undefined}
            >
              <span className="stop-icon">
                <Icon name={s.icon} />
                {state === "done" && (
                  <i>
                    <Icon name="check" />
                  </i>
                )}
              </span>
              <strong>{i === 0 && run?.mode === "saved" ? "기록 불러오기" : s.name}</strong>
              <small>
                {playing && i === at && run?.timeline[s.key]
                  ? new Date(run.timeline[s.key]).toLocaleTimeString("ko-KR", {
                      hour12: false,
                      timeZone: "Asia/Seoul",
                    })
                  : loading && !run
                    ? "—"
                    : playing && i > at
                      ? "대기"
                      : value}
              </small>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
