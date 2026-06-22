# DeepAgent-Driven AutoEDA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the deterministic-only AutoEDA with a DeepSeek-V4-Flash agent (LangChain `deepagents`) that orchestrates analysis tools, produces a data dictionary + semantic layer, streams progress, and falls back to the deterministic engine on failure.

**Architecture:** A FastAPI BackgroundTask parses the CSV (unchanged), then runs a `deepagents` agent over OpenRouter. The agent calls existing deterministic functions as tools (baseline canvas, dataframe profile, sandboxed python, chart validation), composes two new artifacts, and persists everything via one writer tool. The agent's `todos` are streamed to the job for a live UI checklist. If the agent errors/times out, the orchestrator persists the deterministic baseline so the user always gets a result.

**Tech Stack:** Python 3.12, FastAPI, aiosqlite, pandas/numpy, LangChain `deepagents` + `langchain-openai` (ChatOpenAI → OpenRouter), Next.js 14 / TypeScript / Recharts.

## Global Constraints

- **Model:** `deepseek/deepseek-v4-flash` via OpenRouter base URL `https://openrouter.ai/api/v1`; model id read from env `OPENROUTER_MODEL` (default to that value). API key from env `OPENROUTER_API_KEY`.
- **Endpoints:** Do NOT add HTTP endpoints beyond `POST /api/upload` and `GET /api/jobs/{job_id}`.
- **Raw table name:** `raw_{upload_id}` with non-alphanumerics stripped — use `backend.database.raw_table_name(upload_id)` (already exists). Never `raw_{slug}`.
- **No `Any` in Pydantic models / no `any` in TS** (existing convention).
- **Backend imports are package-qualified** (`from backend.x import y`); run Python with `PYTHONPATH=.` from the repo root `C:/Dev/text-sql-proto/text-sql-proto`.
- **Verification strategy (this repo has NO pytest harness — do not scaffold one):** verify each backend task with `python -m py_compile` plus an inline assertion snippet run as a throwaway script under `PYTHONPATH=.`; verify each frontend task with `npx tsc --noEmit` from `frontend/`. The final task is a manual end-to-end smoke test. Pipe noisy NumPy 1.x/2.x import warnings with `2>/dev/null` when running backend snippets.
- **Frontend design tokens:** reuse existing CSS vars (`--accent`, `--accent2`, `--accent3` amber, `--danger`, `--bg2/3/4`, `--text/2/3`, `--border`) — match `Canvas.tsx`/`InsightCards.tsx`.

---

## File Structure

**Backend**
- `backend/llm.py` (new) — OpenRouter `ChatOpenAI` factory. Sole owner of model config.
- `backend/models.py` (modify) — new artifact + progress models; extend `CanvasResponse`, `JobResponse`.
- `backend/database.py` (modify) — new columns + migration guards + `update_job_progress`, `update_upload_artifacts`; `get_job` joins `uploads`.
- `backend/tools/autoeda_baseline.py` (new) — `compute_baseline_canvas` tool wrapping the deterministic engine.
- `backend/tools/autoeda_writer.py` (modify) — persist new canvas fields + mirror artifacts to `uploads`.
- `backend/agents/autoeda.py` (rewrite) — `deepagents` agent builder, system/task prompts, progress-streaming runner.
- `backend/agents/autoeda_deterministic.py` (unchanged) — engine used by the baseline tool + fallback.
- `backend/main.py` (modify) — fallback wrapper in `run_autoeda_pipeline`; pass `job_id`; bump timeout.
- `backend/requirements.txt` (modify) — add `deepagents`.
- `.env` (modify) — add `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`.

**Frontend**
- `frontend/lib/types.ts` (modify) — mirror new models.
- `frontend/components/AgentProgress.tsx` (new) — live todo checklist.
- `frontend/components/DataDictionary.tsx` (new) — column metadata table.
- `frontend/components/SemanticLayer.tsx` (new) — grain / measures / dimensions / suggested questions.
- `frontend/components/Canvas.tsx` (modify) — render progress + new sections.
- `frontend/lib/hooks.ts` (modify) — expose `progress` from the polled job.

---

## Task 1: Dependencies, env, and OpenRouter model factory

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `.env`
- Create: `backend/llm.py`

**Interfaces:**
- Produces: `backend.llm.get_chat_model() -> langchain_core.language_models.BaseChatModel`

- [ ] **Step 1: Add `deepagents` to requirements**

Append one line to `backend/requirements.txt` (after `langgraph`):

```
deepagents
```

- [ ] **Step 2: Install it**

Run from repo root:

```bash
pip install deepagents
```

Expected: installs `deepagents` and its deps (langgraph etc.) without error.

- [ ] **Step 3: Add OpenRouter env vars**

Append to `.env` (repo root):

```
OPENROUTER_API_KEY=
OPENROUTER_MODEL=deepseek/deepseek-v4-flash
```

(Leave `OPENROUTER_API_KEY` blank for the engineer to fill; existing `OPENAI_API_KEY` stays untouched.)

- [ ] **Step 4: Create the model factory**

Create `backend/llm.py`:

```python
"""OpenRouter chat-model factory. Sole owner of LLM provider configuration."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

load_dotenv()

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_MODEL = "deepseek/deepseek-v4-flash"


def get_chat_model() -> BaseChatModel:
    """Return a ChatOpenAI bound to OpenRouter + DeepSeek V4 Flash (model id from env)."""
    return ChatOpenAI(
        model=os.getenv("OPENROUTER_MODEL", _DEFAULT_MODEL),
        base_url=_OPENROUTER_BASE_URL,
        api_key=os.getenv("OPENROUTER_API_KEY"),
        temperature=0,
    )
```

- [ ] **Step 5: Verify it compiles and constructs (no network)**

