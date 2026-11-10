import type { HttpClient } from "../../api/client";
import type { components } from "../../api/schema";

export type Inventory = components["schemas"]["InventorySnapshot"];
export type InventoryList = components["schemas"]["InventoryList"];

const path = (assetId: string) => `/assets/${assetId}/inventories`;
export const listInventories = (
  api: HttpClient,
  assetId: string,
  page: number,
  signal?: AbortSignal,
) => api.request<InventoryList>(`${path(assetId)}?limit=10&offset=${page * 10}`, { signal });
export const getInventory = (api: HttpClient, assetId: string, id: string, signal?: AbortSignal) =>
  api.request<Inventory>(`${path(assetId)}/${id}`, { signal });
export const uploadInventory = (
  api: HttpClient,
  assetId: string,
  json: string,
  signal?: AbortSignal,
) => api.request<Inventory>(path(assetId), { method: "POST", body: json, signal });
export const uploadCsvInventory = (
  api: HttpClient,
  assetId: string,
  content: string,
  signal?: AbortSignal,
) =>
  api.request<Inventory>(`${path(assetId)}/csv`, {
    method: "POST",
    body: JSON.stringify({ csv_text: content }),
    signal,
  });
