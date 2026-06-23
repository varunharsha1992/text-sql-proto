# Feature 003 — Connected-Schema Query Canvas (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Screen 3 — schema-wide natural-language analytics via a DeepAgents orchestrator (Text2SQL + EDA subagents) with on-demand catalog/semantic tools, global query history, and a chat + canvas UI.

**Architecture:** Pattern B (synchronous turn-based). One user message → `POST /api/query/chat` → DeepAgents parent spawns `text2sql` and/or `eda` subagents. Specialists pull schema context via tools only (no prompt injection). Results persist to global `query_history` and render in `QueryCanvas` (insights, charts, results table).

**Tech Stack:** FastAPI + aiosqlite; `deepagents.create_deep_agent` + `SubAgent`; sync `@tool`s with `asyncio.run`; DeepSeek V4 Flash via `get_chat_model()`; Next.js 14 / TypeScript / Recharts.

**Spec:** `docs/superpowers/specs/2026-06-23-feature-003-connected-schema-query-canvas-design.md`

## Plan Revisions (post-review)

| # | Issue | Fix location |
|---|--------|--------------|
| 1 | Stale `_LAST_QUERY_TURN` top-level import in `query.py` | Task 5 — read/write via `sql_tools` module only |
| 2 | NavBar never unlocks Query step | Task 10 — `available` step state + clickable links |
| 3 | No LLM failure handling | Tasks 5–6 — try/except mirroring Phase 2 context agent |
| 4 | Table rows copied through LLM JSON | Task 3 — server-side table from `_LAST_SQL_RESULT` in `write_query_result` |

## Global Constraints

- Model: DeepSeek V4 Flash via OpenRouter through `backend.llm.get_chat_model()` — do NOT reconfigure.
- Schema-wide API: NO `upload_id` in query route paths. Tools use `slug` / `upload_id` only to map to `raw_{upload_id}` tables.
- This phase adds exactly TWO routes — `POST /api/query/chat`, `GET /api/query/history`. No others.
- Backend imports package-qualified; run Python with `PYTHONPATH=.` from repo root `C:/Dev/text-sql-proto/text-sql-proto`.
- No `Any` in Pydantic / no `any` in TypeScript.
- Tools never raise — return error strings/structures.
- Query gating: NavBar step 3 unlocks when `edaDone === true` (≥1 upload `status === "done"`). Context interview NOT required.
- Verification (NO pytest/jest): backend = `python -m py_compile` + inline snippet under `PYTHONPATH=.`; frontend = `npx tsc --noEmit`. Live agent turns need real `OPENROUTER_API_KEY` in `.env`.
- Dev proxy: document/set `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000` in `frontend/.env.local` for long sync turns.
- Hook naming: `useQueryTurn` for Query screen — `useChatTurn` is reserved for Context.
- Raw tables only: `backend.database.raw_table_name(upload_id)`.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/database.py` | modify | `query_history` table; `save_query_turn`, `get_query_history`, `any_upload_done` |
| `backend/tools/query_schema.py` | new | On-demand schema read tools |
| `backend/tools/sql.py` | new | `execute_sql`, `write_query_result`, `get_last_sql_result` |
| `backend/models.py` | modify | Query Pydantic models |
| `backend/agents/query.py` | new | DeepAgents orchestrator + subagents; `run_query_turn` |
| `backend/main.py` | modify | Two query routes |
| `frontend/lib/types.ts` | modify | Query TS interfaces |
| `frontend/lib/api.ts` | modify | `postQueryChat`, `getQueryHistory` |
| `frontend/lib/hooks.ts` | modify | `useQueryTurn` |
| `frontend/components/QueryChatPanel.tsx` | new | Chat + route badges + SQL blocks |
| `frontend/components/ResultsTable.tsx` | new | Renders `TableData` |
| `frontend/components/QueryCanvas.tsx` | new | Insights + charts + table |
| `frontend/app/query/page.tsx` | new | Screen 3 layout |
| `frontend/app/context/page.tsx` | modify | "Continue to Query Canvas →" forward nav |
| `frontend/components/NavBar.tsx` | modify | `available` step state + Link nav when `edaDone` |

---

## Execution Waves

| Wave | Tasks | Notes |
|------|-------|-------|
| 1 | Task 1 | DB foundation |
| 2 | Task 2 ‖ Task 3 ‖ Task 4 | Parallel — disjoint files |
| 3 | Task 5 | Agent (depends 2, 3) |
| 4 | Task 6 | Routes (depends 1, 4, 5) |
| 5 | Task 7 ‖ Task 8 | Frontend API/types then hook (Task 8 after 7 in same wave if one agent) |
| 6 | Task 9 | UI components |
| 7 | Task 10 | Page + NavBar |
| 8 | Task 11 | Live smoke test |

## Task Dependency Graph (Task IDs)

```
T1 → T6, T5 (indirect via write_query_result)
T2 → T5
T3 → T5
T4 → T6, T7
T5 → T6
T7 → T8
T8 → T10
T9 → T10
T10 → T11
```

## Subagent Dispatch Map

| Task ID | subagent_type | Skills to read first | Rationale |
|---------|---------------|----------------------|-----------|
| T1 | python-pro | — | SQLite helpers |
| T2 | python-pro | — | Sync LangChain tools |
| T3 | python-pro | — | SQL safety + persistence |
| T4 | generalPurpose | — | Pydantic + TS mirror |
| T5 | ai-engineer | langfuse (optional) | DeepAgents orchestration |
| T6 | fastapi-developer | — | FastAPI routes |
| T7 | nextjs-developer | — | API client |
| T8 | nextjs-developer | — | React hook |
| T9 | frontend-developer | frontend-design | Chat + canvas UI |
| T10 | nextjs-developer | — | Page wiring + NavBar |
| T11 | generalPurpose | verification-before-completion | E2E smoke |

---

## Task 1: `query_history` table + helpers

**Files:**
- Modify: `backend/database.py`

**Interfaces:**
- Produces: `save_query_turn(...) -> int` (returns new row id); `get_query_history() -> list[dict]` (oldest first); `any_upload_done() -> bool`.

- [ ] **Step 1: Add table to `create_tables`**

Inside the `executescript` string in `create_tables`, after the `context_conversations` block, add:

```sql
        CREATE TABLE IF NOT EXISTS query_history (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            user_query     TEXT NOT NULL,
            route          TEXT NOT NULL,
            route_reason   TEXT,
            sql_query      TEXT,
            chat_response  TEXT NOT NULL,
            canvas_json    TEXT NOT NULL,
            created_at     DATETIME DEFAULT CURRENT_TIMESTAMP
        );