Run:

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && python -m py_compile backend/llm.py && PYTHONPATH=. python -c "import os; os.environ.setdefault('OPENROUTER_API_KEY','x'); from backend.llm import get_chat_model; m=get_chat_model(); print('model:', m.model_name)" 2>/dev/null
```

Expected: prints `model: deepseek/deepseek-v4-flash`.

- [ ] **Step 6: Commit**

```bash
git add backend/requirements.txt .env backend/llm.py
git commit -m "feat(autoeda): add deepagents dep + OpenRouter model factory"
```

---

## Task 2: Pydantic models for artifacts + progress

**Files:**
- Modify: `backend/models.py`

**Interfaces:**
- Consumes: existing `InsightItem`, `ChartSpec`, `TableData`, `CanvasResponse`, `JobResponse`.
- Produces:
  - `DataDictionaryEntry(column, dtype, semantic_type, description, sample_values, null_pct, unit, is_pii)`
  - `Measure(name, column, aggregation, description)`
  - `Dimension(name, column, description)`
  - `Entity(name, description, key_columns)`
  - `SemanticLayer(grain, entities, measures, dimensions, time_dimension, suggested_questions)`
  - `ProgressItem(text, status)`
  - `CanvasResponse` + `data_dictionary: list[DataDictionaryEntry] | None`, `semantic_layer: SemanticLayer | None`
  - `JobResponse` + `progress: list[ProgressItem] | None`

- [ ] **Step 1: Add the new models**

In `backend/models.py`, after the `TableData` class and before `CanvasResponse`, insert:

```python
# ── Data dictionary ──────────────────────────────────────────────────────────
class DataDictionaryEntry(BaseModel):
    column: str
    dtype: str
    semantic_type: Literal[
        "identifier", "categorical", "numeric", "temporal", "currency", "boolean", "text"
    ]
    description: str
    sample_values: list[str]
    null_pct: float
    unit: str | None = None
    is_pii: bool = False


# ── Semantic layer ───────────────────────────────────────────────────────────
class Measure(BaseModel):
    name: str
    column: str
    aggregation: Literal["sum", "avg", "count", "count_distinct", "min", "max", "median"]
    description: str


class Dimension(BaseModel):
    name: str
    column: str
    description: str


class Entity(BaseModel):
    name: str
    description: str
    key_columns: list[str]


class SemanticLayer(BaseModel):
    grain: str
    entities: list[Entity]
    measures: list[Measure]
    dimensions: list[Dimension]
    time_dimension: str | None = None
    suggested_questions: list[str]


# ── Progress (streamed agent todos) ──────────────────────────────────────────
class ProgressItem(BaseModel):
    text: str
    status: Literal["pending", "in_progress", "completed"]
```

- [ ] **Step 2: Extend `CanvasResponse`**

Replace the existing `CanvasResponse` class body with:

```python
class CanvasResponse(BaseModel):
    insights: list[InsightItem]
    charts: list[ChartSpec]
    table: TableData | None = None
    data_dictionary: list[DataDictionaryEntry] | None = None
    semantic_layer: SemanticLayer | None = None
```

- [ ] **Step 3: Extend `JobResponse`**

Replace the existing `JobResponse` class body with:

```python
class JobResponse(BaseModel):
    job_id: str
    status: Literal["pending", "running", "done", "error"]
    result: CanvasResponse | None = None
    error: str | None = None
    progress: list[ProgressItem] | None = None
```

- [ ] **Step 4: Verify compile + round-trip**

Run:

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && python -m py_compile backend/models.py && PYTHONPATH=. python -c "
from backend.models import CanvasResponse, SemanticLayer, DataDictionaryEntry, JobResponse, ProgressItem
c = CanvasResponse(insights=[], charts=[], data_dictionary=[DataDictionaryEntry(column='revenue', dtype='float64', semantic_type='currency', description='Order revenue', sample_values=['100.0'], null_pct=8.5, unit='USD')], semantic_layer=SemanticLayer(grain='one order', entities=[], measures=[], dimensions=[], suggested_questions=['Total revenue by region?']))
j = JobResponse(job_id='j', status='running', progress=[ProgressItem(text='Profiling data', status='in_progress')])
print('canvas ok:', c.data_dictionary[0].semantic_type, '| job ok:', j.progress[0].status)
" 2>/dev/null
```

Expected: `canvas ok: currency | job ok: in_progress`.

- [ ] **Step 5: Commit**

```bash
git add backend/models.py
git commit -m "feat(autoeda): add data dictionary, semantic layer, progress models"
```

---

## Task 3: DB columns, migration guards, and helpers

**Files:**
- Modify: `backend/database.py`

**Interfaces:**
- Consumes: existing `get_db`, `create_tables`, `update_job`, `get_job`, `raw_table_name`.
- Produces:
  - `update_job_progress(job_id: str, progress_json: str) -> None`
  - `update_upload_artifacts(upload_id: str, data_dictionary: str, semantic_layer: str) -> None`
  - `get_job(job_id)` returns dict additionally containing keys `data_dictionary`, `semantic_layer`, `progress` (any may be `None`).

- [ ] **Step 1: Add migration guards inside `create_tables`**

In `backend/database.py`, inside `create_tables`, after the existing `await db.executescript(...)` block and before `await db.commit()`, insert:

```python
    # Idempotent column migrations for existing databases.
    _migrations = [
        "ALTER TABLE uploads ADD COLUMN data_dictionary TEXT",
        "ALTER TABLE uploads ADD COLUMN semantic_layer TEXT",
        "ALTER TABLE jobs ADD COLUMN progress TEXT",
    ]
    for stmt in _migrations:
        try:
            await db.execute(stmt)
        except Exception as exc:  # noqa: BLE001 - "duplicate column name" is expected on re-run
            if "duplicate column name" not in str(exc).lower():
                raise
```

- [ ] **Step 2: Add the two helper functions**

In `backend/database.py`, after `update_job`, add:

```python
async def update_job_progress(job_id: str, progress_json: str) -> None:
    db = await get_db()
    try:
        await db.execute(
            "UPDATE jobs SET progress = ?, updated_at = CURRENT_TIMESTAMP WHERE job_id = ?",
            (progress_json, job_id),
        )
        await db.commit()
    finally:
        await db.close()


async def update_upload_artifacts(
    upload_id: str,
    data_dictionary: str,
    semantic_layer: str,
) -> None:
    db = await get_db()
    try:
        await db.execute(
            "UPDATE uploads SET data_dictionary = ?, semantic_layer = ? WHERE id = ?",
            (data_dictionary, semantic_layer, upload_id),
        )
        await db.commit()
    finally:
        await db.close()
```

- [ ] **Step 3: Make `get_job` attach upload artifacts**

Replace the body of `get_job` with:

```python
async def get_job(job_id: str) -> dict | None:
    db = await get_db()
    try:
        async with db.execute(
            """
            SELECT j.*, u.data_dictionary AS data_dictionary, u.semantic_layer AS semantic_layer
            FROM jobs j
            LEFT JOIN uploads u ON u.id = j.upload_id
            WHERE j.job_id = ?
            """,
            (job_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return {key: row[key] for key in row.keys()}
    finally:
        await db.close()
```

