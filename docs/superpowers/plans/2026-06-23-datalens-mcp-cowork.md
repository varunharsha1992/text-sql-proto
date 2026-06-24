# DataLens MCP Cowork — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a standalone FastMCP Streamable HTTP server (`datalens_mcp`) with three tools (`analyze_csv`, `context_chat`, `query_chat`) that proxy to the existing FastAPI backend, plus incremental `sync_connected_schema` so each new CSV merges into the global catalog and semantic layer.

**Architecture:** Thin HTTP proxy on `:8010` → FastAPI on `:8000`. MCP handles upload multipart, job polling with `ctx.report_progress`, and schema sync after AutoEDA. Backend adds `POST /api/schema/sync` and refactors `ensure_schema_seed` to delegate to shared sync logic.

**Tech Stack:** FastMCP (Streamable HTTP), httpx (async), FastAPI, aiosqlite, existing agent stack unchanged.

**Spec:** `docs/superpowers/specs/2026-06-23-datalens-mcp-cowork-design.md`

---

## Global Constraints

- Run Python from repo root `C:/Dev/text-sql-proto/text-sql-proto` with `PYTHONPATH=.`.
- Backend imports are package-qualified (`backend.*`).
- Do NOT modify frontend in this feature.
- MCP package name: **`datalens_mcp`** (not `mcp` — avoids clash with MCP SDK).
- FastAPI must be running before MCP tools call it (`DATALENS_API_URL`, default `http://127.0.0.1:8000`).
- Single uvicorn on `:8000` (no `--reload` during smoke — stale listeners cause 404s).
- Verification: inline `PYTHONPATH=.` snippets + `python -m py_compile`; live agent smoke needs `OPENROUTER_API_KEY` in `.env`.
- No auth on MCP in v1; bind `127.0.0.1:8010`.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/models.py` | modify | Add `SchemaSyncResponse` |
| `backend/schema_synth.py` | modify | `sync_connected_schema()`; refactor `ensure_schema_seed` |
| `backend/main.py` | modify | `POST /api/schema/sync` |
| `datalens_mcp/__init__.py` | new | Package marker |
| `datalens_mcp/config.py` | new | Env var defaults |
| `datalens_mcp/client.py` | new | httpx async wrapper for FastAPI |
| `datalens_mcp/progress.py` | new | Job poll loop + MCP progress |
| `datalens_mcp/server.py` | new | FastMCP app + three tools |
| `datalens_mcp/__main__.py` | new | `python -m datalens_mcp` entrypoint |
| `datalens_mcp/requirements.txt` | new | `fastmcp`, `httpx` |

---

## Execution Waves

| Wave | Tasks | Notes |
|------|-------|-------|
| 1 | T1 | Pydantic model |
| 2 | T2 | Schema sync core (backend) |
| 3 | T3 | API route (depends T1, T2) |
| 4 | T4 ‖ T5 | MCP scaffold + client ‖ progress helper (disjoint files) |
| 5 | T6 | `analyze_csv` tool (depends T3, T4, T5) |
| 6 | T7 | `context_chat` + `query_chat` (depends T4) |
| 7 | T8 | Entrypoint + requirements |
| 8 | T9 | Live smoke |

## Task Dependency Graph

```
T1 → T3
T2 → T3
T3 → T6
T4 → T5, T6, T7
T5 → T6
T6 → T9
T7 → T9
T8 → T9
```

## Subagent Dispatch Map

| Task | subagent_type | Rationale |
|------|---------------|-----------|
| T1 | python-pro | Pydantic model |
| T2 | python-pro | Schema merge logic |
| T3 | fastapi-developer | Route wiring |
| T4 | python-pro | httpx client |
| T5 | python-pro | Poll + progress |
| T6 | python-pro | analyze_csv tool |
| T7 | python-pro | context + query tools |
| T8 | platform-engineer | Entrypoint / deps |
| T9 | generalPurpose | E2E smoke |

---

## Task 1: `SchemaSyncResponse` model

**Files:**
- Modify: `backend/models.py` (after `SchemaResponse`, ~line 203)

- [ ] **Step 1: Add model**

Insert after `SchemaResponse`:

```python
class SchemaSyncResponse(BaseModel):
    catalog: list[CatalogRow]
    semantic_layer: SchemaSemanticLayer | None = None
    tables_synced: list[str]