```

- [ ] **Step 2: Append helpers**

At end of `backend/database.py`:

```python
async def any_upload_done() -> bool:
    """True when at least one upload has a latest job with status='done'."""
    for row in await list_uploads():
        if row.get("status") == "done":
            return True
    return False


async def save_query_turn(
    user_query: str,
    route: str,
    route_reason: str | None,
    sql_query: str | None,
    chat_response: str,
    canvas_json: str,
) -> int:
    db = await get_db()
    try:
        cur = await db.execute(
            """
            INSERT INTO query_history
                (user_query, route, route_reason, sql_query, chat_response, canvas_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_query, route, route_reason, sql_query, chat_response, canvas_json),
        )
        await db.commit()
        return int(cur.lastrowid)
    finally:
        await db.close()


async def get_query_history() -> list[dict]:
    db = await get_db()
    try:
        async with db.execute(
            "SELECT * FROM query_history ORDER BY id ASC"
        ) as cur:
            rows = await cur.fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]
    finally:
        await db.close()
```

- [ ] **Step 3: Verify**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && PYTHONPATH=. python -c "
import asyncio
from backend.database import create_tables, get_db, save_query_turn, get_query_history, any_upload_done
async def main():
    db = await get_db()
    await create_tables(db)
    await db.close()
    rid = await save_query_turn('q','sql','reason','SELECT 1','chat','{\"insights\":[],\"charts\":[],\"table\":null}')
    hist = await get_query_history()
    assert hist[-1]['id'] == rid
    print('ok', any_upload_done())
asyncio.run(main())
"
```

Expected: `ok True` or `ok False` (depending on DB state); no exception.

- [ ] **Step 4: Commit**

```bash
git add backend/database.py
git commit -m "feat(003): add global query_history table and helpers"
```

---

## Task 2: On-demand schema tools (`query_schema.py`)

**Files:**
- Create: `backend/tools/query_schema.py`

**Interfaces:**
- Produces sync `@tool`s: `list_tables`, `get_catalog_column`, `get_semantic_layer`, `get_data_dictionary`, `resolve_table`.
- Re-exports `get_schema_overview` from `backend.tools.catalog` for agent registration convenience.

- [ ] **Step 1: Create `backend/tools/query_schema.py`**

```python
"""Query Canvas schema read tools — on-demand, never context-injected."""

from __future__ import annotations

import asyncio
import json
import logging

from langchain_core.tools import tool

from backend.database import get_catalog, get_schema_semantic_layer, get_upload, list_uploads, raw_table_name
from backend.models import DataDictionaryEntry, SchemaSemanticLayer
from backend.tools.catalog import get_schema_overview

logger = logging.getLogger(__name__)

_SL_KEYS = ("tables", "relationships", "measures", "dimensions", "suggested_questions")


@tool
def list_tables() -> list[dict]:
    """List queryable tables (AutoEDA done only): slug, upload_id, row_count, col_count, status."""
    try:
        rows = asyncio.run(list_uploads())
        out = []
        for r in rows:
            if r.get("status") != "done":
                continue
            out.append({
                "slug": r["slug"],
                "upload_id": r["id"],
                "row_count": r.get("row_count"),
                "col_count": r.get("col_count"),
                "status": r.get("status"),
            })
        return out
    except Exception as exc:  # noqa: BLE001
        return [{"error": str(exc)}]


@tool
def get_catalog_column(slug: str, column_name: str) -> dict:
    """Full catalog row for one column: roles, FK ref, business_context, sample_values, null_pct, upload_id."""
    try:
        catalog = asyncio.run(get_catalog())
        for c in catalog:
            if c.get("slug") == slug and c.get("column_name") == column_name:
                samples = c.get("sample_values")
                if isinstance(samples, str):
                    try:
                        samples = json.loads(samples)
                    except json.JSONDecodeError:
                        samples = []
                return {
                    "upload_id": c.get("upload_id"),
                    "slug": slug,
                    "column_name": column_name,
                    "data_type": c.get("data_type"),
                    "semantic_role": c.get("semantic_role"),
                    "business_context": c.get("business_context"),
                    "description": c.get("description"),
                    "is_primary_key": bool(c.get("is_primary_key")),
                    "is_foreign_key": bool(c.get("is_foreign_key")),
                    "foreign_key_ref": c.get("foreign_key_ref"),
                    "is_pii": bool(c.get("is_pii")),
                    "unit": c.get("unit"),
                    "sample_values": samples if isinstance(samples, list) else [],
                    "null_pct": c.get("null_pct"),
                }
        return {"error": f"No catalog row for {slug}.{column_name}"}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@tool
def get_semantic_layer(section: str | None = None) -> dict:
    """Full or partial schema semantic layer. section: tables|relationships|measures|dimensions|suggested_questions or null for all."""
    try:
        raw = asyncio.run(get_schema_semantic_layer())
        data = json.loads(raw) if raw else {k: [] for k in _SL_KEYS}
        SchemaSemanticLayer(**data)  # validate stored shape
        if section and section in _SL_KEYS:
            return {section: data.get(section, [])}
        return data
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@tool
def get_data_dictionary(slug: str) -> list[dict]:
    """Per-table AutoEDA data dictionary entries from uploads.data_dictionary. Empty list if missing."""
    try:
        rows = asyncio.run(list_uploads())
        upload_id = next((r["id"] for r in rows if r.get("slug") == slug), None)
        if not upload_id:
            return [{"error": f"No upload with slug={slug!r}"}]
        upload = asyncio.run(get_upload(upload_id))
        if not upload:
            return []
        raw = upload.get("data_dictionary")
        if not raw:
            return []
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        out = []
        for item in parsed:
            try:
                out.append(DataDictionaryEntry(**item).model_dump())
            except Exception:
                continue
        return out
    except Exception as exc:  # noqa: BLE001
        return [{"error": str(exc)}]


@tool
def resolve_table(slug: str) -> dict:
    """Map human slug to SQLite raw table name: { upload_id, slug, raw_table }."""
    try:
        rows = asyncio.run(list_uploads())
        match = next((r for r in rows if r.get("slug") == slug), None)
        if not match:
            return {"error": f"No table with slug={slug!r}"}
        uid = match["id"]
        return {"upload_id": uid, "slug": slug, "raw_table": raw_table_name(uid)}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
```

- [ ] **Step 2: Verify**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && python -m py_compile backend/tools/query_schema.py && PYTHONPATH=. python -c "
from backend.tools.query_schema import list_tables, resolve_table
print(list_tables.invoke({}))
print(resolve_table.invoke({'slug': 'nonexistent'}))
"
```

Expected: compiles; list returns array (possibly empty); resolve returns error dict.

- [ ] **Step 3: Commit**

```bash
git add backend/tools/query_schema.py
git commit -m "feat(003): on-demand query schema read tools"
```

---

## Task 3: SQL tools (`sql.py`)

**Files:**
- Create: `backend/tools/sql.py`

**Interfaces:**
- Module state: `_LAST_SQL_RESULT: dict | None`, `_LAST_QUERY_TURN: dict | None` (set by tools).
- Produces: `execute_sql`, `write_query_result`, `get_last_sql_result`.

- [ ] **Step 1: Create `backend/tools/sql.py`**

```python
"""Query Canvas SQL execution + history persistence tools."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
from pathlib import Path

from langchain_core.tools import tool

from backend.database import _sqlite_file_path, save_query_turn
from backend.models import CanvasResponse

logger = logging.getLogger(__name__)

_LAST_SQL_RESULT: dict | None = None
_LAST_QUERY_TURN: dict | None = None

_BANNED = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|DETACH|PRAGMA|REPLACE|TRUNCATE)\b",
    re.IGNORECASE,
)
_LIMIT_RE = re.compile(r"\blimit\b", re.IGNORECASE)


