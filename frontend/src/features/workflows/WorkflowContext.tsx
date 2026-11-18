import { useCallback } from "react";
import type { HttpClient } from "../../api/client";
import { Icon } from "../../shared/components/Icon";
import { Notice } from "../../shared/components/Notice";
import { usePollingQuery } from "../../shared/hooks/usePollingQuery";
import { getAnalysis } from "../findings/api";
import {
  count,
  shortTime,
  sourceCounts,
  sourceNames,
  sourceStates,
  workspaceLink,
  type Brief,
  type Workflow,
} from "./api";

type SourceRow = Pick<
  Workflow["sources"][number],
  "scope" | "source" | "job_id" | "records" | "captured_at"
> & { status: keyof typeof sourceStates | "PINNED" };
const labels = { ...sourceStates, PINNED: "저장본" };
const marks: Record<string, string> = { ubuntu: "U", apache: "A", kev: "K", nvd: "N", oracle: "O" };

export function Sources({
  api,
  run,
  selected,
}: {
  api: HttpClient;
  run: Workflow | null;
  selected: Brief | null;
}) {
  const id = !run ? selected?.id : null;
  const load = useCallback((signal: AbortSignal) => getAnalysis(api, id!, signal), [api, id]);
  const query = usePollingQuery(id ? load : null, null);
  const rows: SourceRow[] =
    run?.sources ??
    (query.data?.sources ?? []).map((s) => ({
      source: s.source_id,
      scope: s.scope_key,
      job_id: s.job_id,
      status: "PINNED",
      records: s.record_count,
      captured_at: s.captured_at,
    }));
  const warnings = run?.warnings ?? query.data?.warnings ?? [];
  const groups = Array.from(new Set(rows.map((s) => s.source)));
  const counts = sourceCounts(run?.sources ?? []);
  const states = (items: SourceRow[]) =>
    (Object.keys(labels) as Array<keyof typeof labels>).flatMap((status) => {
      const n = items.filter((s) => s.status === status).length;
      return n
        ? [
            <span key={status} className={"source-state st-" + status.toLowerCase()}>
              {labels[status]} {n}건
            </span>,
          ]
        : [];
    });
  return (
    <section className="work-card source-card">
      <div className="card-heading">
        <h2>공식 보안 자료</h2>
        <Icon name="database" />
      </div>
      <Notice error={query.error} />
      {groups.length > 0 ? (
        <>
          <div className="source-summary">
            <strong>{groups.length}개 출처</strong>
            <span>·</span>
            <span>
              {run ? "조회 요청 " : "저장 기준본 "}
              {rows.length}건
            </span>
          </div>
          {run && (counts.CACHED > 0 || counts.FAILED > 0) && (
            <p className="source-caution">
              {[
                counts.CACHED ? "저장본 사용 " + counts.CACHED + "건" : "",
                counts.FAILED ? "조회 실패 " + counts.FAILED + "건" : "",
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          )}
          <ul className="source-list">
            {groups.map((source) => {
              const items = rows.filter((s) => s.source === source);
              return (
                <li key={source}>
                  <span className="source-glyph" aria-hidden="true">
                    {marks[source] ?? source.slice(0, 1).toUpperCase()}
                  </span>
                  <div>
                    <b>{sourceNames[source] ?? source}</b>
                    <small>{states(items)}</small>
                  </div>
                </li>
              );
            })}
          </ul>
        </>
      ) : (
        <p className="aside-empty">
          {id && !query.data && !query.error
            ? "기준 자료를 불러오는 중…"
            : run?.status === "RUNNING"
              ? "패키지 확인 후 조회 요청이 표시됩니다."
              : "이 기록에 저장된 기준 자료가 없습니다."}
        </p>
      )}
      {(rows.length > 0 || warnings.length > 0 || run?.verification_note) && (
        <details className="source-details">
          <summary>
            자료 시각 및 제한 사항
            <Icon name="chevron" />
          </summary>
          {run?.verification_note && (
            <p>
              <strong>패키지 파일 대조</strong>
              {run.verification_note}
            </p>
          )}
          {rows.map((s) => (
            <p key={s.job_id + s.scope}>
              <strong>
                {sourceNames[s.source] ?? s.source} · {s.scope}
              </strong>
              {labels[s.status]} · {s.captured_at ? shortTime(s.captured_at) : "자료 시각 미확정"}
              {s.records != null && " · 자료 " + count(s.records) + "건"}
            </p>
          ))}
          {warnings.map((w) => (
            <p key={w}>{w}</p>
          ))}
        </details>
      )}
    </section>
  );
}

export function History({
  items,
  asset,
  selected,
}: {
  items: Brief[];
  asset: string;
  selected: string;
}) {
  return (
    <section className="work-card history-card">
      <div className="card-heading">
        <h2>최근 분석</h2>
        <a href={"#/findings?asset=" + asset}>
          전체 이력
          <Icon name="arrow" />
        </a>
      </div>
      {items.length ? (
        <ul>
          {items.slice(0, 4).map((h) => (
            <li key={h.id}>
              <a
                className="history-link"
                aria-current={selected === h.id ? "true" : undefined}
                href={workspaceLink(asset, h.id)}
              >
                <i />
                <span>
                  <b>{shortTime(h.completed_at)}</b>
                  <small>
                    {h.workflow_id ? "자동 실행" : "개별 분석"} · 영향 있음{" "}
                    {count(h.summary.AFFECTED ?? 0)}건
                  </small>
                </span>
                <Icon name="arrow" />
              </a>
            </li>
          ))}
        </ul>
      ) : (
        <p className="aside-empty">완료된 분석이 여기에 표시됩니다.</p>
      )}
    </section>
  );
}
