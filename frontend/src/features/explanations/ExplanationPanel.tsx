import { useCallback, useEffect, useRef, useState } from "react";
import type { HttpClient } from "../../api/client";
import { useSession } from "../../app/session";
import { Notice } from "../../shared/components/Notice";
import { useAction } from "../../shared/hooks/useAction";
import { usePollingQuery } from "../../shared/hooks/usePollingQuery";
import { createExplanation, getExplanation, getLLMStatus, listExplanations } from "./api";
import type { Explanation, ExplanationResult } from "./api";

const time = (value: string) => new Date(value).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" });
const statusNames: Record<string, string> = {
  QUEUED: "생성 대기",
  RUNNING: "요약 생성 중",
  SUCCEEDED: "저장 완료",
  FAILED: "생성 실패",
};

export function ExplanationPanel({ api, findingId }: { api: HttpClient; findingId: string }) {
  const { canWrite } = useSession();
  const [page, setPage] = useState(0);
  const [selectedId, setSelectedId] = useState("");
  const [requested, setRequested] = useState<Explanation | null>(null);
  const requestKey = useRef(crypto.randomUUID());
  const action = useAction();
  const configLoad = useCallback((signal: AbortSignal) => getLLMStatus(api, signal), [api]);
  const config = usePollingQuery(configLoad, null);
  const historyLoad = useCallback(
    (signal: AbortSignal) => listExplanations(api, findingId, page, signal),
    [api, findingId, page],
  );
  const history = usePollingQuery(historyLoad);
  const selectedLoad = useCallback(
    (signal: AbortSignal) => getExplanation(api, selectedId, signal),
    [api, selectedId],
  );
  const selected = usePollingQuery(selectedId ? selectedLoad : null);
  const newest = page === 0 ? (history.data?.items[0] ?? requested) : requested;
  const latest =
    requested && newest && new Date(requested.created_at) > new Date(newest.created_at)
      ? requested
      : newest;
  const busy = action.pending || (!!latest && ["QUEUED", "RUNNING"].includes(latest.job.status));
  const successful = history.data?.items.find((item) => item.result !== null);
  const displayed = selected.data?.result ? selected.data : successful;
  const visibleFailure =
    selected.data?.job.status === "FAILED"
      ? selected.data
      : latest?.job.status === "FAILED"
        ? latest
        : null;
  const version = selected.data?.job.status;
  useEffect(() => {
    history.refresh();
  }, [version, history.refresh]);
  useEffect(() => {
    if (
      requested &&
      selected.data?.id === requested.id &&
      selected.data.job.status !== requested.job.status
    )
      setRequested(selected.data);
  }, [selected.data, requested]);

  async function generate() {
    const ok = await action.run(async () => {
      const result = await createExplanation(api, findingId, requestKey.current);
      setRequested(result);
      setSelectedId(result.id);
      setPage(0);
      history.refresh();
    }, "AI Summary 생성 요청이 접수되었습니다.");
    if (ok) requestKey.current = crypto.randomUUID();
  }
  return (
    <section className="ai-explanation" aria-label="CVE AI Summary">
      <div className="ai-heading">
        <div>
          <h3>AI Summary</h3>
          <p>분석 결과·공식 근거 기반 취약점 요약 및 권고 조치</p>
        </div>
        <button
          className="primary"
          disabled={busy || !config.data?.configured || !canWrite}
          onClick={generate}
        >
          {busy ? "요약 생성 중…" : history.data?.total ? "요약 재생성" : "요약 생성"}
        </button>
      </div>
      <p className="ai-transmission">
        학교 API 전송 항목: 패키지·버전·판단·공식 근거 발췌. 자산 이름·주소·담당자는 전송 대상에서
        제외됩니다.
      </p>
      <Notice
        error={action.error || config.error || history.error || selected.error}
        success={action.notice}
      />
      {config.data && !config.data.configured && (
        <p className="ai-warning">{config.data.message} 기존 요약 조회는 가능합니다.</p>
      )}
      {config.data?.configured && <p className="ai-model">모델: {config.data.model}</p>}
      {latest && ["QUEUED", "RUNNING"].includes(latest.job.status) && (
        <p className="ai-progress" role="status">
          {statusNames[latest.job.status]} · 기존 요약을 표시합니다. 진행 상태는 작업 내역에서
          확인할 수 있습니다.
        </p>
      )}
      {visibleFailure && (
        <div className="ai-warning" role="alert">
          <strong>AI Summary 생성 실패</strong>
          <p>
            {String(
              visibleFailure.job.result?.message ??
                "요약 생성이 중단되었습니다. 재요청이 필요합니다.",
            )}
          </p>
          <small>{visibleFailure.job.error_code}</small>
        </div>
      )}
      {displayed?.result ? (
        <ExplanationBody
          explanation={displayed}
          result={displayed.result}
          previous={!!latest && latest.id !== displayed.id}
        />
      ) : (
        <p className="ai-empty">
          {history.loading
            ? "요약 조회 중…"
            : "저장된 요약이 없습니다. ‘요약 생성’으로 분석 결과와 공식 근거를 요약할 수 있습니다."}
        </p>
      )}
      {!!history.data?.total && (
        <details className="ai-history">
          <summary>요약 생성 이력 · {history.data.total}건</summary>
          <div className="ai-history-list">
            {history.data.items.map((item) => (
              <button
                className={`ai-history-item ${displayed?.id === item.id ? "selected" : ""}`}
                key={item.id}
                onClick={() => setSelectedId(item.id)}
              >
                <span>
                  {time(item.created_at)}
                  <small>
                    {item.model} · {item.id.slice(0, 8)}
                  </small>
                </span>
                <span className={`badge ${item.job.status.toLowerCase()}`}>
                  {statusNames[item.job.status] ?? item.job.status}
                </span>
              </button>
            ))}
          </div>
          <div className="analysis-pages">
            <button className="secondary" disabled={page === 0} onClick={() => setPage(page - 1)}>
              요약 이력 이전
            </button>
            <span>
              {page + 1} / {Math.max(1, Math.ceil(history.data.total / 10))}
            </span>
            <button
              className="secondary"
              disabled={(page + 1) * 10 >= history.data.total}
              onClick={() => setPage(page + 1)}
            >
              요약 이력 다음
            </button>
          </div>
        </details>
      )}
    </section>
  );
}