def _is_read_only_sql(sql: str) -> bool:
    stripped = sql.strip().rstrip(";").strip()
    upper = stripped.upper()
    if not (upper.startswith("SELECT") or upper.startswith("WITH")):
        return False
    return _BANNED.search(stripped) is None


def _ensure_limit(sql: str, cap: int = 500) -> str:
    if _LIMIT_RE.search(sql):
        return sql
    return f"{sql.rstrip().rstrip(';')} LIMIT {cap}"


def _sync_query(sql: str) -> dict:
    path = _sqlite_file_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        cur = conn.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        serializable = []
        for row in rows:
            serializable.append([None if v is None else v for v in row])
        return {
            "columns": cols,
            "rows": serializable,
            "row_count": len(serializable),
        }
    finally:
        conn.close()


@tool
def execute_sql(sql: str) -> dict:
    """Run read-only SQL against SQLite raw tables (raw_{upload_id}). LIMIT 500 enforced if absent."""
    global _LAST_SQL_RESULT
    try:
        if not _is_read_only_sql(sql):
            return {"error": "Only read-only SELECT/WITH queries are allowed.", "columns": [], "rows": [], "row_count": 0}
        safe_sql = _ensure_limit(sql)
        result = _sync_query(safe_sql)
        _LAST_SQL_RESULT = result
        return result
    except Exception as exc:  # noqa: BLE001
        err = {"error": str(exc), "columns": [], "rows": [], "row_count": 0}
        _LAST_SQL_RESULT = err
        return err


@tool
def get_last_sql_result() -> dict:
    """Return the most recent execute_sql result in this orchestrator run (for EDA after SQL)."""
    if _LAST_SQL_RESULT is None:
        return {"error": "No SQL result yet in this turn."}
    return _LAST_SQL_RESULT


def _sql_result_to_table(result: dict | None) -> dict | None:
    """Build TableData dict from execute_sql output — server-side, not LLM-copied."""
    if not result or result.get("error"):
        return None
    cols = result.get("columns") or []
    rows = result.get("rows") or []
    if not cols:
        return None
    return {"columns": cols, "rows": rows}


