"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import type { JobResponse, JobStatus } from "./types";
import { getJob } from "./api";

async function getJobWithRetry(jobId: string, maxAttempts = 5): Promise<JobResponse> {
  let last: Error = new Error("Job fetch failed");
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    try {
      return await getJob(jobId);
    } catch (e) {
      last = e instanceof Error ? e : new Error(String(e));
      if (attempt < maxAttempts - 1) {
        await new Promise((r) => setTimeout(r, 600 * (attempt + 1)));
      }
    }
  }
  throw last;
}

// ─── Upload ID context ──────────────────────────────────────────────────────

interface UploadState {
  uploadId: string | null;
  jobId: string | null;
  slug: string | null;
  edaDone: boolean;
  setUpload: (uploadId: string, jobId: string, slug: string) => void;
  setEdaDone: () => void;
  clear: () => void;
}

const LS_KEY = "datalens_upload";

function readLocalStorage(): Partial<UploadState> {
  try {
    const raw = localStorage.getItem(LS_KEY);
    return raw ? (JSON.parse(raw) as Partial<UploadState>) : {};
  } catch {
    return {};
  }
}

export const UploadContext = createContext<UploadState>({
  uploadId: null,
  jobId: null,
  slug: null,
  edaDone: false,
  setUpload: () => {},
  setEdaDone: () => {},
  clear: () => {},
});

export function useUploadId(): UploadState {
  return useContext(UploadContext);
}

export function useUploadState(): UploadState {
  const saved = readLocalStorage();
  const [uploadId, setUploadId] = useState<string | null>(
    saved.uploadId ?? null
  );
  const [jobId, setJobId] = useState<string | null>(saved.jobId ?? null);
  const [slug, setSlug] = useState<string | null>(saved.slug ?? null);
  const [edaDone, setEdaDoneState] = useState<boolean>(
    saved.edaDone ?? false
  );

  const persist = useCallback(
    (u: string, j: string, s: string, done: boolean) => {
      try {
        localStorage.setItem(LS_KEY, JSON.stringify({ uploadId: u, jobId: j, slug: s, edaDone: done }));
      } catch {}
    },
    []
  );

  const setUpload = useCallback(
    (u: string, j: string, s: string) => {
      setUploadId(u);
      setJobId(j);
      setSlug(s);
      setEdaDoneState(false);
      persist(u, j, s, false);
    },
    [persist]
  );

  const setEdaDone = useCallback(() => {
    setEdaDoneState(true);
    if (uploadId && jobId && slug) persist(uploadId, jobId, slug, true);
  }, [uploadId, jobId, slug, persist]);

  const clear = useCallback(() => {
    setUploadId(null);
    setJobId(null);
    setSlug(null);
    setEdaDoneState(false);
    try { localStorage.removeItem(LS_KEY); } catch {}
  }, []);

  return { uploadId, jobId, slug, edaDone, setUpload, setEdaDone, clear };
}

// ─── Polling hook ────────────────────────────────────────────────────────────

interface PollingState {
  status: JobStatus | null;
  result: JobResponse["result"];
  error: string | null;
}

export function usePolling(
  jobId: string | null,
  intervalMs = 2000,
  maxDurationMs = 360_000  // 6 min — matches backend AGENT_TIMEOUT_SEC + buffer
): PollingState {
  const [state, setState] = useState<PollingState>({
    status: null,
    result: null,
    error: null,
  });
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const startedAtRef = useRef<number | null>(null);

  const stop = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!jobId) {
      // No job to poll (e.g. after a reset) — clear any stale status/error.
      setState({ status: null, result: null, error: null });
      return;
    }

    let cancelled = false;
    startedAtRef.current = Date.now();

    const poll = async () => {
      // Hard stop: treat as error if we've been polling longer than maxDurationMs
      if (startedAtRef.current && Date.now() - startedAtRef.current > maxDurationMs) {
        setState((prev) => ({
          ...prev,
          status: "error",
          error: "Analysis timed out. Please try again.",
        }));
        stop();
        return;
      }

      try {
        const job = await getJobWithRetry(jobId);
        if (cancelled) return;
        setState({ status: job.status, result: job.result, error: job.error });
        if (job.status === "done" || job.status === "error") {
          stop();
          return;
        }
      } catch (e) {
        if (cancelled) return;
        setState((prev) => ({
          ...prev,
          error: e instanceof Error ? e.message : "Polling failed",
        }));
        stop();
        return;
      }
      timerRef.current = setTimeout(poll, intervalMs);
    };

    poll();

    return () => {
      cancelled = true;
      stop();
    };
  }, [jobId, intervalMs, maxDurationMs, stop]);

  return state;
}
