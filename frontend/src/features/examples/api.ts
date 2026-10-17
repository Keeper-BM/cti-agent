import type { HttpClient } from "../../api/client";
import type { components } from "../../api/schema";

export type AssessmentExample = components["schemas"]["AssessmentExample"];
export const getAssessmentExample = (api: HttpClient, signal?: AbortSignal) =>
  api.request<AssessmentExample>("/examples/assessment", { signal });