@tool
def write_query_result(
    user_query: str,
    route: str,
    route_reason: str,
    chat_response: str,
    canvas_response: dict,
    sql_query: str | None = None,
) -> str:
    """Persist one query turn to global query_history. Call EXACTLY ONCE at end of orchestration.

    For route sql|both, table is attached server-side from the last execute_sql result —
    the model must NOT paste row data into canvas_response.table."""
    global _LAST_QUERY_TURN
    try:
        if route not in ("sql", "eda", "both"):
            return f"error: invalid route {route!r}"
        canvas = dict(canvas_response or {})
        if route in ("sql", "both"):
            server_table = _sql_result_to_table(_LAST_SQL_RESULT)
            if server_table is not None:
                canvas["table"] = server_table
        validated = CanvasResponse(**canvas)
        canvas_json = validated.model_dump_json()
        row_id = asyncio.run(
            save_query_turn(
                user_query=user_query,
                route=route,
                route_reason=route_reason,
                sql_query=sql_query,
                chat_response=chat_response,
                canvas_json=canvas_json,
            )
        )
        _LAST_QUERY_TURN = {
            "id": row_id,
            "user_query": user_query,
            "route": route,
            "route_reason": route_reason,
            "sql_query": sql_query,
            "chat": chat_response,
            "canvas": validated.model_dump(),
        }
        return "ok"
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}"
```

- [ ] **Step 2: Verify**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && PYTHONPATH=. python -c "
from backend.tools.sql import execute_sql, write_query_result, _is_read_only_sql, _ensure_limit, _sql_result_to_table
assert _is_read_only_sql('SELECT 1')
assert not _is_read_only_sql('DELETE FROM t')
assert 'LIMIT 500' in _ensure_limit('SELECT 1')
execute_sql.invoke({'sql': 'SELECT 1 AS x'})
t = _sql_result_to_table({'columns': ['x'], 'rows': [[1]]})
assert t == {'columns': ['x'], 'rows': [[1]]}
out = write_query_result.invoke({
    'user_query': 'q', 'route': 'sql', 'route_reason': 'test',
    'chat_response': 'hi', 'canvas_response': {'insights': [], 'charts': []},
    'sql_query': 'SELECT 1 AS x',
})
assert out == 'ok'
from backend.tools import sql as sql_tools
print('table attached:', sql_tools._LAST_QUERY_TURN['canvas']['table'])
"
```

Expected: `ok`; `table attached: {'columns': ['x'], 'rows': [[1]]}`.

- [ ] **Step 3: Commit**

```bash
git add backend/tools/sql.py
git commit -m "feat(003): execute_sql and write_query_result tools"
```

---

## Task 4: Query Pydantic + TypeScript models

**Files:**
- Modify: `backend/models.py`
- Modify: `frontend/lib/types.ts`

- [ ] **Step 1: Add to `backend/models.py` (after `SchemaResponse`)**

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

- [ ] **Step 2: Add to `frontend/lib/types.ts` (after `SchemaResponse`)**

```typescript
export type QueryRoute = "sql" | "eda" | "both";

export interface QueryChatRequest {
  message: string;
}

export interface QueryTurn {
  user_query: string;
  route: QueryRoute;
  route_reason?: string | null;
  sql_query?: string | null;
  chat: string;
  canvas: CanvasResponse;
}

export interface QueryChatResponse {
  chat: string;
  canvas: CanvasResponse;
  route: QueryRoute;
  route_reason: string;
  sql_query?: string | null;
}

export interface QueryHistoryResponse {
  turns: QueryTurn[];
}
```

- [ ] **Step 3: Verify**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && PYTHONPATH=. python -c "
from backend.models import QueryChatResponse, CanvasResponse
r=QueryChatResponse(chat='hi', canvas=CanvasResponse(insights=[], charts=[]), route='sql', route_reason='test')
print(r.model_dump_json())
" && cd frontend && npx tsc --noEmit
```

- [ ] **Step 4: Commit**

```bash
git add backend/models.py frontend/lib/types.ts
git commit -m "feat(003): Query API Pydantic and TypeScript models"
```

---

## Task 5: Query agent (`backend/agents/query.py`)

**Files:**
- Create: `backend/agents/query.py`

**Interfaces:**
- Produces: `async def run_query_turn(message: str) -> dict` with keys matching `QueryChatResponse`.

- [ ] **Step 1: Create `backend/agents/query.py`**

```python
"""Query Canvas — DeepAgents orchestrator with Text2SQL + EDA subagents."""

from __future__ import annotations

import json
import logging

from deepagents import create_deep_agent
from deepagents.middleware.subagents import SubAgent
from langchain_core.messages import AIMessage

from backend.llm import get_chat_model
from backend.tools.catalog import get_schema_overview
from backend.tools.chart import generate_chart_spec
from backend.tools.dataframe import sample_column_values
from backend.tools.python_repl import run_python_analysis
from backend.tools.query_schema import (
    get_catalog_column,
    get_data_dictionary,
    get_semantic_layer,
    list_tables,
    resolve_table,
)
from backend.tools.sql import (
    execute_sql,
    get_last_sql_result,
    write_query_result,
)

logger = logging.getLogger(__name__)

ORCHESTRATOR_PROMPT = """You are the Query Canvas orchestrator for a multi-table SQLite schema.

Procedure:
1. Read the user's business question.
2. Optionally call list_tables or get_schema_overview for lightweight grounding.
3. Decide route:
   - text2sql subagent: factual tabular answers, aggregations, JOINs, filters
   - eda subagent: distributions, correlations, patterns, statistical insight
   - both: SQL first (tabular result), then EDA to interpret/visualize
4. Delegate to the appropriate subagent(s) using your subagent tools.
5. Merge outputs when route=both: combined chat, merged canvas (insights+charts from EDA, table from SQL).
6. Call write_query_result EXACTLY ONCE with: user_query, route, route_reason, chat_response, canvas_response (insights + charts only — omit table rows), sql_query (nullable).

Canvas contract: { insights: InsightItem[], charts: ChartSpec[], table: null in your canvas_response }.
For sql/both routes, write_query_result attaches the results table server-side from execute_sql — do NOT copy rows into canvas_response.
Reply conversationally in chat_response — no raw JSON to the user."""

TEXT2SQL_PROMPT = """You are a senior analytics engineer writing multi-table SQLite SQL.

Rules:
- Call get_schema_overview and/or get_catalog_column / get_semantic_layer('relationships') BEFORE writing SQL.
- Use resolve_table(slug) to map slugs to raw_{upload_id} table names in SQL.
- Prefer catalog FK fields and schema relationships over guessing joins.
- Only SELECT/WITH. Always handle NULLs. Fix failed SQL up to 2 times via execute_sql errors.
- Call execute_sql to run the query; do NOT paste result rows into canvas_response — the server attaches the table.
- Optional: generate_chart_spec for a simple viz from results.
- Return structured output to orchestrator: chat_response, canvas_response (insights/charts only), sql_query."""

