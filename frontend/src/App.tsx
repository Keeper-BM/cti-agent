import { WorkspaceLayout } from "./app/WorkspaceLayout";
import { useRoute } from "./app/navigation";
import { SessionProvider } from "./app/session";
import { AssetsPage } from "./features/assets/AssetsPage";
import { ExamplePage } from "./features/examples/ExamplePage";
import { FindingsPage } from "./features/findings/FindingsPage";
import { JobsPage } from "./features/jobs/JobsPage";
import { QuestionsPage } from "./features/questions/QuestionsPage";
import { ReportsPage } from "./features/reports/ReportsPage";
import { SchedulePage } from "./features/schedules/SchedulePage";
import { SourcesPage } from "./features/sources/SourcesPage";
import { AccountsPage } from "./features/accounts/AccountsPage";
import { AuditPage } from "./features/accounts/AuditPage";
import { WorkflowPage } from "./features/workflows/WorkflowPage";

// 공통 세션·레이아웃과 기능별 페이지를 조합한다.
export default function App() {
  const { route, hash, params } = useRoute();
  const pages = {
    workspace: (
      <WorkflowPage
        asset={params.get("mode") === "batch" ? "" : (params.get("asset") ?? "")}
        analysis={params.get("analysis") ?? ""}
      />
    ),
    assets: <AssetsPage key={hash} />,
    sources: <SourcesPage />,
    findings: <FindingsPage key={hash} />,
    questions: <QuestionsPage key={hash} />,
    reports: <ReportsPage key={hash} />,
    schedules: (
      <SchedulePage
        key={hash}
        id={params.get("schedule") ?? ""}
        create={params.get("new") === "1"}
        edit={params.get("edit") === "1"}
      />
    ),
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
