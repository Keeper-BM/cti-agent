import { useEffect, useState, type ReactNode } from "react";
import { Icon } from "../../shared/components/Icon";
import {
  count,
  reportLink,
  shortTime,
  sourceCounts,
  sourceNames,
  sourceStates,
  type Brief,
  type Workflow,
} from "./api";
import { stepName, steps } from "./RunRail";

const stageClock = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul",
  hourCycle: "h23",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

type Stat = { label: string; value: string; unit?: string; tone?: "affected" | "review" };
type Detail = { label: string; value: ReactNode };
type StageDisplay = {
  note: string;
  facts?: Stat[];
  caveat?: string;
  detailTitle: string;
  details: ReactNode;
};

function StageDuration({ start, end }: { start: string; end?: string }) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (end) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [end]);

  const seconds = Math.max(
    0,
    Math.floor(((end ? Date.parse(end) : now) - Date.parse(start)) / 1000),
  );
  if (!Number.isFinite(seconds)) return null;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor(seconds / 60) % 60;
  const duration = [
    hours && hours + "시간",
    minutes || hours ? minutes + "분" : "",
    (seconds % 60) + "초",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <span className="stage-duration">
      {end ? "기록 소요" : "경과 시간"}{" "}
      <strong>{end && seconds === 0 ? "1초 미만" : duration}</strong>
    </span>
  );
}

