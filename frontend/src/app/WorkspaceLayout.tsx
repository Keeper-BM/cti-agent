import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { ConnectionPanel } from "../shared/components/ConnectionPanel";
import { Icon } from "../shared/components/Icon";
import { routes } from "./navigation";
import type { Route } from "./navigation";
import { useSession } from "./session";

const icons = {
  assets: "assets",
  findings: "findings",
  questions: "insights",
  reports: "reports",
  jobs: "jobs",
  example: "example",
} as const;

export function WorkspaceLayout({ route, children }: { route: Route; children: ReactNode }) {
  const { api, disconnect } = useSession();
  const mobileNav = useRef<HTMLElement>(null);
  useEffect(() => {
    const nav = mobileNav.current;
    const active = nav?.querySelector<HTMLElement>('[aria-current="page"]');
    if (!nav || !active || nav.clientWidth === 0) return;
    const bounds = nav.getBoundingClientRect();
    const item = active.getBoundingClientRect();
    if (item.left < bounds.left || item.right > bounds.right) {
      nav.scrollLeft += item.left - bounds.left - 12;
    }
  }, [route.id]);
  const links = routes.map((item) => (
    <a
      key={item.id}
      className={`nav-link ${route.id === item.id ? "selected" : ""}`}
      href={`#/${item.id}`}
      aria-current={route.id === item.id ? "page" : undefined}
    >
      <Icon name={icons[item.id]} className="nav-icon" />
      <span className="nav-text">{item.title}</span>
      {["findings", "questions", "reports"].includes(item.id) && <small>준비 중</small>}
    </a>
  ));
  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" href="#/assets" aria-label="CTI Agent 자산 현황으로 이동">
          <img className="brand-symbol" src="/cti-mark.svg?v=2" alt="" aria-hidden="true" />
          <span className="brand-name">
            CTI Agent<small>THREAT INTELLIGENCE</small>
          </span>
        </a>
        <div className="workspace-label">메뉴</div>
        <nav className="sidebar-nav" aria-label="주 메뉴">
          {links}
        </nav>
        <div className="sidebar-footer">
          <span className={`status-dot ${api ? "online" : ""}`} />
          <span>{api ? "API 연결됨" : "API 연결 대기"}</span>
          <span className="sidebar-version">v0.1</span>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            <span>CTI Agent</span>
            <span aria-hidden="true">/</span>
            <strong>{route.title}</strong>
          </div>
          <div className="topbar-actions">
            <span className="environment">개발 환경</span>
            {api && (
              <button className="topbar-disconnect" onClick={disconnect}>
                연결 해제
              </button>
            )}
          </div>
        </header>
        <nav ref={mobileNav} className="mobile-nav" aria-label="모바일 메뉴">
          {links}
        </nav>
        <main>
          <div className="page-content">
            <div className="heading-row">
              <div>
                <h1>{route.title}</h1>
                <p className="intro">{route.description}</p>
              </div>
              <span className={`connection ${api ? "online" : ""}`}>
                <i />
                {api ? "API 연결됨" : "연결 대기"}
              </span>
            </div>
            <ConnectionPanel />
            <div key={route.id}>{children}</div>
            <footer className="page-footer">
              <span>CTI Agent</span>
              <span>시각은 한국 시간 기준</span>
            </footer>
          </div>
        </main>
      </div>
    </div>
  );
}
