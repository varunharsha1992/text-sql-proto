# DataLens — Minimal Technical Architecture
**Context:** Demo-first, single-user, local-run app. Ruthlessly simple. No queues, no Redis, no microservices.  
**Stack:** Next.js 14 · FastAPI · LangGraph · OpenAI GPT-4o · SQLite

---

## Overall Pattern

Every screen follows one of two patterns. Pick the pattern, not a custom design per screen.

```
Pattern A — Fire & Poll          Pattern B — Turn-based JSON
─────────────────────────        ──────────────────────────────
Frontend triggers a job          Frontend sends a message
Backend runs agent async         Backend runs agent, returns
Frontend polls status + result   {chat: "...", canvas: {...}}
                                 Canvas key also written to SQLite
Used by: Screen 1, Screen 3      Used by: Screen 2, Screen 4
```

Both patterns use plain HTTP. No WebSockets. No SSE. Agent runs in a background thread (FastAPI `BackgroundTasks`). SQLite is the single source of truth.

---

## System Diagram

```
┌─────────────────────────────────────────────────────────┐
│  Next.js 14 Frontend                                     │
│                                                          │
│  Screen 1      Screen 2      Screen 3      Screen 4      │
│  Poll /status  POST /chat    Poll /status  POST /chat    │
│     ↑               ↓            ↑               ↓       │
└─────│───────────────│────────────│───────────────│───────┘
      │               │            │               │
      └───────────────┴────────────┴───────────────┘
                              │
                    ┌─────────▼─────────┐
                    │   FastAPI Server   │
                    │                   │
                    │  BackgroundTasks   │
                    │  ┌─────────────┐  │
                    │  │ LangGraph   │  │
                    │  │  Agents     │  │
                    │  └──────┬──────┘  │
                    └─────────│─────────┘
                              │ read/write
                    ┌─────────▼─────────┐
                    │     SQLite         │
                    │   (app.db)         │
                    │                   │
                    │  jobs             │
                    │  catalog          │
                    │  cleanup_log      │
                    │  raw_{id}         │
                    │  clean_{id}       │
                    │  query_history    │
                    └───────────────────┘
```

---

## The `jobs` Table — Shared Async Backbone

Every background task (Pattern A) writes its state here. Frontend polls this.

```sql
CREATE TABLE jobs (
    job_id    TEXT PRIMARY KEY,    -- uuid4
    job_type  TEXT,                -- "autoeda" | "cleanup"
    upload_id TEXT,
    status    TEXT DEFAULT "pending",  -- "pending" | "running" | "done" | "error"
    result    TEXT,                -- JSON blob: canvas_response when done
    error     TEXT,                -- error message if status="error"
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

Frontend polls `GET /api/jobs/{job_id}` every 2s. When `status="done"`, reads `result` and stops polling. That's it. No pub/sub, no callbacks.

---

## Screen 1 — Upload + Auto EDA

**Pattern A: Fire & Poll**

```
POST /api/upload
  ← { upload_id, job_id }

[agent runs in background]
  - Parses CSV → writes raw_{upload_id} table
  - Runs AutoEDA agent
  - Agent writes canvas_response to jobs.result
  - Sets jobs.status = "done"

GET /api/jobs/{job_id}          ← frontend polls every 2s
  ← { status: "running" }       ← show loading state
  ← { status: "done",
      result: {                  ← render canvas
        insights: [...],
        charts: [...],
        table: null
      }}
```

**FastAPI route (simplified):**
```python
@app.post("/api/upload")
async def upload_file(file: UploadFile, bg: BackgroundTasks):
    upload_id = str(uuid4())
    job_id = str(uuid4())
    # 1. Save file to disk
    # 2. Create job row (status=pending)
    # 3. Schedule background task
    bg.add_task(run_autoeda, upload_id, job_id)
    return {"upload_id": upload_id, "job_id": job_id}

async def run_autoeda(upload_id, job_id):
    update_job(job_id, status="running")
    result = await autoeda_agent.run(upload_id)   # LangGraph invoke
    update_job(job_id, status="done", result=result)
```

**Frontend polling:**
```typescript
const poll = setInterval(async () => {
  const job = await fetch(`/api/jobs/${jobId}`).then(r => r.json())
  if (job.status === "done") {
    clearInterval(poll)
    setCanvas(job.result)
  }
  if (job.status === "error") {
    clearInterval(poll)
    setError(job.error)
  }
}, 2000)
```

---

## Screen 2 — Context Agent

**Pattern B: Turn-based JSON**

Each user message → one POST → one response with both keys.

```
POST /api/context/{upload_id}/chat
  body: { message: "order_id is the primary key" }

  [agent runs synchronously — single LLM call + tool calls]
  - Reads conversation history from context_conversations
  - Calls write_catalog_entry tool → updates SQLite catalog directly
  - Returns structured response

  ← {
      chat: "Got it — order_id set as PK. I've updated the catalog.
             Next question: is revenue pre-tax or post-tax?",
      canvas: {           ← full current catalog state
        table_name: "ecommerce_orders_2024",
        columns: [ ...full catalog rows... ]
      }
    }
