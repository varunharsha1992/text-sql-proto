# DataLens MCP Server for Claude Cowork (Design)

**Date:** 2026-06-23  
**Status:** Implemented — see plan docs/superpowers/plans/2026-06-23-datalens-mcp-cowork.md  
**Builds on:** Feature 001 (AutoEDA upload + job poll), Feature 002 (connected-schema context + catalog + semantic layer), Feature 003 (schema-wide query canvas).  
**Demo moment:** User uploads CSVs in Cowork → `analyze_csv` runs AutoEDA with live progress → optional `context_chat` interview → `query_chat` answers a multi-table business question — all via one Streamable HTTP MCP connector, without opening the web UI.

---

## 1. Summary

A **standalone FastMCP** server exposes three pipeline-stage tools that proxy to the existing FastAPI backend over HTTP. Cowork (or Claude Desktop with Streamable HTTP connector) calls tools; the MCP layer handles upload polling, MCP progress notifications, and incremental schema sync after each CSV. Business logic stays in the backend — the MCP package is a thin HTTP client.

---

## 2. Decisions (locked during brainstorming)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Tool mapping | **Pipeline stages:** `analyze_csv`, `context_chat`, `query_chat` |
| 2 | Backend integration | **HTTP proxy** to FastAPI (`DATALENS_API_URL`, default `http://127.0.0.1:8000`) |
| 3 | CSV input | **Both** `file_path` **or** `csv_content` + `filename` |
| 4 | `analyze_csv` completion | **Blocking** single tool result; internal upload + job poll |
| 5 | Progress UX | MCP **`notifications/progress`** during job poll (Streamable HTTP request-scoped SSE) |
| 6 | MCP transport | **Streamable HTTP** (FastMCP `transport="http"`) |
| 7 | v1 scope | **All three tools** fully implemented |
| 8 | Multi-table uploads | **One CSV per `analyze_csv` call**; incremental **`sync_connected_schema`** after each success |
| 9 | MCP framework | **FastMCP** standalone package — deployable to FastMCP cloud / Prefect Horizon |
| 10 | Deployment shape | **Approach 1:** thin proxy on `:8010`; FastAPI on `:8000`. Optional FastAPI mount deferred (not v1). |
| 11 | MCP exposure (local) | Bind **`127.0.0.1:8010`**; no auth in v1 |

---

## 3. Architecture

```
Cowork / Claude Desktop
    │  Streamable HTTP  POST …/mcp
    ▼
FastMCP server (:8010)          datalens_mcp/
    │  httpx async                   server.py, client.py, progress.py
    ▼
FastAPI (:8000)                 backend/
    │  agents, SQLite
    ▼
SQLite (uploads, catalog, schema_meta, jobs, query_history, raw_*)
```

### Data flow by tool

| Tool | FastAPI calls | Pattern |
|------|---------------|---------|
| `analyze_csv` | `POST /api/upload` → poll `GET /api/jobs/{id}` → `POST /api/schema/sync` | Fire & poll (hidden from Cowork) |
| `context_chat` | `POST /api/context/chat` | Sync turn |
| `query_chat` | `POST /api/query/chat` | Sync turn |

### Package layout

```text
datalens_mcp/
  __init__.py
  __main__.py       # python -m datalens_mcp → streamable-http :8010
  server.py         # FastMCP app + @mcp.tool definitions
  client.py         # httpx AsyncClient → DATALENS_API_URL
  progress.py       # job poll loop + ctx.report_progress()
  requirements.txt  # fastmcp, httpx

backend/
  schema_synth.py   # sync_connected_schema() — incremental merge (new)
  main.py           # POST /api/schema/sync (new)
  models.py         # SchemaSyncResponse (new)
```

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATALENS_API_URL` | `http://127.0.0.1:8000` | FastAPI base URL (MCP → backend) |
| `DATALENS_MCP_HOST` | `127.0.0.1` | MCP bind address (local) |
| `DATALENS_MCP_PORT` | `8010` | MCP port |
| `DATALENS_JOB_TIMEOUT_SEC` | `300` | `analyze_csv` poll timeout |
| `DATALENS_QUERY_TIMEOUT_SEC` | `300` | `context_chat` / `query_chat` HTTP timeout |
| `DATALENS_POLL_INTERVAL_SEC` | `2.0` | Job poll interval |

### Cowork / Desktop connector (local)

