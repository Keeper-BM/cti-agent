import type { components } from "./schema";

type ErrorResponse = components["schemas"]["ErrorResponse"];

// 공통 HTTP 처리. 기능별 요청은 features/*/api.ts에서 관리한다.
export function createHttpClient(token = "", csrfToken = "") {
  async function send(path: string, options: RequestInit = {}): Promise<Response> {
    let response: Response;
    try {
      response = await fetch(`/api/v1${path}`, {
        ...options,
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
          ...options.headers,
        },
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      throw new Error("API에 연결할 수 없습니다. 백엔드 실행 상태를 확인하세요.");
    }
    if (!response.ok) {
      if (response.status === 401 && typeof window !== "undefined")
        window.dispatchEvent(new Event("cti-session-expired"));
      const body = (await response.json().catch(() => null)) as ErrorResponse | null;
      throw new Error(body?.error?.message ?? `요청 실패 (${response.status})`);
    }
    return response;
  }
  async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
    return (await send(path, options)).json() as Promise<T>;
  }
  async function text(path: string, options: RequestInit = {}): Promise<string> {
    return (await send(path, options)).text();
  }
  return { request, text };
}

export type HttpClient = ReturnType<typeof createHttpClient>;
