import type { HttpClient } from "../../api/client";
import type { components } from "../../api/schema";

export type ReportRequest = components["schemas"]["ReportRequest"];
export const createReport = (api: HttpClient, body: ReportRequest) =>
  api.request<unknown>("/reports", { method: "POST", body: JSON.stringify(body) });
