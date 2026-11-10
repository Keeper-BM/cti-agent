import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useSession } from "../../app/session";
import { Icon } from "../../shared/components/Icon";
import { Notice } from "../../shared/components/Notice";
import { formatKst } from "../../shared/format";
import { useAction } from "../../shared/hooks/useAction";
import { usePollingQuery } from "../../shared/hooks/usePollingQuery";
import { createAsset, editAsset, listAssets, setAssetActive } from "./api";
import type { Asset, AssetCreate } from "./api";
import { InventoryPanel } from "../inventories/InventoryPanel";
import { CollectionPanel } from "../collections/CollectionPanel";

const exposureLabels = { PUBLIC: "외부 공개", INTERNAL: "내부", UNKNOWN: "미확인" };

export function AssetsPage() {
  const { api, isAdmin, canWrite } = useSession();
  const [page, setPage] = useState(0);
  const [showForm, setShowForm] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [collected, setCollected] = useState<{ assetId: string; inventoryId: string } | null>(null);
  const onCollected = useCallback((assetId: string, inventoryId: string) => {
    setCollected({ assetId, inventoryId });
  }, []);
  const detailRef = useRef<HTMLElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const load = useCallback(
    (signal: AbortSignal) => listAssets(api!, page * 20, signal),
    [api, page],
  );
  const query = usePollingQuery(api ? load : null);
  const action = useAction();
  const assets = query.data?.items ?? [];
  const total = query.data?.total;
  const selected = assets.find((asset) => asset.id === selectedId);

  useEffect(() => {
    if (selectedId && detailOpen) detailRef.current?.focus({ preventScroll: true });
  }, [selectedId, detailOpen]);

  function closeDetail() {
    setDetailOpen(false);
    if (triggerRef.current?.isConnected) triggerRef.current.focus({ preventScroll: true });
  }

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
      setSelectedId(null);
      query.refresh();
    }
  }

  return (
    <>
      <Notice
        error={action.error || (query.error && `${query.error} 최신 목록을 확인하지 못했습니다.`)}
        success={action.notice}
      />
      <div className="inline-info">
        <span className="info-icon" aria-hidden="true">
          i
        </span>
        <span>자산별 SSH 패키지 수집, 파일 입력 및 저장된 패키지 목록을 관리합니다.</span>
      </div>
      <section className="panel assets-panel" aria-labelledby="assets-title">
        <div className="panel-heading">
          <div>
            <div className="section-title">
              <h2 id="assets-title">관리 자산</h2>
              <span
                className="count"
                aria-label={total === undefined ? "자산 수 확인 전" : `전체 ${total}개`}
              >
                {total ?? "—"}
              </span>
            </div>
            <p>등록된 자산의 주소와 관리 상태를 확인합니다.</p>
          </div>
          <div className="toolbar-actions">
            <button
              className="icon-button"
              disabled={!api || query.loading}
              onClick={query.refresh}
              aria-label="자산 목록 새로고침"
              title="새로고침"
            >
              <Icon name="refresh" />
            </button>
            <button
              className="primary"
              disabled={!api || !isAdmin || action.pending}
              onClick={() => setShowForm(!showForm)}
              aria-expanded={showForm}
            >
              {showForm ? (
                "닫기"
              ) : (
                <>
                  <Icon name="plus" /> 자산 등록
                </>
              )}
            </button>
          </div>
        </div>
        {showForm && api && (
          <form id="asset-registration" className="asset-form" onSubmit={submitAsset}>
            <div className="form-heading">
              <strong>새 자산 등록</strong>
              <span>주소는 등록 정보로만 저장됩니다.</span>
            </div>
            <label>
              자산 이름 <span className="required">필수</span>
              <input name="asset_name" required maxLength={100} placeholder="예: lab-web-01" />
            </label>
            <label>
              IP 또는 호스트명 <span>선택</span>
              <input name="host" maxLength={253} placeholder="예: 192.0.2.10" />
            </label>
            <label>
              예상 Ubuntu 버전 <span>선택</span>
              <select name="release" aria-describedby="asset-release-hint">
                <option value="">미확정</option>
                <option value="22.04">22.04 LTS</option>
                <option value="24.04">24.04 LTS</option>
              </select>
              <small id="asset-release-hint" className="field-hint">
                실제 조회한 OS 정보와 대조합니다. 분석 대상은 Apache2·MySQL Ubuntu 패키지입니다.
              </small>
            </label>
            <label>
              노출 범위
              <select name="exposure">
                <option value="UNKNOWN">미확인</option>
                <option value="INTERNAL">내부</option>
                <option value="PUBLIC">외부 공개</option>
              </select>
            </label>
            <label>
              담당자 <span>선택</span>
              <input name="owner" maxLength={100} placeholder="표시 이름" />
            </label>
            <div className="form-submit">
              <button className="secondary" type="button" onClick={() => setShowForm(false)}>
                취소
              </button>
              <button className="primary" disabled={action.pending} type="submit">
                {action.pending ? "저장 중…" : "자산 저장"}
              </button>
            </div>
          </form>
        )}
        {assets.length ? (
          <div className={`asset-layout ${selected ? "has-detail" : ""}`}>
            <div className="table-wrap">
              <table className="asset-table">
                <thead>
                  <tr>
                    <th>자산 이름</th>
                    <th>IP / 호스트명</th>
                    <th>예상 Ubuntu</th>
                    <th>노출 범위</th>
                    <th>상태</th>
                    <th>
                      <span className="sr-only">관리</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {assets.map((asset) => (
                    <tr key={asset.id} className={selectedId === asset.id ? "selected-row" : ""}>
                      <td>
                        <button
                          className="asset-name"
                          aria-expanded={selectedId === asset.id && detailOpen}
                          aria-label={`${asset.asset_name} 상세 ${selectedId === asset.id && detailOpen ? "닫기" : "보기"}`}
                          onClick={(event) => {
                            triggerRef.current = event.currentTarget;
                            setDetailOpen(selectedId !== asset.id || !detailOpen);
                            setSelectedId(asset.id);
                          }}
                        >
                          {asset.asset_name}
                          <Icon name="arrow" />
                        </button>
                        <small className="cell-sub">
                          {asset.owner_display_name || "담당자 미지정"}
                        </small>
                      </td>
                      <td className="mono">{asset.host || "미등록"}</td>
                      <td>{asset.expected_release || "미확정"}</td>
                      <td>{exposureLabels[asset.exposure]}</td>
                      <td>
                        <span className={`badge ${asset.is_active ? "active" : "inactive"}`}>
                          <i />
                          {asset.is_active ? "활성" : "비활성"}
                        </span>
                      </td>
                      <td>
                        <button
                          className="text-button"
                          disabled={!canWrite || action.pending}
                          aria-label={`${asset.asset_name} ${asset.is_active ? "비활성화" : "활성화"}`}
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
            {selected && detailOpen && (
              <aside
                ref={detailRef}
                tabIndex={-1}
                className="asset-detail"
                aria-labelledby="asset-detail-title"
                onKeyDown={(event) => {
                  if (event.key === "Escape") closeDetail();
                }}
              >
                <div className="detail-top">
                  <span className="eyebrow">자산 정보</span>
                  <button
                    className="icon-button small"
                    onClick={closeDetail}
                    aria-label="자산 상세 닫기"
                  >
                    <Icon name="close" />
                  </button>
                </div>
                <h3 id="asset-detail-title">{selected.asset_name}</h3>
                <p className="detail-sub">등록된 자산 정보</p>
                <dl className="detail-list">
                  <div>
                    <dt>IP / 호스트명</dt>
                    <dd className="mono">{selected.host || "미등록"}</dd>
                  </div>
                  <div>
                    <dt>예상 Ubuntu</dt>
                    <dd>{selected.expected_release || "미확정"}</dd>
                  </div>
                  <div>
                    <dt>노출 범위</dt>
                    <dd>{exposureLabels[selected.exposure]}</dd>
                  </div>
                  <div>
                    <dt>담당자</dt>
                    <dd>{selected.owner_display_name || "미지정"}</dd>
                  </div>
                  <div>
                    <dt>상태</dt>
                    <dd>{selected.is_active ? "활성" : "비활성"}</dd>
                  </div>
                  <div>
                    <dt>등록 시각</dt>
                    <dd>{formatKst(selected.created_at)}</dd>
                  </div>
                </dl>
                <p className="detail-note">
                  예상 Ubuntu는 등록 시 직접 선택한 값입니다. 수집하거나 입력한 정보는 아래 패키지
                  목록에서 확인하세요.
                </p>
                <button
                  className="secondary"
                  onClick={() => {
                    setDetailOpen(false);
                    document.getElementById("inventory-title")?.focus();
                    document
                      .getElementById("asset-inventory")
                      ?.scrollIntoView({ behavior: "smooth", block: "start" });
                  }}
                >
                  패키지 정보로 이동
                </button>
              </aside>
            )}
          </div>
        ) : (
          <div className="empty">
            <div className="empty-icon">
              <Icon name="assets" />
            </div>
            <strong>
              {!api
                ? "연결 후 자산을 확인할 수 있습니다"
                : query.error
                  ? "자산 목록을 불러오지 못했습니다"
                  : query.loading
                    ? "자산을 불러오는 중입니다"
                    : "등록된 자산이 없습니다"}
            </strong>
            <p>
              {!api
                ? "서비스 연결이 필요합니다."
                : query.error
                  ? "잠시 후 다시 시도해 주세요."
                  : query.loading
                    ? "자산 조회 중…"
                    : "자산 등록을 눌러 관리할 서버를 추가하세요."}
            </p>
          </div>
        )}
        {(total ?? 0) > 20 && (
          <div className="pagination">
            <span>전체 {total}개</span>
            <div>
              <button
                disabled={page === 0}
                onClick={() => {
                  setSelectedId(null);
                  setPage(page - 1);
                }}
              >
                이전
              </button>
              <span>
                {page + 1} / {Math.ceil(total! / 20)}
              </span>
              <button
                disabled={(page + 1) * 20 >= total!}
                onClick={() => {
                  setSelectedId(null);
                  setPage(page + 1);
                }}
              >
                다음
              </button>
            </div>
          </div>
        )}
      </section>
      {selected && api && (
        <>
          {canWrite && (
            <AssetEditor key={`edit-${selected.id}`} asset={selected} onSaved={query.refresh} />
          )}
          <CollectionPanel
            key={`ssh-${selected.id}`}
            api={api}
            asset={selected}
            onCollected={onCollected}
          />
          <InventoryPanel
            key={selected.id}
            asset={selected}
            collectedInventoryId={
              collected?.assetId === selected.id ? collected.inventoryId : undefined
            }
          />
        </>
      )}
    </>
  );
}

function AssetEditor({ asset, onSaved }: { asset: Asset; onSaved: () => void }) {
  const { api } = useSession();
  const action = useAction();
  return (
    <section className="panel">
      <details className="inventory-import">
        <summary>자산 정보 수정 · {asset.asset_name}</summary>
        <Notice error={action.error} success={action.notice} />
        <form
          className="asset-form"
          onSubmit={async (event) => {
            event.preventDefault();
            if (!api) return;
            const data = new FormData(event.currentTarget);
            const body = {
              asset_name: String(data.get("name")).trim(),
              host: String(data.get("host")).trim() || null,
              owner_display_name: String(data.get("owner")).trim() || null,
              expected_release: (data.get("release") || null) as AssetCreate["expected_release"],
              exposure: data.get("exposure") as AssetCreate["exposure"],
              criticality: data.get("criticality") as AssetCreate["criticality"],
              exposure_source: "사용자 수정",
            };
            if (
              await action.run(
                () => editAsset(api, asset.id, body),
                "자산 정보를 수정했습니다. 이전 분석·보고서는 당시 정보를 유지합니다.",
              )
            )
              onSaved();
          }}
        >
          <label>
            자산 이름
            <input name="name" required maxLength={100} defaultValue={asset.asset_name} />
          </label>
          <label>
            주소
            <input name="host" maxLength={253} defaultValue={asset.host ?? ""} />
            <small className="field-hint">
              표시용 주소입니다. SSH 연결 설정은 별도로 관리합니다.
            </small>
          </label>
          <label>
            담당자
            <input name="owner" maxLength={100} defaultValue={asset.owner_display_name ?? ""} />
          </label>
          <label>
            예상 Ubuntu
            <select name="release" defaultValue={asset.expected_release ?? ""}>
              <option value="">미확인</option>
              <option>22.04</option>
              <option>24.04</option>
            </select>
          </label>
          <label>
            노출 범위
            <select name="exposure" defaultValue={asset.exposure}>
              {Object.entries(exposureLabels).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            중요도
            <select name="criticality" defaultValue={asset.criticality}>
              <option value="UNKNOWN">미확인</option>
              <option value="LOW">낮음</option>
              <option value="MEDIUM">보통</option>
              <option value="HIGH">높음</option>
            </select>
          </label>
          <div className="form-submit">
            <button className="primary" disabled={action.pending}>
              변경 저장
            </button>
          </div>
        </form>
      </details>
    </section>
  );
}