- [ ] **Step 4: Verify migration idempotency + helpers**

Run:

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && python -m py_compile backend/database.py && PYTHONPATH=. python -c "
import asyncio, tempfile, os
d = tempfile.mkdtemp(); os.environ['DATABASE_URL'] = f'sqlite+aiosqlite:///{d}/t.db'
from backend.database import get_db, create_tables, create_upload, create_job, update_job_progress, update_upload_artifacts, get_job
async def main():
    db = await get_db(); await create_tables(db); await create_tables(db); await db.close()  # twice = idempotent
    await create_upload('u1','f.csv','f','/p'); await create_job('j1','autoeda','u1')
    await update_job_progress('j1','[{\"text\":\"x\",\"status\":\"pending\"}]')
    await update_upload_artifacts('u1','[]','{}')
    row = await get_job('j1')
    print('keys ok:', 'progress' in row and 'data_dictionary' in row and 'semantic_layer' in row)
    print('values ok:', row['progress'].startswith('['), row['data_dictionary']=='[]', row['semantic_layer']=='{}')
asyncio.run(main())
" 2>/dev/null
```

Expected: `keys ok: True` then `values ok: True True True`.

- [ ] **Step 5: Commit**

```bash
git add backend/database.py
git commit -m "feat(autoeda): db columns + helpers for artifacts and progress"
```

---

## Task 4: `compute_baseline_canvas` tool

**Files:**
- Create: `backend/tools/autoeda_baseline.py`

**Interfaces:**
- Consumes: `backend.agents.autoeda_deterministic.build_autoeda_canvas_sync(upload_id) -> dict`.
- Produces: `compute_baseline_canvas` (a LangChain `@tool`) returning a `CanvasResponse`-shaped dict with keys `insights`, `charts`, `table`. Also exports the plain callable `baseline_canvas(upload_id) -> dict` for the fallback path (Task 7).

- [ ] **Step 1: Create the tool**

Create `backend/tools/autoeda_baseline.py`:

```python
"""Tool: compute_baseline_canvas — guaranteed deterministic stats/warnings/charts.

The agent is instructed to call this FIRST so the spec's required stat cards,
>5% null warnings, outlier warnings, and <=5 charts are always present even if
the LLM does nothing else useful.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from backend.agents.autoeda_deterministic import build_autoeda_canvas_sync


def baseline_canvas(upload_id: str) -> dict[str, Any]:
    """Plain callable: deterministic CanvasResponse dict (insights/charts/table)."""
    return build_autoeda_canvas_sync(upload_id)


@tool
def compute_baseline_canvas(upload_id: str) -> dict:
    """Compute the guaranteed baseline analysis for an upload.

    Returns a dict with keys: insights (stat cards + null/outlier warnings),
    charts (up to 5, auto-selected), and table (null). Call this FIRST, then
    build the data dictionary and semantic layer on top of it.
    """
    return baseline_canvas(upload_id)
```

- [ ] **Step 2: Verify against a synthetic upload**

Run:

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && python -m py_compile backend/tools/autoeda_baseline.py && PYTHONPATH=. python -c "
import asyncio, tempfile, os, csv, random
d = tempfile.mkdtemp(); os.environ['DATABASE_URL']=f'sqlite+aiosqlite:///{d}/t.db'
p=os.path.join(d,'o.csv')
rows=[['order_id','order_date','region','revenue','discount_pct']]; random.seed(1)
for i in range(120):
    rev='' if i%12==0 else f'\${random.randint(10,900)}.00'
    disc=250 if i in (5,50) else random.randint(0,40)
    rows.append([f'o{i}', f'2024-{(i%12)+1:02d}-15', random.choice(['X','Y','Z']), rev, disc])
open(p,'w',newline='').write('')
import csv as _c
with open(p,'w',newline='') as f: _c.writer(f).writerows(rows)
from backend.database import get_db, create_tables, create_upload
from backend.utils.csv_parser import parse_csv_to_sqlite
from backend.tools.autoeda_baseline import baseline_canvas
async def boot():
    db=await get_db(); await create_tables(db); await db.close(); await create_upload('u1','o.csv','o',p)
asyncio.run(boot()); parse_csv_to_sqlite('u1','o',p)
c=baseline_canvas('u1')
print('has stats:', any(i['type']=='stat' for i in c['insights']))
print('has outlier warn:', any(i['type']=='warning' and 'discount' in i.get('content','') for i in c['insights']))
print('charts:', len(c['charts']))
" 2>/dev/null
```

Expected: `has stats: True`, `has outlier warn: True`, `charts:` a number ≥ 2.

- [ ] **Step 3: Commit**

```bash
git add backend/tools/autoeda_baseline.py
git commit -m "feat(autoeda): compute_baseline_canvas tool + fallback callable"
```

---

## Task 5: Extend `write_autoeda_result` to persist artifacts

**Files:**
- Modify: `backend/tools/autoeda_writer.py`

**Interfaces:**
- Consumes: `backend.database.update_job`, `backend.database.update_upload_artifacts`.
- Produces:
  - `persist_autoeda_canvas(upload_id: str, canvas_response: dict) -> None` — now also mirrors `data_dictionary` + `semantic_layer` to the `uploads` row.
  - `write_autoeda_result` tool — unchanged signature `(upload_id, canvas_response) -> str`, returns `"ok"` or error string.

- [ ] **Step 1: Update `persist_autoeda_canvas`**

In `backend/tools/autoeda_writer.py`, replace the `persist_autoeda_canvas` function with:

```python
async def persist_autoeda_canvas(upload_id: str, canvas_response: dict) -> None:
    """Write CanvasResponse JSON to the latest job (status=done) and mirror
    data_dictionary + semantic_layer to the uploads row for downstream features."""
    job_id = await _find_job_id(upload_id)
    if job_id is None:
        raise ValueError(f"No job found for upload_id={upload_id!r}")
    json_str = json.dumps(canvas_response)
    await update_job(job_id, "done", result=json_str)
    dd = canvas_response.get("data_dictionary")
    sl = canvas_response.get("semantic_layer")
    await update_upload_artifacts(
        upload_id,
        json.dumps(dd) if dd is not None else None,
        json.dumps(sl) if sl is not None else None,
    )
    logger.info("AutoEDA result persisted for upload_id=%s job_id=%s", upload_id, job_id)
```

- [ ] **Step 2: Update the import line**

In `backend/tools/autoeda_writer.py`, change:

```python
from backend.database import update_job
```

to:

```python
from backend.database import update_job, update_upload_artifacts
```

- [ ] **Step 3: Allow `None` args in `update_upload_artifacts`**

This requires `update_upload_artifacts` to accept `str | None`. In `backend/database.py`, change its signature from:

```python
async def update_upload_artifacts(
    upload_id: str,
    data_dictionary: str,
    semantic_layer: str,
) -> None:
```

to:

```python
async def update_upload_artifacts(
    upload_id: str,
    data_dictionary: str | None,
    semantic_layer: str | None,
) -> None:
```

(Body unchanged — SQLite accepts `None` as NULL.)

- [ ] **Step 4: Verify persist writes both places**

Run:

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && python -m py_compile backend/tools/autoeda_writer.py backend/database.py && PYTHONPATH=. python -c "
import asyncio, tempfile, os, json
d=tempfile.mkdtemp(); os.environ['DATABASE_URL']=f'sqlite+aiosqlite:///{d}/t.db'
from backend.database import get_db, create_tables, create_upload, create_job, get_job
from backend.tools.autoeda_writer import persist_autoeda_canvas
async def main():
    db=await get_db(); await create_tables(db); await db.close()
    await create_upload('u1','f.csv','f','/p'); await create_job('j1','autoeda','u1')
    canvas={'insights':[],'charts':[],'table':None,'data_dictionary':[{'column':'c'}],'semantic_layer':{'grain':'row'}}
    await persist_autoeda_canvas('u1', canvas)
    row=await get_job('j1')
    print('job done:', row['status']=='done')
    print('result has dict:', 'data_dictionary' in json.loads(row['result']))
    print('upload dict mirrored:', json.loads(row['data_dictionary'])[0]['column']=='c')
    print('upload semantic mirrored:', json.loads(row['semantic_layer'])['grain']=='row')
asyncio.run(main())
" 2>/dev/null
```

Expected: four lines all ending `True`.

- [ ] **Step 5: Commit**

```bash
git add backend/tools/autoeda_writer.py backend/database.py
git commit -m "feat(autoeda): persist data dictionary + semantic layer on write"
```

---

## Task 6: DeepAgent builder + prompts + progress-streaming runner

**Files:**
- Rewrite: `backend/agents/autoeda.py`

**Interfaces:**
- Consumes: `backend.llm.get_chat_model`; tools `compute_baseline_canvas`, `get_dataframe_profile`, `run_python_analysis`, `generate_chart_spec`, `write_autoeda_result`; `backend.database.update_job_progress`.
- Produces:
  - `build_deep_agent()` — cached compiled agent (module-level singleton).
  - `run_autoeda_agent(upload_id: str, job_id: str) -> None` — streams todos → `update_job_progress`; the agent persists the result via its `write_autoeda_result` tool.

- [ ] **Step 1: Rewrite `backend/agents/autoeda.py`**

Replace the entire file with:

```python
"""AutoEDA agent — DeepSeek V4 Flash via OpenRouter, orchestrated by deepagents.

