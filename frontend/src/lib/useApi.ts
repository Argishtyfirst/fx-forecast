import { useCallback, useEffect, useRef, useState } from "react";
import { clearApiCache } from "../api/client";

export interface ApiState<T> {
  data: T | undefined;
  error: Error | undefined;
  loading: boolean;
  /** True while refetching the same key: keep the previous render, dimmed. */
  refreshing: boolean;
  reload: () => void;
}

/**
 * Loads data for `key`. Data from a different key is dropped (no EUR/USD numbers under a
 * USD/AMD heading); data for the same key stays visible while it reloads.
 */
export function useApi<T>(key: string | null, load: () => Promise<T>): ApiState<T> {
  const [state, setState] = useState<{ key: string | null; data?: T; error?: Error; loading: boolean }>(
    { key: null, loading: key !== null },
  );
  const [nonce, setNonce] = useState(0);
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    if (key === null) return;
    let alive = true;
    setState((s) => (s.key === key ? { ...s, loading: true, error: undefined } : { key, loading: true }));
    loadRef.current().then(
      (data) => alive && setState({ key, data, loading: false }),
      (error: Error) => alive && setState((s) => ({ key, data: s.key === key ? s.data : undefined, error, loading: false })),
    );
    return () => {
      alive = false;
    };
  }, [key, nonce]);

  const reload = useCallback(() => {
    clearApiCache();
    setNonce((n) => n + 1);
  }, []);

  const sameKey = state.key === key;
  return {
    data: sameKey ? state.data : undefined,
    error: sameKey ? state.error : undefined,
    loading: !sameKey || state.loading,
    refreshing: sameKey && state.loading && state.data !== undefined,
    reload,
  };
}
