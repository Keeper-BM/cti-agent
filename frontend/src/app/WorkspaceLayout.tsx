import type { ReactNode } from "react";
import { ConnectionPanel } from "../shared/components/ConnectionPanel";
import { Icon } from "../shared/components/Icon";
import { routes, type Route } from "./navigation";
import { useSession } from "./session";

const icons = {
  workspace: "workflow",
  assets: "assets",
  sources: "database",
  findings: "findings",
  questions: "insights",
  reports: "reports",
  jobs: "activity",
  example: "example",
  accounts: "users",
  audit: "jobs",
} as const;
const groups = [
  { name: "워크스페이스", ids: ["assets", "workspace", "findings", "reports"] },
  { name: "자료 및 도구", ids: ["sources", "questions"] },
  { name: "운영", ids: ["jobs", "example", "accounts", "audit"] },
];
export function WorkspaceLayout({ route, children }: { route: Route; children: ReactNode }) {
  const { api, disconnect, user, isAdmin, mode } = useSession();
  const group = groups.find((g) => g.ids.includes(route.id));
  const roleLabel = isAdmin ? "관리자" : user?.role === "VIEWER" ? "조회자" : "자산 담당자";
  function link(item: Route) {
    return (
      <a
        key={item.id}
        className={`nav-link ${route.id === item.id ? "selected" : ""}`}
        href={`#/${item.id}`}
        aria-current={route.id === item.id ? "page" : undefined}
      >
        <Icon name={icons[item.id]} className="nav-icon" />
        <span className="nav-text">{item.title}</span>
      </a>
    );
  }
  const visible = routes.filter((r) => r.id !== "audit" || isAdmin);
  return (
    <div className="shell design-shell">
      <aside className="sidebar">
        <a className="brand" href="#/workspace" aria-label="CTI Agent 분석 워크스페이스">
          <img className="brand-symbol" src="/cti-mark.svg" alt="" />
          <span className="brand-name">
            CTI Agent<small>Threat Intelligence</small>
          </span>
        </a>
        <nav className="sidebar-nav" aria-label="주 메뉴">
          {groups.map((g) => (
            <div className="nav-group" key={g.name}>
              <div className="workspace-label">{g.name}</div>
              {g.ids.flatMap((id) => visible.filter((r) => r.id === id)).map(link)}
            </div>
          ))}
        </nav>
        <div className="side-account">
          <span className="user-emblem">
            <Icon name="users" />
          </span>
          <div>
            <strong>{user?.display_name ?? (api ? "개발 관리자" : "로그인 대기")}</strong>
            <small>
              {api ? (user?.display_name === roleLabel ? user.username : roleLabel) : "CTI Agent"}
            </small>
          </div>
          {api && (
            <button
              onClick={() => disconnect()}
              aria-label={mode === "accounts" ? "로그아웃" : "연결 해제"}
            >
              <Icon name="logout" />
            </button>
          )}
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            <span className="breadcrumb-brand">CTI Agent</span>
            <span aria-hidden="true">/</span>
            <span>{group?.name}</span>
            <span aria-hidden="true">/</span>
            <strong>{route.title}</strong>
          </div>
          <div className="topbar-actions">
            {api && (
              <button className="mobile-logout" onClick={() => disconnect()} aria-label="로그아웃">
                <Icon name="logout" />
              </button>
            )}
          </div>
        </header>
        <nav className="mobile-nav" aria-label="모바일 메뉴">
          {groups[0].ids.flatMap((id) => visible.filter((r) => r.id === id)).map(link)}
          <details
            key={route.id}
            className="mobile-more"
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                e.currentTarget.open = false;
                e.currentTarget.querySelector("summary")?.focus();
              }
            }}
          >
            <summary
              aria-label="추가 메뉴"
              className={groups[0].ids.includes(route.id) ? "" : "active"}
            >
              더보기
              <Icon name="chevron" />
            </summary>
            <div
              onClick={(e) => {
                if ((e.target as Element).closest("a"))
                  e.currentTarget.closest("details")!.open = false;
              }}
            >
              {groups
                .slice(1)
                .flatMap((g) => g.ids)
                .flatMap((id) => visible.filter((r) => r.id === id))
                .map(link)}
            </div>
          </details>
        </nav>
        <main>
          <div className="page-content">
            <div className="heading-row">
              <div>
                <h1>{route.title}</h1>
                <p className="intro">{route.description}</p>
              </div>
              {route.id === "workspace" && api && isAdmin && (
                <a className="button-link register-link" href="#/assets?new=1">
                  <Icon name="plus" />
                  자산 등록
                </a>
              )}
            </div>
            <ConnectionPanel />
            {api && (
              <div key={route.id} className="page-body">
                {children}
              </div>
            )}
            <footer className="page-footer">
              <span>CTI Agent</span>
              <span>한국 표준시 (KST)</span>
            </footer>
          </div>
        </main>
      </div>
    </div>
  );
}
