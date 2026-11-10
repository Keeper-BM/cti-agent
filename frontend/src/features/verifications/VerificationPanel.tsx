import { useCallback, useEffect, useRef, useState } from "react";
import { useSession } from "../../app/session";
import { Notice } from "../../shared/components/Notice";
import { formatKst } from "../../shared/format";
import { useAction } from "../../shared/hooks/useAction";
import { usePollingQuery } from "../../shared/hooks/usePollingQuery";
import { getVerification, listVerifications, requestVerification } from "./api";
import type { Verification, VerificationEvidence } from "./api";
import { ApacheRuntimeEvidence } from "./ApacheRuntimeEvidence";

const states: Record<string, string> = {
  QUEUED: "검증 대기",
  RUNNING: "공식 자료·설치 파일 확인 중",
  SUCCEEDED: "검증 완료",
  PARTIAL: "일부 확인 필요",
  FAILED: "검증 실패",
  MATCH: "공식 배포본과 일치",
  DIFFERENT: "차이 발견",
  UNAVAILABLE: "확인 불가",
  CHANGED: "검사 중 변경됨",
  MISSING: "파일 없음",
  UNREADABLE: "읽기 실패",
  CONFIGURATION: "설정 파일 · 별도 확인",
  UNSUPPORTED: "검증 범위 밖",
};
const active = (run?: Verification | null) =>
  !!run && ["QUEUED", "RUNNING"].includes(run.job.status);

export function VerificationPanel({
  assetId,
  inventoryId,
  verificationId,
  enabled,
  onInventory,
}: {
  assetId: string;
  inventoryId: string;
  verificationId?: string | null;
  enabled: boolean;
  onInventory: (id: string) => void;
}) {
  const { api } = useSession();
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState(verificationId ?? "");
  const [requested, setRequested] = useState<Verification | null>(null);
  const key = useRef(crypto.randomUUID());
  const action = useAction();
  const historyLoad = useCallback(
    (signal: AbortSignal) => listVerifications(api!, assetId, page, signal),
    [api, assetId, page],
  );
  const history = usePollingQuery(api ? historyLoad : null);
  const currentLoad = useCallback(
    (signal: AbortSignal) => getVerification(api!, assetId, selected, signal),
    [api, assetId, selected],
  );
  const selectedSummary = history.data?.items.find((r) => r.id === selected) ?? requested;
  const detail = usePollingQuery(
    api && selected ? currentLoad : null,
    active(selectedSummary) ? 5000 : null,
  );
  const busy = action.pending || active(requested) || history.data?.items.some(active);
  useEffect(() => {
    const updated =
      history.data?.items.find((r) => r.id === requested?.id) ??
      (detail.data?.id === requested?.id ? detail.data : null);
    if (requested && updated && requested.job.status !== updated.job.status) setRequested(updated);
  }, [history.data, detail.data, requested]);
  async function verify() {
    if (!api || busy) return;
    if (
      await action.run(async () => {
        const run = await requestVerification(api, assetId, inventoryId, key.current);
        setRequested(run);
        setSelected(run.id);
        setPage(0);
        history.refresh();
      }, "공식 자료와 설치 파일 대조를 요청했습니다. 완료 후 새 패키지 기록을 선택해 분석하세요.")
    )
      key.current = crypto.randomUUID();
  }
  return (
    <section className="collection-result" aria-label="공식 패키지 파일 검증">
      <div className="collection-toolbar">
        <div>
          <strong>공식 패키지 파일 검증</strong>
          <p>선택한 SSH 기록과 서버의 현재 Apache2·MySQL 파일을 공식 Ubuntu 배포본과 대조합니다.</p>
        </div>
        <button className="primary" disabled={!api || !enabled || !!busy} onClick={verify}>
          {busy ? "검증 처리 중…" : "공식 파일 검증"}
        </button>
      </div>
      <p>
        파일을 읽어 비교하며, 결과는 새 패키지 기록으로 저장합니다. 설정 파일과 실행 중인 코드는
        별도 확인 대상입니다.
      </p>
      <Notice error={action.error || history.error || detail.error} success={action.notice} />
      {detail.data && (
        <div aria-live="polite">
          <strong>{states[detail.data.job.status]}</strong>
          {detail.data.job.result?.message != null && (
            <p>{String(detail.data.job.result.message)}</p>
          )}
          {detail.data.job.error_code && <p className="job-error">{detail.data.job.error_code}</p>}
          {detail.data.verified_inventory_id && (
            <button
              className="secondary"
              onClick={() => onInventory(detail.data!.verified_inventory_id!)}
            >
              검증 결과가 담긴 패키지 기록 보기
            </button>
          )}
          {detail.data.evidence && <VerificationBody evidence={detail.data.evidence} />}
        </div>
      )}
      {!!history.data?.total && (
        <details className="inventory-format">
          <summary>검증 이력 {history.data.total}건</summary>
          <div className="ai-history-list">
            {history.data.items.map((run) => (
              <button
                key={run.id}
                className={`ai-history-item ${run.id === selected ? "selected" : ""}`}
                aria-pressed={run.id === selected}
                onClick={() => setSelected(run.id)}
              >
                <span>
                  {formatKst(run.created_at)}
                  <small>입력 {run.inventory_id.slice(0, 8)}</small>
                </span>
                <span>{states[run.job.status]}</span>
              </button>
            ))}
          </div>
          {history.data.total > 10 && (
            <div className="pagination">
              <span>
                {page + 1} / {Math.ceil(history.data.total / 10)}
              </span>
              <div>
                <button disabled={!page} onClick={() => setPage(page - 1)}>
                  이전
                </button>
                <button
                  disabled={(page + 1) * 10 >= history.data.total}
                  onClick={() => setPage(page + 1)}
                >
                  다음
                </button>
              </div>
            </div>
          )}
        </details>
      )}
    </section>
  );
}

export function VerificationBody({ evidence }: { evidence: VerificationEvidence }) {
  return (
    <div className="collection-evidence">
      <p>
        검사 시각 {formatKst(evidence.checked_at)} · {evidence.verifier_version}
      </p>
      <ul>
        {evidence.warnings?.map((w) => (
          <li key={w}>{w}</li>
        ))}
      </ul>
      {evidence.apache_runtime_note && <p>{evidence.apache_runtime_note}</p>}
      {evidence.apache_http2 && <ApacheRuntimeEvidence evidence={evidence.apache_http2} />}
      {evidence.packages.map((p) => (
        <details key={p.package_id}>
          <summary>
            {p.name} · {states[p.status]} · {p.version}
          </summary>
          <p>{p.message}</p>
          {p.archive && (
            <details>
              <summary>공식 자료 식별 정보</summary>
              <dl className="detail-list">
                {[
                  "pocket",
                  "published_at",
                  "signer",
                  "package_sha256",
                  "index_sha256",
                  "inrelease_sha256",
                ].map((key) => (
                  <div key={key}>
                    <dt>{key}</dt>
                    <dd className="mono">{String(p.archive?.[key] ?? "미제공")}</dd>
                  </div>
                ))}
              </dl>
            </details>
          )}
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>파일</th>
                  <th>검사 결과</th>
                </tr>
              </thead>
              <tbody>
                {p.files?.slice(0, 150).map((f) => (
                  <tr key={f.path}>
                    <td className="mono">{f.path}</td>
                    <td>{states[f.status] ?? f.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {(p.files?.length ?? 0) > 150 && (
            <p>
              앞 150개만 표시합니다. 전체 검사 목록은 저장된 검증 기록과 보고서 파일에서 확인할 수
              있습니다.
            </p>
          )}
        </details>
      ))}
    </div>
  );
}
