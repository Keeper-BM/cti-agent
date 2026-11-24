import type { HttpClient } from "../../api/client";
import type { components } from "../../api/schema";

type Schemas = components["schemas"];
export type Schedule = Schemas["ScheduleResponse"];
export type ScheduleInput = Schemas["ScheduleInput"];
export type ScheduleRun = Schemas["ScheduleRunResponse"];
export type Changes = Schemas["ScheduleChanges"];
export type ChangeKind = Schemas["ScheduleChange"]["kind"];

const path = "/workflow-schedules";
export const schedulePageSize = 10;
export const runPageSize = 8;
export const changesPageSize = 20;

export const scheduleLink = (id: string, edit = false) =>
  "#/schedules?" + new URLSearchParams({ schedule: id, ...(edit ? { edit: "1" } : {}) });

export const listSchedules = (api: HttpClient, page: number, signal: AbortSignal) =>
  api.request<Schemas["ScheduleList"]>(
    `${path}?limit=${schedulePageSize}&offset=${page * schedulePageSize}`,
    { signal },
  );
export const getSchedule = (api: HttpClient, id: string, signal: AbortSignal) =>
  api.request<Schedule>(`${path}/${encodeURIComponent(id)}`, { signal });
export const saveSchedule = (api: HttpClient, input: ScheduleInput, id?: string) =>
  api.request<Schedule>(id ? `${path}/${encodeURIComponent(id)}` : path, {
    method: id ? "PUT" : "POST",
    body: JSON.stringify(input),
  });
export const setScheduleEnabled = (api: HttpClient, id: string, enabled: boolean) =>
  api.request<Schedule>(`${path}/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify({ enabled }),
  });
export const listScheduleRuns = (api: HttpClient, id: string, page: number, signal: AbortSignal) =>
  api.request<Schemas["ScheduleRunList"]>(
    `${path}/${encodeURIComponent(id)}/runs?limit=${runPageSize}&offset=${page * runPageSize}`,
    { signal },
  );
export function listChanges(
  api: HttpClient,
  id: string,
  runId: string,
  kind: ChangeKind | "",
  page: number,
  signal: AbortSignal,
) {
  const query = new URLSearchParams({
    limit: String(changesPageSize),
    offset: String(page * changesPageSize),
  });
  if (kind) query.set("kind", kind);
  return api.request<Changes>(
    `${path}/${encodeURIComponent(id)}/runs/${encodeURIComponent(runId)}/changes?${query}`,
    { signal },
  );
}