```

**Key design decision:** Agent runs synchronously here (not background). Why? Context agent turns are short (1–3 tool calls). Keeping it synchronous means no polling complexity, no job management. Frontend just awaits the response. Acceptable because each turn is < 5s.

**What "canvas key also written to SQLite" means:**
The agent calls `write_catalog_entry(...)` as a tool. That tool writes directly to the `catalog` table in SQLite. The `canvas` key in the response is simply a read of those same rows — it's not a separate write, it's just the agent returning what it just wrote. So SQLite is always the source of truth, and the response canvas is a snapshot.

```python
@app.post("/api/context/{upload_id}/chat")
async def context_chat(upload_id: str, body: ChatRequest):
    history = get_conversation_history(upload_id)
    response = await context_agent.invoke({
        "upload_id": upload_id,
        "message": body.message,
        "history": history
    })
    # response is already {"chat": "...", "canvas": {...}}
    save_message(upload_id, "user", body.message)
    save_message(upload_id, "agent", response["chat"])
    return response
```

**Catalog GET endpoint** (for initial load and refresh):
```
GET /api/context/{upload_id}/catalog
  ← { columns: [...catalog rows...] }
```

---

## Screen 3 — Cleanup Agent

**Pattern A: Fire & Poll** (identical shape to Screen 1)

Triggered by the "Mark Context Complete" button.

```
POST /api/context/{upload_id}/complete
  ← { job_id }

[cleanup agent runs in background]
  - Reads catalog from SQLite
  - Per column: calls get_column_quality_report → decides → runs_python_cleaning
  - Writes each decision to cleanup_log table as it goes
  - Calls commit_clean_data → writes clean_{upload_id} table
  - Sets jobs.status = "done", result = { summary, log_count }

GET /api/jobs/{job_id}          ← same poll pattern
  ← { status: "running" }

GET /api/cleanup/{upload_id}/log   ← also polled every 2s
  ← [ ...cleanup_log rows so far... ]   ← log fills in live
```

**Why poll the log separately?** The job endpoint only has a done/not-done signal. Polling the cleanup_log table separately lets the UI show decisions appearing row-by-row as the agent works, which is a much better demo moment than a blank spinner then a full table dump.

```python
@app.get("/api/cleanup/{upload_id}/log")
async def get_cleanup_log(upload_id: str):
    rows = db.execute(
        "SELECT * FROM cleanup_log WHERE upload_id=? ORDER BY executed_at",
        [upload_id]
    ).fetchall()
    return {"rows": rows}
```

---

## Screen 4 — Query + Output

**Pattern B: Turn-based JSON** (same shape as Screen 2)

```
POST /api/query/{upload_id}
  body: { message: "Show me revenue by region for Q4" }

  [LangGraph runs synchronously]
  router_node → decides route ("sql" | "eda" | "both")
  text2sql_node (if sql or both) → generates + runs SQL
  eda_node (if eda or both)     → runs Python analysis

  ← {
      chat: "North leads Q4 with $2.4M. Central has highest
             avg order value despite lowest volume.",
      canvas: {
        insights: [...],
        charts: [...],
        table: { columns: [...], rows: [...] }
      },
      route: "both",
      sql_query: "SELECT region, SUM(revenue)..."
    }
```

**Same synchronous approach as Screen 2.** LangGraph runs the full graph in one `invoke` call. The response comes back when the graph completes. For complex queries this might take 8–12s — acceptable for a demo. The frontend can show a loading state on the canvas while awaiting.

**History is just a SELECT:**
```
GET /api/query/{upload_id}/history
  ← [ ...query_history rows... ]
```

No agent needed. Just reads `query_history` table which gets a row appended after each query.

---

## Agent ↔ SQLite: Who Writes What

This is the most important thing to get right. Agents never write directly — they always go through tools. Tools are the only SQLite writers.

```
Agent                 Tool                    SQLite Table
─────────────────────────────────────────────────────────
AutoEDA agent    →  write_autoeda_result  →  jobs.result
Context agent    →  write_catalog_entry  →  catalog
                 →  mark_catalog_complete →  uploads (status flag)
