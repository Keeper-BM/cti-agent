import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import type { HttpClient } from "../../api/client";
import { useSession } from "../../app/session";
import { Notice } from "../../shared/components/Notice";
import { formatKst } from "../../shared/format";
import { useAction } from "../../shared/hooks/useAction";
import { usePollingQuery } from "../../shared/hooks/usePollingQuery";
import type { Asset } from "../assets/api";
import {
  collectPackages,
  getCollection,
  getSSHProfile,
  getSSHSettings,
  listCollections,
  saveSSHProfile,
} from "./api";
import type { Collection, CollectionDetail, SSHProfile, SSHProfileInput, SSHSettings } from "./api";

const labels: Record<Collection["job"]["status"], string> = {
  QUEUED: "수집 대기",
  RUNNING: "수집 중",
  SUCCEEDED: "수집 완료",
  PARTIAL: "일부 수집",
  FAILED: "수집 실패",
};
const running = (item?: Collection | null) =>
  !!item && ["QUEUED", "RUNNING"].includes(item.job.status);

export function CollectionPanel({
  api,
  asset,
  onCollected,
}: {
  api: HttpClient;
  asset: Asset;
  onCollected: (assetId: string, inventoryId: string) => void;
}) {
  const { isAdmin, canWrite } = useSession();
  const [page, setPage] = useState(0);
  const [selectedId, setSelectedId] = useState("");
  const [requested, setRequested] = useState<Collection | null>(null);
  const [editing, setEditing] = useState(false);
  const requestKey = useRef(crypto.randomUUID());
  const notified = useRef("");
  const observedRun = useRef("");
  const action = useAction();
  const settingsLoad = useCallback((signal: AbortSignal) => getSSHSettings(api, signal), [api]);
  const settings = usePollingQuery(isAdmin ? settingsLoad : null, null);
  const profileLoad = useCallback(
    (signal: AbortSignal) => getSSHProfile(api, asset.id, signal),
    [api, asset.id],
  );
  const profile = usePollingQuery(profileLoad, null);
  const historyLoad = useCallback(
    (signal: AbortSignal) => listCollections(api, asset.id, page, signal),
    [api, asset.id, page],
  );
  const history = usePollingQuery(historyLoad);
  const newestLoad = useCallback(
    (signal: AbortSignal) => listCollections(api, asset.id, 0, signal),
    [api, asset.id],
  );
  const newest = usePollingQuery(page > 0 ? newestLoad : null);
  const latest = (page === 0 ? history.data : newest.data)?.items[0];
  const selectedRun =
    history.data?.items.find((item) => item.id === selectedId) ??
    (requested?.id === selectedId ? requested : null);
  const detailLoad = useCallback(
    (signal: AbortSignal) => getCollection(api, asset.id, selectedId, signal),
    [api, asset.id, selectedId],
  );
  const detail = usePollingQuery(
    selectedId ? detailLoad : null,
    running(selectedRun) ? 5000 : null,
  );
  const savedProfile = profile.data?.profile;
  const busy = action.pending || running(requested) || running(latest);
  const current =
    latest && (!requested || latest.created_at >= requested.created_at) ? latest : requested;
  const completed = current?.inventory_id ? current : null;
  useEffect(() => {
    requestKey.current = crypto.randomUUID();
  }, [savedProfile?.id]);
  useEffect(() => {
    const updated =
      latest?.id === requested?.id
        ? latest
        : detail.data?.id === requested?.id
          ? detail.data
          : null;
    if (requested && updated && updated.job.status !== requested.job.status) {
      setRequested(updated);
      history.refresh();
    }
  }, [detail.data, latest, requested, history.refresh]);
  useEffect(() => {
    if (current && running(current)) observedRun.current = current.id;
    if (
      completed?.inventory_id &&
      (observedRun.current === completed.id || requested?.id === completed.id) &&
      notified.current !== completed.inventory_id
    ) {
      notified.current = completed.inventory_id;
      onCollected(asset.id, completed.inventory_id);
    }
  }, [current, completed, requested?.id, asset.id, onCollected]);

  async function collect() {
    if (!savedProfile || busy) return;
    const ok = await action.run(async () => {
      const result = await collectPackages(api, asset.id, savedProfile.id, requestKey.current);
      setRequested(result);
      setSelectedId(result.id);
      setPage(0);
      history.refresh();
    }, "수집을 요청했습니다. 완료되면 아래 패키지 목록에 새 기록이 표시됩니다.");
    if (ok) requestKey.current = crypto.randomUUID();
  }

  return (
    <section className="panel collection-panel" aria-labelledby="collection-title">
      <div className="panel-heading">
        <div>
          <h2 id="collection-title">SSH 패키지 수집</h2>
          <p>Ubuntu 22.04·24.04 서버에 SSH로 접속해 설치 패키지를 조회합니다.</p>
        </div>
        <button
          className="primary"
          onClick={collect}
          disabled={
            !savedProfile ||
            !asset.is_active ||
            (isAdmin && !settings.data?.enabled) ||
            !canWrite ||
            profile.loading ||
            busy ||
            editing
          }
        >
          {busy ? "수집 처리 중…" : "패키지 수집 실행"}
        </button>
      </div>
      <div className="collection-content">
        <Notice
          error={
            action.error ||
            settings.error ||
            profile.error ||
            history.error ||
            newest.error ||
            detail.error
          }
          success={action.notice}
        />
        <p className="inventory-note">
          조회한 정보를 새 기록으로 저장합니다. 수집 후 취약점 분석 화면에서 분석할 수 있습니다.
        </p>
        {!asset.is_active && (
          <p className="inventory-warning">비활성 자산입니다. 수집하려면 자산을 활성화하세요.</p>
        )}
        {isAdmin && settings.data && !settings.data.enabled && (
          <div className="inventory-warning">
            <strong>SSH 연결 준비가 필요합니다.</strong>
            <p>
              서버 관리자에게 접속 IP·계정·호스트 키 지문을 확인하고, 백엔드에 인증키와 허용 서버를
              등록하세요.
            </p>
          </div>
        )}
        {savedProfile && (
          <div className="collection-connection">
            <div>
              <strong>
                {savedProfile.username}@{savedProfile.host}:{savedProfile.port}
              </strong>
              <span>인증키 {savedProfile.key_alias} · 저장된 연결 설정</span>
            </div>
            <button
              className="secondary"
              disabled={busy || !asset.is_active || !isAdmin}
              onClick={() => setEditing(!editing)}
            >
              {editing ? "편집 닫기" : "연결 설정 변경"}
            </button>
          </div>
        )}
        {isAdmin && profile.data && settings.data && (!savedProfile || editing) && (
          <ProfileForm
            key={savedProfile?.id ?? "new"}
            api={api}
            asset={asset}
            profile={savedProfile ?? null}
            settings={settings.data}
            onSaved={() => {
              setEditing(false);
              profile.refresh();
            }}
          />
        )}
        {!isAdmin && !savedProfile && (
          <p className="inventory-note">
            관리자가 이 자산의 SSH 연결을 설정하면 수집할 수 있습니다.
          </p>
        )}
        <div className="collection-toolbar">
          <span>수집 이력 {history.data?.total ?? "—"}건</span>
          <button
            className="text-button"
            onClick={() => {
              settings.refresh();
              profile.refresh();
              history.refresh();
              detail.refresh();
            }}
          >
            연결 설정·이력 새로고침
          </button>
        </div>
        {!!history.data?.total && (
          <div className="ai-history-list">
            {history.data.items.map((item) => (
              <button
                key={item.id}
                className={`ai-history-item ${selectedId === item.id ? "selected" : ""}`}
                aria-pressed={selectedId === item.id}
                onClick={() => setSelectedId(item.id)}
              >
                <span>
                  {formatKst(item.created_at)}
                  <small>
                    {item.profile.username}@{item.profile.host}:{item.profile.port}
                  </small>
                </span>
                <span className={`badge ${item.job.status.toLowerCase()}`}>
                  {labels[item.job.status]}
                </span>
              </button>
            ))}
          </div>
        )}
        {history.data && history.data.total > 10 && (
          <div className="pagination">
            <span>
              {page + 1} / {Math.ceil(history.data.total / 10)}
            </span>
            <div>
              <button disabled={page === 0} onClick={() => setPage(page - 1)}>
                이전
              </button>
              <button
                disabled={(page + 1) * 10 >= history.data.total}
                onClick={() => setPage(page + 1)}
              >
                다음
              </button>
            </div>
          </div>
        )}
        {detail.data && (
          <CollectionResult
            collection={detail.data}
            onShowInventory={(id) => onCollected(asset.id, id)}
          />
        )}
        {history.data?.total === 0 && (
          <p className="inventory-note">
            아직 수집 이력이 없습니다. 연결 설정을 저장한 뒤 패키지를 가져오세요.
          </p>
        )}
      </div>
    </section>
  );
}