function Details({ items }: { items: Detail[] }) {
  return (
    <dl className="stage-detail-grid">
      {items.map(({ label, value }) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function SourceRequests({ run, recording }: { run: Workflow; recording: boolean }) {
  if (!run.sources.length) {
    return (
      <p className="stage-detail-note">
        {recording ? "조회 요청 0건" : "패키지에 맞는 조회 요청을 준비하고 있습니다."}
      </p>
    );
  }

  return (
    <ul className="stage-source-list">
      {run.sources.map((source) => {
        const scope =
          source.scope === "catalog"
            ? "전체 목록"
            : source.source === "oracle"
              ? source.scope.split("/").pop() || source.scope
              : source.scope;

        return (
          <li key={source.job_id}>
            <div className="stage-source-name">
              <strong>{sourceNames[source.source] ?? source.source}</strong>
              <span>{scope}</span>
            </div>
            <div className="stage-source-meta">
              <span className={"stage-source-state st-" + source.status.toLowerCase()}>
                {sourceStates[source.status]}
              </span>
              {source.records != null && <span>{count(source.records)}건</span>}
              {source.captured_at && (
                <time dateTime={source.captured_at}>{shortTime(source.captured_at)}</time>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function stageDisplay(
  stage: Workflow["stage"],
  run: Workflow,
  analysis: Brief | null,
  recording: boolean,
): StageDisplay {
  switch (stage) {
    case "inventory": {
      const saved = run.mode === "saved";
      const verifying = !!run.timeline.verification && !run.verification_note && !recording;
      const items: Detail[] = [
        { label: "수집 방식", value: saved ? "저장된 패키지 기록" : "SSH 패키지 수집" },
        {
          label: "수집 기준 시각",
          value: run.collected_at ? (
            <time dateTime={run.collected_at}>{shortTime(run.collected_at)}</time>
          ) : (
            "패키지 목록 수신 대기"
          ),
        },
      ];
      if (run.verification_note || verifying) {
        items.push({
          label: "공식 패키지 파일 대조",
          value: run.verification_note ?? "배포본과 대조 중",
        });
      }
      return {
        note: recording
          ? saved
            ? "이 자산의 저장된 패키지 목록을 분석에 사용했습니다."
            : "SSH로 가져온 설치 패키지와 버전을 저장했습니다."
          : verifying
            ? "수집한 설치 파일을 Ubuntu 공식 배포본과 대조하고 있습니다."
            : run.verification_note
              ? "파일 대조 결과를 받은 뒤 공식 보안 자료 조회를 준비하고 있습니다."
              : saved
                ? "저장된 설치 패키지와 버전을 불러오고 있습니다."
                : "SSH로 설치 패키지와 버전을 가져오고 있습니다.",
        facts:
          run.package_count != null
            ? [{ label: "설치 패키지", value: count(run.package_count), unit: "개" }]
            : [],
        detailTitle: "패키지 수집 상세",
        details: <Details items={items} />,
      };
    }
    case "sources": {
      const { UPDATED, CACHED, FAILED } = sourceCounts(run.sources);
      const total = run.sources.length;
      const handled = UPDATED + CACHED + FAILED;
      const providers = new Set(run.sources.map((source) => source.source)).size;
      const notices = [
        total > 0 && "갱신 " + count(UPDATED) + "건",
        CACHED > 0 && "저장본 사용 " + count(CACHED) + "건",
        FAILED > 0 && "자료 미확보 " + count(FAILED) + "건",
      ]
        .filter(Boolean)
        .join(" · ");
      return {
        note: recording
          ? "이번 분석에 사용한 보안 자료와 기준 시각을 저장했습니다."
          : "수집한 패키지에 해당하는 공식 보안 자료를 조회하고 있습니다.",
        facts: total
          ? [
              { label: "조회 대상 출처", value: count(providers), unit: "개" },
              { label: "요청 처리", value: count(handled) + " / " + count(total), unit: "건" },
            ]
          : [],
        caveat: notices,
        detailTitle: "공식 자료 조회 상세",
        details: <SourceRequests run={run} recording={recording} />,
      };
    }
    case "analysis": {
      const verdicts = analysis?.summary;
      const evaluated =
        (verdicts?.AFFECTED ?? 0) +
        (verdicts?.NEEDS_REVIEW ?? 0) +
        (verdicts?.FIXED ?? 0) +
        (verdicts?.NOT_AFFECTED ?? 0);
      const pinnedSources = new Set(
        run.sources.flatMap((source) => (source.snapshot_id ? [source.snapshot_id] : [])),
      ).size;
      const details: Detail[] = [
        {
          label: "수집한 설치 패키지",
          value: run.package_count == null ? "—" : count(run.package_count) + "개",
        },
        { label: "대조에 사용한 공식 기준본", value: count(pinnedSources) + "건" },
        {
          label: "판정 저장",
          value: analysis ? (
            <time dateTime={analysis.completed_at}>{shortTime(analysis.completed_at)}</time>
          ) : (
            "패키지·CVE별 판정 작성 중"
          ),
        },
      ];
      if (verdicts && evaluated) {
        details.splice(2, 0, { label: "수정 기준 충족", value: count(verdicts.FIXED ?? 0) + "건" });
      }
      return {
        note: analysis
          ? evaluated
            ? "공식 기준과 대조해 패키지·CVE 조합별 판정을 저장했습니다."
            : "평가한 패키지·CVE 조합이 없습니다. 결과 화면에서 평가 범위를 확인하세요."
          : "설치 버전과 확인된 적용 조건을 공식 수정 기준과 대조하고 있습니다.",
        facts:
          verdicts && evaluated
            ? [
                {
                  label: "영향 있음",
                  value: count(verdicts.AFFECTED ?? 0),
                  unit: "건",
                  tone: "affected",
                },
                {
                  label: "추가 확인 필요",
                  value: count(verdicts.NEEDS_REVIEW ?? 0),
                  unit: "건",
                  tone: "review",
                },
              ]
            : [],
        caveat: evaluated ? "패키지·CVE 조합 기준" : undefined,
        detailTitle: "판정 상세",
        details: <Details items={details} />,
      };
    }
    case "report":
      return {
        note: recording
          ? "이 분석의 판정과 대응 조치, 공식 근거를 보고서로 저장했습니다."
          : "이 분석의 판정과 대응 조치, 공식 근거를 보고서로 정리하고 있습니다.",
        facts: [{ label: "다운로드 형식", value: "Markdown" }],
        detailTitle: "보고서 세부정보",
        details: (
          <Details
            items={[
              { label: "보고서 상태", value: recording ? "저장 완료" : "생성 중" },
              { label: "포함 항목", value: "판정 결과 · 대응 권고 · 공식 근거" },
              {
                label: "AI Summary",
                value: recording ? "포함 여부는 보고서에서 확인" : "근거가 있는 대표 판정을 요약",
              },
            ]}
          />
        ),
      };
  }
}

export function StageSpotlight({
  run,
  analysis,
  replayIndex,
  advancing,
}: {
  run: Workflow;
  analysis: Brief | null;
  replayIndex: number | null;
  advancing: boolean;
}) {
  const recording = replayIndex !== null;
  const index = replayIndex ?? steps.findIndex((step) => run.stage === step.key);
  const step = steps[index];
  const started = run.timeline[step.key];
  const next = steps[index + 1];
  const ended = (next ? run.timeline[next.key] : run.finished_at) ?? undefined;
  const moving = recording ? advancing : run.status === "RUNNING";
  const display = stageDisplay(
    step.key,
    run,
    analysis?.id === run.analysis_id ? analysis : null,
    recording,
  );
  const facts = display.facts ?? [];
  const last = recording && !next;
  const stateLabel = recording
    ? last
      ? "기록 재생 완료"
      : advancing
        ? "기록 재생 중"
        : "기록 재생 · 수동"
    : "분석 진행 중";
  const activeWarnings = step.key === "sources" ? run.warnings : [];

  return (
    <div className="stage-area" key={step.key} data-moving={moving || undefined}>
      <section className="work-card stage-spotlight" aria-labelledby="stage-title">
        <div className="stage-content" data-readout={facts.length > 0 || undefined}>
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
            <h2 id="stage-title">{stepName(index, run)}</h2>
            <p>{display.note}</p>
          </div>
          {facts.length > 0 && (
            <div className="stage-readout">
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
              {display.caveat && <p className="stage-caveat">{display.caveat}</p>}
            </div>
          )}
        </div>
        <div className="stage-status">
          <span className="activity-status">{stateLabel}</span>
          {started && (!recording || ended) && (
            <StageDuration start={started} end={recording ? ended : undefined} />
          )}
        </div>
        {moving && <div className="activity-track" aria-hidden="true" />}
      </section>
      <section className="work-card stage-details" aria-labelledby="stage-details-title">
        <div className="card-heading">
          <h3 id="stage-details-title">{display.detailTitle}</h3>
          {last && run.report_id && (
            <a href={reportLink(run.report_id)}>
              대응 보고서 보기 <Icon name="arrow" />
            </a>
          )}
        </div>
        {display.details}
        {activeWarnings.length > 0 && (
          <details className="source-details">
            <summary>
              자료 확인 사항 <Icon name="chevron" />
            </summary>
            {activeWarnings.map((warning) => (
              <p key={warning}>{warning}</p>
            ))}
          </details>
        )}
      </section>
    </div>
  );
}