```

- [ ] **Step 2: Verify**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && PYTHONPATH=. python -c "
from backend.models import SchemaSyncResponse, CatalogRow, SchemaSemanticLayer
r = SchemaSyncResponse(catalog=[], semantic_layer=None, tables_synced=['a'])
print('ok', r.tables_synced)
"
```

Expected: `ok ['a']`

- [ ] **Step 3: Commit**

```bash
git add backend/models.py
git commit -m "feat(mcp): add SchemaSyncResponse model"
```

---

## Task 2: `sync_connected_schema()` + refactor `ensure_schema_seed`

**Files:**
- Modify: `backend/schema_synth.py`

**Catalog merge rules (locked):**
- Profiler fields (`data_type`, `semantic_role`, `description`, `sample_values`, `is_pii`, `unit`, `null_pct`) — always upserted from `data_dictionary`.
- Interview fields (`business_context`, `is_primary_key`, `is_foreign_key`, `foreign_key_ref`) — upsert **only if** the existing catalog row lacks that field (None / empty / False for booleans except PK/FK where False means unset only when never interviewed — treat `is_primary_key=True` or `is_foreign_key=True` or non-empty `business_context` / `foreign_key_ref` as user-set and preserve).

**Relationship merge:** Dedupe key `(from_table, from_column, to_table, to_column)`. Start from existing layer relationships; append new candidates from `detect_relationships()` not already present.

**Tables/measures/dimensions:** Rebuild from **all** uploads with latest job `status=done` and non-empty `data_dictionary`. Preserve existing `SchemaTable.description` when non-empty for matching slug.

- [ ] **Step 1: Add helpers at top of `schema_synth.py` (after `_SEMANTIC_ROLE`)**

```python
def _rel_key(rel: dict) -> tuple[str, str, str, str]:
    return (
        rel.get("from_table", ""),
        rel.get("from_column", ""),
        rel.get("to_table", ""),
        rel.get("to_column", ""),
    )


def _catalog_key(row: dict) -> tuple[str, str]:
    return (row["upload_id"], row["column_name"])


def _user_catalog_fields_set(row: dict) -> bool:
    if row.get("business_context"):
        return True
    if row.get("foreign_key_ref"):
        return True
    if row.get("is_primary_key"):
        return True
    if row.get("is_foreign_key"):
        return True
    return False


def _merge_relationships(existing: list[dict], detected: list[dict]) -> list[dict]:
    seen = {_rel_key(r) for r in existing}
    merged = list(existing)
    for rel in detected:
        key = _rel_key(rel)
        if key not in seen:
            merged.append(rel)
            seen.add(key)
    return merged
```

- [ ] **Step 2: Add `_profiler_catalog_updates(entry: dict) -> dict`**

```python
def _profiler_catalog_updates(entry: dict) -> dict:
    return {
        "data_type": entry.get("dtype"),
        "semantic_role": _SEMANTIC_ROLE.get(entry.get("semantic_type", ""), "dimension"),
        "description": entry.get("description"),
        "sample_values": entry.get("sample_values") or [],
        "is_pii": bool(entry.get("is_pii", False)),
        "unit": entry.get("unit"),
        "null_pct": entry.get("null_pct"),
    }
```

- [ ] **Step 3: Add `sync_connected_schema()`**

Add after `_validated_layer_json` and before `ensure_schema_seed`:

