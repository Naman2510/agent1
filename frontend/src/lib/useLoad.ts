"use client";

import { useCallback, useEffect, useState } from "react";

interface Settled<T> {
  load?: () => Promise<T>;
  attempt?: number;
  data?: T;
  error?: unknown;
  at?: number;
}

/**
 * Run `load` (which must be stable — wrap it in useCallback) and track its result. The previous
 * data stays visible while a new load is in flight, so paging does not flash an empty list.
 */
export function useLoad<T>(load: () => Promise<T>) {
  const [attempt, setAttempt] = useState(0);
  const [settled, setSettled] = useState<Settled<T>>({});

  useEffect(() => {
    let active = true;
    load().then(
      (data) => {
        if (active) setSettled({ load, attempt, data, at: Date.now() });
      },
      (error: unknown) => {
        if (active) {
          setSettled((previous) => ({ load, attempt, data: previous.data, error, at: previous.at }));
        }
      },
    );
    return () => {
      active = false;
    };
  }, [load, attempt]);

  const loading = settled.load !== load || settled.attempt !== attempt;
  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  return {
    data: settled.data,
    error: loading ? undefined : settled.error,
    loading,
    reload,
    updatedAt: settled.at,
  };
}