EDA_PROMPT = """You are a senior data scientist doing exploratory analysis across uploaded tables.

Rules:
- Call get_schema_overview or get_catalog_column before analysis.
- Use run_python_analysis(upload_id, code) with pandas/numpy/scipy.stats.
- sample_column_values helps ground questions.
- If SQL ran earlier in the turn, call get_last_sql_result to analyze those rows.
- generate_chart_spec for validated charts (max 5 total in canvas).
- Return chat_response + canvas_response (insights, charts; table usually null unless you tabulate in Python)."""

_AGENT = None


def build_query_agent():
    global _AGENT
    if _AGENT is None:
        text2sql = SubAgent(
            name="text2sql",
            description="Multi-table SQL generation and execution for business questions.",
            system_prompt=TEXT2SQL_PROMPT,
            tools=[
                get_schema_overview,
                get_catalog_column,
                get_semantic_layer,
                get_data_dictionary,
                resolve_table,
                execute_sql,
                generate_chart_spec,
            ],
        )
        eda = SubAgent(
            name="eda",
            description="Exploratory data analysis: patterns, stats, charts.",
            system_prompt=EDA_PROMPT,
            tools=[
                get_schema_overview,
                get_catalog_column,
                get_semantic_layer,
                get_data_dictionary,
                list_tables,
                resolve_table,
                sample_column_values,
                run_python_analysis,
                generate_chart_spec,
                get_last_sql_result,
            ],
        )
        _AGENT = create_deep_agent(
            model=get_chat_model(),
            tools=[list_tables, get_schema_overview, write_query_result],
            subagents=[text2sql, eda],
            system_prompt=ORCHESTRATOR_PROMPT,
        )
    return _AGENT


def _last_ai_text(state: dict) -> str:
    msgs = state.get("messages") or []
    for m in reversed(msgs):
        if isinstance(m, AIMessage):
            content = m.content
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = [p.get("text", "") if isinstance(p, dict) else str(p) for p in content]
                return "".join(parts)
    return ""


async def run_query_turn(message: str) -> dict:
    """Run one query turn synchronously. Returns QueryChatResponse-shaped dict."""
    from backend.tools import sql as sql_tools

    sql_tools._LAST_QUERY_TURN = None
    sql_tools._LAST_SQL_RESULT = None

    agent = build_query_agent()
    prompt = (
        f"User question: {message}\n\n"
        "Finish by calling write_query_result with the full turn payload."
    )
    try:
        final_state = await agent.ainvoke({"messages": [{"role": "user", "content": prompt}]})
    except Exception:  # noqa: BLE001
        logger.exception("Query agent turn failed")
        return {
            "chat": (
                "Sorry — I couldn't reach the analysis model just now. "
                "Please try again in a moment."
            ),
            "canvas": {"insights": [], "charts": [], "table": None},
            "route": "eda",
            "route_reason": "Model unavailable.",
            "sql_query": None,
        }

    if sql_tools._LAST_QUERY_TURN:
        t = sql_tools._LAST_QUERY_TURN
        return {
            "chat": t["chat"],
            "canvas": t["canvas"],
            "route": t["route"],
            "route_reason": t["route_reason"] or "",
            "sql_query": t.get("sql_query"),
        }

    # Fallback if agent forgot write_query_result
    fallback_chat = _last_ai_text(final_state if isinstance(final_state, dict) else {})
    return {
        "chat": fallback_chat or "I couldn't complete that query. Please try rephrasing.",
        "canvas": {"insights": [], "charts": [], "table": None},
        "route": "eda",
        "route_reason": "Agent did not persist a structured result.",
        "sql_query": None,
    }
```

- [ ] **Step 2: Verify compile**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && python -m py_compile backend/agents/query.py
```

- [ ] **Step 3: Commit**

```bash
git add backend/agents/query.py
git commit -m "feat(003): DeepAgents query orchestrator with SQL and EDA subagents"
```

---

## Task 6: API routes

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Add imports**

Near existing context imports, add:

```python
from backend.agents.query import run_query_turn
from backend.database import any_upload_done, get_query_history
from backend.models import (
    QueryChatRequest,
    QueryChatResponse,
    QueryHistoryResponse,
    QueryTurn,
)
```

- [ ] **Step 2: Add helper to map history rows**

```python
def _history_to_turns(rows: list[dict]) -> list[QueryTurn]:
    turns: list[QueryTurn] = []
    for r in rows:
        try:
            canvas = json.loads(r["canvas_json"])
            turns.append(
                QueryTurn(
                    user_query=r["user_query"],
                    route=r["route"],
                    route_reason=r.get("route_reason"),
                    sql_query=r.get("sql_query"),
                    chat=r["chat_response"],
                    canvas=CanvasResponse(**canvas),
                )
            )
        except (json.JSONDecodeError, ValidationError):
            logger.exception("Skipping invalid query_history row id=%s", r.get("id"))
    return turns
```

- [ ] **Step 3: Add routes (after context routes)**

```python
@app.post("/api/query/chat", response_model=QueryChatResponse)
async def query_chat(req: QueryChatRequest) -> QueryChatResponse:
    if not await any_upload_done():
        raise HTTPException(status_code=400, detail="Upload CSVs and wait for AutoEDA first.")
    try:
        turn = await run_query_turn(req.message)
    except Exception:  # noqa: BLE001 — defense in depth if run_query_turn ever raises
        logger.exception("Query chat route failed")
        raise HTTPException(
            status_code=500,
            detail="Query failed — please try again in a moment.",
        ) from None
    return QueryChatResponse(
        chat=turn["chat"],
        canvas=CanvasResponse(**turn["canvas"]) if isinstance(turn["canvas"], dict) else turn["canvas"],
        route=turn["route"],
        route_reason=turn["route_reason"],
        sql_query=turn.get("sql_query"),
    )


@app.get("/api/query/history", response_model=QueryHistoryResponse)
async def query_history() -> QueryHistoryResponse:
    rows = await get_query_history()
    return QueryHistoryResponse(turns=_history_to_turns(rows))
```

