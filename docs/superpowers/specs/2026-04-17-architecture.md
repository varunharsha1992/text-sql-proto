# DataLens — Shared Architecture
**Date:** 2026-04-17  
**Goal:** Live demo prototype — single user, local run, ruthlessly simple.  
**Stack:** Next.js 14 (App Router, TypeScript, Tailwind) · FastAPI (Python 3.11) · LangGraph + LangChain · OpenAI GPT-4o · SQLite

---

## Product Overview

A 3-screen multi-agent data analysis app. User uploads a CSV, an agent profiles it instantly, a conversational agent builds a semantic catalog, and a query canvas answers natural language questions with SQL, charts, and insights.

**Screen flow:**
```
Screen 1: Upload + Auto EDA
    ↓ (EDA complete)
Screen 2: Context Agent — Semantic Catalog Builder
    ↓ (user marks complete)
Screen 3: Query Canvas — Text2SQL + EDA Multi-Agent
```

Navigation is linear. Screens 2–3 are disabled until prerequisites complete. All screens remain accessible via NavBar once unlocked.

---

## Two Interaction Patterns

Every screen uses one of two patterns. No custom patterns per screen.

### Pattern A — Fire & Poll
Frontend triggers a background job. Backend runs the agent asynchronously. Frontend polls `GET /api/jobs/{job_id}` every 2s until `status = "done"`.

Used by: **Screen 1** (Auto EDA).

### Pattern B — Turn-based JSON
Frontend POSTs a message. Backend runs the agent synchronously. Returns `{ chat: "...", canvas: {...} }` in one response.

Used by: **Screen 2** (Context Agent), **Screen 3** (Query Canvas).

Both patterns use plain HTTP. No WebSockets, no SSE.

---

## Shared Canvas Contract

All agents output a single `CanvasResponse`. One `Canvas.tsx` component renders it across all screens.

```typescript
interface CanvasResponse {
  insights: InsightItem[];
  charts: ChartSpec[];
  table: TableData | null;
}

interface InsightItem {
  type: "stat" | "text" | "warning" | "badge";
  label?: string;
  value?: string;
  content?: string;
  color?: "green" | "amber" | "red";
}

interface ChartSpec {
  type: "bar" | "line" | "histogram" | "scatter" | "heatmap" | "boxplot";
  title: string;
  x_label: string;
  y_label: string;
  data: { x: string | number; y: number }[];
}

interface TableData {
  columns: string[];
  rows: (string | number | null)[][];
}
```

---

## The `jobs` Table — Async Backbone

Every Pattern A job writes its state here.

```sql
CREATE TABLE jobs (
    job_id     TEXT PRIMARY KEY,
    job_type   TEXT,               -- "autoeda"
    upload_id  TEXT,
    status     TEXT DEFAULT "pending",  -- "pending" | "running" | "done" | "error"
    result     TEXT,               -- JSON blob: CanvasResponse when done
    error      TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

Frontend polls `GET /api/jobs/{job_id}` every 2s. When `status = "done"`, reads `result` and stops polling.

---

## SQLite Tables — Full Schema

```sql
-- Upload metadata
CREATE TABLE uploads (
    id           TEXT PRIMARY KEY,          -- uuid4
    filename     TEXT,
    slug         TEXT,                      -- filename-derived, e.g. "orders_2024"
    original_path TEXT,
    row_count    INTEGER,
    col_count    INTEGER,
    uploaded_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    context_complete BOOLEAN DEFAULT FALSE
);

