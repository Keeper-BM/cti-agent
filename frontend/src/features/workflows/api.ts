import type { HttpClient } from "../../api/client";
import type { components } from "../../api/schema";

export type Workspace = components["schemas"]["WorkspaceResponse"];
export type Workflow = components["schemas"]["WorkflowResponse"];
export type Brief = components["schemas"]["AnalysisBrief"];
export const getWorkspace = (api: HttpClient, id: string, signal?: AbortSignal) =>
  api.request<Workspace>(`/assets/${id}/workspace`, { signal });
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