- [ ] **Step 4: Verify**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && python -m py_compile backend/main.py
```

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "feat(003): POST /api/query/chat and GET /api/query/history"
```

---

## Task 7: Frontend API wrappers

**Files:**
- Modify: `frontend/lib/api.ts`

- [ ] **Step 1: Extend imports and add functions**

```typescript
import type {
  JobResponse,
  UploadResponse,
  UploadsListResponse,
  SchemaResponse,
  ContextChatResponse,
  QueryChatResponse,
  QueryHistoryResponse,
} from "./types";

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
```

- [ ] **Step 2: Verify**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto/frontend" && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/api.ts
git commit -m "feat(003): query chat and history API wrappers"
```

---

## Task 8: `useQueryTurn` hook

**Files:**
- Modify: `frontend/lib/hooks.ts`

- [ ] **Step 1: Add types and hook**

Append after `useChatTurn`:

```typescript
import type { QueryTurn, CanvasResponse } from "./types";
import { postQueryChat, getQueryHistory } from "./api";

export interface QueryMessage {
  role: "user" | "agent";
  content: string;
  route?: "sql" | "eda" | "both";
  routeReason?: string | null;
  sqlQuery?: string | null;
}

export function useQueryTurn(): {
  messages: QueryMessage[];
  canvas: CanvasResponse | null;
  loading: boolean;
  error: string | null;
  send: (message: string) => Promise<void>;
} {
  const [messages, setMessages] = useState<QueryMessage[]>([]);
  const [canvas, setCanvas] = useState<CanvasResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const loadedRef = useRef(false);

  useEffect(() => {
    if (loadedRef.current) return;
    loadedRef.current = true;
    (async () => {
      try {
        const hist = await getQueryHistory();
        if (hist.turns.length === 0) return;
        setMessages(
          hist.turns.flatMap((t) => [
            { role: "user" as const, content: t.user_query },
            {
              role: "agent" as const,
              content: t.chat,
              route: t.route,
              routeReason: t.route_reason,
              sqlQuery: t.sql_query,
            },
          ])
        );
        setCanvas(hist.turns[hist.turns.length - 1].canvas);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load history");
      }
    })();
  }, []);

  const send = useCallback(async (message: string) => {
    setError(null);
    setLoading(true);
    setMessages((m) => [...m, { role: "user", content: message }]);
    try {
      const res = await postQueryChat(message);
      setMessages((m) => [
        ...m,
        {
          role: "agent",
          content: res.chat,
          route: res.route,
          routeReason: res.route_reason,
          sqlQuery: res.sql_query,
        },
      ]);
      setCanvas(res.canvas);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Query failed");
    } finally {
      setLoading(false);
    }
  }, []);

  return { messages, canvas, loading, error, send };
}
```

Also add `QueryTurn` and `CanvasResponse` to the top import from `./types`, and `postQueryChat`, `getQueryHistory` to the `./api` import.

- [ ] **Step 2: Verify**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto/frontend" && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/hooks.ts
git commit -m "feat(003): useQueryTurn hook with history restore"
```

---

## Task 9: Query UI components

**Files:**
- Create: `frontend/components/ResultsTable.tsx`
- Create: `frontend/components/QueryCanvas.tsx`
- Create: `frontend/components/QueryChatPanel.tsx`

- [ ] **Step 1: Create `ResultsTable.tsx`**

```tsx
import type { TableData } from "@/lib/types";

export default function ResultsTable({ table }: { table: TableData }) {
  return (
    <div className="overflow-x-auto rounded-lg" style={{ border: "1px solid var(--border)" }}>
      <table className="w-full text-[12px]" style={{ color: "var(--text)" }}>
        <thead style={{ background: "var(--bg3)" }}>
          <tr>
            {table.columns.map((c) => (
              <th key={c} className="text-left px-3 py-2 font-mono font-medium">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, i) => (
            <tr key={i} style={{ borderTop: "1px solid var(--border)" }}>
              {row.map((cell, j) => (
                <td key={j} className="px-3 py-1.5 font-mono">
                  {cell === null ? "—" : String(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 2: Create `QueryCanvas.tsx`**

Reuse patterns from `Canvas.tsx` — import `InsightCard`, `ChartRenderer`, `ResultsTable`:

```tsx
import type { CanvasResponse } from "@/lib/types";
import InsightCard from "@/components/InsightCards";
import ChartRenderer from "@/components/ChartRenderer";
import ResultsTable from "@/components/ResultsTable";

function LoadingSkeleton() {
  return (
    <div className="p-5 space-y-4">
      <div className="grid grid-cols-2 gap-3">
        {Array.from({ length: 2 }).map((_, i) => (
          <div key={i} className="h-48 rounded-lg bg-[var(--bg3)] animate-pulse" />
        ))}
      </div>
    </div>
  );
}

