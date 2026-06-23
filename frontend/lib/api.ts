import type {
  JobResponse,
  UploadResponse,
  UploadsListResponse,
  SchemaResponse,
  ContextChatResponse,
  QueryChatResponse,
  QueryHistoryResponse,
} from "./types";

/** Same-origin `/api` (Next rewrites) unless NEXT_PUBLIC_API_URL is set to bypass the dev proxy (e.g. http://127.0.0.1:8000). */
function apiPath(path: string): string {
  const origin = process.env.NEXT_PUBLIC_API_URL?.trim().replace(/\/$/, "");
  if (origin) {
    const p = path.startsWith("/") ? path : `/${path}`;
    return `${origin}/api${p}`;
  }
  const p = path.startsWith("/") ? path : `/${path}`;
  return `/api${p}`;
}

export async function uploadFile(file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);

  const res = await fetch(apiPath("/upload"), {
    method: "POST",
    body: form,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Upload failed");
  }

  return res.json() as Promise<UploadResponse>;
}

export async function getJob(jobId: string): Promise<JobResponse> {
  const res = await fetch(apiPath(`/jobs/${jobId}`));

  if (!res.ok) {
    if (res.status === 404) throw new Error("Job not found");
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to fetch job");
  }

  return res.json() as Promise<JobResponse>;
}

export async function listUploads(): Promise<UploadsListResponse> {
  const res = await fetch(apiPath("/uploads"));
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to list uploads");
  }
  return res.json() as Promise<UploadsListResponse>;
}

export async function getSchema(): Promise<SchemaResponse> {
  const res = await fetch(apiPath("/context/schema"));
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to load schema");
  }
  return res.json() as Promise<SchemaResponse>;
}

export async function postContextChat(message: string): Promise<ContextChatResponse> {
  const res = await fetch(apiPath("/context/chat"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Chat failed");
  }
  return res.json() as Promise<ContextChatResponse>;
}

export async function postContextComplete(): Promise<{ ok: boolean }> {
  const res = await fetch(apiPath("/context/complete"), { method: "POST" });
  if (!res.ok) throw new Error("Failed to mark complete");
  return res.json() as Promise<{ ok: boolean }>;
}

export async function postQueryChat(message: string): Promise<QueryChatResponse> {
  const res = await fetch(apiPath("/query/chat"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Query failed");
  }
  return res.json() as Promise<QueryChatResponse>;
}

export async function getQueryHistory(): Promise<QueryHistoryResponse> {
  const res = await fetch(apiPath("/query/history"));
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to load query history");
  }
  return res.json() as Promise<QueryHistoryResponse>;
}
