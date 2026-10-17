import type { components } from "./schema";

type ErrorResponse = components["schemas"]["ErrorResponse"];

// 공통 HTTP 처리. 기능별 요청은 features/*/api.ts에서 관리한다.
export function createHttpClient(token: string) {
  async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
    let response: Response;
    try {
      response = await fetch(`/api/v1${path}`, {
        ...options,
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
          ...options.headers,
        },
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      throw new Error("API에 연결할 수 없습니다. 백엔드 실행 상태를 확인하세요.");
    }
    if (!response.ok) {
      const body = (await response.json().catch(() => null)) as ErrorResponse | null;
      throw new Error(body?.error?.message ?? `요청 실패 (${response.status})`);
    }
    return response.json() as Promise<T>;
  }
  return { request };
}

export type HttpClient = ReturnType<typeof createHttpClient>;