```json
{
  "datalens": {
    "type": "streamable-http",
    "url": "http://127.0.0.1:8010/mcp"
  }
}
```

### Cloud deployment (FastMCP / Horizon)

Deploy the `datalens_mcp/` package as its own service with `mcp.run(transport="http", host="0.0.0.0")` or `uvicorn` on `mcp.http_app(stateless_http=True)`. Set `DATALENS_API_URL` to the hosted FastAPI URL. Same tool code; no rewrite.

---

## 4. Backend: incremental schema sync

### Problem

`ensure_schema_seed()` short-circuits when catalog and semantic layer already exist:

```python
if await catalog_count() > 0 and await get_schema_semantic_layer():
    return
```

A second CSV can complete AutoEDA without merging into the global catalog / `schema_meta.semantic_layer`, breaking connected-schema tools in `context_chat` and `query_chat`.

### Solution: `sync_connected_schema()`

New function in `backend/schema_synth.py`, exposed as **`POST /api/schema/sync`**.

**Behavior (idempotent):**

1. For every upload with job `status=done` and non-empty `data_dictionary`:
   - Upsert catalog rows from `data_dictionary` (same field mapping as seed)
   - Merge table metadata, measures, and dimensions from per-upload `semantic_layer` into the global layer
2. Re-run `detect_relationships()`; **merge** new relationship candidates into existing `relationships` (dedupe by `from_table/from_column/to_table/to_column`); do not remove relationships already present
3. Preserve context-interview edits in **catalog** rows (`business_context`, `is_primary_key`, `is_foreign_key`, etc.) — upserts patch profiler fields only when catalog row lacks user-set values (see implementation plan for merge rules)
4. Return summary for MCP tool output

**Response model (`SchemaSyncResponse`):**

```python
class SchemaSyncResponse(BaseModel):
    catalog: list[CatalogRow]
    semantic_layer: SchemaSemanticLayer | None
    tables_synced: list[str]   # slugs included in this sync pass
```

`GET /api/context/schema` continues to call `ensure_schema_seed()` for first-time seed; **`POST /api/schema/sync`** is the incremental path used after each upload.

---

## 5. MCP tools

All tools return **JSON strings** (FastMCP serializes dict → text content). Errors use FastMCP tool error responses with actionable messages.

### 5.1 `analyze_csv`

**Purpose:** Upload one CSV, run AutoEDA, sync connected schema, return canvas + metadata.

**Input:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `file_path` | string | mode A | Path readable by MCP process (Cowork sandbox path) |
| `csv_content` | string | mode B | Raw CSV text |
| `filename` | string | mode B | e.g. `orders.csv` — drives slug via backend |
| `poll_interval_sec` | float | optional | Default from `DATALENS_POLL_INTERVAL_SEC` |

**Validation:** Exactly one of mode A or mode B. Reject if both or neither.

**Internal flow:**

1. Read bytes from `file_path` or encode `csv_content`
2. `POST /api/upload` (multipart `file`)
3. Poll `GET /api/jobs/{job_id}` until `status ∈ {done, error}` or timeout
4. During poll, call `ctx.report_progress(progress, total?, message)`:
   - `pending` → "Queued AutoEDA…"
   - `running` → forward each `JobResponse.progress[]` item as message
   - Heartbeat every ~15s if idle (timeout keepalive for Cowork / MCP hosts)
5. On `done`: `POST /api/schema/sync`
6. Return combined JSON

**Output:**

```json
{
  "upload_id": "uuid",
  "job_id": "uuid",
  "slug": "smoke_orders",
  "filename": "smoke_orders.csv",
  "canvas": { "insights": [], "charts": [], "table": null },
  "schema_sync": {
    "tables_synced": ["smoke_customers", "smoke_orders"],
    "catalog_column_count": 42,
    "relationship_count": 1
  }
}
```

On job `error`: tool error with `error` field from `JobResponse`.

---

### 5.2 `context_chat`

**Purpose:** One context-interview turn over the connected schema.

**Input:**

| Field | Type | Required |
|-------|------|----------|
| `message` | string | yes |

Use `"__INIT__"` as `message` to start the interview (same convention as the web app).

**Internal flow:**

1. `POST /api/context/chat` with `{ "message": "..." }`
2. Single long HTTP call (`DATALENS_QUERY_TIMEOUT_SEC`)
3. Optional progress heartbeat every ~20s: "Waiting for context agent…"

**Output:**

