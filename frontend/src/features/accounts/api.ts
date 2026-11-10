import type { HttpClient } from "../../api/client";
import type { components } from "../../api/schema";

export type User = components["schemas"]["UserResponse"];
export const listUsers = (api: HttpClient, page: number, signal?: AbortSignal) =>
  api.request<components["schemas"]["UserList"]>(`/admin/users?limit=30&offset=${page * 30}`, {
    signal,
  });
export const addUser = (api: HttpClient, input: components["schemas"]["UserCreate"]) =>
  api.request<User>("/admin/users", { method: "POST", body: JSON.stringify(input) });
export const changeUser = (
  api: HttpClient,
  id: string,
  input: components["schemas"]["UserPatch"],
) => api.request<User>(`/admin/users/${id}`, { method: "PATCH", body: JSON.stringify(input) });
export const getGrants = (api: HttpClient, asset: string, signal?: AbortSignal) =>
  api.request<components["schemas"]["GrantList"]>(`/admin/assets/${asset}/grants`, { signal });
export const grant = (api: HttpClient, asset: string, user: string) =>
  api.request(`/admin/assets/${asset}/grants`, {
    method: "POST",
    body: JSON.stringify({ user_id: user }),
  });
export const revoke = (api: HttpClient, asset: string, user: string) =>
  api.request(`/admin/assets/${asset}/grants/${user}`, { method: "DELETE" });
export const auditEvents = (api: HttpClient, page: number, signal?: AbortSignal) =>
  api.request<components["schemas"]["AuditList"]>(`/audit?limit=30&offset=${page * 30}`, {
    signal,
  });
