# DataLens

**DataLens** is a demo-first, local-run analytics app that turns uploaded CSVs into a connected schema you can explore and query in natural language. Upload one or more tables, let AutoEDA profile them, optionally refine the schema in a context interview, then ask business questions that span multiple tables.

**Stack:** Next.js 14 · FastAPI · LangGraph / DeepAgents · OpenRouter (DeepSeek V4 Flash) · SQLite

---

## What DataLens Does

DataLens follows a three-stage pipeline:

| Stage | Purpose | Web UI | MCP tool |
|-------|---------|--------|----------|
| **1. Upload + AutoEDA** | Profile each CSV, build data dictionary, charts, and per-table semantic draft | `/upload` | `analyze_csv` |
| **2. Context interview** | Confirm tables, columns, PK/FK, and cross-table relationships | `/context` | `context_chat` |
| **3. Query canvas** | Ask schema-wide business questions (SQL, EDA, or both) | `/query` | `query_chat` |

Every uploaded CSV becomes a table in a **global connected schema**. There is no per-dataset switcher — all tables live in one implicit schema backed by SQLite.

**Demo moment (Cowork):** Upload CSVs via MCP → AutoEDA runs with live progress → optional context interview → ask a multi-table question like *"What is total order revenue by customer country?"* — all without opening the web UI.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Clients                                                         │
│  · Next.js web UI (localhost:3000)                               │
│  · Claude Cowork / Claude Desktop (Streamable HTTP MCP)          │
└───────────────┬─────────────────────────────┬───────────────────┘
                │ HTTP                         │ POST …/mcp
                ▼                              ▼
     ┌──────────────────┐           ┌──────────────────┐
     │  FastAPI (:8000)  │◄──────────│  FastMCP (:8010)  │
     │  backend/         │  httpx    │  datalens_mcp/    │
     └─────────┬─────────┘           └──────────────────┘
               │
               ▼
     ┌──────────────────┐
     │  SQLite (app.db)  │
     │  uploads, catalog │
     │  schema_meta, jobs│
     │  query_history    │
     │  raw_{upload_id}  │
     └──────────────────┘
```

### Interaction patterns

**Pattern A — Fire & Poll** (AutoEDA upload jobs)

- Client triggers a job → backend runs agent in `BackgroundTasks`
- Client polls `GET /api/jobs/{job_id}` until `status=done`
- Used by: upload screen, MCP `analyze_csv` (poll is hidden inside the tool)

**Pattern B — Turn-based JSON** (context + query)

- Client sends one message → backend runs agent synchronously → returns `{ chat, canvas, … }`
- Used by: context screen, query screen, MCP `context_chat` and `query_chat`

### Key artifacts

| Artifact | Location | Role |
|----------|----------|------|
| Per-table data dictionary | `uploads.data_dictionary` | AutoEDA profiler output per CSV |
| Per-table semantic draft | `uploads.semantic_layer` | Grain, measures, dimensions per table |
| Global catalog | `catalog` table | Column-level truth (PK/FK, business context) |
| Schema semantic layer | `schema_meta.semantic_layer` | Join paths, schema measures/dimensions |
| Raw data | `raw_{upload_id}` SQLite tables | Query source (read-only SQL) |
| Query history | `query_history` | Global session log |

After each CSV upload, **`POST /api/schema/sync`** merges all completed uploads into the global catalog and semantic layer (incremental, idempotent).

---

## MCP Server for Claude Cowork

DataLens exposes a **standalone FastMCP** server that proxies to the FastAPI backend over HTTP. Cowork (or Claude Desktop with a Streamable HTTP connector) discovers three tools and runs the full pipeline without the web UI.

### MCP endpoint

| Setting | Value |
|---------|-------|
| **Transport** | Streamable HTTP |
| **URL** | `http://127.0.0.1:8010/mcp` |
| **Bind (local)** | `127.0.0.1:8010` |
| **Auth (v1)** | None — localhost only |

### Cowork / Claude Desktop connector

Add this to your MCP connectors configuration:

```json
{
  "datalens": {
    "type": "streamable-http",
    "url": "http://127.0.0.1:8010/mcp"
  }
}
```

The connector name (`datalens`) is arbitrary; the URL must point at the running MCP server.

### Prerequisites

Both services must be running before Cowork calls any tool:

1. **FastAPI backend** on port **8000** (agents, SQLite, all business logic)
2. **MCP server** on port **8010** (thin HTTP proxy)
3. **`OPENROUTER_API_KEY`** in repo-root `.env` (agents call DeepSeek V4 Flash via OpenRouter)

```bash
# Terminal 1 — backend
cd /path/to/text-sql-proto
PYTHONPATH=. python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

# Terminal 2 — MCP
pip install -r datalens_mcp/requirements.txt
PYTHONPATH=. python -m datalens_mcp
# Listens at http://127.0.0.1:8010/mcp
```

