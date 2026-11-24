import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Icon } from "../../shared/components/Icon";
import { count, sourceCounts, type Workflow } from "./api";

export const steps = [
  { key: "inventory", name: "패키지 수집", icon: "package" },
  { key: "sources", name: "보안 자료 갱신", icon: "database" },
  { key: "analysis", name: "취약점 분석", icon: "shield" },
  { key: "report", name: "보고서 생성", icon: "reports" },
] as const;

const lastStep = steps.length - 1;
const stageDuration = 5000;
const reducedMotionQuery = "(prefers-reduced-motion: reduce)";
const getReducedMotion = () => window.matchMedia(reducedMotionQuery).matches;
const subscribeToMotion = (onChange: () => void) => {
  const preference = window.matchMedia(reducedMotionQuery);
  preference.addEventListener("change", onChange);
  return () => preference.removeEventListener("change", onChange);
};
export function stepName(index: number, run: Workflow | null) {
  return index === 0 && run?.mode === "saved" ? "기록 불러오기" : steps[index].name;
}

type Playback = { runId: string; index: number; automatic: boolean };

export function useRunReplay(run: Workflow | null) {
  const reducedMotion = useSyncExternalStore(subscribeToMotion, getReducedMotion);
  const [playback, setPlayback] = useState<Playback | null>(null);
  const readyRunId =
    run?.status === "COMPLETED" && steps.every((step) => run.timeline[step.key]) ? run.id : null;
  const current = playback?.runId === readyRunId ? playback : null;
  const index = current?.index ?? null;
  const automatic = !!current?.automatic && !reducedMotion;
  const advancing = automatic && index !== lastStep;

  useEffect(() => {
    if (!advancing || !current) return;
    const timer = window.setTimeout(() => {
      setPlayback((previous) =>
        previous === current && !getReducedMotion()
          ? { ...current, index: current.index + 1 }
          : previous,
      );
    }, stageDuration);
    return () => window.clearTimeout(timer);
  }, [current, advancing]);

  return {
    canStart: !!readyRunId,
    index,
    automatic,
    advancing,
    reducedMotion,
    start() {
      if (readyRunId) setPlayback({ runId: readyRunId, index: 0, automatic: !reducedMotion });
    },
    toggleAutomatic() {
      setPlayback((previous) => previous && { ...previous, automatic: !previous.automatic });
    },
    previous() {
      setPlayback(
        (previous) => previous && { ...previous, index: Math.max(0, previous.index - 1) },
      );
    },
    next() {
      setPlayback((previous) => {
        if (!previous || previous.index === lastStep) return null;
        return { ...previous, index: previous.index + 1 };
      });
    },
    end() {
      setPlayback(null);
    },
  };
}

export function RunRail({
  run,
  replay,
}: {
  run: Workflow | null;
  replay: ReturnType<typeof useRunReplay>;
}) {
  const primary = useRef<HTMLButtonElement>(null);
  const recording = replay.index !== null;
  const at = replay.index ?? steps.findIndex((step) => step.key === run?.stage);
  const done = !recording && run?.status === "COMPLETED" ? steps.length : Math.max(0, at);
  const sourceTotal = run?.sources.length ?? 0;
  const sources = sourceCounts(run?.sources ?? []);
  const processed = sources.UPDATED + sources.CACHED + sources.FAILED;
  const moving = recording ? replay.advancing : run?.status === "RUNNING";
  const playbackStatus =
    at === lastStep
      ? "기록 재생 · 마지막 단계"
      : replay.advancing
        ? "기록 재생 중"
        : "기록 재생 · 수동";
  const status = recording
    ? playbackStatus
    : run?.status === "COMPLETED"
      ? "완료"
      : run?.status === "FAILED"
        ? "실행 중단"
        : run
          ? "진행 중"
          : "실행 대기";

  return (
    <section
      className="work-card run-rail"
      aria-label="자동 분석 진행 단계"
      data-moving={moving || undefined}
    >
      <div className="rail-heading">
        <div className="rail-title">
          <h2>실행 단계</h2>
          <span className={"rail-status" + (run?.status === "FAILED" ? " failed" : "")}>
            {status}
          </span>
          <span className="sr-only" role="status">
            {status}
            {(recording || run?.status === "RUNNING" || run?.status === "FAILED") &&
              at >= 0 &&
              " · " + stepName(at, run)}
          </span>
        </div>
        {replay.canStart && (
          <div className="rail-controls" aria-label="기록 재생 제어" role="group">
            {recording && (
              <>
                <button
                  type="button"
                  className="text-tool rail-secondary"
                  onClick={() => {
                    replay.end();
                    primary.current?.focus({ preventScroll: true });
                  }}
                >
                  재생 종료
                </button>
                {!replay.reducedMotion && at !== lastStep && (
                  <button
                    type="button"
                    className="text-tool rail-secondary"
                    onClick={replay.toggleAutomatic}
                  >
                    <Icon name={replay.automatic ? "pause" : "play"} />
                    {replay.automatic ? "일시 정지" : "자동 재생"}
                  </button>
                )}
                <button
                  type="button"
                  className="text-tool rail-secondary"
                  disabled={at === 0}
                  onClick={replay.previous}
                >
                  <Icon className="rail-back-icon" name="arrow" />
                  이전
                </button>
              </>
            )}
            <button
              type="button"
              ref={primary}
              className={
                recording
                  ? "button-link primary-link rail-next"
                  : "button-link secondary-link rail-replay"
              }
              onClick={recording ? replay.next : replay.start}
            >
              <Icon name={recording ? "arrow" : "play"} />
              {recording ? (at === lastStep ? "결과 보기" : "다음 단계") : "기록 재생"}
            </button>
          </div>
        )}
      </div>
      <ol className="rail-stops">
        {steps.map((step, index) => {
          const state =
            index < done
              ? "done"
              : index === at
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
          if (state === "done" || state === "current") {
            if (
              step.key === "inventory" &&
              state === "current" &&
              !recording &&
              run?.timeline.verification
            ) {
              detail = run.verification_note ? "파일 대조 결과 수신" : "공식 파일 대조 중";
            } else if (step.key === "inventory" && run?.package_count != null) {
              detail = "패키지 " + count(run.package_count) + "개";
            }
            if (step.key === "sources" && sourceTotal)
              detail =
                processed === sourceTotal
                  ? [
                      "갱신 " + sources.UPDATED,
                      sources.CACHED > 0 && "저장본 " + sources.CACHED,
                      sources.FAILED > 0 && "미확보 " + sources.FAILED,
                    ]
                      .filter(Boolean)
                      .join(" · ")
                  : "조회 " + processed + "/" + sourceTotal + "건 처리";
            if (step.key === "analysis" && state === "done") detail = "판정 저장";
            if (step.key === "report" && state === "done") detail = "보고서 저장";
          }
          if (state === "current" && recording) detail = "저장 기록";
          return (
            <li
              className={"rail-stop " + state}
              key={step.key}
              aria-current={state === "current" ? "step" : undefined}
            >
              <span className="stop-icon">
                <Icon name={step.icon} />
                {state === "done" && (
                  <span className="stop-check">
                    <Icon name="check" />
                  </span>
                )}
              </span>
              <span className="stop-copy">
                <strong>{stepName(index, run)}</strong>
                <small>{detail}</small>
              </span>
              {index < lastStep && <span className="rail-connector" aria-hidden="true" />}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
