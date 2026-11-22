import type { HttpClient } from "../../api/client";
import type { components } from "../../api/schema";

export type Question = components["schemas"]["QuestionDetail"];
export type QuestionResult = components["schemas"]["QuestionResult"];
export function listQuestions(
  api: HttpClient,
  page: number,
  analysis: string,
  answered: boolean,
  signal?: AbortSignal,
) {
  const query = new URLSearchParams({ limit: "10", offset: String(page * 10) });
  if (analysis) query.set("analysis_id", analysis);
  if (answered) query.set("answered", "true");
  return api.request<components["schemas"]["QuestionList"]>("/questions?" + query, { signal });
}
export const getQuestion = (api: HttpClient, id: string, signal?: AbortSignal) =>
  api.request<Question>(`/questions/${id}`, { signal });
export const askQuestion = (
  api: HttpClient,
  analysisIds: string[],
  question: string,
  key: string,
) =>
  api.request<components["schemas"]["QuestionResponse"]>("/questions", {
    method: "POST",
    headers: { "Idempotency-Key": key },
    body: JSON.stringify({ analysis_ids: analysisIds, question }),
  });
