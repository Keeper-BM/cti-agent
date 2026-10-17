import { createContext, useContext, useState } from "react";
import type { ReactNode } from "react";
import { createHttpClient } from "../api/client";
import type { HttpClient } from "../api/client";
import type { components } from "../api/schema";

type Capabilities = components["schemas"]["CapabilitiesResponse"];
type Session = { api: HttpClient; capabilities: Capabilities };
type SessionValue = {
  api: HttpClient | null;
  capabilities: Capabilities | null;
  connect: (token: string) => Promise<void>;
  disconnect: () => void;
};
const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  async function connect(token: string) {
    const api = createHttpClient(token);
    const capabilities = await api.request<Capabilities>("/capabilities");
    setSession({ api, capabilities });
  }
  return (
    <SessionContext.Provider
      value={{
        api: session?.api ?? null,
        capabilities: session?.capabilities ?? null,
        connect,
        disconnect: () => setSession(null),
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
