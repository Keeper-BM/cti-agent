import type { HttpClient } from "../../api/client";
import type { components } from "../../api/schema";

export type FindingList = components["schemas"]["FindingList"];
export type Analysis = components["schemas"]["AnalysisResponse"];
export type AnalysisList = components["schemas"]["AnalysisList"];
export type Finding = components["schemas"]["AssessmentFinding"];
export type FindingDetail = components["schemas"]["FindingDetail"];
export const createAnalysis = (api: HttpClient, inventoryId: string, key: string) =>
  api.request<Analysis>("/analyses", {
    method: "POST",
    headers: { "Idempotency-Key": key },
    body: JSON.stringify({ inventory_id: inventoryId }),
  });
export const listAnalyses = (
  api: HttpClient,
  assetId: string,
  page: number,
  signal?: AbortSignal,
) =>
  api.request<AnalysisList>(`/analyses?asset_id=${assetId}&limit=10&offset=${page * 10}`, {
    signal,
  });
export const getAnalysis = (api: HttpClient, id: string, signal?: AbortSignal) =>
  api.request<Analysis>(`/analyses/${id}`, { signal });
export const listFindings = (
  api: HttpClient,
  filters: Record<string, string>,
  signal?: AbortSignal,
) => api.request<FindingList>(`/findings?${new URLSearchParams(filters)}`, { signal });
export const getFinding = (api: HttpClient, id: string, signal?: AbortSignal) =>
  api.request<FindingDetail>(`/findings/${id}`, { signal });
