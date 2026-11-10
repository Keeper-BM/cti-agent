import { useCallback, useState } from "react";
import { useSession } from "../../app/session";
import { Notice } from "../../shared/components/Notice";
import { formatKst } from "../../shared/format";
import { usePollingQuery } from "../../shared/hooks/usePollingQuery";
import { auditEvents } from "./api";

export function AuditPage() {
  const { api, isAdmin } = useSession();
  const [page, setPage] = useState(0);
  const load = useCallback((signal: AbortSignal) => auditEvents(api!, page, signal), [api, page]);
  const query = usePollingQuery(api && isAdmin ? load : null);
  if (!isAdmin)
    return (
      <p className="inventory-note">관리자 계정으로 연결하면 운영 기록을 확인할 수 있습니다.</p>
    );
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <h2>운영 기록</h2>
          <p>로그인·접근 거부·자산 변경·작업 요청과 처리 결과를 기록합니다.</p>
        </div>
        <button className="secondary" onClick={query.refresh}>
          새로고침
        </button>
      </div>
      <Notice error={query.error} />
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>시각</th>
              <th>작업</th>
              <th>결과</th>
              <th>식별 정보·상세</th>
            </tr>
          </thead>
          <tbody>
            {query.data?.items.map((event) => (
              <tr key={event.id}>
                <td>{formatKst(event.created_at)}</td>
                <td>{event.action}</td>
                <td>{event.outcome}</td>
                <td>
                  <details>
                    <summary>{event.target_id?.slice(0, 8) || "상세 보기"}</summary>
                    <p>
                      계정 {event.actor_id ?? "개발 토큰 또는 미인증"}
                      <br />
                      자산 {event.asset_id ?? "공통"}
                      <br />
                      요청 {event.request_id ?? "서버 작업"}
                    </p>
                    <pre>{JSON.stringify(event.details, null, 2)}</pre>
                  </details>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="pagination">
        <span>전체 {query.data?.total ?? 0}건</span>
        <div>
          <button disabled={!page} onClick={() => setPage(page - 1)}>
            이전
          </button>
          <button
            disabled={(page + 1) * 30 >= (query.data?.total ?? 0)}
            onClick={() => setPage(page + 1)}
          >
            다음
          </button>
        </div>
      </div>
    </section>
  );
}