export default function QueryCanvas({
  canvas,
  loading,
}: {
  canvas: CanvasResponse | null;
  loading: boolean;
}) {
  if (loading && !canvas) return <LoadingSkeleton />;
  if (!canvas) {
    return (
      <div className="text-[13px] p-5" style={{ color: "var(--text3)" }}>
        Ask a question about your connected schema to see results here.
      </div>
    );
  }

  const stats = canvas.insights.filter((i) => i.type === "stat");
  const warnings = canvas.insights.filter((i) => i.type === "warning");
  const texts = canvas.insights.filter((i) => i.type === "text" || i.type === "badge");

  return (
    <div className="p-5 space-y-5">
      {stats.length > 0 && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {stats.map((s, i) => (
            <InsightCard key={i} item={s} />
          ))}
        </div>
      )}
      {warnings.map((w, i) => (
        <InsightCard key={`w-${i}`} item={w} />
      ))}
      {texts.map((t, i) => (
        <InsightCard key={`t-${i}`} item={t} />
      ))}
      {canvas.charts.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {canvas.charts.map((ch, i) => (
            <ChartRenderer key={i} spec={ch} />
          ))}
        </div>
      )}
      {canvas.table && <ResultsTable table={canvas.table} />}
    </div>
  );
}
```

- [ ] **Step 3: Create `QueryChatPanel.tsx`**

```tsx
"use client";

import { useState } from "react";
import type { QueryMessage } from "@/lib/hooks";

const ROUTE_STYLE: Record<string, { label: string; bg: string; color: string }> = {
  sql: { label: "SQL", bg: "rgba(99,179,237,0.15)", color: "#63B3ED" },
  eda: { label: "EDA", bg: "rgba(167,139,250,0.15)", color: "#A78BFA" },
  both: { label: "Both", bg: "rgba(110,231,183,0.15)", color: "var(--accent)" },
};

function RouteBadge({ route, reason }: { route?: string; reason?: string | null }) {
  if (!route) return null;
  const s = ROUTE_STYLE[route] ?? ROUTE_STYLE.eda;
  return (
    <span
      title={reason ?? undefined}
      className="inline-block text-[9px] font-mono px-1.5 py-0.5 rounded ml-1"
      style={{ background: s.bg, color: s.color }}
    >
      {s.label}
    </span>
  );
}