The agent owns the pipeline: it calls compute_baseline_canvas first (guaranteed
stats/warnings/charts), profiles the data, runs deeper analysis, builds a data
dictionary + semantic layer, and persists everything via write_autoeda_result.
Progress (the agent's todo list) is streamed to jobs.progress for the UI.
"""

from __future__ import annotations

import json
import logging

from deepagents import create_deep_agent

from backend.database import update_job_progress
from backend.llm import get_chat_model
from backend.tools.autoeda_baseline import compute_baseline_canvas
from backend.tools.autoeda_writer import write_autoeda_result
from backend.tools.chart import generate_chart_spec
from backend.tools.dataframe import get_dataframe_profile
from backend.tools.python_repl import run_python_analysis

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are AutoEDA, an expert data analyst agent. Given an uploaded \
dataset (one CSV table), you profile it, surface data-quality issues, build charts, \
and produce a data dictionary and a semantic layer.

Procedure (follow in order):
1. Call compute_baseline_canvas(upload_id) FIRST. This returns guaranteed stat cards, \
null/outlier warnings, and up to 5 charts. Keep ALL of these in your final output.
2. Call get_dataframe_profile(upload_id) to understand columns, dtypes, and stats.
3. Use run_python_analysis(upload_id, code) for deeper analysis when it adds insight \
(correlations, segment breakdowns, anomalies). Add the most useful findings as \
extra insight items (type "text"). Do not exceed 5 charts total.
4. Build a DATA DICTIONARY: one entry per column with column, dtype, semantic_type \
(one of identifier|categorical|numeric|temporal|currency|boolean|text), a concise \
description, up to 5 sample_values (as strings), null_pct (number), optional unit, \
and is_pii (true for names/emails/phones/addresses).
5. Build a SEMANTIC LAYER: grain (what one row represents), entities, measures \
(name, column, aggregation in sum|avg|count|count_distinct|min|max|median, \
description), dimensions (name, column, description), time_dimension (or null), \
and 3-6 suggested_questions a business user might ask.
6. Call write_autoeda_result(upload_id, canvas_response) EXACTLY ONCE with the \
complete object. canvas_response must be a JSON object with keys: insights (list), \
charts (list, <=5), table (null), data_dictionary (list), semantic_layer (object).

Use the write_todos planning tool to track your steps so the user sees progress. \
Keep the baseline insights and charts intact; only add to them."""


def _task_prompt(upload_id: str) -> str:
    return (
        f"Analyze the uploaded dataset with upload_id='{upload_id}'. "
        f"Pass this exact upload_id to every tool call. Follow the procedure and "
        f"finish by calling write_autoeda_result exactly once."
    )


_AGENT = None


def build_deep_agent():
    """Build (once) and return the compiled deep agent."""
    global _AGENT
    if _AGENT is None:
        _AGENT = create_deep_agent(
            model=get_chat_model(),
            tools=[
                compute_baseline_canvas,
                get_dataframe_profile,
                run_python_analysis,
                generate_chart_spec,
                write_autoeda_result,
            ],
            system_prompt=SYSTEM_PROMPT,
        )
    return _AGENT


def _todos_to_progress(todos: list) -> list[dict]:
    """Map deepagents todo dicts to ProgressItem-shaped dicts."""
    out: list[dict] = []
    for t in todos:
        if isinstance(t, dict):
            text = str(t.get("content") or t.get("text") or "")
            status = str(t.get("status") or "pending")
        else:
            text, status = str(t), "pending"
        if status not in ("pending", "in_progress", "completed"):
            status = "pending"
        if text:
            out.append({"text": text, "status": status})
    return out


async def run_autoeda_agent(upload_id: str, job_id: str) -> None:
    """Run the agent, streaming its todo list to jobs.progress as it goes.

    The agent persists the final CanvasResponse itself via write_autoeda_result.
    """
    logger.info("AutoEDA agent start upload_id=%s job_id=%s", upload_id, job_id)
    agent = build_deep_agent()
    last_serialized = ""
    async for state in agent.astream(
        {"messages": [{"role": "user", "content": _task_prompt(upload_id)}]},
        stream_mode="values",
    ):
        todos = state.get("todos") if isinstance(state, dict) else None
        if todos:
            progress = _todos_to_progress(todos)
            serialized = json.dumps(progress)
            if serialized != last_serialized:
                await update_job_progress(job_id, serialized)
                last_serialized = serialized
    logger.info("AutoEDA agent finished upload_id=%s job_id=%s", upload_id, job_id)
```

- [ ] **Step 2: Verify it imports and builds offline**

Run:

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && python -m py_compile backend/agents/autoeda.py && PYTHONPATH=. python -c "import os; os.environ.setdefault('OPENROUTER_API_KEY','x'); from backend.agents.autoeda import build_deep_agent, _todos_to_progress; a=build_deep_agent(); print('agent built:', a is not None); print(_todos_to_progress([{'content':'Profile data','status':'in_progress'},{'content':'','status':'pending'}]))" 2>/dev/null
```

Expected: `agent built: True` then `[{'text': 'Profile data', 'status': 'in_progress'}]`.

> If `create_deep_agent` raises on the kwargs above (API drift), check the installed version's signature with `PYTHONPATH=. python -c "import inspect, deepagents; print(inspect.signature(deepagents.create_deep_agent))"` and adjust `system_prompt`/`tools` keyword names to match. Do not change the model wiring.

- [ ] **Step 3: Commit**

```bash
git add backend/agents/autoeda.py
git commit -m "feat(autoeda): deepagents orchestrator with progress streaming"
```

---

## Task 7: Fallback wrapper + wiring in `main.py`

**Files:**
- Modify: `backend/main.py`

**Interfaces:**
- Consumes: `run_autoeda_agent(upload_id, job_id)`, `baseline_canvas(upload_id)`, `persist_autoeda_canvas(upload_id, canvas)`, `get_job`, `update_job`.
- Produces: `run_autoeda_pipeline(upload_id, job_id, slug)` — parses CSV, runs the agent with timeout, falls back to the deterministic baseline on any failure or if the job is not `done` afterward.

- [ ] **Step 1: Update imports in `main.py`**

In `backend/main.py`, replace:

```python
from backend.agents.autoeda import run_autoeda_agent
from backend.database import (
    create_job,
    create_tables,
    create_upload,
    get_db,
    get_job,
    update_job,
)
```

with:

```python
from backend.agents.autoeda import run_autoeda_agent
from backend.database import (
    create_job,
    create_tables,
    create_upload,
    get_db,
    get_job,
    update_job,
)
from backend.tools.autoeda_baseline import baseline_canvas
from backend.tools.autoeda_writer import persist_autoeda_canvas
```

- [ ] **Step 2: Bump the timeout default**

In `backend/main.py`, change:

```python
AGENT_TIMEOUT_SEC = int(os.getenv("AGENT_TIMEOUT_SEC", "300"))  # 5 min hard cap
```

to:

```python
AGENT_TIMEOUT_SEC = int(os.getenv("AGENT_TIMEOUT_SEC", "240"))  # agent run cap
```

- [ ] **Step 3: Rewrite `run_autoeda_pipeline` with fallback**

Replace the entire `run_autoeda_pipeline` function with:

```python
async def _persist_fallback(upload_id: str, job_id: str) -> None:
    """Persist the deterministic baseline so the user always gets a result."""
    canvas = await asyncio.to_thread(baseline_canvas, upload_id)
    await persist_autoeda_canvas(upload_id, canvas)
    logger.info("Persisted deterministic fallback for upload_id=%s", upload_id)


async def run_autoeda_pipeline(upload_id: str, job_id: str, slug: str) -> None:
    """Background task: parse CSV → run agent → fallback to baseline on failure."""
    file_path = str(Path(UPLOAD_DIR) / f"{upload_id}.csv")
    try:
        await update_job(job_id, "running")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, parse_csv_to_sqlite, upload_id, slug, file_path)
        await asyncio.wait_for(
            run_autoeda_agent(upload_id, job_id), timeout=AGENT_TIMEOUT_SEC
        )
        # The agent should have called write_autoeda_result. If not, fall back.
        row = await get_job(job_id)
        if row is None or row.get("status") != "done":
            logger.warning("Agent left job not done; using baseline. job_id=%s", job_id)
            await _persist_fallback(upload_id, job_id)
    except asyncio.CancelledError:
        raise
    except BaseException as exc:  # noqa: BLE001 - includes TimeoutError + agent/tool escapes
        logger.exception("AutoEDA agent failed; attempting baseline fallback. job_id=%s", job_id)
        try:
            await _persist_fallback(upload_id, job_id)
        except Exception:
            logger.exception("Baseline fallback also failed for job_id=%s", job_id)
            await update_job(job_id, "error", error=str(exc))
```

- [ ] **Step 4: Attach `progress` in `get_job_status`**

In `backend/main.py`, in `get_job_status`, after the `error_msg` line and before the `return JobResponse(...)`, insert:

```python
    raw_progress = row.get("progress")
    progress_items = None
    if isinstance(raw_progress, str) and raw_progress:
        parsed_progress: object = json.loads(raw_progress)
        if isinstance(parsed_progress, list):
            progress_items = parsed_progress
```

Then change the `return JobResponse(...)` to include progress:

```python
    return JobResponse(
        job_id=resolved_job_id,
        status=status,
        result=canvas_response,
        error=error_msg,
        progress=progress_items,
    )
```

- [ ] **Step 5: Verify fallback path (simulate agent failure, no network)**

Run:

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && python -m py_compile backend/main.py && PYTHONPATH=. python -c "
import asyncio, tempfile, os, csv, random, json
d=tempfile.mkdtemp(); os.environ['DATABASE_URL']=f'sqlite+aiosqlite:///{d}/t.db'; os.environ['UPLOAD_DIR']=d; os.environ.setdefault('OPENROUTER_API_KEY','x')
p=os.path.join(d,'a3f7.csv'); rows=[['id','order_date','region','revenue','discount_pct']]; random.seed(1)
for i in range(60):
    rows.append([f'o{i}', f'2024-{(i%12)+1:02d}-15', random.choice(['X','Y']), '' if i%12==0 else f'\${random.randint(10,900)}.00', 250 if i==5 else random.randint(0,40)])
with open(p,'w',newline='') as f: csv.writer(f).writerows(rows)
import backend.main as m
# Force the agent to fail so the fallback runs:
async def boom(upload_id, job_id): raise RuntimeError('simulated agent failure')
m.run_autoeda_agent = boom
from backend.database import get_db, create_tables, create_upload, create_job, get_job
async def main():
    db=await get_db(); await create_tables(db); await db.close()
    await create_upload('a3f7','a3f7.csv','a3f7',p); await create_job('j1','autoeda','a3f7')
    await m.run_autoeda_pipeline('a3f7','j1','a3f7')
    row=await get_job('j1'); print('status:', row['status'])
    res=json.loads(row['result']); print('baseline insights present:', len(res['insights'])>0)
asyncio.run(main())
" 2>/dev/null
```

Expected: `status: done` and `baseline insights present: True`.

- [ ] **Step 6: Commit**

```bash
git add backend/main.py
git commit -m "feat(autoeda): agent timeout + deterministic fallback + progress in JobResponse"
```

---

## Task 8: Frontend types

**Files:**
- Modify: `frontend/lib/types.ts`

**Interfaces:**
- Produces: `DataDictionaryEntry`, `Measure`, `Dimension`, `Entity`, `SemanticLayer`, `ProgressItem`; extended `CanvasResponse`, `JobResponse`.

- [ ] **Step 1: Add the new interfaces**

In `frontend/lib/types.ts`, after the `TableData` interface, insert:

```typescript
export type SemanticType =
  | "identifier"
  | "categorical"
  | "numeric"
  | "temporal"
  | "currency"
  | "boolean"
  | "text";

export interface DataDictionaryEntry {
  column: string;
  dtype: string;
  semantic_type: SemanticType;
  description: string;
  sample_values: string[];
  null_pct: number;
  unit?: string | null;
  is_pii: boolean;
}

export type Aggregation =
  | "sum"
  | "avg"
  | "count"
  | "count_distinct"
  | "min"
  | "max"
  | "median";

export interface Measure {
  name: string;
  column: string;
  aggregation: Aggregation;
  description: string;
}

export interface Dimension {
  name: string;
  column: string;
  description: string;
}

export interface Entity {
  name: string;
  description: string;
  key_columns: string[];
}

export interface SemanticLayer {
  grain: string;
  entities: Entity[];
  measures: Measure[];
  dimensions: Dimension[];
  time_dimension?: string | null;
  suggested_questions: string[];
}

export type ProgressStatus = "pending" | "in_progress" | "completed";

export interface ProgressItem {
  text: string;
  status: ProgressStatus;
}
```

- [ ] **Step 2: Extend `CanvasResponse` and `JobResponse`**

Replace the `CanvasResponse` interface with:

```typescript
export interface CanvasResponse {
  insights: InsightItem[];
  charts: ChartSpec[];
  table: TableData | null;
  data_dictionary?: DataDictionaryEntry[] | null;
  semantic_layer?: SemanticLayer | null;
}
```

Replace the `JobResponse` interface with:

```typescript
export interface JobResponse {
  job_id: string;
  status: JobStatus;
  result: CanvasResponse | null;
  error: string | null;
  progress?: ProgressItem[] | null;
}
```

- [ ] **Step 3: Verify typecheck**

Run:

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto/frontend" && npx tsc --noEmit && echo TSC_OK
```

Expected: `TSC_OK`.

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/types.ts
git commit -m "feat(autoeda): frontend types for dictionary, semantic layer, progress"
```

---

## Task 9: Progress, DataDictionary, and SemanticLayer components

**Files:**
- Create: `frontend/components/AgentProgress.tsx`
- Create: `frontend/components/DataDictionary.tsx`
- Create: `frontend/components/SemanticLayer.tsx`

**Interfaces:**
- Consumes: `ProgressItem`, `DataDictionaryEntry`, `SemanticLayer` from `@/lib/types`.
- Produces: default-exported React components `AgentProgress({ items })`, `DataDictionary({ entries })`, `SemanticLayer({ layer })`.

- [ ] **Step 1: Create `AgentProgress.tsx`**

```tsx
import type { ProgressItem } from "@/lib/types";

const ICON: Record<ProgressItem["status"], string> = {
  completed: "✓",
  in_progress: "◐",
  pending: "○",
};

const COLOR: Record<ProgressItem["status"], string> = {
  completed: "var(--accent)",
  in_progress: "var(--info, #63B3ED)",
  pending: "var(--text3)",
};

export default function AgentProgress({ items }: { items: ProgressItem[] }) {
  if (!items.length) return null;
  return (
    <div className="space-y-1.5">
      <div
        className="text-[10px] uppercase tracking-widest font-medium"
        style={{ color: "var(--text3)" }}
      >
        Agent plan
      </div>
      <ul className="space-y-1">
        {items.map((it, i) => (
          <li key={i} className="flex items-center gap-2 text-[12px]">
            <span style={{ color: COLOR[it.status] }}>{ICON[it.status]}</span>
            <span
              style={{
                color: it.status === "completed" ? "var(--text3)" : "var(--text2)",
                textDecoration: it.status === "completed" ? "line-through" : "none",
              }}
            >
              {it.text}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 2: Create `DataDictionary.tsx`**

```tsx
import type { DataDictionaryEntry } from "@/lib/types";

export default function DataDictionary({
  entries,
}: {
  entries: DataDictionaryEntry[];
}) {
  if (!entries.length) return null;
  return (
    <div className="space-y-2">
      <div
        className="text-[10px] uppercase tracking-widest font-medium"
        style={{ color: "var(--text3)" }}
      >
        Data Dictionary
      </div>
      <div
        className="rounded-lg border overflow-hidden"
        style={{ borderColor: "var(--border)" }}
      >
        <table className="w-full text-[11px]" style={{ borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ background: "var(--bg3)", color: "var(--text3)" }}>
              <th className="text-left px-3 py-1.5 font-medium">Column</th>
              <th className="text-left px-3 py-1.5 font-medium">Type</th>
              <th className="text-left px-3 py-1.5 font-medium">Description</th>
              <th className="text-right px-3 py-1.5 font-medium">Null %</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.column} style={{ borderTop: "1px solid var(--border)" }}>
                <td
                  className="px-3 py-1.5"
                  style={{ fontFamily: "'DM Mono', monospace", color: "var(--text)" }}
                >
                  {e.column}
                  {e.is_pii && (
                    <span
                      className="ml-1.5 px-1 rounded text-[9px]"
                      style={{ background: "rgba(248,113,113,0.12)", color: "var(--danger)" }}
                    >
                      PII
                    </span>
                  )}
                </td>
                <td className="px-3 py-1.5" style={{ color: "var(--text2)" }}>
                  {e.semantic_type}
                  {e.unit ? ` (${e.unit})` : ""}
                </td>
                <td className="px-3 py-1.5" style={{ color: "var(--text2)" }}>
                  {e.description}
                </td>
                <td
                  className="px-3 py-1.5 text-right"
                  style={{ color: e.null_pct > 5 ? "var(--accent3)" : "var(--text3)" }}
                >
                  {e.null_pct.toFixed(1)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Create `SemanticLayer.tsx`**

```tsx
import type { SemanticLayer as SemanticLayerType } from "@/lib/types";

export default function SemanticLayer({ layer }: { layer: SemanticLayerType }) {
  return (
    <div className="space-y-3">
      <div
        className="text-[10px] uppercase tracking-widest font-medium"
        style={{ color: "var(--text3)" }}
      >
        Semantic Layer
      </div>

      <p className="text-[12px]" style={{ color: "var(--text2)" }}>
        <span style={{ color: "var(--text3)" }}>Grain: </span>
        {layer.grain}
        {layer.time_dimension ? (
          <>
            {"  ·  "}
            <span style={{ color: "var(--text3)" }}>Time: </span>
            <span style={{ fontFamily: "'DM Mono', monospace" }}>
              {layer.time_dimension}
            </span>
          </>
        ) : null}
      </p>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <div className="text-[11px] mb-1" style={{ color: "var(--text3)" }}>
            Measures
          </div>
          <ul className="space-y-1">
            {layer.measures.map((m) => (
              <li key={m.name} className="text-[11px]" style={{ color: "var(--text2)" }}>
                <span style={{ color: "var(--accent)" }}>{m.aggregation}</span>(
                <span style={{ fontFamily: "'DM Mono', monospace" }}>{m.column}</span>) —{" "}
                {m.name}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <div className="text-[11px] mb-1" style={{ color: "var(--text3)" }}>
            Dimensions
          </div>
          <ul className="space-y-1">
            {layer.dimensions.map((d) => (
              <li key={d.name} className="text-[11px]" style={{ color: "var(--text2)" }}>
                <span style={{ fontFamily: "'DM Mono', monospace" }}>{d.column}</span> —{" "}
                {d.name}
              </li>
            ))}
          </ul>
        </div>
      </div>

      {layer.suggested_questions.length > 0 && (
        <div>
          <div className="text-[11px] mb-1" style={{ color: "var(--text3)" }}>
            Suggested questions
          </div>
          <div className="flex flex-wrap gap-1.5">
            {layer.suggested_questions.map((q, i) => (
              <span
                key={i}
                className="text-[11px] px-2 py-1 rounded-full"
                style={{ background: "var(--bg3)", color: "var(--text2)" }}
              >
                {q}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Verify typecheck**

Run:

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto/frontend" && npx tsc --noEmit && echo TSC_OK
```

Expected: `TSC_OK`.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/AgentProgress.tsx frontend/components/DataDictionary.tsx frontend/components/SemanticLayer.tsx
git commit -m "feat(autoeda): progress, data dictionary, semantic layer components"
```

---

## Task 10: Wire new sections into Canvas + expose progress in hook

**Files:**
- Modify: `frontend/components/Canvas.tsx`
- Modify: `frontend/lib/hooks.ts`

**Interfaces:**
- Consumes: `AgentProgress`, `DataDictionary`, `SemanticLayer` components; `ProgressItem` type.
- Produces: `Canvas` accepts a new optional `progress?: ProgressItem[] | null` prop; `usePolling` returns `progress` in its state.

- [ ] **Step 1: Add `progress` to `usePolling` state**

In `frontend/lib/hooks.ts`, change the `PollingState` interface to:

```typescript
interface PollingState {
  status: JobStatus | null;
  result: JobResponse["result"];
  error: string | null;
  progress: JobResponse["progress"];
}
```

Change the initial state in `usePolling` from:

```typescript
  const [state, setState] = useState<PollingState>({
    status: null,
    result: null,
    error: null,
  });
```

to:

```typescript
  const [state, setState] = useState<PollingState>({
    status: null,
    result: null,
    error: null,
    progress: null,
  });
```

In the `if (!jobId)` reset block, change:

```typescript
      setState({ status: null, result: null, error: null });
```

to:

```typescript
      setState({ status: null, result: null, error: null, progress: null });
```

And in the successful poll branch, change:

```typescript
        setState({ status: job.status, result: job.result, error: job.error });
```

to:

```typescript
        setState({
          status: job.status,
          result: job.result,
          error: job.error,
          progress: job.progress ?? null,
        });
```

- [ ] **Step 2: Pass `progress` from the page to Canvas**

In `frontend/app/upload/page.tsx`, change:

```typescript
  const { status, result, error } = usePolling(jobId);
```

to:

```typescript
  const { status, result, error, progress } = usePolling(jobId);
```

And change the Canvas render:

```tsx
        <Canvas result={result} status={status} />
```

to:

```tsx
        <Canvas result={result} status={status} progress={progress} />
```

- [ ] **Step 3: Update `Canvas.tsx` imports and props**

In `frontend/components/Canvas.tsx`, change the imports at top to add:

```tsx
import type { CanvasResponse, InsightItem, ChartSpec, ProgressItem } from "@/lib/types";
import InsightCard from "@/components/InsightCards";
import ChartRenderer from "@/components/ChartRenderer";
import AgentProgress from "@/components/AgentProgress";
import DataDictionary from "@/components/DataDictionary";
import SemanticLayer from "@/components/SemanticLayer";
```

Change the `CanvasProps` interface to:

```tsx
interface CanvasProps {
  result: CanvasResponse | null;
  status?: "pending" | "running" | "done" | "error" | null;
  progress?: ProgressItem[] | null;
}
```

Change the component signature to:

```tsx
export default function Canvas({ result, status, progress }: CanvasProps) {
```

- [ ] **Step 4: Render progress while loading**

In `Canvas.tsx`, replace:

```tsx
      {/* Body */}
      {isLoading && <LoadingSkeleton />}
```

with:

```tsx
      {/* Body */}
      {isLoading && (
        <div className="p-5 space-y-4">
          {progress && progress.length > 0 && <AgentProgress items={progress} />}
          <LoadingSkeleton />
        </div>
      )}
```

- [ ] **Step 5: Render dictionary + semantic layer when done**

In `Canvas.tsx`, inside the `{!isLoading && result && (...)}` block, after the charts grid `</div>` (the closing of the `{charts.length > 0 && (...)}` block) and before the block's final `</div>`, insert:

```tsx
          {/* Data dictionary */}
          {result.data_dictionary && result.data_dictionary.length > 0 && (
            <DataDictionary entries={result.data_dictionary} />
          )}

          {/* Semantic layer */}
          {result.semantic_layer && <SemanticLayer layer={result.semantic_layer} />}
```

- [ ] **Step 6: Verify typecheck**

Run:

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto/frontend" && npx tsc --noEmit && echo TSC_OK
```

Expected: `TSC_OK`.

- [ ] **Step 7: Commit**

```bash
git add frontend/components/Canvas.tsx frontend/lib/hooks.ts frontend/app/upload/page.tsx
git commit -m "feat(autoeda): render agent progress, data dictionary, semantic layer on canvas"
```

---

## Task 11: Update spec divergences + end-to-end smoke test

**Files:**
- Modify: `specs/001-upload-auto-eda/spec.md`

**Interfaces:** none (documentation + manual verification).

- [ ] **Step 1: Update the spec assumptions**

In `specs/001-upload-auto-eda/spec.md`, in the **Assumptions** section, replace the bullet:

```
- The analysis agent has access to an LLM API (OpenAI GPT-4o). If the API is unavailable, the job will fail with an error — no fallback analysis mode is provided.
```

with:

```
- The analysis agent runs on DeepSeek V4 Flash via OpenRouter (model id configurable via `OPENROUTER_MODEL`), orchestrated with LangChain `deepagents`. If the LLM is unavailable or the agent fails/times out, the system falls back to a deterministic analysis (stats, quality warnings, charts) so the user always receives a result — only the data dictionary, semantic layer, and agent narrative are omitted in that case.
```

- [ ] **Step 2: Relax the 60s SLA wording**

In `specs/001-upload-auto-eda/spec.md`, change **FR-014**:

```
- **FR-014**: System MUST complete analysis and display results within 60 seconds of file upload for a dataset up to 50MB.
```

to:

```
- **FR-014**: System MUST complete analysis and display results within the agent timeout (default 240 seconds, configurable via `AGENT_TIMEOUT_SEC`) of file upload for a dataset up to 50MB; on timeout the deterministic fallback result is shown.
```

And **SC-001**:

```
- **SC-001**: Users can drop a CSV file and see analysis results appear on the canvas within 60 seconds, with no configuration required.
```

to:

```
- **SC-001**: Users can drop a CSV file and see analysis results appear on the canvas within the agent timeout (default 240s), with no configuration required.
```

- [ ] **Step 3: Commit the spec update**

```bash
git add specs/001-upload-auto-eda/spec.md
git commit -m "docs(001): align spec with deepagents + fallback + relaxed SLA"
```

- [ ] **Step 4: Live smoke test (requires real `OPENROUTER_API_KEY`)**

Ensure `.env` has a real `OPENROUTER_API_KEY`. Start backend and frontend:

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && PYTHONPATH=. python -m uvicorn backend.main:app --reload --port 8000
```

In a second shell:

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto/frontend" && npm run dev
```

- [ ] **Step 5: Verify end-to-end in the browser**

Open `http://localhost:3000`, upload a CSV (the messy e-commerce demo CSV if available). Confirm:
- The canvas shows a live **Agent plan** checklist while running.
- On completion: ≥4 stat cards, ≥1 quality warning, 2–5 charts.
- A **Data Dictionary** table renders with one row per column (PII badge where relevant).
- A **Semantic Layer** section shows grain, measures, dimensions, and suggested questions.
- The left-panel Rows/Columns counts populate.
- "Continue to Context →" activates only when done.

- [ ] **Step 6: Verify fallback (optional but recommended)**

Temporarily set an invalid `OPENROUTER_API_KEY` in `.env`, restart backend, upload again. Confirm the canvas still shows stats/warnings/charts (the deterministic fallback) and the job reaches `done` — the dictionary/semantic sections are simply absent. Restore the real key afterward.

- [ ] **Step 7: Inspect persisted artifacts**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && python -c "
import sqlite3
c=sqlite3.connect('backend/data/app.db')
for r in c.execute('SELECT id, substr(data_dictionary,1,40), substr(semantic_layer,1,40) FROM uploads ORDER BY uploaded_at DESC LIMIT 1'):
    print(r)
"
```

Expected: the latest upload row shows non-null `data_dictionary` and `semantic_layer` JSON (after a successful agent run).

---

## Self-Review

**Spec coverage:**
- Model = DeepSeek V4 Flash / OpenRouter / env-configurable → Task 1, Global Constraints. ✓
- Agent harness = deepagents, agent owns pipeline, deterministic funcs as tools → Tasks 4, 6. ✓
- Data dictionary + semantic layer, persisted to DB AND rendered → Tasks 2, 3, 5 (persist) + 8, 9, 10 (render). ✓
- Progress streaming (todos → job → checklist) → Tasks 3 (column), 6 (stream), 8/9/10 (render). ✓
- Fallback to deterministic baseline → Tasks 4 (callable), 7 (wrapper). ✓
- No new endpoints → honored (artifacts via `get_job` join, progress via JobResponse). ✓
- Spec divergences (FR-014, fail-hard assumption, model) written back → Task 11. ✓
- Existing FR-006/007/009 guarantees preserved via `compute_baseline_canvas` first-call → Task 4 + system prompt in Task 6. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; verification commands have expected output. ✓

**Type consistency:** `baseline_canvas`/`compute_baseline_canvas` (Task 4) used consistently in Tasks 6, 7. `update_upload_artifacts` signature widened to `str | None` in Task 5 before use. `persist_autoeda_canvas` consumes `data_dictionary`/`semantic_layer` keys matching the model field names (Task 2). `run_autoeda_agent(upload_id, job_id)` signature matches the call in Task 7. TS `ProgressItem`/`SemanticLayer`/`DataDictionaryEntry` names match component props (Tasks 8–10). ✓