Use a single uvicorn instance on `:8000` (avoid `--reload` during smoke tests — stale listeners can cause 404s).

### Environment variables (MCP)

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATALENS_API_URL` | `http://127.0.0.1:8000` | FastAPI base URL (MCP → backend) |
| `DATALENS_MCP_HOST` | `127.0.0.1` | MCP bind address |
| `DATALENS_MCP_PORT` | `8010` | MCP port |
| `DATALENS_JOB_TIMEOUT_SEC` | `300` | `analyze_csv` job poll timeout |
| `DATALENS_QUERY_TIMEOUT_SEC` | `300` | `context_chat` / `query_chat` HTTP timeout |
| `DATALENS_POLL_INTERVAL_SEC` | `2.0` | Job poll interval inside `analyze_csv` |

### MCP tools

All tools return **JSON strings**. Errors surface as tool errors with actionable messages.

#### `analyze_csv`

Upload one CSV, run AutoEDA (blocking), sync connected schema, return canvas + metadata.

**Input** — provide exactly one mode:

| Field | Type | Mode | Notes |
|-------|------|------|-------|
| `file_path` | string | A | Path readable by the MCP process (e.g. Cowork sandbox path) |
| `csv_content` | string | B | Raw CSV text |
| `filename` | string | B | Required with `csv_content` (e.g. `orders.csv`) |
| `poll_interval_sec` | float | optional | Default from `DATALENS_POLL_INTERVAL_SEC` |

**Internal flow:** `POST /api/upload` → poll `GET /api/jobs/{id}` with MCP progress notifications → `POST /api/schema/sync`

**Example output:**

```json
{
  "upload_id": "uuid",
  "job_id": "uuid",
  "slug": "smoke_orders",
  "filename": "smoke_orders.csv",
  "canvas": {
    "insights": [],
    "charts": [],
    "table": null
  },
  "schema_sync": {
    "tables_synced": ["smoke_customers", "smoke_orders"],
    "catalog_column_count": 42,
    "relationship_count": 1
  }
}
```

**Multi-table uploads:** Call `analyze_csv` once per CSV. Each successful run triggers schema sync so later tables merge into the global semantic layer.

#### `context_chat`

One context-interview turn over the connected schema.

| Field | Type | Required |
|-------|------|----------|
| `message` | string | yes |

Use `message="__INIT__"` to start the interview (same convention as the web app).

**Example output:**

```json
{
  "chat": "agent reply",
  "complete": false,
  "catalog_column_count": 42,
  "semantic_layer": {
    "tables": [],
    "relationships": [],
    "measures": [],
    "dimensions": [],
    "suggested_questions": []
  },
  "catalog_preview": []
}
```

Full catalog is omitted by default (can be large). `catalog_preview` contains the first 5 rows for grounding.

#### `query_chat`

One natural-language query turn over the connected schema.

| Field | Type | Required |
|-------|------|----------|
| `message` | string | yes |

Requires at least one completed AutoEDA upload. The orchestrator routes to SQL, EDA, or both.

**Example output:**

```json
{
  "chat": "North leads with $2.4M…",
  "route": "sql",
  "route_reason": "Question asks for aggregated revenue by dimension",
  "sql_query": "SELECT …",
  "canvas": {
    "insights": [],
    "charts": [],
    "table": { "columns": [], "rows": [] }
  }
}
```

### Recommended Cowork workflow

Copy or adapt this prompt when starting a Cowork session with the DataLens connector enabled:

```
Use the DataLens MCP tools in order:

1. analyze_csv — upload each CSV one at a time (use file_path or csv_content + filename)
2. context_chat — start with message="__INIT__", then answer the agent's questions
3. query_chat — ask business questions spanning the uploaded tables

Wait for each analyze_csv to finish before uploading the next file.
Report schema_sync.tables_synced after each upload.
```

**Smoke sequence** (repo test data):

1. `analyze_csv(file_path="test-data/smoke/smoke_customers.csv")`
2. `analyze_csv(file_path="test-data/smoke/smoke_orders.csv")` — verify both slugs in `schema_sync.tables_synced`
3. `context_chat(message="__INIT__")`
4. `query_chat(message="What is total order revenue by customer country?")`

### MCP progress notifications

During `analyze_csv`, the server emits MCP `notifications/progress` while polling the AutoEDA job:

- `pending` → "Queued AutoEDA…"
- `running` → forwards each job progress item
- Heartbeat every ~15s if idle (helps timeout keepalive on compliant hosts)

Host support for progress UI varies; heartbeats still help on long runs.

### MCP error handling

| Failure | Behavior |
|---------|----------|
| FastAPI unreachable | Tool error: `DataLens API unreachable at {DATALENS_API_URL}` |
| Upload 400 / 413 | Pass through FastAPI `detail` |
| Job poll timeout | Tool error with last `status`, `job_id`, elapsed time |
| Job `error` status | Tool error with `JobResponse.error` |
| Query before any EDA done | Pass through HTTP 400 detail |
| Invalid CSV input modes | Tool error before any HTTP call |