```python
async def sync_connected_schema() -> dict:
    """Incremental idempotent merge of all done uploads into catalog + global semantic layer.

    Returns dict with keys: tables_synced (list[str]), catalog (list[dict]), semantic_layer (dict|None).
    """
    existing_catalog = await get_catalog()
    catalog_by_key = {_catalog_key(c): c for c in existing_catalog}

    existing_layer_raw = await get_schema_semantic_layer()
    existing_layer: dict = {}
    if existing_layer_raw:
        try:
            existing_layer = json.loads(existing_layer_raw)
        except json.JSONDecodeError:
            existing_layer = {}

    existing_tables = {
        t.get("name", ""): t
        for t in (existing_layer.get("tables") or [])
        if isinstance(t, dict)
    }

    uploads = await list_uploads()
    tables_meta: list[dict] = []
    measures: list[dict] = []
    dimensions: list[dict] = []
    suggested: list[str] = []
    tables_synced: list[str] = []

    for u in uploads:
        if u.get("status") != "done":
            continue
        try:
            upload = await get_upload(u["id"])
            if upload is None:
                continue
            slug = upload["slug"]
            dd_raw = upload.get("data_dictionary")
            sl_raw = upload.get("semantic_layer")
            entries = json.loads(dd_raw) if isinstance(dd_raw, str) and dd_raw else []
            if not entries:
                continue
            per_table_sl = json.loads(sl_raw) if isinstance(sl_raw, str) and sl_raw else {}

            for e in entries:
                col = e.get("column")
                if not col:
                    continue
                updates = _profiler_catalog_updates(e)
                existing_row = catalog_by_key.get((u["id"], col))
                if existing_row and _user_catalog_fields_set(existing_row):
                    pass  # preserve interview fields — only patch profiler keys
                await upsert_catalog_entry(u["id"], slug, col, updates)

            prev_desc = ""
            if slug in existing_tables:
                prev_desc = str(existing_tables[slug].get("description") or "")
            tables_meta.append({
                "name": slug,
                "grain": str(per_table_sl.get("grain") or ""),
                "description": prev_desc,
            })
            for m in per_table_sl.get("measures", []) or []:
                measures.append({
                    "name": m.get("name", ""), "table": slug,
                    "column": m.get("column", ""),
                    "aggregation": m.get("aggregation", "sum"),
                    "description": m.get("description", ""),
                })
            for dim in per_table_sl.get("dimensions", []) or []:
                dimensions.append({
                    "name": dim.get("name", ""), "table": slug,
                    "column": dim.get("column", ""),
                    "description": dim.get("description", ""),
                })
            for q in per_table_sl.get("suggested_questions", []) or []:
                if q and q not in suggested:
                    suggested.append(q)
            tables_synced.append(slug)
        except Exception:  # noqa: BLE001
            logger.exception("Skipping table %s during schema sync", u.get("id"))
            continue

    try:
        detected = detect_relationships()
    except Exception:  # noqa: BLE001
        logger.exception("Relationship detection failed during sync; continuing without")
        detected = []

    existing_rels = existing_layer.get("relationships") or []
    if not isinstance(existing_rels, list):
        existing_rels = []
    relationships = _merge_relationships(
        [r for r in existing_rels if isinstance(r, dict)],
        detected,
    )

    candidate = {
        "tables": tables_meta,
        "relationships": relationships,
        "measures": measures,
        "dimensions": dimensions,
        "suggested_questions": suggested[:8],
    }
    layer_json = _validated_layer_json(candidate, tables_meta, suggested)
    await set_schema_semantic_layer(layer_json)
    logger.info("Synced schema: %s tables, %s relationships", len(tables_meta), len(relationships))

    refreshed_catalog = await get_catalog()
    layer_parsed = None
    try:
        layer_parsed = json.loads(layer_json)
    except json.JSONDecodeError:
        layer_parsed = None

    return {
        "tables_synced": tables_synced,
        "catalog": refreshed_catalog,
        "semantic_layer": layer_parsed,
    }
```

Add `get_catalog` to imports from `backend.database`:

```python
from backend.database import (
    catalog_count,
    get_catalog,
    get_schema_semantic_layer,
    get_upload,
    list_uploads,
    set_schema_semantic_layer,
    upsert_catalog_entry,
)
```

- [ ] **Step 4: Refactor `ensure_schema_seed` to delegate**

Replace the body of `ensure_schema_seed` (keep signature and docstring) with:

