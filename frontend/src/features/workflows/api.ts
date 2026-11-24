import type { HttpClient } from "../../api/client";
import type { components } from "../../api/schema";

export type Workspace = components["schemas"]["WorkspaceResponse"];
export type Workflow = components["schemas"]["WorkflowResponse"];
export type Brief = components["schemas"]["AnalysisBrief"];
export const getWorkspace = (api: HttpClient, id: string, analysis: string, signal?: AbortSignal) =>
  api.request<Workspace>(
    `/assets/${id}/workspace${analysis ? "?analysis_id=" + encodeURIComponent(analysis) : ""}`,
    { signal },
  );
export const startWorkflow = (api: HttpClient, id: string, inventory: string | null, key: string) =>
  api.request<Workflow>(`/assets/${id}/workflows`, {
    method: "POST",
    headers: { "Idempotency-Key": key },
    body: JSON.stringify({ inventory_id: inventory }),
  });
export const checkProfile = (api: HttpClient, asset: string, profile: string) =>
  api.request<components["schemas"]["ConnectionCheck"]>(
    `/assets/${asset}/ssh-profile/${profile}/check`,
    { method: "POST" },
  );

export function routeParam(key: string) {
  return new URLSearchParams(window.location.hash.split("?")[1] ?? "").get(key) ?? "";
}

export const sourceNames: Record<string, string> = {
  ubuntu: "Ubuntu CVE",
  kev: "CISA KEV",
  apache: "Apache HTTP Server",
  nvd: "NVD",
  oracle: "Oracle / MySQL",
};
export const count = (value: number) => value.toLocaleString("ko-KR");
export const shortTime = (value: string) =>
  new Intl.DateTimeFormat("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: "Asia/Seoul",
  }).format(new Date(value));

export function workspaceLink(asset = "", analysis?: string) {
  const query = new URLSearchParams();
  if (asset) query.set("asset", asset);
  if (analysis) query.set("analysis", analysis);
  return query.size ? "#/workspace?" + query : "#/workspace";
}

export function reportLink(id: string) {
  return "#/reports?report=" + encodeURIComponent(id);
}

export const sourceStates = {
  UPDATED: "갱신",
  CACHED: "저장본 사용",
  FAILED: "자료 미확보",
  RUNNING: "조회 중",
  QUEUED: "대기",
} as const;

export function sourceCounts(sources: Workflow["sources"]) {
  const counts = { UPDATED: 0, CACHED: 0, FAILED: 0, RUNNING: 0, QUEUED: 0 };
  for (const source of sources) counts[source.status]++;
  return counts;
}
