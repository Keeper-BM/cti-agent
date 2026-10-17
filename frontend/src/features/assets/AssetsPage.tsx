// 자산 목록, 등록, 활성 상태 변경 화면.
import { useCallback, useState } from "react";
import type { FormEvent } from "react";
import { useSession } from "../../app/session";
import { Notice } from "../../shared/components/Notice";
import { useAction } from "../../shared/hooks/useAction";
import { usePollingQuery } from "../../shared/hooks/usePollingQuery";
import { createAsset, listAssets, setAssetActive } from "./api";
import type { AssetCreate } from "./api";

const exposureLabels = { PUBLIC: "외부 공개", INTERNAL: "내부", UNKNOWN: "미확인" };

export function AssetsPage() {
  const { api } = useSession();
  const [page, setPage] = useState(0);
  const [showForm, setShowForm] = useState(false);
  const load = useCallback(
    (signal: AbortSignal) => listAssets(api!, page * 20, signal),
    [api, page],
  );
  const query = usePollingQuery(api ? load : null);
  const action = useAction();
  const assets = query.data?.items ?? [];
  const total = query.data?.total;

  async function submitAsset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!api) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    const payload: AssetCreate = {
      asset_name: String(data.get("asset_name")).trim(),
      host: String(data.get("host")).trim() || null,
      owner_display_name: String(data.get("owner")).trim() || null,
      expected_release: (data.get("release") || null) as AssetCreate["expected_release"],
      exposure: data.get("exposure") as AssetCreate["exposure"],
      exposure_source: "관리자 수동 입력",
      criticality: "UNKNOWN",
      collection_method: "MANUAL",
    };
    if (await action.run(() => createAsset(api, payload), "자산을 등록했습니다.")) {
      form.reset();
      setShowForm(false);
      setPage(0);
      query.refresh();
    }
  }

  return (
    <>
      <Notice
        error={action.error || (query.error && `${query.error} 최신 목록을 확인하지 못했습니다.`)}
        success={action.notice}
      />
      <div className="stats">
        <article className="stat">
          <span>등록 자산</span>
          <strong>
            {total ?? "—"}
            <small>대</small>
          </strong>
          <p>활성·비활성 자산 포함</p>
        </article>
        <article className="stat">
          <span>정보 수집</span>
          <strong className="muted-value">연동 전</strong>
          <p>승인 서버의 읽기 전용 수집 예정</p>
        </article>
        <article className="stat">
          <span>수집 작업</span>
          <strong className="muted-value">
            <a href="#/jobs">작업 내역 →</a>
          </strong>
          <p>처리 상태와 실패 사유 확인</p>
        </article>
      </div>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>
              관리 자산 <span className="count">{total ?? "—"}</span>
            </h2>
            <p>주소는 등록 정보로 보관되며, 자동으로 접속하지 않습니다.</p>
          </div>
          <button
            className="primary"
            disabled={!api || action.pending}
            onClick={() => setShowForm(!showForm)}
          >
            {showForm ? "닫기" : "+ 자산 등록"}
          </button>
        </div>
        {showForm && api && (
          <form className="asset-form" onSubmit={submitAsset}>
            <label>
              자산 이름
              <input name="asset_name" required maxLength={100} placeholder="예: lab-web-01" />
            </label>
            <label>
              IP 또는 호스트명
              <input name="host" maxLength={253} placeholder="예: 192.0.2.10 (선택)" />
            </label>
            <label>
              예상 Ubuntu 릴리스
              <select name="release">
                <option value="">미확정</option>
                <option value="22.04">22.04 LTS (후보)</option>
                <option value="24.04">24.04 LTS (후보)</option>
              </select>
            </label>
            <label>
              외부 공개 여부
              <select name="exposure">
                <option value="UNKNOWN">미확인</option>
                <option value="INTERNAL">내부</option>
                <option value="PUBLIC">외부 공개</option>
              </select>
            </label>
            <label>
              담당자
              <input name="owner" maxLength={100} placeholder="표시 이름 (선택)" />
            </label>
            <div className="form-submit">
              <button className="primary" disabled={action.pending} type="submit">
                {action.pending ? "저장 중…" : "자산 저장"}
              </button>
            </div>
          </form>
        )}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>자산 이름</th>
                <th>접속 주소</th>
                <th>Ubuntu</th>
                <th>노출 범위</th>
                <th>상태</th>
                <th>관리</th>
              </tr>
            </thead>
            <tbody>
              {assets.map((asset) => (
                <tr key={asset.id}>
                  <td>
                    <strong>{asset.asset_name}</strong>
                    <small className="cell-sub">
                      {asset.owner_display_name || "담당자 미지정"}
                    </small>
                  </td>
                  <td className="mono">{asset.host || "미등록"}</td>
                  <td>{asset.expected_release || "미확정"}</td>
                  <td>{exposureLabels[asset.exposure]}</td>
                  <td>
                    <span className={`badge ${asset.is_active ? "active" : ""}`}>
                      {asset.is_active ? "활성" : "비활성"}
                    </span>
                  </td>
                  <td>
                    <button
                      className="text-button"
                      disabled={action.pending}
                      onClick={async () => {
                        if (
                          api &&
                          (await action.run(
                            () => setAssetActive(api, asset.id, !asset.is_active),
                            "자산 상태를 변경했습니다.",
                          ))
                        )
                          query.refresh();
                      }}
                    >
                      {asset.is_active ? "비활성화" : "활성화"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {assets.length === 0 && (
          <div className="empty">
            <div className="empty-symbol">＋</div>
            <strong>
              {!api
                ? "연결 후 자산을 확인할 수 있습니다"
                : query.error
                  ? "자산 목록을 불러오지 못했습니다"
                  : query.loading
                    ? "자산을 불러오는 중입니다"
                    : "첫 번째 자산을 등록하세요"}
            </strong>
            <p>등록한 시험 서버의 실제 수집 기능은 다음 단계에서 연결합니다.</p>
          </div>
        )}
        {(total ?? 0) > 20 && (
          <div className="pagination">
            <button disabled={page === 0} onClick={() => setPage(page - 1)}>
              이전
            </button>
            <span>
              {page + 1} / {Math.ceil(total! / 20)}
            </span>
            <button disabled={(page + 1) * 20 >= total!} onClick={() => setPage(page + 1)}>
              다음
            </button>
          </div>
        )}
      </section>
    </>
  );
}