```python
async def ensure_schema_seed() -> None:
    """Idempotent first-time seed. Short-circuits once catalog + layer exist."""
    if await catalog_count() > 0 and await get_schema_semantic_layer():
        return
    await sync_connected_schema()
```

- [ ] **Step 5: Verify sync with two-upload scenario**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && PYTHONPATH=. python -c "
import asyncio, json
from backend.database import create_tables, get_db, create_upload, create_job, update_job, update_upload_artifacts, get_schema_semantic_layer, get_catalog
from backend.schema_synth import sync_connected_schema

DD1 = json.dumps([{'column':'id','dtype':'int64','semantic_type':'identifier','description':'pk','sample_values':['1'],'null_pct':0.0}])
SL1 = json.dumps({'grain':'one row per customer','measures':[],'dimensions':[],'suggested_questions':[]})
DD2 = json.dumps([{'column':'customer_id','dtype':'int64','semantic_type':'identifier','description':'fk','sample_values':['1'],'null_pct':0.0}])

async def main():
    db = await get_db()
    await create_tables(db)
    await db.close()
    await create_upload('u1','c.csv','customers','/tmp/c.csv')
    await create_job('j1','autoeda','u1')
    await update_upload_artifacts('u1', DD1, SL1)
    await update_job('j1','done', result='{}')
    await sync_connected_schema()
    sl = await get_schema_semantic_layer()
    assert sl and 'customers' in sl
    await create_upload('u2','o.csv','orders','/tmp/o.csv')
    await create_job('j2','autoeda','u2')
    await update_upload_artifacts('u2', DD2, SL1)
    await update_job('j2','done', result='{}')
    out = await sync_connected_schema()
    assert 'orders' in out['tables_synced'] and 'customers' in out['tables_synced']
    sl2 = json.loads(await get_schema_semantic_layer() or '{}')
    names = {t['name'] for t in sl2.get('tables', [])}
    assert names == {'customers','orders'}, names
    print('ok', len(await get_catalog()))
asyncio.run(main())
"
```

Expected: `ok 2` (or higher if DB has prior rows — adjust asserts if needed on dirty DB; prefer fresh `./data/app.db` or temp DB if test fails).

- [ ] **Step 6: Commit**

```bash
git add backend/schema_synth.py
git commit -m "feat(mcp): sync_connected_schema incremental merge"
```

---

## Task 3: `POST /api/schema/sync` route

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Add imports**

```python
from backend.schema_synth import ensure_schema_seed, sync_connected_schema
```

(replace existing `ensure_schema_seed`-only import)

Add to models import:

```python
    SchemaSyncResponse,
```

- [ ] **Step 2: Add route after `context_schema` (~line 291)**

```python
@app.post("/api/schema/sync", response_model=SchemaSyncResponse)
async def schema_sync() -> SchemaSyncResponse:
    raw = await sync_connected_schema()
    catalog = [_to_catalog_row(c) for c in raw["catalog"]]
    layer = _parse_schema_layer(
        json.dumps(raw["semantic_layer"]) if raw.get("semantic_layer") else None
    )
    return SchemaSyncResponse(
        catalog=catalog,
        semantic_layer=layer,
        tables_synced=raw["tables_synced"],
    )
```

- [ ] **Step 3: Verify route**

Start backend (or use TestClient):

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && PYTHONPATH=. python -c "
from fastapi.testclient import TestClient
from backend.main import app
c = TestClient(app)
r = c.post('/api/schema/sync')
print(r.status_code, r.json().get('tables_synced'))
"
```

Expected: `200` and a list (possibly empty on fresh DB).

- [ ] **Step 4: Commit**

```bash
git add backend/main.py
git commit -m "feat(mcp): POST /api/schema/sync route"
```

---

## Task 4: MCP package scaffold + httpx client

**Files:**
- Create: `datalens_mcp/__init__.py`
- Create: `datalens_mcp/config.py`
- Create: `datalens_mcp/client.py`

- [ ] **Step 1: Create `datalens_mcp/__init__.py`**

```python
"""DataLens MCP server — thin FastAPI proxy for Cowork."""
```

