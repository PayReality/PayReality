import { useEffect, useState } from "react";
import { ApiError } from "./apiClient";

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    const detail =
      err.body && typeof err.body === "object" && "detail" in err.body ? (err.body as { detail?: unknown }).detail : null;
    return typeof detail === "string" ? detail.replaceAll("_", " ") : `Request failed (${err.status})`;
  }
  if (err instanceof Error) return err.message;
  return "Something went wrong.";
}

/**
 * Re-fetches `loader()` whenever any value in `deps` changes. Guards
 * against out-of-order responses with a per-call epoch, the same
 * discipline the real QuestionDetailPage fix (recovered from this
 * branch's own git history) used for exactly this race.
 */
export function useFetch<T>(loader: () => Promise<T>, deps: unknown[]): {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
} {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [epoch, setEpoch] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    loader()
      .then((result) => {
        if (cancelled) return;
        setData(result);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(errorMessage(err));
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, epoch]);

  return { data, loading, error, reload: () => setEpoch((e) => e + 1) };
}
