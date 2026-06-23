# Feature 003 — Connected-Schema Query Canvas (Design)

**Date:** 2026-06-23  
**Status:** Approved (brainstorming) — pending implementation plan  
**Supersedes:** `docs/superpowers/specs/2026-04-17-group3-query-canvas.md` (single-table, per-`upload_id`, context-injected catalog, LangGraph `Command` graph). That doc’s UI shape (chat + canvas, route badge, SQL block, history) is retained where noted below.  
**Builds on:** Feature 001 (per-table AutoEDA + `uploads.data_dictionary` / per-table semantic drafts), Feature 002 Phase 1 (multi-table upload list), Feature 002 Phase 2 (global `catalog`, `schema_meta.semantic_layer`, context interview).  
**Demo moment:** User asks a business question spanning multiple uploaded tables (e.g. “total order revenue by customer country”). A DeepAgents orchestrator delegates to a **Text2SQL** or **EDA** specialist. Specialists **pull schema context on demand via tools** — nothing is injected into the system prompt. The canvas shows narrative, optional chart, and/or a results table; SQL appears in a collapsible block when applicable.

---

## 1. Summary

The Query Canvas is Screen 3: natural-language analytics over the **global connected schema**. Unlike the superseded group3 spec, queries are **not scoped to a single `upload_id`**. The agent must JOIN across `raw_{upload_id}` tables using the validated **catalog** and **schema semantic layer** from Feature 002.

Two specialist subagents run under a **DeepAgents** orchestrator (same stack family as Feature 001 AutoEDA):

- **Text2SQL** — business question → multi-table SQL → execute → table + optional chart + narrative  
- **EDA** — patterns, distributions, correlations → insights + charts + narrative  

The orchestrator chooses which specialist(s) to invoke for each user message. Specialists **never** receive the full catalog or semantic layer in their system prompt; they **call tools** to fetch what they need.

---

## 2. Decisions (locked during brainstorming)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Query scope | **Schema-wide** — all `uploads` rows are queryable tables; no `upload_id` in API paths |
| 2 | Schema context delivery | **On-demand tools only** — catalog, schema semantic layer, and per-table data dictionary are **not** context-injected |
| 3 | Orchestration | **DeepAgents** (`create_deep_agent`) orchestrator spawning **Text2SQL** and **EDA** subagents (matches Feature 001 pattern) |
| 4 | Routing | **Two specialists** (SQL + EDA). Orchestrator may run one or both in a single turn via planning; no separate LangGraph `Command` supervisor node |
| 5 | Query gating | **≥1 table AutoEDA `done`** (`edaDone`) — Context interview **not** required to unlock Query |
| 6 | LLM | **`get_chat_model()`** — DeepSeek V4 Flash via OpenRouter (same as Features 001–002) |
| 7 | Data source | **`raw_{upload_id}`** SQLite tables only — no `clean_{id}` (never built) |
| 8 | History | **Global** `query_history` (one session for the schema), not per-`upload_id` |
| 9 | Dev proxy | Long sync turns must use **`NEXT_PUBLIC_API_URL=http://127.0.0.1:8000`** in frontend dev (Next.js rewrite timeout ~60s) |

---

## 3. Architecture

```
User question (POST /api/query/chat)
    ↓
Query Orchestrator (DeepAgents, backend/agents/query.py)
    │  tools: list_tables, get_schema_overview (lightweight grounding)
    │  spawns subagent(s) as needed
    ├── Text2SQL subagent
    │     tools: get_catalog_column, get_semantic_layer, get_data_dictionary,
    │             resolve_table, execute_sql, write_query_result, generate_chart_spec
    └── EDA subagent
          tools: get_catalog_column, get_semantic_layer, get_data_dictionary,
                  sample_column_values, run_python_analysis, generate_chart_spec,
                  get_sql_result (when continuing from SQL in same turn)

SQLite (source of truth)
    uploads, catalog, schema_meta, query_history, raw_{upload_id} × N
```

### Pattern

**Pattern B — turn-based JSON** (same as Context screen). One user message → one synchronous POST → one orchestrator run → one response `{ chat, canvas, route, route_reason, sql_query? }`. No polling, no WebSockets.

### Relationship to Feature 002 artifacts

| Artifact | Role in Query Canvas |
|----------|----------------------|
| **`catalog`** | Primary column-level truth after context interview; FK/PK, business_context, semantic_role |
| **`schema_meta.semantic_layer`** | Join paths (`relationships`), schema-level measures/dimensions, suggested_questions |
| **`uploads.data_dictionary`** | Fallback per-table profiler output when catalog row missing (pre-interview or incomplete seed) |
| **`uploads.semantic_layer`** | Per-table draft only; Query agents prefer schema semantic layer via tools |

Tools **prefer catalog + schema semantic layer** over re-running `detect_relationships()` heuristics on every query.

---

## 4. On-demand schema tools (NOT context injection)

All tools are sync `@tool`s (worker-thread safe with `asyncio.run` internally), catch their own errors, and return strings/structures — **never raise**. Query agents call these when needed; the system prompt stays compact (persona + procedure + output contract only).