### Cloud deployment (optional)

Deploy the `datalens_mcp/` package as its own service with `mcp.run(transport="http", host="0.0.0.0")`. Set `DATALENS_API_URL` to the hosted FastAPI URL. Add auth before exposing beyond localhost (not in v1).

---

## Backend API

Base URL: `http://127.0.0.1:8000`

| Method | Path | Pattern | Description |
|--------|------|---------|-------------|
| `POST` | `/api/upload` | A | Upload CSV → `{ upload_id, job_id, slug }` |
| `GET` | `/api/jobs/{job_id}` | A | Poll job status, progress, result canvas |
| `GET` | `/api/uploads` | — | List all uploaded tables |
| `GET` | `/api/context/schema` | — | Global catalog + semantic layer |
| `POST` | `/api/schema/sync` | — | Incremental merge of all done uploads |
| `POST` | `/api/context/chat` | B | Context interview turn |
| `POST` | `/api/context/complete` | — | Mark context interview complete |
| `POST` | `/api/query/chat` | B | Schema-wide query turn |
| `GET` | `/api/query/history` | — | Global query history |

Context and query routes are **schema-wide** (no `upload_id` in paths). Query requires ≥1 upload with AutoEDA `done`.

---

## Web UI

| Route | Screen | Pattern |
|-------|--------|---------|
| `/upload` | Upload + AutoEDA | Fire & poll |
| `/context` | Context interview | Turn-based chat |
| `/query` | Query canvas | Turn-based chat |

**Frontend dev:** Set `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000` in `frontend/.env.local` so long sync turns bypass the Next.js rewrite timeout (~60s).

```bash
# Terminal 3 — frontend
cd frontend
npm install
npm run dev
# http://localhost:3000
```

---

## Local development (full stack)

### Backend environment (repo root `.env`)

| Variable | Example | Purpose |
|----------|---------|---------|
| `OPENROUTER_API_KEY` | `sk-or-…` | LLM access (required for agents) |
| `OPENROUTER_MODEL` | `deepseek/deepseek-v4-flash` | Model id |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/app.db` | SQLite path |
| `UPLOAD_DIR` | `./data/uploads` | CSV storage |
| `MAX_FILE_SIZE_MB` | `50` | Upload limit |

### Project layout

```text
backend/           FastAPI, agents, tools, SQLite
frontend/          Next.js 14 App Router
datalens_mcp/      FastMCP Streamable HTTP server
test-data/smoke/   smoke_customers.csv, smoke_orders.csv
docs/              Architecture and feature specs
```

### Package entrypoints

```bash
# Backend
PYTHONPATH=. python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

# MCP
PYTHONPATH=. python -m datalens_mcp

# Frontend
cd frontend && npm run dev
```

---

## Agents (summary)

| Agent | File | Role |
|-------|------|------|
| AutoEDA | `backend/agents/autoeda.py` | DeepAgents pipeline: profile CSV, data dictionary, charts |
| Context | `backend/agents/context.py` | Turn-based interview; writes catalog + semantic layer |
| Query | `backend/agents/query.py` | DeepAgents orchestrator → Text2SQL and/or EDA subagents |

Query agents pull schema context **on demand via tools** (catalog, semantic layer, data dictionary) — nothing is injected into system prompts at full size.

**LLM:** `get_chat_model()` → DeepSeek V4 Flash via OpenRouter (`OPENROUTER_MODEL`, default `deepseek/deepseek-v4-flash`).

If the LLM is unavailable during AutoEDA, a deterministic fallback still returns stats, warnings, and charts (data dictionary and semantic layer may be omitted).

---

## Non-goals (current version)

- MCP auth / API keys (add when deploying beyond localhost)
- Batch multi-file upload in one MCP call
- Mounting MCP on FastAPI `/mcp` (deferred)
- Replacing the web UI
- Production auth, job queues, streaming tokens

---

## Related documentation

| Document | Contents |
|----------|----------|
| [datalens-architecture.md](./datalens-architecture.md) | Original minimal technical architecture (screens, jobs table, agent ↔ SQLite) |
| [superpowers/specs/2026-06-23-datalens-mcp-cowork-design.md](./superpowers/specs/2026-06-23-datalens-mcp-cowork-design.md) | MCP design spec (implemented) |
| [superpowers/specs/2026-06-22-feature-002-connected-schema-context-design.md](./superpowers/specs/2026-06-22-feature-002-connected-schema-context-design.md) | Connected schema + context agent |
| [superpowers/specs/2026-06-23-feature-003-connected-schema-query-canvas-design.md](./superpowers/specs/2026-06-23-feature-003-connected-schema-query-canvas-design.md) | Schema-wide query canvas |
