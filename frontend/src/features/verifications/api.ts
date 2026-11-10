import type { HttpClient } from "../../api/client";
import type { components } from "../../api/schema";

export type Verification = components["schemas"]["VerificationResponse"];
export type VerificationDetail = components["schemas"]["VerificationDetail"];
export type VerificationEvidence = components["schemas"]["VerificationEvidence"];
const base = (asset: string) => `/assets/${asset}/verifications`;
export const requestVerification = (
  api: HttpClient,
  asset: string,
  inventory: string,
  key: string,
) =>
  api.request<Verification>(base(asset), {
    method: "POST",
    headers: { "Idempotency-Key": key },
    body: JSON.stringify({ inventory_id: inventory }),
  });
export const listVerifications = (
  api: HttpClient,
  asset: string,
  page: number,
  signal?: AbortSignal,
) =>
  api.request<components["schemas"]["VerificationList"]>(
    `${base(asset)}?limit=10&offset=${page * 10}`,
    { signal },
  );
export const getVerification = (api: HttpClient, asset: string, id: string, signal?: AbortSignal) =>
  api.request<VerificationDetail>(`${base(asset)}/${id}`, { signal });