- [ ] **Step 2: Create `datalens_mcp/config.py`**

```python
from __future__ import annotations

import os

API_URL = os.getenv("DATALENS_API_URL", "http://127.0.0.1:8000").rstrip("/")
MCP_HOST = os.getenv("DATALENS_MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("DATALENS_MCP_PORT", "8010"))
JOB_TIMEOUT_SEC = float(os.getenv("DATALENS_JOB_TIMEOUT_SEC", "300"))
QUERY_TIMEOUT_SEC = float(os.getenv("DATALENS_QUERY_TIMEOUT_SEC", "300"))
POLL_INTERVAL_SEC = float(os.getenv("DATALENS_POLL_INTERVAL_SEC", "2.0"))
PROGRESS_HEARTBEAT_SEC = 15.0
```

- [ ] **Step 3: Create `datalens_mcp/client.py`**

```python
from __future__ import annotations

import httpx

from datalens_mcp.config import API_URL, JOB_TIMEOUT_SEC, QUERY_TIMEOUT_SEC


class DataLensClient:
    def __init__(self, base_url: str = API_URL) -> None:
        self.base_url = base_url.rstrip("/")

    async def upload_csv(self, filename: str, content: bytes) -> dict:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=JOB_TIMEOUT_SEC) as client:
            files = {"file": (filename, content, "text/csv")}
            r = await client.post("/api/upload", files=files)
            r.raise_for_status()
            return r.json()

    async def get_job(self, job_id: str) -> dict:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as client:
            r = await client.get(f"/api/jobs/{job_id}")
            r.raise_for_status()
            return r.json()

    async def schema_sync(self) -> dict:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=60.0) as client:
            r = await client.post("/api/schema/sync")
            r.raise_for_status()
            return r.json()

    async def context_chat(self, message: str) -> dict:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=QUERY_TIMEOUT_SEC) as client:
            r = await client.post("/api/context/chat", json={"message": message})
            r.raise_for_status()
            return r.json()

    async def query_chat(self, message: str) -> dict:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=QUERY_TIMEOUT_SEC) as client:
            r = await client.post("/api/query/chat", json={"message": message})
            r.raise_for_status()
            return r.json()


def format_http_error(exc: httpx.HTTPStatusError) -> str:
    try:
        detail = exc.response.json().get("detail", exc.response.text)
    except Exception:  # noqa: BLE001
        detail = exc.response.text
    return f"HTTP {exc.response.status_code}: {detail}"


def format_connect_error(base_url: str) -> str:
    return f"DataLens API unreachable at {base_url}"
```

- [ ] **Step 4: Verify import**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && PYTHONPATH=. python -c "
from datalens_mcp.client import DataLensClient
print('ok', DataLensClient().base_url)
"
```

Expected: `ok http://127.0.0.1:8000`

- [ ] **Step 5: Commit**

```bash
git add datalens_mcp/__init__.py datalens_mcp/config.py datalens_mcp/client.py
git commit -m "feat(mcp): datalens_mcp config and httpx client"
```

---

## Task 5: Job poll loop with MCP progress

**Files:**
- Create: `datalens_mcp/progress.py`

- [ ] **Step 1: Create `datalens_mcp/progress.py`**