### Shared read tools (`backend/tools/query_schema.py`, new)

| Tool | Signature | Returns |
|------|-----------|---------|
| `list_tables` | `() -> list[dict]` | Each table: `{ slug, upload_id, row_count, col_count, status }` from `list_uploads()` (done tables only for SQL) |
| `get_schema_overview` | `() -> dict` | **Reuse** Feature 002 `get_schema_overview` — tables grouped by slug with catalog columns + relationships + grain |
| `get_catalog_column` | `(slug: str, column_name: str) -> dict` | Full catalog row: roles, FK ref, business_context, sample_values, null_pct, upload_id |
| `get_semantic_layer` | `(section: str \| None) -> dict` | Full or partial `SchemaSemanticLayer` JSON: `tables`, `relationships`, `measures`, `dimensions`, `suggested_questions` |
| `get_data_dictionary` | `(slug: str) -> list[dict]` | Per-table AutoEDA `DataDictionaryEntry` list from `uploads.data_dictionary`; empty list if missing |
| `resolve_table` | `(slug: str) -> dict` | `{ upload_id, slug, raw_table: "raw_…" }` for SQL identifier mapping |

### Text2SQL tools (`backend/tools/sql.py`, new)

| Tool | Signature | Notes |
|------|-----------|-------|
| `execute_sql` | `(sql: str) -> dict` | Runs read-only SQL against SQLite. Agent references tables as **`raw_{upload_id}`** (tool docs explain mapping via `resolve_table`). Hard **`LIMIT 500`** appended if absent. Returns `{ columns, rows, row_count, error? }`. Max **2 retries** left to agent loop. |
| `write_query_result` | `(user_query, route, sql, canvas, chat) -> str` | Appends row to global `query_history` |

**SQL safety:** Only LLM-generated SQL executed; no user string concatenation into queries. Validator rejects statements that are not `SELECT` / `WITH` (read-only).

### EDA tools (reuse + extend)

| Tool | Source | Notes |
|------|--------|-------|
| `run_python_analysis` | `backend/tools/python_repl.py` | Existing; `(upload_id, code) -> str`. EDA subagent picks table(s) after `list_tables` / overview |
| `sample_column_values` | `backend/tools/dataframe.py` | Existing |
| `generate_chart_spec` | `backend/tools/chart.py` | Existing validation |
| `get_last_sql_result` | new in `sql.py` | Returns last `sql_results` from orchestrator state when EDA runs after SQL in same turn |

---

## 5. Agents (`backend/agents/query.py`, new)

### Orchestrator (DeepAgents parent)

- **Model:** `get_chat_model()`
- **Subagents:** `text2sql`, `eda` (registered with DeepAgents subagent API — mirror Feature 001 `create_deep_agent` usage)
- **Procedure:** Read user question → optionally call `list_tables` / `get_schema_overview` → spawn the appropriate subagent(s) → assemble final `{ chat, canvas, route, route_reason, sql_query }`
- **`route` values:** `"sql"` | `"eda"` | `"both"` (when both subagents contributed in one turn)
- **`route_reason`:** one-sentence orchestrator rationale (shown in badge tooltip)

### Text2SQL subagent persona

Senior analytics engineer; writes **multi-table SQL** using catalog FK fields and schema `relationships` before guessing joins; handles NULLs; always LIMIT; fixes failed SQL up to 2 times.

**Required tool order:** `get_schema_overview` or targeted `get_catalog_column` / `get_semantic_layer("relationships")` before writing SQL.

### EDA subagent persona

Senior data scientist; pandas/numpy/scipy.stats; interprets findings; returns insight cards + charts.

**Required tool order:** `get_schema_overview` or `get_catalog_column` before analysis code.

### Output contract (both subagents)

Must produce structured output consumed by orchestrator:

```python
{
  "chat_response": str,
  "canvas_response": CanvasResponse,  # insights, charts, table (table required for SQL path)
  "sql_query": str | None,            # Text2SQL only
}
```

`CanvasResponse.table` uses existing `TableData` shape (`columns`, `rows`).

---

## 6. Data layer

### New table: `query_history` (global)

```sql
CREATE TABLE IF NOT EXISTS query_history (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_query     TEXT NOT NULL,
    route          TEXT NOT NULL,       -- "sql" | "eda" | "both"
    route_reason   TEXT,
    sql_query      TEXT,
    chat_response  TEXT NOT NULL,
    canvas_json    TEXT NOT NULL,       -- serialized CanvasResponse
    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

Helpers in `backend/database.py`: `save_query_turn(...)`, `get_query_history() -> list[dict]`.

Idempotent `CREATE TABLE IF NOT EXISTS` in `create_tables()`.

---

## 7. API endpoints (`backend/main.py`)

Exactly **two** new routes (schema-wide, no path params):

```
POST /api/query/chat
  Body:     { message: string }
  Response: {
    chat: string,
    canvas: CanvasResponse,
    route: "sql" | "eda" | "both",
    route_reason: string,
    sql_query: string | null
  }
  Effects:  run query orchestrator synchronously; append query_history

