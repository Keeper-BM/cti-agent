import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import type { HttpClient } from "../../api/client";
import { Notice } from "../../shared/components/Notice";
import { formatKstWithYear } from "../../shared/format";
import { usePollingQuery } from "../../shared/hooks/usePollingQuery";
import { findingLink, type Verdict } from "../findings/api";
import { routeParam } from "../workflows/api";
import { compareBatch, coverageLabels, type Batch } from "./api";

const verdictLabels: Record<Verdict, string> = {
  AFFECTED: "영향 있음",
  NEEDS_REVIEW: "추가 확인 필요",
  FIXED: "수정 기준 충족",
  NOT_AFFECTED: "영향 없음",
};

export function BatchComparison({ api, batch }: { api: HttpClient; batch: Batch }) {
  const [initial] = useState(() => routeParam("cve").toUpperCase());
  const [requested, setRequested] = useState(initial);
  const [input, setInput] = useState(initial);
  const heading = useRef<HTMLHeadingElement>(null);
  const id = batch.id;
  const load = useCallback(
    (signal: AbortSignal) => compareBatch(api, id, requested, signal),
    [api, id, requested],
  );
  const query = usePollingQuery(load, null);
  const result = query.data && (!requested || query.data.cve_id === requested) ? query.data : null;
  const bases = new Set(
    result?.items.flatMap((item) => (item.ubuntu_snapshot_id ? [item.ubuntu_snapshot_id] : [])),
  );
  const assetNames = new Map(batch.assets.map((asset) => [asset.asset_id, asset.asset_name]));
  const comparedAssets = new Set(result?.items.map((item) => item.asset_id));
  useEffect(() => {
    if (initial) heading.current?.focus();
  }, [initial]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cve = input.trim().toUpperCase();
    setInput(cve);
    if (cve === requested) query.refresh();
    else setRequested(cve);
  }

  return (
    <section
      className="panel batch-panel batch-comparison"
      aria-labelledby="batch-comparison-title"
    >
      <div className="panel-heading">
        <div>
          <h2 id="batch-comparison-title" tabIndex={-1} ref={heading}>
            같은 CVE 비교
          </h2>
          <p>이 실행에 저장된 설치 버전과 Ubuntu 수정 기준을 자산별로 확인합니다.</p>
        </div>
        <form onSubmit={submit}>
          <label className="sr-only" htmlFor="batch-cve">
            비교할 CVE 번호
          </label>
          <input
            id="batch-cve"
            value={input}
            onChange={(event) => setInput(event.currentTarget.value)}
            placeholder="예: CVE-2024-27316"
            pattern="[Cc][Vv][Ee]-[0-9]{4}-[0-9]{4,}"
            title="CVE-연도-번호 형식"
            maxLength={32}
            autoComplete="off"
            spellCheck={false}
          />
          <button className="secondary" type="submit">
            비교
          </button>
        </form>
      </div>
      <Notice error={query.error} />
      {result?.cve_id ? (
        <>
          <div className="batch-comparison-caption">
            <h3>{result.cve_id}</h3>
            {bases.size > 1 && (
              <p>사용한 Ubuntu 기준본이 여러 개입니다. 자산별 기준 시각을 확인하세요.</p>
            )}
          </div>
          <div
            className="table-wrap"
            role="region"
            tabIndex={0}
            aria-label={result.cve_id + " 자산별 판정"}
          >
            <table>
              <thead>
                <tr>
                  <th scope="col">자산</th>
                  <th scope="col">패키지</th>
                  <th scope="col">설치 버전</th>
                  <th scope="col">Ubuntu 수정 기준</th>
                  <th scope="col">판정</th>
                  <th scope="col">근거</th>
                </tr>
              </thead>
              <tbody>
                {result.items.map((item) => {
                  const name = assetNames.get(item.asset_id) ?? "자산 미확인";
                  return (
                    <tr key={item.finding_id}>
                      <th scope="row">{name}</th>
                      <td>
                        {item.package_name ?? "패키지 미확인"}
                        {item.architecture && <small>{item.architecture}</small>}
                      </td>
                      <td>
                        <samp>{item.binary_version ?? item.installed_version ?? "미확인"}</samp>
                        {item.binary_version &&
                          item.installed_version &&
                          item.binary_version !== item.installed_version && (
                            <small>대조 버전 {item.installed_version}</small>
                          )}
                      </td>
                      <td>
                        <samp>{item.fixed_version ?? "기준 미제공"}</samp>
                        {item.captured_at && <small>{formatKstWithYear(item.captured_at)}</small>}
                      </td>
                      <td>
                        <span
                          className={
                            item.verdict === "AFFECTED"
                              ? "batch-affected"
                              : item.verdict === "NEEDS_REVIEW"
                                ? "batch-review"
                                : "batch-state"
                          }
                        >
                          {verdictLabels[item.verdict]}
                        </span>
                      </td>
                      <td>
                        <a
                          href={findingLink(item.finding_id, id, result.cve_id ?? undefined)}
                          aria-label={name + " " + (item.package_name ?? "패키지") + " 근거 보기"}
                        >
                          근거 보기
                        </a>
                      </td>
                    </tr>
                  );
                })}
                {batch.assets
                  .filter((asset) => !comparedAssets.has(asset.asset_id))
                  .map((asset) => (
                    <tr key={asset.asset_id}>
                      <th scope="row">{asset.asset_name}</th>
                      <td colSpan={5}>
                        {asset.status === "FAILED"
                          ? "분석 실패"
                          : asset.coverage && asset.coverage !== "EVALUATED"
                            ? coverageLabels[asset.coverage]
                            : "이 CVE에 대한 판정 기록 없음"}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </>
      ) : !query.error ? (
        <p className="batch-comparison-caption" role="status">
          {query.loading || !result
            ? "CVE 판정을 불러오는 중…"
            : "비교할 CVE 판정 기록이 없습니다."}
        </p>
      ) : null}
    </section>
  );
}