```python
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Callable, Awaitable

from datalens_mcp.config import JOB_TIMEOUT_SEC, POLL_INTERVAL_SEC, PROGRESS_HEARTBEAT_SEC

if TYPE_CHECKING:
    from fastmcp import Context


async def poll_job_until_done(
    get_job: Callable[[], Awaitable[dict]],
    *,
    ctx: Context | None = None,
    timeout_sec: float = JOB_TIMEOUT_SEC,
    poll_interval_sec: float = POLL_INTERVAL_SEC,
) -> dict:
    """Poll job status; emit MCP progress from status + progress[] items."""
    start = time.monotonic()
    last_heartbeat = start
    last_progress_sig = ""
    tick = 0

    while True:
        job = await get_job()
        status = job.get("status", "pending")
        progress_items = job.get("progress") or []

        if ctx is not None:
            if status == "pending":
                await ctx.report_progress(progress=tick, message="Queued AutoEDA…")
            elif status == "running":
                if progress_items:
                    for item in progress_items:
                        sig = f"{item.get('text')}:{item.get('status')}"
                        if sig != last_progress_sig:
                            await ctx.report_progress(
                                progress=tick,
                                message=str(item.get("text") or "Running AutoEDA…"),
                            )
                            last_progress_sig = sig
                else:
                    await ctx.report_progress(progress=tick, message="Running AutoEDA…")
            tick += 1

        if status == "done":
            if ctx is not None:
                await ctx.report_progress(progress=tick, message="AutoEDA complete")
            return job
        if status == "error":
            err = job.get("error") or "AutoEDA job failed"
            raise RuntimeError(str(err))

        elapsed = time.monotonic() - start
        if elapsed >= timeout_sec:
            raise TimeoutError(
                f"Job poll timeout after {int(elapsed)}s (job_id={job.get('job_id')}, status={status})"
            )

        now = time.monotonic()
        if ctx is not None and (now - last_heartbeat) >= PROGRESS_HEARTBEAT_SEC:
            await ctx.report_progress(progress=tick, message=f"Still {status}… ({int(elapsed)}s)")
            last_heartbeat = now

        await asyncio.sleep(poll_interval_sec)
```

- [ ] **Step 2: Verify (mock get_job)**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && PYTHONPATH=. python -c "
import asyncio
from datalens_mcp.progress import poll_job_until_done

calls = {'n': 0}
async def get_job():
    calls['n'] += 1
    if calls['n'] < 2:
        return {'status': 'running', 'progress': [{'text':'Profiling','status':'in_progress'}]}
    return {'status': 'done', 'result': {}}

async def main():
    j = await poll_job_until_done(get_job, timeout_sec=5, poll_interval_sec=0.01)
    assert j['status']=='done'
    print('ok')
asyncio.run(main())
"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add datalens_mcp/progress.py
git commit -m "feat(mcp): job poll loop with progress heartbeats"
```

---

## Task 6: `analyze_csv` tool

**Files:**
- Create: `datalens_mcp/server.py` (partial — analyze_csv only; extend in T7)

- [ ] **Step 1: Create `datalens_mcp/server.py` with `analyze_csv`**

```python
from __future__ import annotations

import json
from pathlib import Path

import httpx
from fastmcp import Context, FastMCP

from datalens_mcp.client import DataLensClient, format_connect_error, format_http_error
from datalens_mcp.config import API_URL, POLL_INTERVAL_SEC
from datalens_mcp.progress import poll_job_until_done

mcp = FastMCP("DataLens")
_client = DataLensClient()


def _read_csv_bytes(file_path: str | None, csv_content: str | None, filename: str | None) -> tuple[str, bytes]:
    has_path = bool(file_path and file_path.strip())
    has_content = bool(csv_content is not None and csv_content != "")
    if has_path == has_content:
        raise ValueError("Provide exactly one of file_path OR (csv_content + filename).")
    if has_path:
        p = Path(file_path)  # type: ignore[arg-type]
        if not p.is_file():
            raise ValueError(f"file_path not found: {file_path}")
        return p.name, p.read_bytes()
    if not filename or not filename.strip():
        raise ValueError("filename is required when using csv_content.")
    return filename.strip(), csv_content.encode("utf-8")  # type: ignore[union-attr]


