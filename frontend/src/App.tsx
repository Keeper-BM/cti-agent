import { WorkspaceLayout } from "./app/WorkspaceLayout";
import { useRoute } from "./app/navigation";
import { SessionProvider } from "./app/session";
import { AssetsPage } from "./features/assets/AssetsPage";
import { ExamplePage } from "./features/examples/ExamplePage";
import { FindingsPage } from "./features/findings/FindingsPage";
import { JobsPage } from "./features/jobs/JobsPage";
import { QuestionsPage } from "./features/questions/QuestionsPage";
import { ReportsPage } from "./features/reports/ReportsPage";
import { SourcesPage } from "./features/sources/SourcesPage";
import { AccountsPage } from "./features/accounts/AccountsPage";
import { AuditPage } from "./features/accounts/AuditPage";

// 공통 세션·레이아웃과 기능별 페이지를 조합한다.
export default function App() {
  const route = useRoute();
  const pages = {
    assets: <AssetsPage />,
    sources: <SourcesPage />,
    findings: <FindingsPage />,
    questions: <QuestionsPage />,
    reports: <ReportsPage />,
    jobs: <JobsPage />,
    example: <ExamplePage />,
    accounts: <AccountsPage />,
    audit: <AuditPage />,
  };
  return (
    <SessionProvider>
      <WorkspaceLayout route={route}>{pages[route.id]}</WorkspaceLayout>
    </SessionProvider>
  );
}
