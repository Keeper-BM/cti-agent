import { useCallback, useRef, useState } from "react";
import type { HttpClient } from "../../api/client";
import { Icon } from "../../shared/components/Icon";
import { Notice } from "../../shared/components/Notice";
import { usePollingQuery } from "../../shared/hooks/usePollingQuery";
import {
  listFindings,
  listFindingGroups,
  type Finding,
  type FindingGroup,
  type Verdict,
} from "../findings/api";
import { count, shortTime, type Brief } from "./api";

const labels: Record<Verdict, string> = {
  AFFECTED: "영향 있음",
  NEEDS_REVIEW: "추가 확인 필요",
  FIXED: "수정 기준 충족",
  NOT_AFFECTED: "영향 없음",
};
const verdictOrder: Verdict[] = ["AFFECTED", "NEEDS_REVIEW", "FIXED", "NOT_AFFECTED"];
const pageSize = 5;
function Pager({
  page,
  total,
  setPage,
  unit,
}: {
  page: number;
  total: number;
  setPage: (n: number) => void;
  unit: string;
}) {
  return total > pageSize ? (
    <div className="work-pager">
      <span>
        {unit} {count(total)}
        {unit === "CVE" ? "개" : "건"} · {page + 1} / {Math.ceil(total / pageSize)}
      </span>
      <button disabled={!page} onClick={() => setPage(page - 1)}>
        이전
      </button>
      <button disabled={(page + 1) * pageSize >= total} onClick={() => setPage(page + 1)}>
        다음
      </button>
    </div>
  ) : null;
}
function ComparedVersions({ finding: f }: { finding: Finding }) {
  const source = f.comparison_basis === "SOURCE";
  const installed = source
    ? f.installed_version
    : (f.binary_version ?? (f.comparison_basis === "BINARY" ? f.installed_version : null));
  return (
    <dl className="compared-versions">
      <div>
        <dt>{source ? "설치 소스 버전" : "설치 바이너리 버전"}</dt>
        <dd>
          <samp>{installed ?? "미확인"}</samp>
        </dd>
      </div>
      <div>
        <dt>공식 수정 기준</dt>
        <dd>
          <samp>{f.fixed_version ?? "기준 미제공"}</samp>
        </dd>
      </div>
    </dl>
  );
}
function FindingEvidence({ finding: f }: { finding: Finding }) {
  return (
    <div className="finding-evidence">
      {f.reasons?.length ? (
        <div>
          <h4>판정 근거</h4>
          <ul>
            {f.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {f.remediation?.steps.length ? (
        <div>
          <h4>권고 조치</h4>
          <ol>
            {f.remediation.steps.map((s, i) => (
              <li key={i}>
                <b>{s.title}</b> · {s.description}
              </li>
            ))}
          </ol>
        </div>
      ) : null}
      {f.limitations?.length ? (
        <div>
          <h4>판정 범위</h4>
          <ul>
            {f.limitations.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {!!f.evidence_refs?.length && (
        <div className="evidence-links">
          {f.evidence_refs.map((e, i) => (
            <a href={e.url} key={e.document_version_id + ":" + i} target="_blank" rel="noreferrer">
              {e.source} 공식 근거
              <Icon name="external" />
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

function PriorityFinding({ api, analysis }: { api: HttpClient; analysis: Brief }) {
  const load = useCallback(
    (signal: AbortSignal) => listFindingGroups(api, analysis.id, "AFFECTED", 0, signal),
    [api, analysis.id],
  );
  const query = usePollingQuery(load, null);
  const [open, setOpen] = useState(false);
  const f = query.data?.items[0]?.representative;
  const action = f?.remediation?.steps[0];
  const reason = f?.reasons?.at(-1);
  return (
    <article className="work-card priority-finding">
      <div className="lead-label">
        <Icon name="alert" />
        <span>영향 있음 · {count(analysis.summary.AFFECTED)}건</span>
        {analysis.summary.AFFECTED > 1 && <span className="lead-selection">우선 대응 항목</span>}
      </div>
      {f ? (
        <>
          <div className="lead-heading">
            <h3>{f.cve_id}</h3>
            <span className="package-name">{f.package_name ?? "패키지 미확인"}</span>
          </div>
          {reason && <p className="reason-line">{reason}</p>}
          <ComparedVersions finding={f} />
          {action && (
            <div className="first-action">
              <Icon name="shield" />
              <div>
                <h4>{action.title}</h4>
                <p>{action.description}</p>
              </div>
            </div>
          )}
          <button className="evidence-button" aria-expanded={open} onClick={() => setOpen(!open)}>
            {open ? "판정 근거 닫기" : "판정 근거 보기"}
            <Icon name="chevron" />
          </button>
          {open && <FindingEvidence finding={f} />}
        </>
      ) : (
        <>
          <Notice error={query.error} />
          {!query.error && (
            <p className="aside-empty">
              {query.data
                ? "판정 목록에서 패키지 근거를 확인하세요."
                : "영향이 확인된 패키지를 불러오는 중…"}
            </p>
          )}
        </>
      )}
    </article>
  );
}

function PackageEvidence({
  finding: f,
  expanded = false,
}: {
  finding: Finding;
  expanded?: boolean;
}) {
  return (
    <div className="package-evidence">
      <details open={expanded || undefined}>
        <summary>
          <span>
            <b>{f.package_name ?? "패키지 미확인"}</b>
            {f.architecture && <small>{f.architecture}</small>}
          </span>
          <span className="summary-action">
            패키지 근거
            <Icon name="chevron" />
          </span>
        </summary>
        <ComparedVersions finding={f} />
        <FindingEvidence finding={f} />
      </details>
    </div>
  );
}

function PackageRows({
  api,
  analysis,
  verdict,
  group,
}: {
  api: HttpClient;
  analysis: string;
  verdict: Verdict;
  group?: FindingGroup;
}) {
  const [page, setPage] = useState(0);
  const single = group?.finding_count === 1;
  const load = useCallback(
    (signal: AbortSignal) =>
      listFindings(
        api,
        {
          analysis_id: analysis,
          limit: String(pageSize),
          offset: String(page * pageSize),
          ...(group ? { verdict, cve_id: group.cve_id } : { processing_status: "OUT_OF_SCOPE" }),
        },
        signal,
      ),
    [api, analysis, group?.cve_id, verdict, page],
  );
  const query = usePollingQuery(single ? null : load, null);
  const items = single ? [group!.representative] : query.data?.items;
  return (
    <div className="group-packages">
      <Notice error={query.error} />
      {!items && !query.error && <p role="status">패키지 근거를 불러오는 중…</p>}
      {items?.map((f) => (
        <PackageEvidence key={f.finding_id} finding={f} expanded={single} />
      ))}
      {query.data && <Pager page={page} total={query.data.total} setPage={setPage} unit="결과" />}
    </div>
  );
}

function Groups({
  api,
  analysis,
  verdict,
}: {
  api: HttpClient;
  analysis: string;
  verdict: Verdict;
}) {
  const [page, setPage] = useState(0);
  const [open, setOpen] = useState("");
  const load = useCallback(
    (signal: AbortSignal) => listFindingGroups(api, analysis, verdict, page, signal),
    [api, analysis, verdict, page],
  );
  const query = usePollingQuery(load, null);
  return (
    <div className="group-results">
      <Notice error={query.error} />
      {query.data ? (
        <>
          {query.data.total > 0 ? (
            <>
              <div className="group-count">
                <span>CVE</span>
                <strong>{count(query.data.total)}개</strong>
              </div>
              <ul className="group-list">
                {query.data.items.map((g) => (
                  <li key={g.cve_id}>
                    <button
                      className="group-row"
                      aria-label={g.cve_id + (open === g.cve_id ? " 근거 닫기" : " 근거 보기")}
                      aria-expanded={open === g.cve_id}
                      onClick={() => setOpen(open === g.cve_id ? "" : g.cve_id)}
                    >
                      <span className="group-title">
                        <b>{g.cve_id}</b>
                        <small>
                          {g.package_count === 1 && g.representative.package_name
                            ? g.representative.package_name
                            : "관련 패키지 " + count(g.package_count) + "개"}
                          {g.finding_count > g.package_count && " · 결과 " + g.finding_count + "건"}
                        </small>
                      </span>
                      <span className="summary-action">
                        {open === g.cve_id ? "근거 닫기" : "근거 보기"}
                        <Icon name="chevron" />
                      </span>
                    </button>
                    {open === g.cve_id && (
                      <PackageRows api={api} analysis={analysis} verdict={verdict} group={g} />
                    )}
                  </li>
                ))}
              </ul>
              <Pager
                page={page}
                total={query.data.total}
                setPage={(n) => {
                  setPage(n);
                  setOpen("");
                }}
                unit="CVE"
              />
            </>
          ) : (
            <p className="quiet-empty">이 판정에 해당하는 CVE가 없습니다.</p>
          )}
        </>
      ) : (
        !query.error && (
          <p role="status" className="quiet-empty">
            CVE를 불러오는 중…
          </p>
        )
      )}
    </div>
  );
}

export function Results({ api, analysis }: { api: HttpClient; analysis: Brief }) {
  const totals = analysis.summary;
  const grouped = useRef<HTMLElement>(null);
  const [filter, setFilter] = useState<Verdict>(() =>
    totals.NEEDS_REVIEW ? "NEEDS_REVIEW" : (verdictOrder.find((v) => totals[v]) ?? "AFFECTED"),
  );
  const [outside, setOutside] = useState(false);
  const metrics = verdictOrder.filter((v) => v !== "NOT_AFFECTED" || (totals[v] ?? 0) > 0);
  const evaluated = verdictOrder.reduce((n, v) => n + (totals[v] ?? 0), 0);
  return (
    <>
      <div className="result-heading">
        <div className="result-date">
          {" "}
          <h2>분석 결과</h2>
          <span>
            <time dateTime={analysis.completed_at}>{shortTime(analysis.completed_at)}</time> 기준
          </span>
        </div>
        <div className="result-links">
          {" "}
          <a href={"#/questions?analysis=" + analysis.id}>
            <Icon name="insights" />이 분석에 질문
          </a>
        </div>
      </div>
      {totals.AFFECTED > 0 ? (
        <PriorityFinding api={api} analysis={analysis} />
      ) : (
        <div className="summary-note">
          <Icon name="shield" />
          <div>
            <strong>
              {evaluated
                ? "평가 범위에서 영향이 확인된 항목은 0건입니다."
                : "최종 판정된 패키지·CVE 조합이 없습니다."}
            </strong>
            {totals.NEEDS_REVIEW > 0 && (
              <p>추가 확인이 필요한 조합 {count(totals.NEEDS_REVIEW)}건의 근거를 확인하세요.</p>
            )}
          </div>
        </div>
      )}
      <div className="work-card result-metrics" role="group" aria-label="판정별 패키지·CVE 조합 수">
        {metrics.map((v) => (
          <button
            key={v}
            className={"metric metric-" + v.toLowerCase()}
            onClick={() => {
              setFilter(v);
              grouped.current?.scrollIntoView({ block: "start" });
            }}
            aria-pressed={filter === v}
          >
            <span>
              <i />
              {labels[v]}
            </span>
            <strong>
              {count(totals[v] ?? 0)}
              <small>건</small>
            </strong>
          </button>
        ))}
      </div>
      <p className="metric-note">평가한 패키지·CVE 조합 {count(evaluated)}건</p>
      <section ref={grouped} className="work-card grouped-findings">
        <div className="card-heading">
          <h2>CVE별 판정</h2>
          <label className="filter-select">
            <span className="sr-only">결과 분류</span>
            <select value={filter} onChange={(e) => setFilter(e.target.value as Verdict)}>
              {metrics.map((v) => (
                <option key={v} value={v}>
                  {labels[v]}
                </option>
              ))}
            </select>
          </label>
        </div>
        <Groups key={filter} api={api} analysis={analysis.id} verdict={filter} />
        {(totals.OUT_OF_SCOPE ?? 0) > 0 && (
          <div className="outside-block">
            <button aria-expanded={outside} onClick={() => setOutside(!outside)}>
              지원 범위 밖 <b>{count(totals.OUT_OF_SCOPE)}건</b>
              <Icon name="chevron" />
            </button>
            {outside && <PackageRows api={api} analysis={analysis.id} verdict={filter} />}
          </div>
        )}
        <div className="result-links">
          <a href={"#/findings?analysis=" + analysis.id}>
            <Icon name="findings" />
            전체 분석 근거
          </a>
        </div>
      </section>
    </>
  );
}