@mcp.tool
async def analyze_csv(
    ctx: Context,
    file_path: str | None = None,
    csv_content: str | None = None,
    filename: str | None = None,
    poll_interval_sec: float = POLL_INTERVAL_SEC,
) -> str:
    """Upload one CSV, run AutoEDA (blocking), sync connected schema, return canvas + metadata."""
    try:
        fname, content = _read_csv_bytes(file_path, csv_content, filename)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc

    try:
        upload = await _client.upload_csv(fname, content)
    except httpx.ConnectError as exc:
        raise RuntimeError(format_connect_error(API_URL)) from exc
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(format_http_error(exc)) from exc

    job_id = upload["job_id"]
    upload_id = upload["upload_id"]
    slug = upload["slug"]

    await ctx.report_progress(progress=0, message=f"Uploaded {fname}, job queued…")

    try:
        job = await poll_job_until_done(
            lambda: _client.get_job(job_id),
            ctx=ctx,
            poll_interval_sec=poll_interval_sec,
        )
    except (TimeoutError, RuntimeError):
        raise
    except httpx.ConnectError as exc:
        raise RuntimeError(format_connect_error(API_URL)) from exc

    canvas = job.get("result") or {}
    try:
        sync = await _client.schema_sync()
    except httpx.ConnectError as exc:
        raise RuntimeError(format_connect_error(API_URL)) from exc
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(format_http_error(exc)) from exc

    layer = sync.get("semantic_layer") or {}
    relationships = layer.get("relationships") or []
    out = {
        "upload_id": upload_id,
        "job_id": job_id,
        "slug": slug,
        "filename": fname,
        "canvas": canvas,
        "schema_sync": {
            "tables_synced": sync.get("tables_synced") or [],
            "catalog_column_count": len(sync.get("catalog") or []),
            "relationship_count": len(relationships),
        },
    }
    return json.dumps(out, indent=2)
```

- [ ] **Step 2: py_compile**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && PYTHONPATH=. python -m py_compile datalens_mcp/server.py
```

Expected: no output (success)

- [ ] **Step 3: Commit**

```bash
git add datalens_mcp/server.py
git commit -m "feat(mcp): analyze_csv tool with upload poll and schema sync"
```

---

## Task 7: `context_chat` and `query_chat` tools

**Files:**
- Modify: `datalens_mcp/server.py`

- [ ] **Step 1: Append tools at end of `server.py`**

```python
@mcp.tool
async def context_chat(ctx: Context, message: str) -> str:
    """One context-interview turn. Use message='__INIT__' to start."""
    await ctx.report_progress(progress=0, message="Starting context turn…")
    try:
        raw = await _client.context_chat(message)
    except httpx.ConnectError as exc:
        raise RuntimeError(format_connect_error(API_URL)) from exc
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(format_http_error(exc)) from exc

    catalog = raw.get("catalog") or []
    out = {
        "chat": raw.get("chat", ""),
        "complete": bool(raw.get("complete")),
        "catalog_column_count": len(catalog),
        "semantic_layer": raw.get("semantic_layer"),
        "catalog_preview": catalog[:5],
    }
    return json.dumps(out, indent=2)


@mcp.tool
async def query_chat(ctx: Context, message: str) -> str:
    """One schema-wide query turn (SQL / EDA / both)."""
    await ctx.report_progress(progress=0, message="Running query…")
    try:
        raw = await _client.query_chat(message)
    except httpx.ConnectError as exc:
        raise RuntimeError(format_connect_error(API_URL)) from exc
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(format_http_error(exc)) from exc

    out = {
        "chat": raw.get("chat", ""),
        "route": raw.get("route"),
        "route_reason": raw.get("route_reason"),
        "sql_query": raw.get("sql_query"),
        "canvas": raw.get("canvas"),
    }
    return json.dumps(out, indent=2)
```

- [ ] **Step 2: py_compile**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && PYTHONPATH=. python -m py_compile datalens_mcp/server.py
```

- [ ] **Step 3: Commit**

```bash
git add datalens_mcp/server.py
git commit -m "feat(mcp): context_chat and query_chat tools"
```

---

## Task 8: Entrypoint + requirements

**Files:**
- Create: `datalens_mcp/__main__.py`
- Create: `datalens_mcp/requirements.txt`

- [ ] **Step 1: Create `datalens_mcp/requirements.txt`**

```text
fastmcp>=2.0.0
httpx>=0.27.0
```

- [ ] **Step 2: Create `datalens_mcp/__main__.py`**

```python
from __future__ import annotations

from datalens_mcp.config import MCP_HOST, MCP_PORT
from datalens_mcp.server import mcp


def main() -> None:
    mcp.run(transport="http", host=MCP_HOST, port=MCP_PORT)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Install and list tools**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto"