export default function QueryChatPanel({
  messages,
  loading,
  onSend,
}: {
  messages: QueryMessage[];
  loading: boolean;
  onSend: (msg: string) => void;
}) {
  const [draft, setDraft] = useState("");

  const submit = () => {
    const t = draft.trim();
    if (!t || loading) return;
    onSend(t);
    setDraft("");
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 min-h-0 overflow-y-auto space-y-3 p-1">
        {messages.map((m, i) => (
          <div key={i}>
            <div
              className="rounded-lg px-3 py-2 text-[13px] max-w-[90%]"
              style={{
                marginLeft: m.role === "user" ? "auto" : 0,
                background: m.role === "user" ? "var(--accent)" : "var(--bg3)",
                color: m.role === "user" ? "#000" : "var(--text)",
                whiteSpace: "pre-wrap",
              }}
            >
              {m.content}
              {m.role === "agent" && <RouteBadge route={m.route} reason={m.routeReason} />}
            </div>
            {m.role === "agent" && m.sqlQuery && (
              <details className="mt-1 text-[11px] max-w-[90%]">
                <summary className="cursor-pointer font-mono" style={{ color: "var(--text3)" }}>
                  SQL
                </summary>
                <pre
                  className="mt-1 p-2 rounded overflow-x-auto"
                  style={{ background: "var(--bg3)", color: "var(--text2)" }}
                >
                  {m.sqlQuery}
                </pre>
              </details>
            )}
          </div>
        ))}
        {loading && (
          <div className="text-[12px]" style={{ color: "var(--text3)" }}>
            Analysing…
          </div>
        )}
      </div>
      <div className="flex gap-2 pt-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          disabled={loading}
          placeholder="Ask about your data…"
          className="flex-1 rounded-lg px-3 py-2 text-[13px] outline-none"
          style={{ background: "var(--bg3)", border: "1px solid var(--border)", color: "var(--text)" }}
        />
        <button
          onClick={submit}
          disabled={loading}
          className="rounded-lg px-3 py-2 text-[13px] font-medium"
          style={{ background: "var(--bg4)", color: "var(--text)", opacity: loading ? 0.5 : 1 }}
        >
          Send
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Verify**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto/frontend" && npx tsc --noEmit
```

- [ ] **Step 5: Commit**

```bash
git add frontend/components/ResultsTable.tsx frontend/components/QueryCanvas.tsx frontend/components/QueryChatPanel.tsx
git commit -m "feat(003): QueryCanvas, ResultsTable, QueryChatPanel components"
```

---

## Task 10: Query page + NavBar gating + Context forward nav

**Files:**
- Create: `frontend/app/query/page.tsx`
- Modify: `frontend/components/NavBar.tsx`
- Modify: `frontend/app/context/page.tsx`

- [ ] **Step 1: Create `frontend/app/query/page.tsx`**

```tsx
"use client";

import { useQueryTurn } from "@/lib/hooks";
import QueryChatPanel from "@/components/QueryChatPanel";
import QueryCanvas from "@/components/QueryCanvas";

export default function QueryPage() {
  const { messages, canvas, loading, error, send } = useQueryTurn();

  return (
    <div className="flex-1 min-h-0 flex overflow-hidden" style={{ background: "var(--bg)" }}>
      <section
        className="w-[35%] shrink-0 flex flex-col p-4"
        style={{ borderRight: "1px solid var(--border)", background: "var(--bg2)" }}
      >
        {error && (
          <div className="text-[12px] mb-2" style={{ color: "var(--danger)" }}>
            {error}
          </div>
        )}
        <QueryChatPanel messages={messages} loading={loading} onSend={send} />
      </section>
      <main className="flex-1 min-h-0 overflow-y-auto">
        <QueryCanvas canvas={canvas} loading={loading} />
      </main>
    </div>
  );
}
```

- [ ] **Step 2: Update `NavBar.tsx` — add `available` state and clickable steps**

Replace the `StepState` type and `getStepState`:

```typescript
type StepState = "active" | "done" | "available" | "locked";

function getStepState(
  stepIndex: number,
  activeIndex: number,
  edaDone: boolean
): StepState {
  if (stepIndex === activeIndex) return "active";
  if (stepIndex < activeIndex) return "done";
  if (!edaDone) return "locked";
  // edaDone: steps not yet visited are navigable (Context + Query)
  return "available";
}
```

Update step styling in the map callback — treat `available` like `done` for color but with `cursor: pointer` and full opacity (not 0.35). Example color branch:

```typescript
color:
  state === "active"
    ? "var(--text)"
    : state === "done" || state === "available"
    ? "var(--text2)"
    : "var(--text3)",
opacity: state === "locked" ? 0.35 : 1,
cursor: state === "locked" ? "not-allowed" : "pointer",
```

Wrap each step label in `Link` when not locked:

```tsx
import Link from "next/link";

// inside STEPS.map:
const inner = (
  <div className="flex items-center gap-1.5 px-4 text-[12px] ..." style={{ ... }}>
    {/* step number + label */}
  </div>
);
return (
  <div key={step.path} className="flex items-stretch">
    {state === "locked" ? inner : <Link href={step.path}>{inner}</Link>}
    ...
  </div>
);
```

Remove the old "Step 3 always locked" comment and the `if (stepIndex === 2) return "locked"` branch.

- [ ] **Step 2b: Add forward nav on Context page**

Modify `frontend/app/context/page.tsx` — add a footer button (mirrors upload page):

```tsx
import { useRouter } from "next/navigation";
import { useUploadId } from "@/lib/hooks";

// inside component:
const router = useRouter();
const { edaDone } = useUploadId();

// below ChatPanel section or in a footer bar:
{edaDone && (
  <button
    type="button"
    onClick={() => router.push("/query")}
    className="mt-2 w-full rounded-lg px-3 py-2 text-[13px] font-medium"
    style={{ background: "var(--accent)", color: "#000" }}
  >
    Continue to Query Canvas →
  </button>
)}
```

This gives a second nav path besides the NavBar when Context is skipped.

- [ ] **Step 3: Optional dev env**

Create or append `frontend/.env.local`:

```
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

- [ ] **Step 4: Verify**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto/frontend" && npx tsc --noEmit
```

- [ ] **Step 5: Commit**

```bash
git add frontend/app/query/page.tsx frontend/app/context/page.tsx frontend/components/NavBar.tsx
git commit -m "feat(003): Query page, NavBar available steps, Context forward nav"
```

---

## Task 11: Live integrated smoke test

- [ ] **Step 1: Start servers**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && PYTHONPATH=. python -m uvicorn backend.main:app --reload --port 8000
# second shell
cd "C:/Dev/text-sql-proto/text-sql-proto/frontend" && npm run dev
```

Ensure `frontend/.env.local` has `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000`.

- [ ] **Step 2: Browser flow**

1. `/upload` — upload `test-data/smoke/smoke_customers.csv` and `test-data/smoke/smoke_orders.csv`; wait for both Ready.
2. **Nav path A:** Click **Query Canvas** in the NavBar (must show as `available`, not locked/faded). **Nav path B:** Click **Continue to Context →**, then **Continue to Query Canvas →**.
3. Confirm `/query` loads (do not type the URL manually unless verifying a fallback).
4. Ask: **"What is total order amount by customer country?"** (cross-table SQL).
5. Expect: agent turn with SQL badge, collapsible SQL block, **results table on canvas matching SQL output** (not empty fallback canvas), chat narrative.
6. Refresh page — history restores from `GET /api/query/history`; table rows still present.

- [ ] **Step 3: SQLite check**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && python -c "
import sqlite3, json
c=sqlite3.connect('data/app.db')
n=c.execute('SELECT COUNT(*) FROM query_history').fetchone()[0]
print('query_history rows:', n)
row=c.execute('SELECT route, substr(sql_query,1,60), substr(chat_response,1,80) FROM query_history ORDER BY id DESC LIMIT 1').fetchone()
print('latest:', row)
"
```

Expected: `query_history rows: >= 1`; latest route `sql` or `both`.

- [ ] **Step 4: Record progress**

Update `.superpowers/sdd/progress-feature003.md` (create if missing) with task checklist status.

---

## Self-Review

**Spec coverage:**
- Global `query_history` → Task 1. ✓
- On-demand tools (`list_tables`, `get_schema_overview`, `get_catalog_column`, `get_semantic_layer`, `get_data_dictionary`, `resolve_table`) → Task 2. ✓
- SQL tools (`execute_sql`, `write_query_result`, `get_last_sql_result`) → Task 3. ✓
- DeepAgents orchestrator + Text2SQL + EDA subagents → Task 5. ✓
- Two API routes, schema-wide → Task 6. ✓
- Pydantic + TS models → Task 4. ✓
- Frontend Screen 3 (chat + canvas + table + route badges + SQL block) → Tasks 8–10. ✓
- NavBar `edaDone` gating + Context forward button → Task 10. ✓
- `useQueryTurn` naming → Task 8. ✓
- Dev proxy note → Task 10, 11. ✓
- Error handling (400 empty schema, tool errors, SQL retry left to agent, LLM graceful degradation) → Tasks 3, 5, 6. ✓
- Server-side SQL table attachment (no LLM row copy) → Task 3. ✓
- `_LAST_QUERY_TURN` read via `sql_tools` module (no stale import) → Task 5. ✓

**Placeholder scan:** No TBD/TODO; code blocks are complete for each task.

**Type consistency:** `QueryTurn` / `QueryChatResponse` fields align across models (T4), `_history_to_turns` (T6), `useQueryTurn` (T8), and `write_query_result` (T3). `route` enum `sql|eda|both` consistent everywhere. Canvas uses existing `CanvasResponse` / `TableData`. Persisted `canvas_json.table` is populated server-side from `_LAST_SQL_RESULT` for sql/both routes.
