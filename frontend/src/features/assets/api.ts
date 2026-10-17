import type { HttpClient } from "../../api/client";
import type { components } from "../../api/schema";

export type Asset = components["schemas"]["AssetResponse"];
export type AssetCreate = components["schemas"]["AssetCreate"];
export type AssetList = components["schemas"]["AssetList"];
export const listAssets = (api: HttpClient, offset = 0, signal?: AbortSignal) =>
  api.request<AssetList>(`/assets?limit=20&offset=${offset}`, { signal });
export const createAsset = (api: HttpClient, body: AssetCreate) =>
  api.request<Asset>("/assets", { method: "POST", body: JSON.stringify(body) });
export const setAssetActive = (api: HttpClient, id: string, active: boolean) =>
  api.request<Asset>(`/assets/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ is_active: active }),
  });
