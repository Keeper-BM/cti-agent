import type { HttpClient } from "../../api/client";
import type { components } from "../../api/schema";
export type Comparison = components["schemas"]["ComparisonDetail"];
export type ComparisonResult = components["schemas"]["ComparisonResult"];
export const createComparison = (api: HttpClient, baseline: string, target: string, key: string) =>
  api.request<components["schemas"]["ComparisonResponse"]>("/comparisons", {
    method: "POST",
    headers: { "Idempotency-Key": key },
    body: JSON.stringify({ baseline_analysis_id: baseline, target_inventory_id: target }),
  });
export const getComparison = (api: HttpClient, id: string, signal?: AbortSignal) =>
  api.request<Comparison>(`/comparisons/${id}`, { signal });
export const listComparisons = (
  api: HttpClient,
  asset: string,
  page: number,
  signal?: AbortSignal,
) =>
  api.request<components["schemas"]["ComparisonList"]>(
    `/comparisons?asset_id=${asset}&limit=10&offset=${page * 10}`,
    { signal },
  );