GET /api/query/history
  Response: { turns: QueryTurn[] }
  Effects:  read query_history (newest last or first — pick one, document in plan)
```

### Pydantic models (`backend/models.py`)

```python
class QueryChatRequest(BaseModel):
    message: str

class QueryTurn(BaseModel):
    user_query: str
    route: Literal["sql", "eda", "both"]
    route_reason: str | None = None
    sql_query: str | None = None
    chat: str
    canvas: CanvasResponse

class QueryChatResponse(BaseModel):
    chat: str
    canvas: CanvasResponse
    route: Literal["sql", "eda", "both"]
    route_reason: str
    sql_query: str | None = None

class QueryHistoryResponse(BaseModel):
    turns: list[QueryTurn]
```

Mirror in `frontend/lib/types.ts`. No `any`.

---

## 8. Frontend — Screen 3 (`frontend/app/query/page.tsx`)

### Layout

Same split as Context / superseded group3:

- **Left (~35%):** query chat — turn list, route badges, collapsible SQL `<details>`, input  
- **Right (~65%):** query canvas — insights, charts, **results table**

### Gating

- **NavBar:** unlock Query step when `edaDone === true` (≥1 upload `done` on upload screen — existing `useUploadId` / `setEdaDone` flow)
- Remove “always locked” hardcode for step 3 in `NavBar.tsx`
- Optional: show suggested starters from `GET /api/context/schema` → `semantic_layer.suggested_questions` (nice-to-have, not blocking)

### Components

| Component | Notes |
|-----------|-------|
| `query/page.tsx` | New |
| `QueryChatPanel.tsx` | Extends ChatPanel pattern: route badge (SQL=blue, EDA=purple, Both=green), SQL block per turn |
| `QueryCanvas.tsx` | New — renders `CanvasResponse` **including `table`** via `ResultsTable.tsx`; loading skeleton while `loading` |
| `ResultsTable.tsx` | New — simple HTML table from `TableData` |

### Hooks & API

- **`useQueryTurn()`** in `hooks.ts` — **not** `useChatTurn` (reserved for Context)
- `postQueryChat(message)`, `getQueryHistory()` in `api.ts`
- Page load: `getQueryHistory()` restores prior turns; canvas shows latest turn’s canvas or empty state
- Each new query **replaces** right-panel canvas; chat scrolls history (group3 behavior)

### Dev note

Document in plan/README: set `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000` for local dev.

---

## 9. Error handling

| Case | Behavior |
|------|----------|
| Tool failure | Return error string; subagent reports conversationally; prior state preserved |
| SQL execution error | Agent retries up to 2 times; then friendly `chat` error, canvas unchanged |
| Orchestrator / LLM failure | HTTP 500 with graceful message; frontend shows inline error |
| Empty schema (no uploads) | `POST /api/query/chat` returns 400 “Upload CSVs first” |
| Missing catalog row | Subagent falls back to `get_data_dictionary(slug)` via tool |
| Python analysis | 30s timeout (`PYTHON_REPL_TIMEOUT_SEC`); restricted imports (existing) |

---

## 10. Testing (demo build)

No pytest/jest harness. Verify with:

- `python -m py_compile` on new modules
- Inline snippets: `execute_sql` LIMIT enforcement, read-only guard, `query_history` roundtrip
- `npx tsc --noEmit`
- Manual smoke: upload 2 related CSVs → optional context → ask cross-table SQL question → see table + SQL block → refresh restores history

---

## 11. Out of scope (deferred)

- Per-`upload_id` query endpoints (superseded by schema-wide model)
- Context-injected catalog blobs (`get_catalog_summary(upload_id)` as a single string in prompt)
- LangGraph `Command` supervisor graph from group3 (replaced by DeepAgents)
- `clean_{upload_id}` / cleanup agent
- Export CSV button (group3 nice-to-have)
- Query step gated on `context_complete` (user chose EDA-only gating)
- Relationship graph visualization
- Automated pruning of spurious heuristic relationships (agents should prefer validated catalog/FK fields)

---

## 12. Affected files (implementation preview)

**Backend (new):** `backend/agents/query.py`, `backend/tools/query_schema.py`, `backend/tools/sql.py`  
**Backend (modify):** `backend/database.py`, `backend/models.py`, `backend/main.py`  
**Frontend (new):** `frontend/app/query/page.tsx`, `QueryChatPanel.tsx`, `QueryCanvas.tsx`, `ResultsTable.tsx`  
**Frontend (modify):** `frontend/lib/types.ts`, `api.ts`, `hooks.ts`, `NavBar.tsx`

---

## 13. Self-review (2026-06-23)

- **Placeholders:** None — all endpoints, tools, and models specified.  
- **Consistency:** Schema-wide API aligns with Feature 002; tools-not-injection aligns with user requirement; DeepAgents aligns with Feature 001 and brainstorming choice.  
- **Scope:** Single feature spec suitable for one implementation plan; no cleanup-agent dependency.  
- **Ambiguity resolved:** History is global; gating is `edaDone`; raw tables only; `useQueryTurn` naming distinct from context hook.
