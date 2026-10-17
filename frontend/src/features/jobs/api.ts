import type { HttpClient } from "../../api/client";
import type { components } from "../../api/schema";

export type Job = components["schemas"]["JobResponse"];
type JobList = components["schemas"]["JobList"];
export const listJobs = (api: HttpClient, signal?: AbortSignal) =>
  api.request<JobList>("/jobs?limit=20", { signal });
export const checkWorker = (api: HttpClient) =>
  api.request<Job>("/jobs/system-checks", {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
  });
