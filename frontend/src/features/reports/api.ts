import type { HttpClient } from "../../api/client";
import type { components } from "../../api/schema";

export type ReportRequest = components["schemas"]["ReportRequest"];
export type Report = components["schemas"]["ReportResponse"];
export type ReportDetail = components["schemas"]["ReportDetail"];
export type ReportContent = components["schemas"]["ReportContent"];
type ReportList = components["schemas"]["ReportList"];
export const createReport = (
  api: HttpClient,
  analysisId: string,
  includeAI: boolean,
  key: string,
) =>
  api.request<Report>("/reports", {
    method: "POST",
    headers: { "Idempotency-Key": key },
    body: JSON.stringify({ analysis_id: analysisId, include_ai_explanations: includeAI }),
  });
export const listReports = (api: HttpClient, assetId: string, page: number, signal?: AbortSignal) =>
  api.request<ReportList>(
    `/reports?limit=10&offset=${page * 10}${assetId ? `&asset_id=${assetId}` : ""}`,
    { signal },
  );
export const getReport = (api: HttpClient, id: string, signal?: AbortSignal) =>
  api.request<ReportDetail>(`/reports/${id}`, { signal });
export const downloadReport = (api: HttpClient, id: string) => api.text(`/reports/${id}/markdown`);