function ProfileForm({
  api,
  asset,
  profile,
  settings,
  onSaved,
}: {
  api: HttpClient;
  asset: Asset;
  profile: SSHProfile | null;
  settings: SSHSettings;
  onSaved: () => void;
}) {
  const action = useAction();
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (action.pending) return;
    const data = new FormData(event.currentTarget);
    const body: SSHProfileInput = {
      host: String(data.get("host")).trim(),
      port: Number(data.get("port")),
      username: String(data.get("username")).trim(),
      key_alias: String(data.get("key_alias")),
      host_fingerprint: String(data.get("fingerprint")).trim(),
    };
    if (await action.run(() => saveSSHProfile(api, asset.id, body), "연결 설정을 저장했습니다."))
      onSaved();
  }
  return (
    <form className="asset-form collection-form" onSubmit={save}>
      <div className="form-heading">
        <strong>SSH 연결 설정</strong>
        <span>저장 후 수집 버튼을 눌러 접속합니다.</span>
      </div>
      <label>
        서버 IP
        <input
          name="host"
          required
          maxLength={45}
          placeholder="192.0.2.10"
          defaultValue={profile?.host ?? asset.host ?? ""}
        />
      </label>
      <label>
        SSH 포트
        <input
          name="port"
          type="number"
          required
          min={1}
          max={65535}
          defaultValue={profile?.port ?? 22}
        />
      </label>
      <label>
        접속 계정
        <input
          name="username"
          required
          maxLength={32}
          placeholder="collector"
          defaultValue={profile?.username ?? ""}
          autoComplete="off"
        />
      </label>
      <label>
        등록된 인증키
        <select name="key_alias" required defaultValue={profile?.key_alias ?? ""}>
          <option value="">인증키 선택</option>
          {settings.key_aliases.map((key) => (
            <option key={key} value={key}>
              {key}
            </option>
          ))}
        </select>
      </label>
      <label className="collection-fingerprint">
        서버 호스트 키 지문
        <input
          name="fingerprint"
          required
          maxLength={50}
          placeholder="SHA256:…"
          defaultValue={profile?.host_fingerprint ?? ""}
          autoComplete="off"
          spellCheck={false}
          aria-describedby="ssh-fingerprint-hint"
        />
        <small className="field-hint" id="ssh-fingerprint-hint">
          서버 관리자가 확인한 호스트 키 지문을 입력하세요. 접속 시 같은 서버인지 대조합니다.
        </small>
      </label>
      <div className="collection-form-note">
        <Notice error={action.error} success={action.notice} />
        <p>허용 서버: {settings.allowed_targets.join(", ") || "아직 등록되지 않았습니다"}</p>
      </div>
      <div className="form-submit">
        <button
          className="secondary"
          disabled={!asset.is_active || !settings.enabled || action.pending}
          type="submit"
        >
          {action.pending ? "저장 중…" : "연결 설정 저장"}
        </button>
      </div>
    </form>
  );
}

