import type { HttpClient } from "../../api/client";
import type { components } from "../../api/schema";

export type QuestionRequest = components["schemas"]["QuestionRequest"];
// LLM·작업 큐가 연결되기 전에는 501을 반환한다.
export const submitQuestion = (api: HttpClient, body: QuestionRequest) =>
  api.request<unknown>("/questions", { method: "POST", body: JSON.stringify(body) });