pip install -r datalens_mcp/requirements.txt
PYTHONPATH=. python -m datalens_mcp &
sleep 2
curl -s -o NUL -w "%{http_code}" http://127.0.0.1:8010/mcp || echo "check fastmcp path"
```

Note: FastMCP may require POST for MCP protocol; if curl fails, verify with `fastmcp dev datalens_mcp/server.py:mcp` or MCP inspector. Success = process starts without traceback on port 8010.

- [ ] **Step 4: Commit**

```bash
git add datalens_mcp/__main__.py datalens_mcp/requirements.txt
git commit -m "feat(mcp): datalens_mcp entrypoint and requirements"
```

---

## Task 9: Live smoke test

**Files:** none (manual verification)

- [ ] **Step 1: Start backend**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto"
# Kill stale listeners on 8000 if needed (Windows):
# Get-NetTCPConnection -LocalPort 8000 | Select OwningProcess
PYTHONPATH=. python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

- [ ] **Step 2: Start MCP (second terminal)**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto"
pip install -r datalens_mcp/requirements.txt
PYTHONPATH=. python -m datalens_mcp
```

- [ ] **Step 3: Smoke via Python client (third terminal)**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && PYTHONPATH=. python -c "
import asyncio, json
from pathlib import Path
from datalens_mcp.client import DataLensClient

SMOKE = Path('test-data/smoke')

async def main():
    c = DataLensClient()
    u1 = await c.upload_csv('smoke_customers.csv', SMOKE.joinpath('smoke_customers.csv').read_bytes())
    u2 = await c.upload_csv('smoke_orders.csv', SMOKE.joinpath('smoke_orders.csv').read_bytes())
    print('uploads', u1['slug'], u2['slug'])
    sync = await c.schema_sync()
    assert 'smoke_customers' in sync['tables_synced']
    assert 'smoke_orders' in sync['tables_synced']
    print('sync ok', sync['tables_synced'])
asyncio.run(main())
"
```

For full AutoEDA completion, poll jobs until done before schema_sync (or call `analyze_csv` via MCP inspector). Minimum pass: both slugs appear in `tables_synced` after jobs reach `done`.

- [ ] **Step 4: Optional MCP tool smoke (requires completed jobs + OPENROUTER_API_KEY)**

1. `analyze_csv(file_path="test-data/smoke/smoke_customers.csv")`
2. `analyze_csv(file_path="test-data/smoke/smoke_orders.csv")` — verify both slugs in `schema_sync.tables_synced`
3. `context_chat(message="__INIT__")` — returns `chat` + `semantic_layer`
4. `query_chat(message="What is total order revenue by customer country?")` — returns `route`, `sql_query`, canvas table rows

- [ ] **Step 5: Update spec status**

In `docs/superpowers/specs/2026-06-23-datalens-mcp-cowork-design.md`, change Status line to:

` **Status:** Implemented — see plan docs/superpowers/plans/2026-06-23-datalens-mcp-cowork.md`

- [ ] **Step 6: Commit smoke notes (if spec updated)**

```bash
git add docs/superpowers/specs/2026-06-23-datalens-mcp-cowork-design.md
git commit -m "docs(mcp): mark spec implemented after smoke"
```

---

## Spec Coverage Checklist

| Spec requirement | Task |
|------------------|------|
| `analyze_csv` both input modes | T6 |
| Blocking upload + poll + progress | T5, T6 |
| `POST /api/schema/sync` | T2, T3 |
| Incremental multi-CSV semantic layer | T2 |
| `context_chat` with `__INIT__` | T7 |
| `query_chat` full response | T7 |
| Streamable HTTP FastMCP | T8 |
| Env vars | T4 |
| Error handling table | T4, T6, T7 |
| Cowork connector URL `:8010/mcp` | T8 |
| Cloud-ready standalone package | T4, T8 |

---

## Cowork Connector Reference

Add to Claude Desktop config (or Cowork connectors):

```json
{
  "datalens": {
    "type": "streamable-http",
    "url": "http://127.0.0.1:8010/mcp"
  }
}
```