function CollectionResult({
  collection,
  onShowInventory,
}: {
  collection: CollectionDetail;
  onShowInventory: (id: string) => void;
}) {
  const evidence = collection.evidence;
  const commandLabels: Record<string, string> = {
    os_release: "운영체제",
    architecture: "아키텍처",
    packages: "설치 패키지",
    apt_policy: "APT 저장소 참고 정보",
    service_apache2: "Apache 서비스 상태",
    service_mysql: "MySQL 서비스 상태",
  };
  return (
    <div className="collection-result" aria-live="polite">
      <strong>{labels[collection.job.status]}</strong>
      {running(collection) && (
        <p>완료되면 결과가 표시됩니다. 대기가 계속되면 작업 내역에서 Worker 상태를 확인하세요.</p>
      )}
      {collection.job.result?.message != null && <p>{String(collection.job.result.message)}</p>}
      {collection.job.error_code && (
        <p className="job-error">{collection.job.error_code} · 이전 패키지 기록은 유지됩니다.</p>
      )}
      {collection.inventory_id && (
        <button
          className="secondary"
          onClick={() => {
            onShowInventory(collection.inventory_id!);
            document
              .getElementById("asset-inventory")
              ?.scrollIntoView({ behavior: "smooth", block: "start" });
          }}
        >
          이 수집의 패키지 목록 보기
        </button>
      )}
      {evidence && (
        <>
          <p className="inventory-warning">
            서버에서 조회한 패키지 정보입니다. 설치 출처와 파일 무결성은 미검증 상태이며, SSH
            수집만으로 취약 여부를 확정하지 않습니다.
          </p>
          <div className="collection-services">
            <h3>서비스 상태</h3>
            <p className="inventory-note">
              수집 당시의 서비스 상태입니다. 서비스 유닛 부재와 패키지 미설치는 다르며, 활성
              상태만으로 취약 여부를 판단하지 않습니다.
            </p>
            {evidence.services?.length ? (
              <ul>
                {evidence.services.map((service) => (
                  <li key={service.unit}>
                    <strong>{service.unit === "apache2.service" ? "Apache" : "MySQL"}</strong>
                    {" · "}
                    {service.status === "UNKNOWN"
                      ? "확인 불가"
                      : service.status === "NOT_FOUND"
                        ? "서비스 유닛 없음"
                        : service.active_state === "active"
                          ? "활성"
                          : service.active_state === "inactive"
                            ? "중지"
                            : service.active_state === "failed"
                              ? "서비스 실패"
                              : service.active_state}
                    {service.status === "OBSERVED" && (
                      <span>
                        {" · "}
                        {service.unit} · 로드 {service.load_state} · 상세 {service.sub_state}
                        {" · "}활성화 설정 {service.unit_file_state ?? "없음"}
                      </span>
                    )}
                    {service.status === "UNKNOWN" && (
                      <span>
                        {service.error_code === "COMMAND_FAILED"
                          ? " · 조회 명령이 실패했습니다. 접속 계정의 허용 명령을 확인하세요."
                          : " · 조회 출력이 불완전하거나 형식이 올바르지 않습니다."}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <p>이 수집 기록에는 서비스 상태가 없습니다. 새로 수집하면 확인할 수 있습니다.</p>
            )}
          </div>
          <details className="collection-evidence">
            <summary>수집 근거 및 제한 사항</summary>
            <ul>
              {evidence.warnings.map((warning, index) => (
                <li key={index}>{warning}</li>
              ))}
            </ul>
            <p>조회 시각 {formatKst(evidence.observed_at)}</p>
            <p className="mono">
              확인한 호스트 키 {evidence.verified_host_fingerprint}
              <br />
              수집기 {evidence.collector_version}
              <br />
              출력 SHA-256 {evidence.output_sha256}
            </p>
            {evidence.commands.map((command) => (
              <details key={command.name}>
                <summary>
                  {commandLabels[command.name] ?? command.name} · 종료 코드 {command.exit_code}
                  {command.stderr_present ? " · 오류/진단 출력 있음" : ""}
                </summary>
                <pre>{command.stdout.slice(0, 20000) || "출력 없음"}</pre>
                {command.stdout.length > 20000 && (
                  <p>
                    긴 출력은 앞 20,000자만 표시합니다. 전체 출력은 수집 기록에 저장되어 있습니다.
                  </p>
                )}
              </details>
            ))}
          </details>
        </>
      )}
    </div>
  );
}
