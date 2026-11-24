import { useCallback, useState } from "react";
import type { HttpClient } from "../../api/client";
import { Icon } from "../../shared/components/Icon";
import { Notice } from "../../shared/components/Notice";
import { formatKstWithYear } from "../../shared/format";
import { usePollingQuery } from "../../shared/hooks/usePollingQuery";
import { findingLink } from "../findings/api";
import { ReportPages } from "../reports/ReportPreview";
import { workspaceLink } from "../workflows/api";
import { changesPageSize, listChanges, type ChangeKind, type ScheduleRun } from "./api";

const categories = [
  ["NEW_AFFECTED", "새로 영향 확인"],
  ["FIXED", "수정 기준 충족"],
  ["RECHECK", "재확인 필요"],
] as const;
const verdicts = {
  AFFECTED: "영향 있음",
  FIXED: "수정 기준 충족",
  NOT_AFFECTED: "영향 없음",
  NEEDS_REVIEW: "추가 확인 필요",
};

export function ScheduleChangesPanel({
  api,
  id,
  run,
}: {
  api: HttpClient;
  id: string;
  run: ScheduleRun;
}) {
  const [kind, setKind] = useState<ChangeKind | "">("");
  const [page, setPage] = useState(0);
  const load = useCallback(
    (signal: AbortSignal) => listChanges(api, id, run.id, kind, page, signal),
    [api, id, run.id, kind, page],
  );
  const query = usePollingQuery(load, null);
  const result = query.data;
  const comparable = result?.assets.some((asset) => asset.status === "COMPARED");
  const names = new Map(result?.assets.map((asset) => [asset.asset_id, asset.asset_name]));
  const batchId = run.batch_id;
  return (
    <div className="schedule-changes">
      <Notice error={query.error} />
      {query.error && (
        <button type="button" className="text-tool" onClick={query.refresh}>
          <Icon name="refresh" /> 변경 내역 다시 불러오기
        </button>
      )}
      {!result && !query.error && <p role="status">변경 내역을 불러오는 중…</p>}
      {comparable && result && (
        <>
          <div className="schedule-metrics" aria-label="변경 유형으로 필터링">
            {categories.map(([value, label]) => (
              <button
                key={value}
                className={value.toLowerCase()}
                aria-pressed={kind === value}
                onClick={() => {
                  setKind(kind === value ? "" : value);
                  setPage(0);
                }}
              >
                <span>{label}</span>
                <strong>{result.counts[value] ?? 0}</strong>
              </button>
            ))}
          </div>
          {result.items.length && batchId ? (
            <div className="schedule-finding-table">
              <table role="table" aria-label="변경된 자산·패키지·CVE 판정">
                <thead role="rowgroup">
                  <tr role="row">
                    <th scope="col" role="columnheader">
                      CVE·패키지
                    </th>
                    <th scope="col" role="columnheader">
                      자산
                    </th>
                    <th scope="col" role="columnheader">
                      판정 변화
                    </th>
                    <th scope="col" role="columnheader">
                      근거
                    </th>
                  </tr>
                </thead>
                <tbody role="rowgroup">
                  {result.items.map((item) => {
                    const finding = item.finding_id ?? item.previous_finding_id;
                    return (
                      <tr
                        key={`${item.asset_id}/${item.cve_id}/${item.package_name}/${item.architecture}`}
                        role="row"
                      >
                        <th scope="row" role="rowheader">
                          <strong>{item.cve_id}</strong>
                          <small>
                            {item.package_name}
                            {item.architecture ? ` · ${item.architecture}` : ""}
                          </small>
                        </th>
                        <td role="cell">{names.get(item.asset_id)}</td>
                        <td role="cell">
                          {item.previous_verdict
                            ? verdicts[item.previous_verdict]
                            : "이전 판정 없음"}
                          {" → "}
                          {item.verdict ? verdicts[item.verdict] : "이번 판정 없음"}
                        </td>
                        <td role="cell">
                          {finding && (
                            <a href={findingLink(finding, batchId, item.cve_id)}>
                              {item.finding_id ? "근거 보기" : "이전 근거"}
                            </a>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="schedule-empty" role="status">
              {kind ? "선택한 유형의 변경이 없습니다." : "비교한 자산에서 판정 변경이 없습니다."}
            </p>
          )}
          {result.total > changesPageSize && (
            <ReportPages
              label="판정 변경 내역"
              page={page}
              total={result.total}
              size={changesPageSize}
              setPage={setPage}
            />
          )}
        </>
      )}
      {!!result?.assets.length && (
        <div className="schedule-baselines">
          <h3>자산별 비교 기준</h3>
          <ul>
            {result.assets.map((asset) => (
              <li key={asset.asset_id}>
                <strong>{asset.asset_name}</strong>
                {asset.status === "COMPARED" && asset.previous_completed_at ? (
                  <a href={workspaceLink(asset.asset_id, asset.previous_analysis_id ?? undefined)}>
                    기준 분석 {formatKstWithYear(asset.previous_completed_at)}
                  </a>
                ) : asset.status === "BASELINE" ? (
                  <span>첫 성공 결과를 비교 기준으로 사용합니다.</span>
                ) : (
                  <span className="schedule-unavailable">비교 보류 · {asset.reason}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