Cleanup agent    →  write_cleanup_log    →  cleanup_log
                 →  commit_clean_data    →  clean_{upload_id}
Query agents     →  execute_sql          →  (reads clean_{id})
                 →  write_query_result   →  query_history
```

---

## FastAPI Project Layout

```
backend/
├── main.py              # All routes — thin, delegates to agents
├── database.py          # SQLite init, table creation, helper queries
├── models.py            # Pydantic request/response schemas
│
├── agents/
│   ├── autoeda.py       # LangGraph single-node agent
│   ├── context.py       # LangGraph single-node agent  
│   ├── cleanup.py       # LangGraph single-node agent
│   └── query_graph.py   # LangGraph 3-node graph (router→sql→eda)
│
└── tools/
    ├── dataframe.py     # get_dataframe_profile, sample_column_values
    ├── catalog.py       # get_catalog, write_catalog_entry, get_catalog_summary
    ├── python_repl.py   # run_python_analysis, run_python_cleaning
    ├── sql.py           # execute_sql, write_query_result
    └── chart.py         # generate_chart_spec (validation only, no render)
```

**main.py route map:**
```python
POST /api/upload                       → bg: run_autoeda()
GET  /api/jobs/{job_id}                → read jobs table
GET  /api/upload/{id}/autoeda          → read jobs.result for upload

POST /api/context/{id}/chat            → context_agent.invoke()
GET  /api/context/{id}/catalog         → read catalog table
POST /api/context/{id}/complete        → bg: run_cleanup()

GET  /api/cleanup/{id}/log             → read cleanup_log table

POST /api/query/{id}                   → query_graph.invoke()
GET  /api/query/{id}/history           → read query_history table
```

That's 9 endpoints total. Nothing exotic.

---

## Next.js Frontend Layout

```
frontend/app/
├── upload/page.tsx      # Screen 1 — usePolling(jobId)
├── context/page.tsx     # Screen 2 — useChatTurn()
├── cleanup/page.tsx     # Screen 3 — usePolling(jobId) + useLogPolling()
└── query/page.tsx       # Screen 4 — useChatTurn()

frontend/components/
├── Canvas.tsx           # Shared — renders CanvasResponse
├── ChartRenderer.tsx    # Bar, histogram, line, scatter via Recharts
├── InsightCards.tsx     # Stat / text / warning cards
├── ChatPanel.tsx        # Shared — message list + input
├── CatalogTable.tsx     # Screen 2 right panel
├── CleanupLog.tsx       # Screen 3 decision table
└── NavBar.tsx           # Step progress

frontend/lib/
├── api.ts               # Typed fetch wrappers for all 9 endpoints
├── types.ts             # CanvasResponse, ChartSpec, CatalogRow, etc.
└── hooks.ts             # usePolling, useChatTurn, useUploadId
```

**Two reusable hooks cover all interaction patterns:**

```typescript
// Pattern A — used by Screen 1 and Screen 3
function usePolling(jobId: string, interval = 2000) {
  // polls GET /api/jobs/{jobId} until status=done
  // returns { status, result, error }
}

// Pattern B — used by Screen 2 and Screen 4  
function useChatTurn(endpoint: string) {
  // POSTs message, awaits response
  // returns { send(msg), chat, canvas, loading }
}
```

---

## State Passed Between Screens

Screens share one piece of state: `upload_id`. Everything else is fetched from SQLite on demand.

```typescript
// Store in localStorage or a simple React context
const AppContext = {
  uploadId: string | null,     // set on Screen 1 upload
  // nothing else needed — all other state is in SQLite
}
```

Screen 2 reads catalog via `GET /api/context/{uploadId}/catalog`.  
Screen 3 reads log via `GET /api/cleanup/{uploadId}/log`.  
Screen 4 reads history via `GET /api/query/{uploadId}/history`.  
Each screen is independently refreshable.

---

## What This Architecture Deliberately Leaves Out

For a demo build these are correct omissions. Note them so you can explain the gap to the audience.

| Left out | Why omitted | What you'd add in production |
|---|---|---|
| Auth / sessions | Single user demo | JWT + user_id scoping on all tables |
| Job queue (Celery/Redis) | BackgroundTasks is fine for 1 user | Add when concurrent users matter |
| Streaming tokens | Polling is simpler, sufficient for demo | SSE or WebSocket for live token stream |
| File storage (S3) | Local disk fine for demo | S3/GCS for multi-user |
| Error retry logic | Manual retry via UI is fine | Exponential backoff + dead letter |
| Rate limiting | No need for demo | FastAPI middleware + per-user limits |
| Logging / tracing | Print statements fine for demo | LangSmith for agent tracing |
