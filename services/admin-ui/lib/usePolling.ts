import { useCallback, useEffect, useRef } from "react";

export function usePolling(task: () => Promise<void>, intervalMs = 5000) {
  const running = useRef(false);
  const mounted = useRef(true);

  const refresh = useCallback(async () => {
    if (running.current || document.visibilityState === "hidden") return;
    running.current = true;
    try {
      await task();
    } finally {
      running.current = false;
    }
  }, [task]);

  useEffect(() => {
    mounted.current = true;
    let timer: ReturnType<typeof setTimeout>;
    const schedule = async () => {
      await refresh();
      if (mounted.current) timer = setTimeout(schedule, intervalMs);
    };
    void schedule();
    const onVisibility = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      mounted.current = false;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [intervalMs, refresh]);

  return refresh;
}
