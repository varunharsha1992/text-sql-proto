# Feature 002 Phase 1 — Multi-file → Visible Global Schema (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every uploaded CSV a table in one global schema: upload multiple files, list all tables with per-table analysis status, and browse each table's AutoEDA canvas.

**Architecture:** The backend already analyzes each upload independently (one `uploads` row + `raw_{upload_id}` + one job per CSV). This phase adds a single read endpoint (`GET /api/uploads`) listing every table with its job status, and rewires the upload screen to upload multiple files and render a table list whose selection drives the existing `Canvas`. No change to the per-table AutoEDA pipeline.

**Tech Stack:** FastAPI + aiosqlite (backend); Next.js 14 / TypeScript / React (frontend). Reuses feature-001's `usePolling`, `Canvas`, `uploadFile`, `getJob`.

## Global Constraints

- Endpoints: this phase adds exactly ONE new endpoint, `GET /api/uploads`. Do not add others. Existing `POST /api/upload` and `GET /api/jobs/{job_id}` are unchanged.
- Backend imports package-qualified (`from backend.x import y`); run Python with `PYTHONPATH=.` from repo root `C:/Dev/text-sql-proto/text-sql-proto`.
- No `Any` in Pydantic models / no `any` in TypeScript.
- Verification (this repo has NO pytest/jest harness — do NOT scaffold one): backend = `python -m py_compile` + an inline assertion snippet run under `PYTHONPATH=.` against a temp DB; frontend = `npx tsc --noEmit` from `frontend/`. Pipe NumPy import warnings with `2>/dev/null`.
- The active database is `./data/app.db` (DATABASE_URL=`sqlite+aiosqlite:///./data/app.db`).
- Frontend design tokens: reuse `--accent`, `--accent3`, `--danger`, `--info`, `--bg2/3/4`, `--text/2/3`, `--border` (match existing `Canvas.tsx`).

---

## File Structure

- `backend/database.py` (modify) — add `list_uploads()`.
- `backend/models.py` (modify) — add `UploadSummary`, `UploadsListResponse`.
- `backend/main.py` (modify) — add `GET /api/uploads`.
- `frontend/lib/types.ts` (modify) — add `UploadSummary`, `UploadsListResponse`.
- `frontend/lib/api.ts` (modify) — add `listUploads()`.
- `frontend/lib/hooks.ts` (modify) — add `useUploads()` polling hook.
- `frontend/components/TableList.tsx` (new) — the table list with status badges.
- `frontend/app/upload/page.tsx` (modify) — multi-file upload + table list + selected-table canvas + Continue gating.

---

## Task 1: Backend — list uploads endpoint

**Files:**
- Modify: `backend/database.py`
- Modify: `backend/models.py`
- Modify: `backend/main.py`

**Interfaces:**
- Produces: `database.list_uploads() -> list[dict]` (keys: `id, slug, filename, row_count, col_count, job_id, status`); models `UploadSummary`, `UploadsListResponse`; route `GET /api/uploads`.

- [ ] **Step 1: Add `list_uploads()` to `database.py`**

Append after `get_job` in `backend/database.py`:

```python
async def list_uploads() -> list[dict]:
    """Every uploaded table with its latest job id + status. Newest first."""
    db = await get_db()
    try:
        async with db.execute(
            """
            SELECT
                u.id        AS id,
                u.slug      AS slug,
                u.filename  AS filename,
                u.row_count AS row_count,
                u.col_count AS col_count,
                (SELECT job_id FROM jobs WHERE upload_id = u.id
                 ORDER BY created_at DESC LIMIT 1) AS job_id,
                (SELECT status FROM jobs WHERE upload_id = u.id
                 ORDER BY created_at DESC LIMIT 1) AS status
            FROM uploads u
            ORDER BY u.uploaded_at DESC
            """
        ) as cursor:
            rows = await cursor.fetchall()
        return [{key: row[key] for key in row.keys()} for row in rows]
    finally:
        await db.close()
```

- [ ] **Step 2: Add the models to `models.py`**

In `backend/models.py`, after `UploadResponse`, insert:

