import { useCallback, useEffect, useRef, useState } from "react";
import { useSession } from "../../app/session";
import { Notice } from "../../shared/components/Notice";
import { useAction } from "../../shared/hooks/useAction";
import { usePollingQuery } from "../../shared/hooks/usePollingQuery";
import { listAssets } from "../assets/api";
import { listAnalyses } from "../findings/api";
import type { Analysis } from "../findings/api";
import { getLLMStatus } from "../explanations/api";
import { ReportPages, reportTime } from "../reports/ReportPreview";
import { askQuestion, getQuestion, listQuestions } from "./api";
import type { Question, QuestionResult } from "./api";

const states: Record<string, string> = {
  QUEUED: "대기",
  RUNNING: "답변 생성 중",
  SUCCEEDED: "저장 완료",
  FAILED: "실패",
};

export function QuestionsPage() {
  const { api, canWrite } = useSession();
  const [assetId, setAssetId] = useState("");
  const [assetPage, setAssetPage] = useState(0);
  const [analysisPage, setAnalysisPage] = useState(0);
  const [scope, setScope] = useState<Analysis[]>([]);
  const [question, setQuestion] = useState("");
  const [page, setPage] = useState(0);
  const [selectedId, setSelectedId] = useState("");
  const [poll, setPoll] = useState(true);
  const action = useAction();
  const key = useRef({ input: "", value: crypto.randomUUID() });
  const assetsLoad = useCallback(
    (signal: AbortSignal) => listAssets(api!, assetPage * 20, signal),
    [api, assetPage],
  );
  const assets = usePollingQuery(api ? assetsLoad : null, null);
  const analysesLoad = useCallback(
    (signal: AbortSignal) => listAnalyses(api!, assetId, analysisPage, signal),
    [api, assetId, analysisPage],
  );
  const analyses = usePollingQuery(api && assetId ? analysesLoad : null, null);
  const historyLoad = useCallback(
    (signal: AbortSignal) => listQuestions(api!, page, signal),
    [api, page],
  );
  const history = usePollingQuery(api ? historyLoad : null);
  const detailLoad = useCallback(
    (signal: AbortSignal) => getQuestion(api!, selectedId, signal),
    [api, selectedId],
  );
  const detail = usePollingQuery(api && selectedId ? detailLoad : null, poll ? 3000 : null);
  const configLoad = useCallback((signal: AbortSignal) => getLLMStatus(api!, signal), [api]);
  const config = usePollingQuery(api ? configLoad : null, null);
  useEffect(() => {
    if (detail.data && ["SUCCEEDED", "FAILED"].includes(detail.data.job.status)) {
      setPoll(false);
      history.refresh();
    }
  }, [detail.data?.job.status, history.refresh]);
  function choose(id: string) {
    setSelectedId(id);
    setPoll(true);
  }
  async function submit() {
    if (!api) return;
    const ids = scope.map((a) => a.id).sort();
    const input = JSON.stringify([ids, question.trim()]);
    if (key.current.input !== input) key.current = { input, value: crypto.randomUUID() };
    const ok = await action.run(async () => {
      const result = await askQuestion(api, ids, question.trim(), key.current.value);
      choose(result.id);
      setPage(0);
      history.refresh();
    }, "질의가 접수되었습니다. 완료 후 답변과 근거가 저장됩니다.");
    if (ok) key.current = { input: "", value: crypto.randomUUID() };
  }
  return (
    <>
      <div className="inline-info">
        <span className="info-icon">i</span>
        <span>
          선택한 분석 결과와 공식 자료를 기반으로 취약점 및 대응 절차에 대한 질의응답을 제공합니다.
        </span>
      </div>
      <Notice
        error={
          action.error ||
          assets.error ||
          analyses.error ||
          history.error ||
          detail.error ||
          config.error
        }
        success={action.notice}
      />
      <section className="panel report-create">
        <div className="panel-heading">
          <div>
            <h2>AI Q&amp;A</h2>
            <p>질의 범위: 완료된 분석 최대 5개</p>
          </div>
        </div>
        <div className="report-form">
          <label>
            대상 자산
            <select
              value={assetId}
              disabled={!api || action.pending}
              onChange={(e) => {
                setAssetId(e.target.value);
                setAnalysisPage(0);
              }}
            >
              <option value="">자산 선택</option>
              {assets.data?.items.map((a) => (
                <option key={a.id} value={a.id} disabled={!a.is_active}>
                  {a.asset_name}
                  {a.is_active ? "" : " (비활성)"}
                </option>
              ))}
            </select>
          </label>
          <label>
            분석 범위 추가
            <select
              value=""
              disabled={!assetId || scope.length >= 5 || action.pending}
              onChange={(e) => {
                const a = analyses.data?.items.find((i) => i.id === e.target.value);
                if (a) setScope([...scope, a]);
              }}
            >
              <option value="">완료된 분석 선택</option>
              {analyses.data?.items
                .filter((a) => a.job.status === "SUCCEEDED" && !scope.some((s) => s.id === a.id))
                .map((a) => (
                  <option key={a.id} value={a.id}>
                    {reportTime(a.created_at)} · {a.id.slice(0, 8)}
                    {a.is_synthetic ? " · 가상 입력" : ""}
                  </option>
                ))}
            </select>
          </label>
        </div>
        <ReportPages
          page={assetPage}
          total={assets.data?.total ?? 0}
          size={20}
          setPage={(p) => {
            setAssetPage(p);
            setAssetId("");
            setAnalysisPage(0);
          }}
          label="자산"
        />
        {!!assetId && (
          <ReportPages
            page={analysisPage}
            total={analyses.data?.total ?? 0}
            size={10}
            setPage={setAnalysisPage}
            label="분석"
          />
        )}
        <ul className="question-scope">
          {scope.map((a) => (
            <li key={a.id}>
              <span>
                {a.asset_name} · {reportTime(a.created_at)}
                {a.is_synthetic ? " · 가상 입력" : ""}
              </span>
              <button
                className="secondary"
                disabled={action.pending}
                onClick={() => setScope(scope.filter((s) => s.id !== a.id))}
                aria-label={`${a.asset_name} 분석 제외`}
              >
                제외
              </button>
            </li>
          ))}
        </ul>
        {!scope.length && (
          <p className="empty-description">
            질의 대상 분석을 선택하세요. 완료된 분석이 없으면 취약점 분석 실행이 필요합니다.
          </p>
        )}
        <form
          className="question-form"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <label>
            질의 내용
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              rows={3}
              minLength={5}
              maxLength={2000}
              required
              disabled={!api || action.pending}
              placeholder="예: 선택한 CVE의 판정 근거와 권고 조치는 무엇인가요?"
            />
          </label>
          <p className="ai-transmission">
            질문·분석 결과·공식 근거 발췌를 학교 API에 전달합니다. 비밀번호나 API 키는 질문에
            입력하지 마세요.
          </p>
          {config.data && !config.data.configured && (
            <p className="ai-warning">{config.data.message} 기존 답변은 계속 확인할 수 있습니다.</p>
          )}
          <button
            className="primary"
            disabled={
              !api ||
              !canWrite ||
              !scope.length ||
              question.trim().length < 5 ||
              action.pending ||
              !config.data?.configured
            }
          >
            {action.pending ? "접수 중…" : "질의 실행"}
          </button>
        </form>
      </section>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>질의 이력</h2>
            <p>저장된 답변·분석 결과·참조 근거</p>
          </div>
        </div>
        <div className="ai-history-list">
          {history.data?.items.map((q) => (
            <button
              key={q.id}
              className={`ai-history-item ${selectedId === q.id ? "selected" : ""}`}
              onClick={() => choose(q.id)}
            >
              <span>
                {q.question}
                <small>
                  {reportTime(q.created_at)} · 분석 {q.analysis_ids.length}개
                </small>
              </span>
              <span className={`badge ${q.job.status.toLowerCase()}`}>
                {states[q.job.status] ?? q.job.status}
              </span>
            </button>
          ))}
        </div>
        {!history.data?.total && <p className="empty-description">저장된 질의가 없습니다.</p>}
        <ReportPages
          page={page}
          total={history.data?.total ?? 0}
          size={10}
          setPage={setPage}
          label="질의 이력"
        />
      </section>
      {detail.data && (
        <section className="panel question-answer">
          <h2>{detail.data.question}</h2>
          {detail.data.result ? (
            <Answer key={detail.data.id} question={detail.data} result={detail.data.result} />
          ) : (
            <div className="ai-progress" role="status">
              <p>{states[detail.data.job.status]}</p>
              <p>
                {String(
                  detail.data.job.result?.message ??
                    "답변 생성 중입니다. 진행 상태는 작업 내역에서 확인할 수 있습니다.",
                )}
              </p>
              {detail.data.job.error_code && <small>{detail.data.job.error_code}</small>}
            </div>
          )}
        </section>
      )}
    </>
  );
}

