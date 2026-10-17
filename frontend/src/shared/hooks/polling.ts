type Handlers<T> = {
  success: (result: T) => void;
  error: (cause: unknown) => void;
  loading: (pending: boolean) => void;
};

// Schedule the next poll after completion so slow requests can finish.
export function startPolling<T>(
  load: (signal: AbortSignal) => Promise<T>,
  handlers: Handlers<T>,
  intervalMs: number | null = 5000,
) {
  let stopped = false;
  let pending = false;
  let refreshAfterRequest = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let controller: AbortController | null = null;

  async function run() {
    pending = true;
    controller = new AbortController();
    handlers.loading(true);
    try {
      const result = await load(controller.signal);
      if (!stopped) handlers.success(result);
    } catch (cause: unknown) {
      if (!stopped) handlers.error(cause);
    } finally {
      pending = false;
      if (!stopped) {
        handlers.loading(false);
        if (refreshAfterRequest) {
          refreshAfterRequest = false;
          void run();
        } else if (intervalMs !== null) {
          timer = setTimeout(() => void run(), intervalMs);
        }
      }
    }
  }

  function refresh() {
    if (stopped) return;
    clearTimeout(timer);
    if (pending) refreshAfterRequest = true;
    else void run();
  }

  function stop() {
    stopped = true;
    clearTimeout(timer);
    controller?.abort();
  }

  void run();
  return { refresh, stop };
}
