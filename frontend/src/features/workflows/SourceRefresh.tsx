import type { components } from "../../api/schema";
import { formatKstWithYear } from "../../shared/format";
import { count, sourceNames, type Workflow } from "./api";

type BatchSource = components["schemas"]["BatchSource"];
type Source = Workflow["sources"][number] | BatchSource;

const outcomes = [
  { id: "UPDATED", label: "이번에 갱신" },
  { id: "CACHED", label: "저장본 사용" },
  { id: "FAILED", label: "자료 미확보" },
  { id: "REUSED", label: "이전 분석 기준본" },
] as const;

export function SourceRefresh({ sources }: { sources: Source[] }) {
  const groups = outcomes.map(({ id, label }) => {
    const items = sources.filter((source) => source.status === id);
    const dates = items
      .flatMap((source) => (source.captured_at ? [source.captured_at] : []))
      .sort();
    return { id, label, items, oldest: dates[0], newest: dates.at(-1) };
  });
  return (
    <section className="refresh-summary" aria-label="공식 자료 조회 결과">
      <h3>공식 자료 조회 결과</h3>
      {groups.some(({ items }) => items.length > 0) ? (
        <>
          <dl className="refresh-metrics">
            {groups.map(({ id, label, items, oldest, newest }) =>
              id !== "REUSED" || items.length > 0 ? (
                <div
                  key={id}
                  data-caution={
                    (items.length > 0 && (id === "CACHED" || id === "FAILED")) || undefined
                  }
                >
                  <dt>{label}</dt>
                  <dd>
                    <strong>{count(items.length)}건</strong>
                  </dd>
                  {oldest && (
                    <dd>
                      {oldest === newest ? "기준 " : "가장 오래된 기준 "}
                      <time dateTime={oldest}>{formatKstWithYear(oldest)}</time>
                    </dd>
                  )}
                </div>
              ) : null,
            )}
          </dl>
          <details className="refresh-details">
            <summary>출처별 기준 시각 (KST)</summary>
            <ul>
              {groups.flatMap(({ id, label, items }) =>
                items.map((source) => (
                  <li key={source.job_id + id + (source.snapshot_id ?? "")}>
                    <strong>
                      {sourceNames[source.source] ?? source.source} · {source.scope}
                    </strong>
                    <span>
                      {label} ·{" "}
                      {source.captured_at ? (
                        <time dateTime={source.captured_at}>
                          {formatKstWithYear(source.captured_at)}
                        </time>
                      ) : (
                        "기준본 없음"
                      )}
                      {"asset_names" in source && " · " + source.asset_names.join(", ")}
                    </span>
                  </li>
                )),
              )}
            </ul>
          </details>
        </>
      ) : (
        <p>완료된 공식 자료 조회가 없습니다.</p>
      )}
    </section>
  );
}