function ExplanationBody({
  explanation,
  result,
  previous,
}: {
  explanation: Explanation;
  result: ExplanationResult;
  previous: boolean;
}) {
  const [citationId, setCitationId] = useState("");
  const citation = result.citations.find((c) => c.id === citationId);
  const prefix = `explanation-${explanation.id}`;
  function refs(ids: string[]) {
    return (
      <span className="ai-refs">
        {ids.map((id) => (
          <button
            key={id}
            className="ai-reference"
            aria-label={`근거 ${id} 확인`}
            onClick={() => setCitationId(id)}
            aria-controls={`${prefix}-citation`}
          >
            {id}
          </button>
        ))}
      </span>
    );
  }
  return (
    <div className="ai-saved">
      <p className="ai-saved-meta">
        {previous ? "이전 요약" : "저장된 요약"} ·{" "}
        {time(explanation.completed_at ?? explanation.created_at)} · {explanation.model}
      </p>
      {result.facts.is_synthetic && (
        <p className="ai-warning">가상 입력 기반 요약입니다. 실제 서버 상태를 나타내지 않습니다.</p>
      )}
      <article>
        <h4>
          취약점 개요 <span>AI 생성</span>
        </h4>
        <p>
          {result.meaning.text} {refs(result.meaning.evidence_ids)}
        </p>
      </article>
      <article className="ai-original">
        <h4>
          패키지 분석 결과 <span>분석 원본</span>
        </h4>
        <p>
          {result.assessment_text} {refs(["A1"])}
        </p>
        <dl className="ai-versions">
          <div>
            <dt>대조한 설치 버전</dt>
            <dd>{result.facts.installed_version ?? "미제공"}</dd>
          </div>
          <div>
            <dt>Ubuntu 수정 기준</dt>
            <dd>{result.facts.fixed_version ?? "미제공"}</dd>
          </div>
        </dl>
        <ul>
          {result.assessment_reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      </article>
      <article>
        <h4>
          권고 조치 <span>AI 생성</span>
        </h4>
        <ol>
          {result.next_steps.map((step, i) => (
            <li key={i}>
              {step.text} {refs(step.evidence_ids)}
            </li>
          ))}
        </ol>
      </article>
      <div className="ai-citations" id={`${prefix}-citation`}>
        <h4>참조 근거</h4>
        <div className="ai-citation-buttons">
          {result.citations.map((c) => (
            <button
              className="ai-reference"
              key={c.id}
              aria-pressed={c.id === citationId}
              onClick={() => setCitationId(c.id)}
            >
              {c.id} · {c.title}
            </button>
          ))}
        </div>
        {citation && (
          <div className="ai-citation-detail">
            <strong>{citation.title}</strong>
            <p>
              기준 시각 {time(citation.captured_at)}
              {citation.truncated ? " · 일부 발췌" : ""}
            </p>
            <pre>{citation.excerpt}</pre>
            {citation.url && (
              <a href={citation.url} target="_blank" rel="noreferrer">
                공식 출처
              </a>
            )}
            {citation.document_id && <p>전체 원문: 하단 공식 근거 참조</p>}
            {citation.sha256 && (
              <details>
                <summary>원문 식별 정보</summary>
                <p className="mono">
                  SHA-256 {citation.sha256}
                  <br />
                  자료 기준본 {citation.snapshot_id}
                  <br />
                  원문 {citation.document_id}
                </p>
              </details>
            )}
          </div>
        )}
      </div>
      <div className="ai-validation">
        <p>검증 범위: 인용 ID·기준값. 생성 문장의 사실성은 별도 검토 대상입니다.</p>
        <details>
          <summary>생성 정보 및 제한 사항</summary>
          <ul>
            {result.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
          <p>
            생성 규칙 {explanation.prompt_version}
            <br />
            분석 ID {explanation.analysis_id}
            <br />
            서버 응답 모델 {explanation.reported_model ?? "미제공"}
          </p>
          {explanation.usage && <p>사용 토큰 {explanation.usage.total_tokens ?? "미제공"}</p>}
          <p className="mono">입력 SHA-256 {explanation.context_sha256}</p>
        </details>
      </div>
    </div>
  );
}
