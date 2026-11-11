"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "./api";

type ResourceState<T> = { data: T | undefined; error: ApiError | Error | undefined; loading: boolean };

export function useResource<T>(fetcher: () => Promise<T>, key: string | null) {
  const [state, setState] = useState<ResourceState<T>>({ data: undefined, error: undefined, loading: key !== null });
  const [version, setVersion] = useState(0);
  const fetcherRef = useRef(fetcher);

  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  useEffect(() => {
    if (key === null) return;
    let active = true;
    fetcherRef.current().then(
      (data) => active && setState({ data, error: undefined, loading: false }),
      (error: Error) => active && setState((current) => ({ ...current, error, loading: false })),
    );
    return () => {
      active = false;
    };
  }, [key, version]);

  const reload = useCallback(() => setVersion((value) => value + 1), []);
  const mutate = useCallback((data: T) => setState({ data, error: undefined, loading: false }), []);
  return { ...state, reload, mutate };
}

export function useInterval(callback: () => void, delay: number | null) {
  const saved = useRef(callback);
  useEffect(() => {
    saved.current = callback;
  });
  useEffect(() => {
    if (delay === null) return;
    const id = setInterval(() => saved.current(), delay);
    return () => clearInterval(id);
  }, [delay]);
}

export function useAction() {
  const [busy, setBusy] = useState<string | null>(null);
  const run = useCallback(async <T,>(name: string, action: () => Promise<T>): Promise<T | undefined> => {
    setBusy(name);
    try {
      return await action();
    } finally {
      setBusy(null);
    }
  }, []);
  return { busy, run };
}
