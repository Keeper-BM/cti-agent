import { useCallback, useState } from "react";
import { useSession } from "../../app/session";
import { Notice } from "../../shared/components/Notice";
import { useAction } from "../../shared/hooks/useAction";
import { usePollingQuery } from "../../shared/hooks/usePollingQuery";
import { listAssets } from "../assets/api";
import { addUser, changeUser, getGrants, grant, listUsers, revoke } from "./api";
import type { User } from "./api";

const roles: Record<User["role"], string> = {
  ADMIN: "관리자",
  OPERATOR: "담당자",
  VIEWER: "조회자",
};
export function AccountsPage() {
  const { api, isAdmin, user, mode, disconnect } = useSession();
  const [page, setPage] = useState(0);
  const [assetPage, setAssetPage] = useState(0);
  const [asset, setAsset] = useState("");
  const [chosenUser, setChosenUser] = useState("");
  const action = useAction();
  const usersLoad = useCallback(
    (signal: AbortSignal) => listUsers(api!, page, signal),
    [api, page],
  );
  const users = usePollingQuery(api && isAdmin ? usersLoad : null, null);
  const assetsLoad = useCallback(
    (signal: AbortSignal) => listAssets(api!, assetPage * 20, signal),
    [api, assetPage],
  );
  const assets = usePollingQuery(api && isAdmin ? assetsLoad : null, null);
  const grantsLoad = useCallback(
    (signal: AbortSignal) => getGrants(api!, asset, signal),
    [api, asset],
  );
  const grants = usePollingQuery(api && isAdmin && asset ? grantsLoad : null, null);
  return (
    <>
      <Notice
        error={action.error || users.error || assets.error || grants.error}
        success={action.notice}
      />
      {user && (
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>내 계정</h2>
              <p>
                {user.display_name} · {roles[user.role]}
              </p>
            </div>
          </div>
          <form
            className="asset-form"
            onSubmit={async (event) => {
              event.preventDefault();
              if (!api) return;
              const form = event.currentTarget;
              const data = new FormData(form);
              if (
                await action.run(
                  () =>
                    api.request("/auth/password", {
                      method: "POST",
                      body: JSON.stringify({
                        current_password: data.get("current"),
                        new_password: data.get("new"),
                      }),
                    }),
                  "비밀번호를 변경했습니다. 다시 로그인하세요.",
                )
              ) {
                form.reset();
                disconnect(true);
              }
            }}
          >
            <label>
              현재 비밀번호
              <input
                name="current"
                type="password"
                required
                autoComplete="current-password"
                maxLength={256}
              />
            </label>
            <label>
              새 비밀번호
              <input
                name="new"
                type="password"
                required
                autoComplete="new-password"
                minLength={12}
                maxLength={256}
              />
              <small className="field-hint">12자 이상</small>
            </label>
            <div className="form-submit">
              <button className="secondary" disabled={action.pending}>
                비밀번호 변경
              </button>
            </div>
          </form>
        </section>
      )}
      {isAdmin && (
        <>
          <section className="panel">
            <div className="panel-heading">
              <div>
                <h2>계정 관리</h2>
                <p>
                  관리자는 전체 자산, 담당자는 지정 자산의 작업 실행, 조회자는 지정 자산의 조회를
                  허용합니다.
                </p>
              </div>
            </div>
            {mode === "token" && (
              <p className="inventory-warning">
                개발용 토큰 모드입니다. 계정을 만든 뒤 서버의 AUTH_MODE를 accounts로 바꾸면 계정
                로그인이 적용됩니다.
              </p>
            )}
            <form
              className="asset-form"
              onSubmit={async (event) => {
                event.preventDefault();
                if (!api) return;
                const form = event.currentTarget;
                const data = new FormData(form);
                if (
                  await action.run(
                    () =>
                      addUser(api, {
                        username: String(data.get("username")),
                        display_name: String(data.get("name")),
                        password: String(data.get("password")),
                        role: data.get("role") as User["role"],
                      }),
                    "계정을 생성했습니다.",
                  )
                ) {
                  form.reset();
                  users.refresh();
                }
              }}
            >
              <label>
                로그인 이름
                <input
                  name="username"
                  required
                  pattern="[a-z0-9][a-z0-9_.\-]{2,63}"
                  maxLength={64}
                  autoComplete="off"
                />
              </label>
              <label>
                표시 이름
                <input name="name" required maxLength={100} />
              </label>
              <label>
                초기 비밀번호
                <input
                  name="password"
                  type="password"
                  required
                  minLength={12}
                  maxLength={256}
                  autoComplete="new-password"
                />
              </label>
              <label>
                역할
                <select name="role" defaultValue="VIEWER">
                  {Object.entries(roles).map(([key, label]) => (
                    <option value={key} key={key}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <div className="form-submit">
                <button className="primary" disabled={action.pending}>
                  계정 생성
                </button>
              </div>
            </form>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>계정</th>
                    <th>역할</th>
                    <th>상태</th>
                    <th>변경</th>
                  </tr>
                </thead>
                <tbody>
                  {users.data?.items.map((item) => (
                    <tr key={item.id}>
                      <td>
                        {item.display_name}
                        <small className="cell-sub">{item.username}</small>
                      </td>
                      <td>
                        <select
                          aria-label={`${item.username} 역할`}
                          value={item.role}
                          disabled={action.pending || item.id === user?.id}
                          onChange={async (e) => {
                            if (
                              api &&
                              (await action.run(
                                () =>
                                  changeUser(api, item.id, {
                                    role: e.target.value as User["role"],
                                  }),
                                "역할을 변경했습니다. 해당 사용자는 다시 로그인해야 합니다.",
                              ))
                            )
                              users.refresh();
                          }}
                        >
                          {Object.entries(roles).map(([key, label]) => (
                            <option key={key} value={key}>
                              {label}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>{item.is_active ? "활성" : "비활성"}</td>
                      <td>
                        <button
                          className="text-button"
                          disabled={action.pending || item.id === user?.id}
                          onClick={async () => {
                            if (
                              api &&
                              (await action.run(
                                () => changeUser(api, item.id, { is_active: !item.is_active }),
                                "활성 상태를 변경했습니다.",
                              ))
                            )
                              users.refresh();
                          }}
                        >
                          {item.is_active ? "비활성화" : "활성화"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="pagination">
              <span>계정 {users.data?.total ?? 0}개</span>
              <div>
                <button disabled={!page} onClick={() => setPage(page - 1)}>
                  이전
                </button>
                <button
                  disabled={(page + 1) * 30 >= (users.data?.total ?? 0)}
                  onClick={() => setPage(page + 1)}
                >
                  다음
                </button>
              </div>
            </div>
          </section>
          <section className="panel">
            <div className="panel-heading">
              <div>
                <h2>자산 접근 권한</h2>
                <p>
                  담당자·조회자에게 필요한 자산만 지정합니다. 관리자는 별도 지정 없이 전체 자산에
                  접근합니다.
                </p>
              </div>
            </div>
            <div className="asset-form">
              <label>
                자산
                <select value={asset} onChange={(e) => setAsset(e.target.value)}>
                  <option value="">선택</option>
                  {assets.data?.items.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.asset_name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                계정
                <select value={chosenUser} onChange={(e) => setChosenUser(e.target.value)}>
                  <option value="">선택</option>
                  {users.data?.items
                    .filter((u) => u.role !== "ADMIN")
                    .map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.display_name} ({u.username})
                      </option>
                    ))}
                </select>
                <small className="field-hint">현재 계정 목록 페이지의 계정을 표시합니다.</small>
              </label>
              <div className="form-submit">
                <button
                  className="primary"
                  disabled={!asset || !chosenUser || action.pending}
                  onClick={async () => {
                    if (
                      api &&
                      (await action.run(
                        () => grant(api, asset, chosenUser),
                        "자산 권한을 부여했습니다.",
                      ))
                    )
                      grants.refresh();
                  }}
                >
                  권한 부여
                </button>
              </div>
            </div>
            <div className="pagination">
              <span>자산 페이지 {assetPage + 1}</span>
              <div>
                <button
                  disabled={!assetPage}
                  onClick={() => {
                    setAssetPage(assetPage - 1);
                    setAsset("");
                  }}
                >
                  이전
                </button>
                <button
                  disabled={(assetPage + 1) * 20 >= (assets.data?.total ?? 0)}
                  onClick={() => {
                    setAssetPage(assetPage + 1);
                    setAsset("");
                  }}
                >
                  다음
                </button>
              </div>
            </div>
            {grants.data && (
              <div className="inventory-content">
                {grants.data.users.length ? (
                  grants.data.users.map((u) => (
                    <div className="collection-connection" key={u.id}>
                      <span>
                        {u.display_name} ({u.username})
                      </span>
                      <button
                        className="text-button"
                        disabled={action.pending}
                        onClick={async () => {
                          if (
                            api &&
                            (await action.run(
                              () => revoke(api, asset, u.id),
                              "접근 권한을 회수했습니다.",
                            ))
                          )
                            grants.refresh();
                        }}
                      >
                        권한 회수
                      </button>
                    </div>
                  ))
                ) : (
                  <p>명시적으로 권한을 부여한 계정이 없습니다.</p>
                )}
              </div>
            )}
          </section>
        </>
      )}
      {!api && <p className="inventory-note">먼저 로그인하거나 개발용 토큰으로 연결하세요.</p>}
    </>
  );
}
