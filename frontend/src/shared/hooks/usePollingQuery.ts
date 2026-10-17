import { useCallback, useEffect, useRef, useState } from "react";
import { startPolling } from "./polling";

// The caller memoizes load; each feature owns its request and display state.
export function usePollingQuery<T>(
  load: ((signal: AbortSignal) => Promise<T>) | null,
  intervalMs: number | null = 5000,
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const polling = useRef<ReturnType<typeof startPolling<T>> | null>(null);
  const refresh = useCallback(() => polling.current?.refresh(), []);
  useEffect(() => {
    setData(null);
    setError("");
    if (!load) {
      setLoading(false);
      return;
    }
    const current = startPolling(
      load,
      {
        success: (result) => {
          setData(result);
          setError("");
        },
        error: (cause) => setError(cause instanceof Error ? cause.message : "조회에 실패했습니다."),
        loading: setLoading,
      },
      intervalMs,
    );
    polling.current = current;
    return () => {
      current.stop();
      polling.current = null;
    };
  }, [load, intervalMs]);
  return { data: load ? data : null, error: load ? error : "", loading, refresh };
}
