import type { HttpClient } from "../../api/client";
import type { components } from "../../api/schema";

export type SSHProfile = components["schemas"]["SSHProfileResponse"];
export type SSHProfileInput = components["schemas"]["SSHProfileInput"];
export type SSHSettings = components["schemas"]["SSHSettingsResponse"];
export type Collection = components["schemas"]["CollectionResponse"];
export type CollectionDetail = components["schemas"]["CollectionDetail"];
type CollectionList = components["schemas"]["CollectionList"];
const path = (assetId: string) => `/assets/${assetId}/collections`;

export const getSSHSettings = (api: HttpClient, signal?: AbortSignal) =>
  api.request<SSHSettings>("/collections/settings", { signal });
export const getSSHProfile = (api: HttpClient, assetId: string, signal?: AbortSignal) =>
  api.request<{ profile: SSHProfile | null }>(`/assets/${assetId}/ssh-profile`, { signal });
export const saveSSHProfile = (api: HttpClient, assetId: string, body: SSHProfileInput) =>
  api.request<SSHProfile>(`/assets/${assetId}/ssh-profile`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
export const collectPackages = (api: HttpClient, assetId: string, profileId: string, key: string) =>
  api.request<Collection>(path(assetId), {
    method: "POST",
    headers: { "Idempotency-Key": key },
    body: JSON.stringify({ profile_id: profileId }),
  });
export const listCollections = (
  api: HttpClient,
  assetId: string,
  page: number,
  signal?: AbortSignal,
) => api.request<CollectionList>(`${path(assetId)}?limit=10&offset=${page * 10}`, { signal });
export const getCollection = (api: HttpClient, assetId: string, id: string, signal?: AbortSignal) =>
  api.request<CollectionDetail>(`${path(assetId)}/${id}`, { signal });
