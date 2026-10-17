import type { ReactNode } from "react";
import { ConnectionPanel } from "../shared/components/ConnectionPanel";
import { routes } from "./navigation";
import type { Route } from "./navigation";
import { useSession } from "./session";

export function WorkspaceLayout({ route, children }: { route: Route; children: ReactNode }) {
  const { api } = useSession();
  const links = routes.map((item) => (
    <a
      key={item.id}
      className={`nav-link ${route.id === item.id ? "selected" : ""}`}
      href={`#/${item.id}`}
      aria-current={route.id === item.id ? "page" : undefined}
    >
      {item.title}
      {["findings", "questions", "reports"].includes(item.id) && <small>준비 중</small>}
    </a>
  ));
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-symbol">B</span>
          <span>
            Blended<span className="brand-sub">THREAT INTELLIGENCE</span>
          </span>
        </div>
        <div className="workspace-label">
          WORKSPACE <span>LOCAL</span>
        </div>
        <nav aria-label="주 메뉴">{links}</nav>
        <div className="sidebar-footer">
          <span className="tiny-dot" /> 개발 환경 <span>v0.1.0</span>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <span>
            블랜디드매시업 <span className="separator">/</span> {route.title}
          </span>
          <span className="environment">LOCAL DEVELOPMENT</span>
        </header>
        <nav className="mobile-nav" aria-label="모바일 메뉴">
          {links}
        </nav>
        <main>
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
          <div className="scope-note">
            <strong>프로젝트 시작 버전</strong>
            <span>자산 관리, 작업 큐와 시험 예제를 사용할 수 있습니다.</span>
          </div>
          <ConnectionPanel />
          <div key={route.id}>{children}</div>
          <footer className="page-footer">
            <span>BlendedMeshup · 사이버 위협 Intelligence Agent</span>
            <span>Ubuntu · Apache · MySQL</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
