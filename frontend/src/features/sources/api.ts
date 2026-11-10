import type { HttpClient } from "../../api/client";
import type { components } from "../../api/schema";

export type StatusList = components["schemas"]["SourceStatusList"];
export type Source = components["schemas"]["SourceStatus"]["source_id"];
export type SnapshotList = components["schemas"]["SnapshotList"];
export type RecordList = components["schemas"]["RecordList"];
export type RecordData = components["schemas"]["RecordResponse"];
export type CVE = components["schemas"]["CVEDetail"];
export type SyncInput = Partial<components["schemas"]["SourceSyncRequest"]>;
type Job = components["schemas"]["JobResponse"];

export const names: Record<Source, string> = {
  ubuntu: "Ubuntu CVE",
  nvd: "NVD",
  kev: "CISA KEV",
  apache: "Apache HTTP Server",
  oracle: "Oracle / MySQL",
};
export const getStatus = (api: HttpClient, signal?: AbortSignal) =>
  api.request<StatusList>("/sources/status", { signal });
export const syncSource = (api: HttpClient, source: Source, body: SyncInput) =>
  api.request<Job>(`/sources/${source}/sync`, {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify(body),
  });
export const getSnapshots = (api: HttpClient, source: string, page: number, signal?: AbortSignal) =>
  api.request<SnapshotList>(
    `/sources/snapshots?limit=20&offset=${page * 20}${source ? `&source_id=${source}` : ""}`,
    { signal },
  );
export const getRecords = (
  api: HttpClient,
  filters: Record<string, string>,
  signal?: AbortSignal,
) => api.request<RecordList>(`/sources/records?${new URLSearchParams(filters)}`, { signal });
export const getCVE = (api: HttpClient, cve: string, signal?: AbortSignal) =>
  api.request<CVE>(`/sources/cves/${cve}`, { signal });
export const getDocument = (api: HttpClient, id: string) =>
  api.request<{ raw_text: string; sha256: string; url: string }>(`/sources/documents/${id}`);
