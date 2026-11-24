import type { HttpClient } from "../../api/client";
import type { components } from "../../api/schema";

export type Batch = components["schemas"]["WorkflowBatchResponse"];
export type BatchComparison = components["schemas"]["BatchComparison"];
type BatchList = components["schemas"]["WorkflowBatchList"];
export const coverageLabels = {
  EVALUATED: "평가 결과 있음",
  NO_TARGET: "평가 대상 없음",
  NO_EVIDENCE: "평가 근거 부족",
} as const;
export function batchLink(id: string, cve?: string) {
  const query = new URLSearchParams({ batch: id });
  if (cve) query.set("cve", cve);
  return "#/reports?" + query;
}

export const startBatch = (api: HttpClient, assetIds: string[], key: string) =>
  api.request<Batch>("/workflow-batches", {
    method: "POST",
    headers: { "Idempotency-Key": key },
    body: JSON.stringify({ asset_ids: assetIds }),
  });
export const getBatch = (api: HttpClient, id: string, signal?: AbortSignal) =>
  api.request<Batch>(`/workflow-batches/${encodeURIComponent(id)}`, { signal });
export const listBatches = (api: HttpClient, page: number, signal?: AbortSignal) =>
  api.request<BatchList>(`/workflow-batches?limit=5&offset=${page * 5}`, { signal });
export const retryBatch = (api: HttpClient, id: string, key: string) =>
  api.request<Batch>(`/workflow-batches/${encodeURIComponent(id)}/retry`, {
    method: "POST",
    headers: { "Idempotency-Key": key },
  });
export const retryBatchReport = (api: HttpClient, id: string) =>
  api.request<Batch>(`/workflow-batches/${encodeURIComponent(id)}/report/retry`, {
    method: "POST",
  });
export const compareBatch = (api: HttpClient, id: string, cve: string, signal?: AbortSignal) =>
  api.request<BatchComparison>(
    `/workflow-batches/${encodeURIComponent(id)}/comparison` +
      (cve ? "?" + new URLSearchParams({ cve_id: cve }) : ""),
    { signal },
  );
export const downloadBatch = (api: HttpClient, id: string) =>
  api.text(`/workflow-batches/${encodeURIComponent(id)}/markdown`);
