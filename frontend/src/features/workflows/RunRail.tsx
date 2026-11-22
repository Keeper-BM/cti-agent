import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Icon } from "../../shared/components/Icon";
import { count, sourceCounts, type Brief, type Workflow } from "./api";

const steps = [
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
const stageClock = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul",
  hourCycle: "h23",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

function stepName(index: number, run: Workflow | null) {
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

  useEffect(() => {
    if (!automatic || !current || current.index === lastStep) return;
    const timer = window.setTimeout(() => {
      setPlayback((previous) =>
        previous === current && !getReducedMotion()
          ? { ...current, index: current.index + 1 }
          : previous,
      );
    }, stageDuration);
    return () => window.clearTimeout(timer);
  }, [current, automatic]);

  return {
    canStart: !!readyRunId,
    index,
    automatic,
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
  const playbackStatus = replay.automatic ? "기록 재생 중" : "기록 재생 · 수동";
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
    <section className="work-card run-rail" aria-label="자동 분석 진행 단계">
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
                {!replay.reducedMotion && (
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
              detail = "공식 파일 대조 중";
            } else if (step.key === "inventory" && run?.package_count != null) {
              detail = "패키지 " + count(run.package_count) + "개";
            }
            if (step.key === "sources" && sourceTotal)
              detail = "조회 " + processed + "/" + sourceTotal + "건 처리";
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

export function StageSpotlight({
  run,
  analysis,
  replayIndex,
}: {
  run: Workflow;
  analysis: Brief | null;
  replayIndex: number | null;
}) {
  const recording = replayIndex !== null;
  const index = replayIndex ?? steps.findIndex((step) => run.stage === step.key);
  const step = steps[index];
  const facts: { label: string; value: string; unit?: string; tone?: string }[] = [];
  let note: string;
  let caveat: string | undefined;
  switch (step.key) {
    case "inventory":
      if (run.package_count != null)
        facts.push({ label: "설치 패키지", value: count(run.package_count), unit: "개" });
      note = recording
        ? run.mode === "saved"
          ? "이 자산에 저장된 패키지 목록을 분석 대상으로 불러왔습니다."
          : "SSH로 가져온 설치 패키지와 버전을 저장했습니다."
        : run.timeline.verification
          ? "설치 파일을 Ubuntu 공식 배포본과 대조하고 있습니다."
          : run.mode === "saved"
            ? "저장된 설치 패키지와 버전을 불러오고 있습니다."
            : "SSH로 설치 패키지와 버전을 가져오고 있습니다.";
      break;
    case "sources": {
      const sourceTotal = run.sources.length;
      const sources = sourceCounts(run.sources);
      if (sourceTotal)
        facts.push(
          {
            label: "공식 출처",
            value: count(new Set(run.sources.map((s) => s.source)).size),
            unit: "개",
          },
          {
            label: "처리 완료 / 전체 요청",
            value:
              count(sources.UPDATED + sources.CACHED + sources.FAILED) + " / " + count(sourceTotal),
            unit: "건",
          },
        );
      caveat = [
        sources.CACHED ? "저장본 사용 " + count(sources.CACHED) + "건" : "",
        sources.FAILED ? "조회 실패 " + count(sources.FAILED) + "건" : "",
      ]
        .filter(Boolean)
        .join(" · ");
      note = recording
        ? "조회 결과에서 이 분석에 사용한 보안 자료와 기준 시각을 저장했습니다."
        : "설치 패키지에 해당하는 공식 보안 자료를 조회하고 있습니다.";
      break;
    }
    case "analysis":
      if (recording && analysis && analysis.id === run.analysis_id) {
        facts.push(
          {
            label: "영향 있음",
            value: count(analysis.summary.AFFECTED ?? 0),
            unit: "건",
            tone: "affected",
          },
          {
            label: "추가 확인 필요",
            value: count(analysis.summary.NEEDS_REVIEW ?? 0),
            unit: "건",
            tone: "review",
          },
        );
        caveat = "패키지·CVE 조합 기준";
      }
      note = recording
        ? "공식 기준과 대조해 패키지·CVE 조합별 판정을 저장했습니다."
        : "설치 버전과 확인된 적용 조건을 공식 수정 기준과 대조하고 있습니다.";
      break;
    case "report":
      if (recording && run.report_id) facts.push({ label: "다운로드 형식", value: "Markdown" });
      note = recording
        ? "분석 결과와 권고 조치, 공식 근거를 대응 보고서로 저장했습니다."
        : "이번 분석의 판정과 대응 근거를 보고서로 정리하고 있습니다.";
      break;
  }
  const started = run.timeline[step.key];
  return (
    <section
      className="work-card stage-spotlight"
      aria-label={recording ? "저장된 실행 단계" : "현재 실행 단계"}
    >
      <div className="stage-content" key={step.key}>
        <span className="stage-symbol">
          <Icon name={step.icon} />
        </span>
        <div className="stage-copy">
          <div className="stage-meta">
            <span>
              {index + 1} / {steps.length}단계
            </span>
            {started && (
              <span>
                시작 시각 <time dateTime={started}>{stageClock.format(new Date(started))}</time>
              </span>
            )}
          </div>
          <h2>{stepName(index, run)}</h2>
          <p>{note}</p>
        </div>
        {(facts.length > 0 || caveat) && (
          <div className="stage-readout">
            {facts.length > 0 && (
              <dl className="stage-facts">
                {facts.map(({ label, value, unit, tone }) => (
                  <div key={label} className={tone && "stage-fact-" + tone}>
                    <dt>{label}</dt>
                    <dd>
                      {value}
                      {unit && <small>{unit}</small>}
                    </dd>
                  </div>
                ))}
              </dl>
            )}
            {caveat && <p className="stage-caveat">{caveat}</p>}
          </div>
        )}
      </div>
    </section>
  );
}
