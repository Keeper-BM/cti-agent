import type { HttpClient } from "../../api/client";
import type { components } from "../../api/schema";

export type Explanation = components["schemas"]["ExplanationResponse"];
export type ExplanationResult = components["schemas"]["ExplanationResult"];
type ExplanationList = components["schemas"]["ExplanationList"];
type LLMStatus = components["schemas"]["LLMStatus"];

export const getLLMStatus = (api: HttpClient, signal?: AbortSignal) =>
  api.request<LLMStatus>("/explanations/status", { signal });
export const createExplanation = (api: HttpClient, findingId: string, key: string) =>
  api.request<Explanation>("/explanations", {
    method: "POST",
    headers: { "Idempotency-Key": key },
    body: JSON.stringify({ finding_id: findingId }),
  });
export const listExplanations = (
  api: HttpClient,
  findingId: string,
  page: number,
  signal?: AbortSignal,
) =>
  api.request<ExplanationList>(
    `/explanations?finding_id=${findingId}&limit=10&offset=${page * 10}`,
    { signal },
  );
export const getExplanation = (api: HttpClient, id: string, signal?: AbortSignal) =>
  api.request<Explanation>(`/explanations/${id}`, { signal });