function Answer({ question, result }: { question: Question; result: QuestionResult }) {
  const [citationId, setCitationId] = useState(result.citations[0]?.id ?? "");
  const citation = result.citations.find((c) => c.id === citationId);
  return (
    <div className="ai-saved">
      <p className="ai-saved-meta">
        {reportTime(question.completed_at ?? question.created_at)} ·{" "}
        {question.model === "none" ? "근거 부족 확인" : question.model}
      </p>
      {result.status === "INSUFFICIENT_EVIDENCE" && (
        <p className="ai-warning">선택한 자료만으로 답변할 근거가 부족합니다.</p>
      )}
      {result.summaries.some((s) => s.is_synthetic) && (
        <p className="ai-warning">
          가상 입력의 분석이 포함되어 있습니다. 실제 서버 상태와 구분하세요.
        </p>
      )}
      <h3>{question.model === "none" ? "근거 검토 결과" : "AI Response"}</h3>
      {result.answer.map((part, i) => (
        <p key={i}>
          {part.text}{" "}
          <span className="ai-refs">
            {part.evidence_ids.map((id) => (
              <button
                key={id}
                className="ai-reference"
                aria-label={`근거 ${id} 확인`}
                onClick={() => setCitationId(id)}
              >
                {id}
              </button>
            ))}
          </span>
        </p>
      ))}
      <details open>
        <summary>참조 분석 · 대표 결과 {result.facts.length}건</summary>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>분석</th>
                <th>CVE / 패키지</th>
                <th>설치 / 수정 기준</th>
                <th>판단 / 비교</th>
              </tr>
            </thead>
            <tbody>
              {result.facts.map((f) => (
                <tr key={f.finding_id}>
                  <td>
                    {f.asset_ref}
                    <br />
                    <a href={`#/reports?analysis=${f.analysis_id}`}>분석 보고서</a>
                  </td>
                  <td>
                    {f.cve_id}
                    <small>{f.package_name}</small>
                  </td>
                  <td>
                    {f.installed_version ?? "미제공"}
                    <br />
                    {f.fixed_version ?? "미제공"}
                  </td>
                  <td>
                    {f.verdict ?? "판단 없음"}
                    <br />
                    {f.version_comparison}
                    <details>
                      <summary>판정 근거</summary>
                      {f.reasons.map((r, i) => (
                        <p key={i}>{r}</p>
                      ))}
                    </details>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
      <div className="ai-citations">
        <h3>참조 근거</h3>
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
            <p>기준 시각 {reportTime(citation.captured_at)}</p>
            <pre>{citation.excerpt}</pre>
            {citation.url && (
              <a href={citation.url} target="_blank" rel="noreferrer">
                공식 출처
              </a>
            )}
            <details>
              <summary>근거 식별 정보</summary>
              <p className="mono">
                SHA-256 {citation.sha256 ?? "미제공"}
                <br />
                자료 기준본 {citation.snapshot_id}
                <br />
                원문 {citation.document_id}
                <br />
                정규화 자료 조각 {citation.chunk_id}
                <br />
                문자 위치 {citation.chunk_start ?? "—"}~{citation.chunk_end ?? "—"}
              </p>
              <p>
                조각 위치는 저장된 정규화 자료 기준입니다. 공식 원문은 출처와 해시로 연결합니다.
              </p>
            </details>
          </div>
        )}
      </div>
      <details className="ai-validation">
        <summary>답변 범위 및 제한 사항</summary>
        <ul>
          {result.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
        <p>
          검색 {result.retrieval_version} · 생성 {question.prompt_version}
        </p>
      </details>
    </div>
  );
}
