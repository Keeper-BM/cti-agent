import { useCallback, useEffect, useRef, useState } from "react";
import { useSession } from "../../app/session";
import { Notice } from "../../shared/components/Notice";
import { useAction } from "../../shared/hooks/useAction";
import { usePollingQuery } from "../../shared/hooks/usePollingQuery";
import { getCVE, getDocument, getRecords, getSnapshots, getStatus, names, syncSource } from "./api";
import type { RecordData, Source, SyncInput } from "./api";

const time = (value: string) => new Date(value).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" });
const jobNames: Record<string, string> = {
  QUEUED: "대기 중",
  RUNNING: "가져오는 중",
  SUCCEEDED: "완료",
  FAILED: "실패",
  PARTIAL: "일부 완료",
};
const recordStatus: Record<string, string> = {
  FIX_AVAILABLE: "수정 기준 있음",
  UNKNOWN: "추가 확인",
  WITHDRAWN: "철회된 자료",
  REJECTED: "기각된 CVE",
  KNOWN_EXPLOITED: "악용 확인",
  REFERENCE: "참고 자료",
};

export function SourcesPage() {
  const { api, isAdmin } = useSession();
  const action = useAction();
  const [release, setRelease] = useState("22.04");
  const [pkg, setPkg] = useState("apache2");
  const [nvdCve, setNvdCve] = useState("");
  const [oracleUrl, setOracleUrl] = useState("");
  const [source, setSource] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [historyPage, setHistoryPage] = useState(0);
  const [snapshot, setSnapshot] = useState("");
  const [selected, setSelected] = useState<RecordData | null>(null);
  const detailRef = useRef<HTMLDivElement>(null);
  const statusLoad = useCallback((signal: AbortSignal) => getStatus(api!, signal), [api]);
  const status = usePollingQuery(api ? statusLoad : null);
  const revision = status.data?.items
    .map((i) => `${i.latest_job?.id}:${i.latest_job?.status}`)
    .join("|");
  const historyLoad = useCallback(
    (signal: AbortSignal) => getSnapshots(api!, source, historyPage, signal),
    [api, source, historyPage],
  );
  const history = usePollingQuery(api ? historyLoad : null, null);
  const listLoad = useCallback(
    (signal: AbortSignal) =>
      getRecords(
        api!,
        {
          ...(source ? { source_id: source } : {}),
          ...(snapshot ? { snapshot_id: snapshot } : {}),
          cve: search,
          limit: "20",
          offset: String(page * 20),
        },
        signal,
      ),
    [api, source, snapshot, search, page],
  );
  const list = usePollingQuery(api ? listLoad : null, null);
  useEffect(() => {
    history.refresh();
    list.refresh();
  }, [revision, history.refresh, list.refresh]);
  useEffect(() => {
    if (selected) detailRef.current?.focus({ preventScroll: true });
  }, [selected?.id]);

  async function sync(id: Source, body: SyncInput) {
    if (!api) return;
    await action.run(
      () => syncSource(api, id, body),
      `${names[id]} 수집을 요청했습니다. 처리 상태는 출처 카드와 작업 내역에서 확인하세요.`,
    );
    status.refresh();
  }
  function clearSelection() {
    setPage(0);
    setSelected(null);
  }

  return (
    <>
      <Notice error={action.error || status.error} success={action.notice} />
      <div className="inline-info">
        <span className="info-icon">i</span>
        <span>
          공식 자료를 CVE 번호로 연결해 확인합니다. 아래 수정 기준과 위험 정보는 자산에 대한 판정
          결과가 아닙니다.
        </span>
      </div>
      <div className="source-cards">
        {(Object.keys(names) as Source[]).map((id) => {
          const item = status.data?.items.find((s) => s.source_id === id);
          const busy = item?.latest_job && ["QUEUED", "RUNNING"].includes(item.latest_job.status);
          const payload: SyncInput =
            id === "ubuntu"
              ? { release: release as "22.04" | "24.04", package: pkg as "apache2" | "mysql-8.0" }
              : id === "nvd"
                ? { cve_id: nvdCve.trim().toUpperCase() }
                : id === "oracle"
                  ? { url: oracleUrl.trim() }
                  : {};
          return (
            <section className="panel source-card" key={id} aria-label={`${names[id]} 자료 수집`}>
              <div className="source-card-top">
                <h2>{names[id]}</h2>
                <span
                  className={`badge ${busy ? "queued" : item?.latest_job?.status === "FAILED" ? "failed" : ""}`}
                >
                  {item?.latest_job ? jobNames[item.latest_job.status] : "수집 전"}
                </span>
              </div>
              <p>{item?.purpose ?? "공식 자료 연결"}</p>
              {id === "ubuntu" && (
                <div className="source-fields">
                  <label>
                    Ubuntu 버전
                    <select value={release} onChange={(e) => setRelease(e.target.value)}>
                      <option>22.04</option>
                      <option>24.04</option>
                    </select>
                  </label>
                  <label>
                    패키지
                    <select value={pkg} onChange={(e) => setPkg(e.target.value)}>
                      <option value="apache2">Apache2</option>
                      <option value="mysql-8.0">MySQL 8.0</option>
                    </select>
                  </label>
                </div>
              )}
              {id === "nvd" && (
                <label>
                  CVE 번호
                  <input
                    value={nvdCve}
                    onChange={(e) => setNvdCve(e.target.value)}
                    placeholder="CVE-2023-25690"
                    maxLength={32}
                  />
                </label>
              )}
              {id === "oracle" && (
                <label>
                  Oracle 공식 공지 주소
                  <input
                    value={oracleUrl}
                    onChange={(e) => setOracleUrl(e.target.value)}
                    placeholder="https://www.oracle.com/security-alerts/cpu…html"
                    maxLength={450}
                  />
                </label>
              )}
              {id === "nvd" && (
                <small>
                  {status.data?.nvd_key_configured
                    ? "설정된 NVD 키 사용"
                    : "키 없이 사용 가능 · 요청 간격을 두고 조회"}
                </small>
              )}
              {id === "oracle" && (
                <small>
                  선택한 공지의 MySQL 표를 가져옵니다. CVE 상세에서도 관련 공지를 선택할 수
                  있습니다.
                </small>
              )}
              {item?.latest_snapshot && (
                <div className="source-last">
                  <span>마지막 저장 {time(item.latest_snapshot.captured_at)}</span>
                  <span>
                    {item.latest_snapshot.record_count}건 · {item.latest_snapshot.scope_key}
                  </span>
                </div>
              )}
              {item?.latest_job?.status === "FAILED" && (
                <p className="source-failure">
                  {String(
                    item.latest_job.result?.message ?? item.latest_job.error_code ?? "수집 실패",
                  )}{" "}
                  기존에 저장한 자료는 유지됩니다.
                </p>
              )}
              <button
                className="secondary"
                disabled={
                  !api ||
                  !isAdmin ||
                  action.pending ||
                  !!busy ||
                  (id === "nvd" && !/^CVE-\d{4}-\d{4,19}$/i.test(nvdCve.trim())) ||
                  (id === "oracle" && !oracleUrl.trim())
                }
                onClick={() => sync(id, payload)}
              >
                {busy ? "수집 처리 중…" : `${names[id]} 수집`}
              </button>
            </section>
          );
        })}
      </div>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>저장된 보안 자료</h2>
            <p>
              출처별로 가장 최근에 저장한 범위를 표시합니다. 같은 CVE도 출처와 릴리스가 다르면 별도
              자료입니다.
            </p>
          </div>
          <button
            className="secondary"
            disabled={!api || list.loading}
            onClick={() => {
              list.refresh();
              history.refresh();
              status.refresh();
            }}
          >
            새로고침
          </button>
        </div>
        <div className="source-filters">
          <label>
            출처
            <select
              value={source}
              onChange={(e) => {
                setSource(e.target.value);
                setSnapshot("");
                setHistoryPage(0);
                clearSelection();
              }}
            >
              <option value="">전체 출처</option>
              {(Object.keys(names) as Source[]).map((id) => (
                <option key={id} value={id}>
                  {names[id]}
                </option>
              ))}
            </select>
          </label>
          <label>
            CVE 검색
            <input
              type="search"
              placeholder="CVE 번호로 검색"
              maxLength={40}
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                clearSelection();
              }}
            />
          </label>
        </div>
        <div className="source-history">
          <details>
            <summary>저장 이력 {history.data ? `· ${history.data.total}개 기준본` : ""}</summary>
            <Notice error={history.error} />
            <button
              className="text-button"
              onClick={() => {
                setSnapshot("");
                clearSelection();
              }}
            >
              최신 자료로 돌아가기
            </button>
            <ul>
              {history.data?.items.map((s) => (
                <li key={s.id}>
                  <button
                    className={snapshot === s.id ? "selected" : ""}
                    onClick={() => {
                      setSnapshot(s.id);
                      clearSelection();
                    }}
                    aria-pressed={snapshot === s.id}
                  >
                    {names[s.source_id]} · {time(s.captured_at)} · {s.record_count}건{" "}
                    <small>{s.scope_key}</small>
                  </button>
                </li>
              ))}
            </ul>
            {(history.data?.total ?? 0) > 20 && (
              <div className="pagination">
                <button
                  disabled={!historyPage || history.loading}
                  onClick={() => setHistoryPage(historyPage - 1)}
                >
                  이전 이력
                </button>
                <span>{historyPage + 1} 페이지</span>
                <button
                  disabled={(historyPage + 1) * 20 >= history.data!.total || history.loading}
                  onClick={() => setHistoryPage(historyPage + 1)}
                >
                  다음 이력
                </button>
              </div>
            )}
          </details>
        </div>
        {snapshot && (
          <p className="source-history-note">
            선택한 과거 기준본을 조회하고 있습니다.{" "}
            <button
              className="text-button"
              onClick={() => {
                setSnapshot("");
                clearSelection();
              }}
            >
              최신 자료 보기
            </button>
          </p>
        )}
        <Notice error={list.error} />
        <div className="table-wrap">
          <table className="sources-table">
            <thead>
              <tr>
                <th>CVE · 출처</th>
                <th>대상 범위</th>
                <th>자료 상태</th>
                <th>Ubuntu 수정 버전</th>
                <th>수집 시각</th>
              </tr>
            </thead>
            <tbody>
              {list.data?.items.map((r) => (
                <tr key={r.id} className={selected?.id === r.id ? "selected-row" : ""}>
                  <td>
                    <button className="asset-name" onClick={() => setSelected(r)}>
                      {r.data.cve_id}
                    </button>
                    <small className="cell-sub">{names[r.source_id]}</small>
                  </td>
                  <td>
                    {r.data.package_name ?? "제품 공지 / 참고"}
                    <small className="cell-sub">
                      {r.data.release ? `Ubuntu ${r.data.release}` : "출처의 적용 조건 확인"}
                    </small>
                  </td>
                  <td>
                    <span className="badge">{recordStatus[r.data.status]}</span>
                  </td>
                  <td className="mono">
                    {r.source_id === "ubuntu" ? (r.data.fixed_version ?? "미제공") : "—"}
                  </td>
                  <td>{time(r.document.captured_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!list.data?.items.length && (
          <div className="empty compact">
            <strong>
              {!api
                ? "연결 후 자료를 확인할 수 있습니다"
                : list.loading
                  ? "자료를 불러오는 중입니다"
                  : list.error
                    ? "자료 조회 실패"
                    : "표시할 자료가 없습니다"}
            </strong>
            <p>위의 출처에서 자료를 가져오거나 검색 조건을 변경하세요.</p>
          </div>
        )}
        {!!list.data?.total && (
          <div className="pagination">
            <span>
              자료 {list.data.total}건 · {page + 1} / {Math.ceil(list.data.total / 20)}
            </span>
            <div>
              <button
                disabled={!page || list.loading}
                onClick={() => {
                  setPage(page - 1);
                  setSelected(null);
                }}
              >
                이전
              </button>
              <button
                disabled={(page + 1) * 20 >= list.data.total || list.loading}
                onClick={() => {
                  setPage(page + 1);
                  setSelected(null);
                }}
              >
                다음
              </button>
            </div>
          </div>
        )}
      </section>
      {selected && (
        <div ref={detailRef} tabIndex={-1} className="source-detail-focus">
          <CVEDetail
            key={`${selected.id}:${snapshot}`}
            record={selected}
            historical={!!snapshot}
            revision={revision}
            sync={sync}
            pending={action.pending}
          />
        </div>
      )}
    </>
  );
}

function CVEDetail({
  record,
  historical,
  revision,
  sync,
  pending,
}: {
  record: RecordData;
  historical: boolean;
  revision?: string;
  sync: (id: Source, body: SyncInput) => Promise<void>;
  pending: boolean;
}) {
  const { api } = useSession();
  const load = useCallback(
    (signal: AbortSignal) => getCVE(api!, record.data.cve_id, signal),
    [api, record.data.cve_id],
  );
  const query = usePollingQuery(api && !historical ? load : null, null);
  useEffect(() => query.refresh(), [revision, query.refresh]);
  const rows = historical ? [record] : (query.data?.records ?? []);
  return (
    <section className="panel source-detail">
      <div className="panel-heading">
        <div>
          <h2>{record.data.cve_id}</h2>
          <p>{historical ? "선택한 과거 자료 기준본" : "출처별 최신 저장 자료"}</p>
        </div>
        {!historical && (
          <button
            className="secondary"
            disabled={pending}
            onClick={() => sync("nvd", { cve_id: record.data.cve_id })}
          >
            이 CVE의 NVD 정보 갱신
          </button>
        )}
      </div>
      <div className="source-detail-body">
        <Notice error={query.error} />
        {!historical && query.data && (
          <div className="inline-info">
            <span>
              CISA KEV:{" "}
              {query.data.kev_status === "LISTED"
                ? "악용 확인 목록 등재"
                : query.data.kev_status === "NOT_LISTED"
                  ? "저장된 목록에 미등재 · 악용이 없다는 뜻은 아닙니다"
                  : "아직 가져오지 않음"}
              {query.data.kev_snapshot &&
                ` (${time(query.data.kev_snapshot.captured_at)} 수집 기준)`}
            </span>
          </div>
        )}
        {!historical && !!query.data?.oracle_urls.length && (
          <div className="oracle-links">
            <strong>관련 Oracle 공지</strong>
            {query.data.oracle_urls.map((url) => (
              <div key={url}>
                <a href={url} target="_blank" rel="noreferrer">
                  {url}
                </a>
                <button
                  className="secondary"
                  disabled={pending}
                  onClick={() => sync("oracle", { url })}
                >
                  공지 수집
                </button>
              </div>
            ))}
          </div>
        )}
        {rows.map((row) => (
          <SourceRecordDetail key={row.id} record={row} />
        ))}
      </div>
    </section>
  );
}

function SourceRecordDetail({ record }: { record: RecordData }) {
  const { api } = useSession();
  const action = useAction();
  const [raw, setRaw] = useState<string | null>(null);
  const data = record.data;
  return (
    <article className="source-evidence">
      <div className="source-evidence-heading">
        <h3>{names[record.source_id]}</h3>
        <span className="badge">{recordStatus[data.status]}</span>
      </div>
      <p className="source-description">{data.description || "설명 미제공"}</p>
      <dl className="source-facts">
        <div>
          <dt>적용 대상</dt>
          <dd>
            {data.package_name ?? "제품 공지 참조"} {data.release && `· Ubuntu ${data.release}`}
          </dd>
        </div>
        {record.source_id === "ubuntu" && (
          <div>
            <dt>Ubuntu 수정 기준</dt>
            <dd className="mono">{data.fixed_version ?? "미제공 / 추가 확인"}</dd>
          </div>
        )}
        {data.upstream_fixed_version && (
          <div>
            <dt>제품 자체 수정 버전</dt>
            <dd>{data.upstream_fixed_version}</dd>
          </div>
        )}
        <div>
          <dt>원문 공개 / 수정 시각</dt>
          <dd>
            {data.published_at ?? "미제공"} / {data.modified_at ?? "미제공"}
          </dd>
        </div>
        <div>
          <dt>가져온 시각</dt>
          <dd>{time(record.document.captured_at)}</dd>
        </div>
      </dl>
      <div className="source-metrics">
        <strong>심각도 정보</strong>
        {data.priority && <p>Ubuntu 우선순위: {data.priority}</p>}
        {data.metrics?.length ? (
          data.metrics.map((m, i) => (
            <p key={i}>
              CVSS {m.version} · {m.score ?? "숫자 점수 미제공"} {m.provider && `· ${m.provider}`}
              <small className="mono">{m.vector}</small>
            </p>
          ))
        ) : (
          <p>CVSS 미제공</p>
        )}
        {!!data.weaknesses?.length && <p>취약점 유형: {data.weaknesses.join(", ")}</p>}
      </div>
      {data.notes?.filter(Boolean).map((note) => (
        <p className="source-caution" key={note}>
          {note}
        </p>
      ))}
      {!!Object.keys(data.attributes ?? {}).length && (
        <details>
          <summary>출처의 추가 정보</summary>
          <dl className="source-attributes">
            {Object.entries(data.attributes ?? {}).map(([key, value]) => (
              <div key={key}>
                <dt>{key}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
      {!!data.ranges?.length && (
        <details>
          <summary>원문의 영향 버전 범위</summary>
          <pre>
            {JSON.stringify({ ranges: data.ranges, versions: data.affected_versions }, null, 2)}
          </pre>
        </details>
      )}
      <details>
        <summary>공식 출처 · 저장 원문</summary>
        <ul className="source-links">
          {data.references?.map((url) => (
            <li key={url}>
              <a href={url} target="_blank" rel="noreferrer">
                {url}
              </a>
            </li>
          ))}
        </ul>
        <p className="mono">가져온 주소: {record.document.url}</p>
        <p className="mono">SHA-256: {record.document.sha256}</p>
        <p className="mono">기준본: {record.snapshot_id}</p>
        <Notice error={action.error} />
        <button
          className="secondary"
          disabled={!api || action.pending}
          onClick={() =>
            action.run(async () => {
              const result = await getDocument(api!, String(record.document.id));
              setRaw(result.raw_text);
            }, "원문을 불러왔습니다.")
          }
        >
          {action.pending ? "원문 조회 중…" : "저장 원문 보기"}
        </button>
        {raw !== null && (
          <>
            <p>원문을 텍스트로 표시합니다{raw.length > 50000 ? " (앞 50,000자)" : ""}.</p>
            <pre>{raw.slice(0, 50000)}</pre>
            <button
              className="secondary"
              onClick={() => {
                const url = URL.createObjectURL(
                  new Blob([raw], { type: "text/plain;charset=utf-8" }),
                );
                const a = document.createElement("a");
                a.href = url;
                a.download = `source-${record.document.id}.txt`;
                a.click();
                setTimeout(() => URL.revokeObjectURL(url), 1000);
              }}
            >
              전체 원문 다운로드
            </button>
          </>
        )}
      </details>
    </article>
  );
}