-- Semantic catalog: one row per column
CREATE TABLE catalog (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    upload_id        TEXT,
    slug             TEXT,                  -- same slug as uploads.slug
    column_name      TEXT,
    data_type        TEXT,
    description      TEXT,
    sample_values    TEXT,                  -- JSON array of 3-5 values
    is_primary_key   BOOLEAN DEFAULT FALSE,
    is_foreign_key   BOOLEAN DEFAULT FALSE,
    foreign_key_ref  TEXT,                  -- "table.column" format
    null_pct         REAL,
    cardinality      INTEGER,
    inferred_role    TEXT,                  -- "dimension" | "measure" | "identifier" | "datetime"
    business_context TEXT,
    updated_at       DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Context agent conversation history
CREATE TABLE context_conversations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    upload_id  TEXT,
    role       TEXT,   -- "agent" | "user"
    message    TEXT,
    timestamp  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Query history
CREATE TABLE query_history (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    upload_id      TEXT,
    user_message   TEXT,
    route          TEXT,    -- "sql" | "eda" | "both"
    sql_query      TEXT,
    chat_response  TEXT,
    canvas_response TEXT,   -- JSON: CanvasResponse
    timestamp      DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

Raw data table is written dynamically as `raw_{upload_id}` after CSV parse + light type coercion.

---

## Agent → SQLite Write Rules

Agents never write to SQLite directly. Only tools write.

```
Agent               Tool                      SQLite Table
────────────────────────────────────────────────────────────
AutoEDA          →  write_autoeda_result    →  jobs.result
Context Agent    →  write_catalog_entry     →  catalog
                 →  mark_catalog_complete   →  uploads.context_complete
Query Agents     →  execute_sql             →  (reads raw_{id})
                 →  write_query_result      →  query_history
```

---

## Full API Surface (7 endpoints)

```
POST  /api/upload                    → { upload_id, job_id, slug }
GET   /api/jobs/{job_id}             → { status, result, error }

POST  /api/context/{id}/chat         → { chat, canvas, catalog, complete }
GET   /api/context/{id}/catalog      → { slug, columns: [...] }
POST  /api/context/{id}/complete     → { ok: true }

POST  /api/query/{id}                → { chat, canvas, route, route_reason, sql_query }
GET   /api/query/{id}/history        → [ ...query_history rows... ]
```

---

## Project File Structure

```
text2sql-eda/
├── backend/
│   ├── main.py                  # FastAPI app, all routes
│   ├── database.py              # SQLite init, table creation, helpers
│   ├── models.py                # Pydantic request/response models
│   ├── agents/
│   │   ├── autoeda.py           # LangGraph single-node agent
│   │   ├── context.py           # LangGraph single-node agent
│   │   └── query_graph.py       # LangGraph supervisor + text2sql + eda
│   ├── tools/
│   │   ├── dataframe.py         # get_dataframe_profile, sample_column_values
│   │   ├── catalog.py           # get_catalog, write_catalog_entry, get_catalog_summary
│   │   ├── python_repl.py       # run_python_analysis
│   │   ├── sql.py               # execute_sql, write_query_result
│   │   └── chart.py             # generate_chart_spec
│   ├── utils/
│   │   ├── csv_parser.py        # CSV → SQLite raw table + light type coercion
│   │   └── heuristics.py        # infer_relationships, slug generation
│   └── requirements.txt
│
├── frontend/
│   ├── app/
│   │   ├── page.tsx             # Root → redirect to /upload
│   │   ├── upload/page.tsx      # Screen 1
│   │   ├── context/page.tsx     # Screen 2
│   │   └── query/page.tsx       # Screen 3
│   ├── components/
│   │   ├── Canvas.tsx           # Shared CanvasResponse renderer
│   │   ├── ChartRenderer.tsx    # Recharts wrapper for ChartSpec
│   │   ├── InsightCards.tsx     # Stat / text / warning / badge cards
│   │   ├── CatalogTable.tsx     # Screen 2 right panel
│   │   ├── ChatPanel.tsx        # Shared chat message list + input
│   │   └── NavBar.tsx           # Step progress (1→2→3), disabled states
│   ├── lib/
│   │   ├── api.ts               # Typed fetch wrappers for all endpoints
│   │   ├── types.ts             # CanvasResponse, ChartSpec, CatalogRow, etc.
│   │   └── hooks.ts             # usePolling, useChatTurn, useUploadId
│   └── package.json
│
├── data/
│   └── app.db
└── .env
```

---

## Shared State Between Screens

One value shared across all screens via `localStorage` + React context:

```typescript
const AppContext = {
  uploadId: string | null,   // set on Screen 1 upload
  slug: string | null,       // human-readable label in NavBar
}
```

All other state is fetched from SQLite on demand per screen.

---

## Deliberate Omissions (correct for demo)

| Omitted | Why | Production addition |
|---|---|---|
| Auth / sessions | Single user demo | JWT + user_id scoping |
| Job queue (Celery/Redis) | BackgroundTasks sufficient | Add when concurrent users matter |
| Streaming tokens | Polling simpler, sufficient | SSE for live token stream |
| File storage (S3) | Local disk fine | S3/GCS for multi-user |
| Error retry logic | UI retry fine | Exponential backoff |
| LangSmith tracing | Not needed for demo | Add for production debugging |

---

## Environment Variables

```
OPENAI_API_KEY=
DATABASE_URL=sqlite:///./data/app.db
UPLOAD_DIR=./data/uploads
MAX_FILE_SIZE_MB=50
PYTHON_REPL_TIMEOUT_SEC=30
```