```python
class UploadSummary(BaseModel):
    upload_id: str
    slug: str
    filename: str
    row_count: int | None = None
    col_count: int | None = None
    job_id: str | None = None
    status: Literal["pending", "running", "done", "error"] | None = None


class UploadsListResponse(BaseModel):
    uploads: list[UploadSummary]
```

- [ ] **Step 3: Add the route + import to `main.py`**

In `backend/main.py`, add `list_uploads` to the `backend.database` import group:

```python
from backend.database import (
    create_job,
    create_tables,
    create_upload,
    get_db,
    get_job,
    list_uploads,
    update_job,
)
```

Add `UploadSummary, UploadsListResponse` to the `backend.models` import:

```python
from backend.models import (
    CanvasResponse,
    JobResponse,
    UploadResponse,
    UploadSummary,
    UploadsListResponse,
)
```

Then add the route after `get_job_status`:

```python
def _opt_status(value: object) -> Literal["pending", "running", "done", "error"] | None:
    if value in ("pending", "running", "done", "error"):
        return value  # type: ignore[return-value]
    return None


@app.get("/api/uploads", response_model=UploadsListResponse)
async def list_uploads_route() -> UploadsListResponse:
    rows = await list_uploads()
    uploads = [
        UploadSummary(
            upload_id=_require_str(r["id"], "id"),
            slug=_require_str(r["slug"], "slug"),
            filename=_require_str(r["filename"], "filename"),
            row_count=r["row_count"] if isinstance(r["row_count"], int) else None,
            col_count=r["col_count"] if isinstance(r["col_count"], int) else None,
            job_id=r["job_id"] if isinstance(r["job_id"], str) else None,
            status=_opt_status(r["status"]),
        )
        for r in rows
    ]
    return UploadsListResponse(uploads=uploads)
```

- [ ] **Step 4: Verify compile + behavior**

Run:

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && python -m py_compile backend/database.py backend/models.py backend/main.py && PYTHONPATH=. python -c "
import asyncio, tempfile, os
d=tempfile.mkdtemp(); os.environ['DATABASE_URL']=f'sqlite+aiosqlite:///{d}/t.db'
from backend.database import get_db, create_tables, create_upload, create_job, update_job, list_uploads
async def main():
    db=await get_db(); await create_tables(db); await db.close()
    await create_upload('u1','orders.csv','orders','/p1'); await create_job('j1','autoeda','u1'); await update_job('j1','done')
    await create_upload('u2','customers.csv','customers','/p2'); await create_job('j2','autoeda','u2')
    rows=await list_uploads()
    print('count:', len(rows))
    print('newest slug:', rows[0]['slug'])
    by={r['id']:r for r in rows}
    print('u1 status:', by['u1']['status'], '| u2 status:', by['u2']['status'])
    print('u1 job_id:', by['u1']['job_id'])
asyncio.run(main())
" 2>/dev/null
```

Expected: `count: 2`, `newest slug: customers`, `u1 status: done | u2 status: pending`, `u1 job_id: j1`.

- [ ] **Step 5: Commit**

```bash
git add backend/database.py backend/models.py backend/main.py
git commit -m "feat(schema): GET /api/uploads lists all tables with job status"
```

---

## Task 2: Frontend — list types, API wrapper, and polling hook

**Files:**
- Modify: `frontend/lib/types.ts`
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/lib/hooks.ts`

**Interfaces:**
- Consumes: `apiPath` (already in `api.ts`), `JobStatus` (already in `types.ts`).
- Produces: TS `UploadSummary`, `UploadsListResponse`; `listUploads(): Promise<UploadsListResponse>`; `useUploads(intervalMs?): { uploads: UploadSummary[]; loading: boolean; refetch: () => void }`.

- [ ] **Step 1: Add the types**

In `frontend/lib/types.ts`, after `UploadResponse`, insert:

```typescript
export interface UploadSummary {
  upload_id: string;
  slug: string;
  filename: string;
  row_count?: number | null;
  col_count?: number | null;
  job_id?: string | null;
  status?: JobStatus | null;
}

export interface UploadsListResponse {
  uploads: UploadSummary[];
}
```

(`JobStatus` is declared later in the file; TypeScript hoists type declarations, so order does not matter.)

- [ ] **Step 2: Add the API wrapper**

In `frontend/lib/api.ts`, after `getJob`, insert:

