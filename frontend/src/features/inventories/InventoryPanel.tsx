import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useSession } from "../../app/session";
import { Icon } from "../../shared/components/Icon";
import { Notice } from "../../shared/components/Notice";
import { usePollingQuery } from "../../shared/hooks/usePollingQuery";
import type { Asset } from "../assets/api";
import { getInventory, listInventories, uploadCsvInventory, uploadInventory } from "./api";
import type { Inventory } from "./api";
import { readInventoryFile } from "./file";
import { VerificationPanel } from "../verifications/VerificationPanel";

const time = (value: string) =>
  new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: "Asia/Seoul",
  }).format(new Date(value));

export function InventoryPanel({
  asset,
  collectedInventoryId,
}: {
  asset: Asset;
  collectedInventoryId?: string;
}) {
  const { api, canWrite } = useSession();
  const [file, setFile] = useState<File | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [page, setPage] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const upload = useRef<AbortController | null>(null);
  useEffect(() => () => upload.current?.abort(), []);
  const load = useCallback(
    (signal: AbortSignal) => listInventories(api!, asset.id, page, signal),
    [api, asset.id, page],
  );
  const history = usePollingQuery(api ? load : null, null);
  useEffect(() => {
    if (collectedInventoryId) {
      setSelectedId(collectedInventoryId);
      setPage(0);
      history.refresh();
    }
  }, [collectedInventoryId, history.refresh]);
  const entries = history.data?.items ?? [];
  const currentId = selectedId ?? entries[0]?.inventory_id;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!api || !file || pending) return;
    const controller = new AbortController();
    upload.current = controller;
    setPending(true);
    setError("");
    setNotice("");
    try {
      const content = await readInventoryFile(file);
      if (controller.signal.aborted) return;
      const uploadFile = file.name.toLowerCase().endsWith(".csv")
        ? uploadCsvInventory
        : uploadInventory;
      const result = await uploadFile(api, asset.id, content, controller.signal);
      if (controller.signal.aborted) return;
      setSelectedId(result.inventory_id);
      setPage(0);
      history.refresh();
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
      setNotice(`${result.packages.length}개 패키지를 새 입력 기록으로 저장했습니다.`);
    } catch (cause) {
      if (!controller.signal.aborted) {
        setError(cause instanceof Error ? cause.message : "파일을 저장하지 못했습니다.");
      }
    } finally {
      if (!controller.signal.aborted) setPending(false);
    }
  }

  return (
    <section
      className="panel inventory-panel"
      id="asset-inventory"
      aria-labelledby="inventory-title"
    >
      <div className="panel-heading">
        <div>
          <div className="section-title">
            <h2 id="inventory-title" tabIndex={-1}>
              패키지 정보 · {asset.asset_name}
            </h2>
            <span className="badge">입력·수집 기록</span>
          </div>
          <p>SSH 수집과 JSON 입력으로 저장한 시점별 패키지 목록을 확인합니다.</p>
        </div>
        <button
          className="secondary"
          disabled={!api || history.loading || pending}
          onClick={history.refresh}
        >
          <Icon name="refresh" /> 기록 새로고침
        </button>
      </div>
      <div className="inventory-import">
        <Notice error={error} success={notice} />
        <form className="inventory-upload" onSubmit={submit}>
          <label htmlFor="inventory-file">
            패키지 정보 JSON·CSV 파일
            <input
              id="inventory-file"
              ref={fileInput}
              type="file"
              accept=".json,.csv,application/json,text/csv"
              disabled={!api || !canWrite || pending || !asset.is_active}
              aria-describedby="inventory-file-help"
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null);
                setError("");
                setNotice("");
              }}
            />
          </label>
          <button
            className="primary"
            type="submit"
            disabled={!api || !canWrite || !file || pending || !asset.is_active}
          >
            {pending ? "검증·저장 중…" : "선택한 파일 저장"}
          </button>
        </form>
        <div className="inventory-upload-help" id="inventory-file-help">
          <span>UTF-8 JSON·CSV · 요청 최대 2 MiB · 패키지 1~5,000개</span>
          <a href="/examples/inventory.sample.json" download="inventory.sample.json">
            입력 예제 다운로드
          </a>
          <a href="/examples/inventory.sample.csv" download="inventory.sample.csv">
            CSV 예제 다운로드
          </a>
        </div>
        <p className="inventory-note">
          새로 저장해도 이전 기록은 보존됩니다. 파일의 출처 설명은 사용자가 입력한 정보로
          표시합니다.
        </p>
        {!asset.is_active && (
          <p className="inventory-warning">
            비활성 자산입니다. 기존 기록을 조회할 수 있으며, 새 파일은 자산을 활성화한 뒤 저장할 수
            있습니다.
          </p>
        )}
        <details className="inventory-format">
          <summary>입력 파일 형식</summary>
          <p>
            CSV는 예제의 열 이름을 유지하세요. OS·확인 시각·전체 목록 여부·가상 여부는 모든 행에서
            같아야 합니다. true/false를 사용하고 알 수 없는 패키지 값은 빈 칸으로 둡니다.
          </p>
          <p>
            입력 예제를 내려받아 <code>os</code>의 Ubuntu 정보와 <code>packages</code>의 패키지
            목록을 수정하세요. <code>collected_at</code>에는 정보를 확인한 시각과 시간대(예:
            +09:00)를 적습니다.
          </p>
          <p>
            버전이나 출처를 모르면 <code>null</code>로 남기세요. 전체 패키지 목록이 아니라면{" "}
            <code>package_list_complete</code>는 <code>false</code>로 둡니다. 예제는 가상 입력으로
            표시되며, 실제 자료를 입력할 때는 <code>is_synthetic</code>을 <code>false</code>로
            바꿉니다.
          </p>
        </details>
      </div>
      <div className="inventory-content">
        <Notice error={history.error} />
        {history.data && history.data.total > 0 && (
          <details className="inventory-history">
            <summary>
              저장 이력 <span>{history.data.total}건</span>
            </summary>
            <ul>
              {entries.map((entry) => (
                <li key={entry.inventory_id}>
                  <button
                    type="button"
                    className={currentId === entry.inventory_id ? "selected" : ""}
                    aria-pressed={currentId === entry.inventory_id}
                    onClick={() => setSelectedId(entry.inventory_id)}
                  >
                    <span>{time(entry.ingested_at)}</span>
                    <span>
                      Ubuntu {entry.os_release} · {entry.package_count}개{" "}
                      {entry.is_synthetic ? "· 가상 입력" : ""}
                    </span>
                    <span className="mono">{entry.inventory_id.slice(0, 8)}</span>
                  </button>
                </li>
              ))}
            </ul>
            {history.data.total > 10 && (
              <div className="pagination">
                <span>
                  이력 {page + 1} / {Math.ceil(history.data.total / 10)} 페이지
                </span>
                <div>
                  <button
                    disabled={page === 0 || history.loading}
                    onClick={() => setPage(page - 1)}
                  >
                    이전
                  </button>
                  <button
                    disabled={(page + 1) * 10 >= history.data.total || history.loading}
                    onClick={() => setPage(page + 1)}
                  >
                    다음
                  </button>
                </div>
              </div>
            )}
          </details>
        )}
        {currentId ? (
          <SnapshotDetail
            key={currentId}
            asset={asset}
            inventoryId={currentId}
            onInventory={(id) => {
              setSelectedId(id);
              setPage(0);
              history.refresh();
            }}
          />
        ) : (
          <div className="empty compact">
            <strong>
              {history.error
                ? "입력 기록을 확인하지 못했습니다"
                : history.loading
                  ? "입력 기록을 불러오는 중입니다"
                  : "저장된 패키지 정보가 없습니다"}
            </strong>
            <p>
              {history.error
                ? "새로고침으로 다시 조회하세요."
                : "SSH로 가져오거나 JSON 파일을 저장하면 이 자산의 패키지 목록이 표시됩니다."}
            </p>
          </div>
        )}
      </div>
    </section>
  );
}

