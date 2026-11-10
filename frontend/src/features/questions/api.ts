import type { HttpClient } from "../../api/client";
import type { components } from "../../api/schema";

export type Question = components["schemas"]["QuestionDetail"];
export type QuestionResult = components["schemas"]["QuestionResult"];
export const listQuestions = (api: HttpClient, page: number, signal?: AbortSignal) =>
  api.request<components["schemas"]["QuestionList"]>(`/questions?limit=10&offset=${page * 10}`, {
    signal,
  });
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