```typescript
export async function listUploads(): Promise<UploadsListResponse> {
  const res = await fetch(apiPath("/uploads"));
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to list uploads");
  }
  return res.json() as Promise<UploadsListResponse>;
}
```

And update the import at the top of `api.ts`:

```typescript
import type { JobResponse, UploadResponse, UploadsListResponse } from "./types";
```

- [ ] **Step 3: Add the `useUploads` hook**

In `frontend/lib/hooks.ts`, update the type import to include the new types:

```typescript
import type { JobResponse, JobStatus, UploadSummary } from "./types";
import { getJob, listUploads } from "./api";
```

Then append at the end of the file:

```typescript
// ─── Uploads list (the global schema's tables) ───────────────────────────────

export function useUploads(intervalMs = 2000): {
  uploads: UploadSummary[];
  loading: boolean;
  refetch: () => void;
} {
  const [uploads, setUploads] = useState<UploadSummary[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [tick, setTick] = useState(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refetch = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        const res = await listUploads();
        if (cancelled) return;
        setUploads(res.uploads);
        setLoading(false);
        const anyInFlight = res.uploads.some(
          (u) => u.status === "pending" || u.status === "running"
        );
        if (anyInFlight) {
          timerRef.current = setTimeout(poll, intervalMs);
        }
      } catch {
        if (cancelled) return;
        setLoading(false);
      }
    };

    poll();
    return () => {
      cancelled = true;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [intervalMs, tick]);

  return { uploads, loading, refetch };
}
```

(`useState`, `useEffect`, `useRef`, `useCallback` are already imported at the top of `hooks.ts`.)

- [ ] **Step 4: Verify typecheck**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto/frontend" && npx tsc --noEmit && echo TSC_OK
```

Expected: `TSC_OK`.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/types.ts frontend/lib/api.ts frontend/lib/hooks.ts
git commit -m "feat(schema): frontend uploads-list types, api wrapper, useUploads hook"
```

---

## Task 3: TableList component

**Files:**
- Create: `frontend/components/TableList.tsx`

**Interfaces:**
- Consumes: `UploadSummary` from `@/lib/types`.
- Produces: default `TableList({ uploads, selectedId, onSelect })` where `selectedId: string | null`, `onSelect: (uploadId: string) => void`.

- [ ] **Step 1: Create the component**

Create `frontend/components/TableList.tsx`:

```tsx
import type { UploadSummary, JobStatus } from "@/lib/types";

const STATUS_COLOR: Record<JobStatus, string> = {
  pending: "var(--text3)",
  running: "var(--info, #63B3ED)",
  done: "var(--accent)",
  error: "var(--danger)",
};

const STATUS_LABEL: Record<JobStatus, string> = {
  pending: "Queued",
  running: "Analysing",
  done: "Ready",
  error: "Error",
};

export default function TableList({
  uploads,
  selectedId,
  onSelect,
}: {
  uploads: UploadSummary[];
  selectedId: string | null;
  onSelect: (uploadId: string) => void;
}) {
  if (uploads.length === 0) return null;
  return (
    <div className="space-y-1.5">
      <div
        className="text-[10px] uppercase tracking-widest font-medium"
        style={{ color: "var(--text3)" }}
      >
        Tables in schema ({uploads.length})
      </div>
      <ul className="space-y-1">
        {uploads.map((u) => {
          const status = (u.status ?? "pending") as JobStatus;
          const selected = u.upload_id === selectedId;
          return (
            <li key={u.upload_id}>
              <button
                onClick={() => onSelect(u.upload_id)}
                className="w-full text-left rounded-lg px-3 py-2 transition-colors"
                style={{
                  background: selected ? "var(--bg4)" : "var(--bg3)",
                  border: `1px solid ${selected ? "var(--accent)" : "var(--border)"}`,
                }}
              >
                <div className="flex items-center justify-between gap-2">
                  <span
                    className="text-[12px] truncate"
                    style={{ fontFamily: "'DM Mono', monospace", color: "var(--text)" }}
                  >
                    {u.slug}
                  </span>
                  <span
                    className="text-[10px] shrink-0 px-1.5 py-0.5 rounded-full"
                    style={{ color: STATUS_COLOR[status] }}
                  >
                    {STATUS_LABEL[status]}
                  </span>
                </div>
                <div className="text-[10px] mt-0.5" style={{ color: "var(--text3)" }}>
                  {u.row_count != null ? `${u.row_count.toLocaleString()} rows` : "— rows"}
                  {"  ·  "}
                  {u.col_count != null ? `${u.col_count} cols` : "— cols"}
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
```