function SnapshotDetail({
  asset,
  inventoryId,
  onInventory,
}: {
  asset: Asset;
  inventoryId: string;
  onInventory: (id: string) => void;
}) {
  const { api, canWrite } = useSession();
  const load = useCallback(
    (signal: AbortSignal) => getInventory(api!, asset.id, inventoryId, signal),
    [api, asset.id, inventoryId],
  );
  const query = usePollingQuery(api ? load : null, null);
  if (!query.data) {
    return (
      <div className="inventory-loading" role="status">
        <Notice error={query.error} />
        {query.error ? (
          <button className="secondary" onClick={query.refresh}>
            기록 다시 불러오기
          </button>
        ) : (
          "패키지 목록을 불러오는 중입니다…"
        )}
      </div>
    );
  }
  return (
    <>
      <PackageSnapshot inventory={query.data} expectedRelease={asset.expected_release} />
      {query.data.collection_method === "SSH" && (
        <VerificationPanel
          assetId={asset.id}
          inventoryId={inventoryId}
          verificationId={query.data.verification_id}
          enabled={asset.is_active && canWrite}
          onInventory={onInventory}
        />
      )}
    </>
  );
}

function PackageSnapshot({
  inventory,
  expectedRelease,
}: {
  inventory: Inventory;
  expectedRelease?: string | null;
}) {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const packages = useMemo(() => {
    const term = search.trim().toLowerCase();
    return inventory.packages.filter((item) =>
      [item.binary_name, item.source_name, item.architecture].some((value) =>
        value?.toLowerCase().includes(term),
      ),
    );
  }, [inventory, search]);
  const pageItems = packages.slice(page * 25, (page + 1) * 25);
  const missingCount = inventory.coverage.missing_fields?.length ?? 0;
  const isSSH = inventory.collection_method === "SSH";
  const inputLabel = isSSH ? "SSH 조회값" : "파일 입력값";
  return (
    <div className="inventory-snapshot">
      {inventory.is_synthetic && (
        <div className="inventory-warning" role="note">
          가상 입력 자료입니다. 실제 서버에서 수집한 결과가 아닙니다.
        </div>
      )}
      {expectedRelease && expectedRelease !== inventory.os.version_id && (
        <div className="inventory-warning" role="note">
          등록 시 예상한 Ubuntu {expectedRelease}와 저장된 Ubuntu {inventory.os.version_id}가
          다릅니다. 대상 자산을 확인하세요.
        </div>
      )}
      <dl className="inventory-meta">
        <div>
          <dt>운영체제 · {inputLabel}</dt>
          <dd>
            Ubuntu {inventory.os.version_id} <span>{inventory.os.codename}</span>
          </dd>
        </div>
        <div>
          <dt>아키텍처</dt>
          <dd>{inventory.os.architecture || "미입력"}</dd>
        </div>
        <div>
          <dt>정보 확인 시각 · {inputLabel}</dt>
          <dd>{time(inventory.collected_at)}</dd>
        </div>
        <div>
          <dt>저장 시각</dt>
          <dd>{time(inventory.ingested_at)}</dd>
        </div>
        <div>
          <dt>목록 범위 · {inputLabel}</dt>
          <dd>{inventory.coverage.package_list_complete ? "전체 목록" : "일부 목록"}</dd>
        </div>
        <div>
          <dt>저장 기록 ID</dt>
          <dd className="mono">{inventory.inventory_id}</dd>
        </div>
      </dl>
      {isSSH && !!inventory.errors?.length && (
        <details className="inventory-format">
          <summary>수집 상태 및 제한 사항</summary>
          <ul>
            {inventory.errors.map((message, i) => (
              <li key={i}>{message}</li>
            ))}
          </ul>
        </details>
      )}
      <div className="inventory-package-toolbar">
        <strong>
          패키지 {inventory.packages.length}개{" "}
          <span>{missingCount > 0 ? `· 미입력 항목 ${missingCount}개` : ""}</span>
        </strong>
        <label>
          <span className="sr-only">패키지 검색</span>
          <input
            type="search"
            placeholder="패키지 이름 또는 아키텍처 검색"
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(0);
            }}
          />
        </label>
      </div>
      <div className="table-wrap">
        <table className="inventory-table">
          <caption className="sr-only">선택한 입력 기록의 설치 패키지 목록</caption>
          <thead>
            <tr>
              <th>패키지</th>
              <th>설치 버전</th>
              <th>소스 패키지 · 버전</th>
              <th>아키텍처</th>
              <th>설치 출처</th>
            </tr>
          </thead>
          <tbody>
            {pageItems.map((item) => (
              <tr key={item.package_id}>
                <td>
                  <strong>{item.binary_name}</strong>
                </td>
                <td className="mono">{item.binary_version ?? "미입력"}</td>
                <td>
                  <span>{item.source_name ?? "미입력"}</span>
                  <small className="cell-sub mono">{item.source_version ?? "버전 미입력"}</small>
                </td>
                <td>{item.architecture ?? "미입력"}</td>
                <td>
                  <span className="badge">
                    {item.origin_status === "OFFICIAL_MATCH"
                      ? "공식 파일 일치"
                      : item.origin_status === "USER_DECLARED"
                        ? "사용자 입력"
                        : "미확인"}
                  </span>
                  {item.origin_description && (
                    <small className="cell-sub">{item.origin_description}</small>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {packages.length === 0 && (
          <p className="inventory-no-results" role="status">
            검색 조건에 맞는 패키지가 없습니다.
          </p>
        )}
      </div>
      {(packages.length > 25 || search) && (
        <div className="pagination">
          <span>
            {packages.length}개 검색됨 · {packages.length ? page * 25 + 1 : 0}–
            {Math.min((page + 1) * 25, packages.length)}
          </span>
          <div>
            <button disabled={page === 0} onClick={() => setPage(page - 1)}>
              이전
            </button>
            <button disabled={(page + 1) * 25 >= packages.length} onClick={() => setPage(page + 1)}>
              다음
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
