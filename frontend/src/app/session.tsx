import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { createHttpClient } from "../api/client";
import type { HttpClient } from "../api/client";
import type { components } from "../api/schema";

type Capabilities = components["schemas"]["CapabilitiesResponse"];
type User = components["schemas"]["UserResponse"];
type Session = { api: HttpClient; capabilities: Capabilities; user: User | null };
type SessionValue = {
  api: HttpClient | null;
  capabilities: Capabilities | null;
  connect: (token: string) => Promise<void>;
  disconnect: (alreadyLoggedOut?: boolean) => void;
  signIn: (username: string, password: string) => Promise<void>;
  user: User | null;
  mode: "token" | "accounts" | null;
  loading: boolean;
  connectionError: string;
  isAdmin: boolean;
  canWrite: boolean;
};
const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [mode, setMode] = useState<"token" | "accounts" | null>(null);
  const [loading, setLoading] = useState(true);
  const [connectionError, setConnectionError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    const expired = () => setSession(null);
    window.addEventListener("cti-session-expired", expired);
    void (async () => {
      try {
        const publicApi = createHttpClient();
        const status = await publicApi.request<{ mode: "token" | "accounts" }>("/auth/status", {
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        setMode(status.mode);
        if (status.mode === "accounts") {
          const response = await fetch("/api/v1/auth/me", {
            credentials: "same-origin",
            signal: controller.signal,
          });
          if (response.status === 401) return;
          if (!response.ok) throw new Error("로그인 상태를 확인하지 못했습니다.");
          const me = (await response.json()) as components["schemas"]["SessionResponse"];
          const api = createHttpClient("", me.csrf_token);
          const capabilities = await api.request<Capabilities>("/capabilities", {
            signal: controller.signal,
          });
          if (!controller.signal.aborted) setSession({ api, capabilities, user: me.user });
        }
      } catch (error) {
        if (!controller.signal.aborted)
          setConnectionError(
            error instanceof Error ? error.message : "연결 상태를 확인하지 못했습니다.",
          );
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => {
      controller.abort();
      window.removeEventListener("cti-session-expired", expired);
    };
  }, []);
  async function connect(token: string) {
    const api = createHttpClient(token);
    const capabilities = await api.request<Capabilities>("/capabilities");
    setSession({ api, capabilities, user: null });
  }
  async function signIn(username: string, password: string) {
    setConnectionError("");
    const me = await createHttpClient().request<components["schemas"]["SessionResponse"]>(
      "/auth/login",
      { method: "POST", body: JSON.stringify({ username, password }) },
    );
    const api = createHttpClient("", me.csrf_token);
    const capabilities = await api.request<Capabilities>("/capabilities");
    setSession({ api, capabilities, user: me.user });
  }
  function disconnect(alreadyLoggedOut = false) {
    if (mode === "accounts" && session && !alreadyLoggedOut) {
      void session.api
        .request("/auth/logout", { method: "POST" })
        .then(() => setSession(null))
        .catch((error) => setConnectionError(String(error)));
    } else setSession(null);
  }
  return (
    <SessionContext.Provider
      value={{
        api: session?.api ?? null,
        capabilities: session?.capabilities ?? null,
        connect,
        disconnect,
        signIn,
        mode,
        loading,
        connectionError,
        user: session?.user ?? null,
        isAdmin: !!session && (!session.user || session.user.role === "ADMIN"),
        canWrite: !!session && (!session.user || session.user.role !== "VIEWER"),
      }}
    >
      {children}
    </SessionContext.Provider>
  );
}

export function useSession() {
  const session = useContext(SessionContext);
  if (!session) throw new Error("SessionProvider is required");
  return session;
}