- [ ] **Step 2: Verify typecheck**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto/frontend" && npx tsc --noEmit && echo TSC_OK
```

Expected: `TSC_OK`.

- [ ] **Step 3: Commit**

```bash
git add frontend/components/TableList.tsx
git commit -m "feat(schema): TableList component with per-table status"
```

---

## Task 4: Upload page — multi-file upload + table list + selected-table canvas

**Files:**
- Modify: `frontend/app/upload/page.tsx`

**Interfaces:**
- Consumes: `uploadFile` (api), `useUploads` + `useUploadId` + `usePolling` (hooks), `TableList`, `Canvas`.

- [ ] **Step 1: Rewrite `upload/page.tsx`**

Replace the entire contents of `frontend/app/upload/page.tsx` with:

```tsx
"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { uploadFile } from "@/lib/api";
import { useUploadId, useUploads, usePolling } from "@/lib/hooks";
import Canvas from "@/components/Canvas";
import TableList from "@/components/TableList";

function formatBytes(bytes: number): string {
  if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`;
  if (bytes >= 1_024) return `${(bytes / 1_024).toFixed(0)} KB`;
  return `${bytes} B`;
}

export default function UploadPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { uploads, loading, refetch } = useUploads();
  const { setEdaDone } = useUploadId();
  const router = useRouter();

  // Default the selected table to the first ready (or first) table.
  useEffect(() => {
    if (selectedId && uploads.some((u) => u.upload_id === selectedId)) return;
    const firstDone = uploads.find((u) => u.status === "done");
    const pick = firstDone ?? uploads[0];
    if (pick) setSelectedId(pick.upload_id);
  }, [uploads, selectedId]);

  const anyDone = uploads.some((u) => u.status === "done");
  useEffect(() => {
    if (anyDone) setEdaDone();
  }, [anyDone, setEdaDone]);

  const selected = useMemo(
    () => uploads.find((u) => u.upload_id === selectedId) ?? null,
    [uploads, selectedId]
  );
  const { status, result } = usePolling(selected?.job_id ?? null);

  const handleFiles = useCallback(
    async (files: FileList) => {
      setUploadError(null);
      setIsUploading(true);
      try {
        for (const f of Array.from(files)) {
          await uploadFile(f);
        }
        refetch();
      } catch (e) {
        setUploadError(e instanceof Error ? e.message : "Upload failed");
      } finally {
        setIsUploading(false);
      }
    },
    [refetch]
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      if (e.dataTransfer.files?.length) handleFiles(e.dataTransfer.files);
    },
    [handleFiles]
  );

  const onFileInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files?.length) handleFiles(e.target.files);
    },
    [handleFiles]
  );

  const canContinue = anyDone;

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: "var(--bg)" }}>
      {/* Left panel */}
      <aside
        className="flex flex-col w-[360px] shrink-0 overflow-y-auto"
        style={{ background: "var(--bg2)", borderRight: "1px solid var(--border)" }}
      >
        <div className="p-4">
          <div
            role="button"
            tabIndex={0}
            className="flex flex-col items-center justify-center gap-2 rounded-xl p-8 cursor-pointer transition-colors duration-150 select-none"
            style={{
              border: `1.5px dashed ${isDragging ? "var(--accent)" : "var(--border2)"}`,
              background: isDragging ? "rgba(110,231,183,0.04)" : "transparent",
            }}
            onClick={() => fileInputRef.current?.click()}
            onKeyDown={(e) => e.key === "Enter" && fileInputRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setIsDragging(true);
            }}
            onDragLeave={(e) => {
              e.preventDefault();
              setIsDragging(false);
            }}
            onDrop={onDrop}
          >
            <span className="text-3xl">📊</span>
            <p className="font-medium" style={{ color: "var(--text)" }}>
              Drop CSV files here
            </p>
            <p className="text-[12px]" style={{ color: "var(--text3)" }}>
              one or more · max 50MB each
            </p>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv"
            multiple
            className="hidden"
            onChange={onFileInputChange}
          />
          {isUploading && (
            <p className="text-[12px] mt-2" style={{ color: "var(--text2)" }}>
              Uploading…
            </p>
          )}
          {uploadError && (
            <p className="text-[12px] mt-2" style={{ color: "var(--danger)" }}>
              {uploadError}
            </p>
          )}
        </div>

        <div className="mx-4 mb-4 flex-1">
          {loading && uploads.length === 0 ? (
            <p className="text-[12px]" style={{ color: "var(--text3)" }}>
              Loading tables…
            </p>
          ) : (
            <TableList
              uploads={uploads}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          )}
        </div>

        <div className="p-4 mt-auto">
          <button
            disabled={!canContinue}
            onClick={() => canContinue && router.push("/context")}
            className="w-full rounded-lg py-2.5 text-[13px] font-medium transition-opacity"
            style={{
              background: "var(--accent)",
              color: "#000",
              opacity: canContinue ? 1 : 0.5,
              cursor: canContinue ? "pointer" : "not-allowed",
            }}
          >
            Continue to Context →
          </button>
        </div>
      </aside>

      {/* Right panel — selected table's canvas */}
      <main className="flex-1 flex flex-col overflow-hidden p-5">
        {selected ? (
          <Canvas result={result} status={status} />
        ) : (
          <div
            className="flex-1 flex items-center justify-center text-[12px]"
            style={{ color: "var(--text3)" }}
          >
            Upload a CSV to begin.
          </div>
        )}
      </main>
    </div>
  );
}
```

(Note: `formatBytes` is retained for potential reuse; if your linter rejects the unused helper, delete it. The selected-table file size is no longer shown since the list is server-driven.)

- [ ] **Step 2: Verify typecheck**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto/frontend" && npx tsc --noEmit && echo TSC_OK
```

Expected: `TSC_OK`. If `formatBytes` triggers an unused-variable error, remove the function and re-run.

- [ ] **Step 3: Commit**

```bash
git add frontend/app/upload/page.tsx
git commit -m "feat(schema): multi-file upload + table list + per-table canvas"
```

---

## Task 5: Manual smoke test

**Files:** none (verification).

- [ ] **Step 1: Start backend + frontend**

```bash
# terminal 1
cd "C:/Dev/text-sql-proto/text-sql-proto" && PYTHONPATH=. python -m uvicorn backend.main:app --reload --port 8000
# terminal 2
cd "C:/Dev/text-sql-proto/text-sql-proto/frontend" && npm run dev
```

- [ ] **Step 2: Verify in the browser**

Open `http://localhost:3000`. Confirm:
- Dropping **two** CSVs at once adds two entries to the table list (each shows "Analysing" → "Ready").
- Each table shows row/col counts once analysed.
- Selecting a table renders that table's AutoEDA canvas on the right (stats/charts/dictionary/semantic layer).
- "Continue to Context →" enables once at least one table is "Ready".
- Reloading the page still shows all tables (list is server-driven, not localStorage).

---

## Self-Review

**Spec coverage (Phase 1 of the design):**
- Every CSV is a table in the global schema, browseable → Tasks 1–4. ✓
- `GET /api/uploads` returns all tables + per-table status → Task 1. ✓
- Multi-file upload → Task 4 (`multiple` input + loop). ✓
- Upload screen shows all tables, not just the latest → Tasks 3, 4 (`useUploads` is server-driven). ✓
- Per-table AutoEDA unchanged → no pipeline edits in any task. ✓
- Continue enables when ≥1 table done → Task 4 (`anyDone`). ✓
- Only one new endpoint → Task 1. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; verification commands have expected output. ✓

**Type consistency:** `list_uploads()` dict keys (`id, slug, filename, row_count, col_count, job_id, status`) match the route's `UploadSummary` construction (Task 1). TS `UploadSummary`/`UploadsListResponse` fields match the Pydantic models (Task 2). `useUploads()` return shape (`uploads, loading, refetch`) matches its use in Task 4. `TableList` props (`uploads, selectedId, onSelect`) match Task 4's usage. ✓
