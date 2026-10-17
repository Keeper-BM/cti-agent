import type { HttpClient } from "../../api/client";
import type { components } from "../../api/schema";

export type FindingList = components["schemas"]["FindingList"];
export type AnalysisRequest = components["schemas"]["AnalysisRequest"];
// 현재 API는 501을 반환한다. 판정·저장소를 연결한 뒤 페이지에서 사용한다.
export const listFindings = (api: HttpClient, signal?: AbortSignal) =>
  api.request<FindingList>("/findings", { signal });