```json
{
  "chat": "agent reply",
  "complete": false,
  "catalog_column_count": 42,
  "semantic_layer": { "tables": [], "relationships": [], "measures": [], "dimensions": [], "suggested_questions": [] },
  "catalog_preview": []
}
```

Full catalog omitted by default (can be large). `catalog_preview` = first 5 catalog rows for grounding. Cowork can call `GET /api/context/schema` via future tool if full catalog is needed; not in v1.

---

### 5.3 `query_chat`

**Purpose:** One natural-language query turn over the connected schema.

**Input:**

| Field | Type | Required |
|-------|------|----------|
| `message` | string | yes |

**Internal flow:**

1. `POST /api/query/chat` — backend gates on `any_upload_done()`
2. Long sync call with progress heartbeats (turns may run several minutes)
3. Return full `QueryChatResponse` fields

**Output:**

```json
{
  "chat": "...",
  "route": "sql",
  "route_reason": "...",
  "sql_query": "SELECT ...",
  "canvas": { "insights": [], "charts": [], "table": { "columns": [], "rows": [] } }
}
```

Matches `QueryChatResponse` from `backend/models.py`.

---

## 6. Error handling

| Failure | MCP behavior |
|---------|----------------|
| FastAPI unreachable | Tool error: `DataLens API unreachable at {DATALENS_API_URL}` |
| Upload 400 / 413 | Pass through FastAPI `detail` |
| Job poll timeout | Tool error with last `status`, `job_id`, elapsed time |
| Job `error` status | Tool error with `JobResponse.error` |
| Query before any EDA done | Pass through HTTP 400 detail |
| Context / query HTTP 500 | Pass through backend friendly message |
| Invalid CSV input modes | Tool error before any HTTP call |

---

## 7. Progress and timeouts

- MCP progress uses FastMCP **`Context.report_progress()`** on Streamable HTTP (request-scoped SSE per MCP spec)
- Host support for progress UI varies; heartbeats still help timeout reset on compliant clients
- Job and query timeouts default to **300s** (align with Claude connector limits)
- Backend `AGENT_TIMEOUT_SEC` (240s) remains the agent run cap inside AutoEDA pipeline

---

## 8. Local development

```bash
# Terminal 1 — FastAPI (single instance, no reload on :8000)
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

# Terminal 2 — MCP
pip install -r datalens_mcp/requirements.txt && python -m datalens_mcp
# Listens http://127.0.0.1:8010/mcp
```

**Smoke sequence (Cowork or FastMCP inspector):**

1. `analyze_csv` with `test-data/smoke/smoke_customers.csv`
2. `analyze_csv` with `test-data/smoke/smoke_orders.csv` — verify `schema_sync.tables_synced` includes both slugs
3. `context_chat` with `message="__INIT__"`
4. `query_chat` with "What is total order revenue by customer country?"

---

## 9. Testing

| Test | Layer |
|------|-------|
| `sync_connected_schema` merges second upload into catalog + semantic layer | Backend pytest |
| `sync_connected_schema` preserves catalog FK/PK after context interview | Backend pytest |
| `POST /api/schema/sync` returns `tables_synced` | Backend API test |
| MCP upload + poll with mocked httpx responses | MCP unit |
| Progress callbacks during mock poll loop | MCP unit |
| E2E smoke (two CSVs → context init → query) | Manual / inspector |

---

## 10. Non-goals (v1)

- MCP auth / API keys (add when deploying beyond localhost)
- Mounting MCP on FastAPI `/mcp` (optional dev convenience — deferred)
- Batch multi-file upload in one tool call
- Exposing `GET /api/query/history` as a separate MCP tool
- Replacing the web UI

---

## 11. Dependencies

**New (`datalens_mcp/requirements.txt`):**

- `fastmcp` (Streamable HTTP server)
- `httpx` (async HTTP client to FastAPI)

**Backend:** no new runtime deps for sync route (uses existing `schema_synth`, `database`).

---

## 12. Success criteria

1. Cowork connects via Streamable HTTP to `:8010/mcp` and discovers three tools
2. `analyze_csv` returns full AutoEDA canvas + schema sync summary; progress events emit during long runs
3. Second CSV merges into global semantic layer without manual intervention
4. `context_chat("__INIT__")` returns agent greeting + draft semantic layer
5. `query_chat` returns SQL route, query text, and results table for smoke multi-table question
6. MCP package deployable standalone to FastMCP cloud with only `DATALENS_API_URL` changed
