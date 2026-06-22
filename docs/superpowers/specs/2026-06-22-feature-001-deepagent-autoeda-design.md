# Design: DeepAgent-Driven AutoEDA (with Data Dictionary & Semantic Layer)

**Date**: 2026-06-22
**Branch**: `001-upload-auto-eda`
**Status**: Approved (brainstorming) — pending implementation plan
**Supersedes**: the deterministic-only AutoEDA path introduced as a stopgap in `backend/agents/autoeda_deterministic.py`

---

## 1. Summary

Restore an LLM agent as the driver of AutoEDA, replacing the deterministic-only pipeline.
The agent is built with LangChain's **`deepagents`** harness (planning + virtual filesystem +
tool orchestration on top of LangGraph) and runs on **DeepSeek V4 Flash via OpenRouter**.

The deterministic engine is **not deleted** — it survives as (a) a tool the agent calls to get a
guaranteed baseline and (b) the fallback result if the agent fails.

On top of the existing stats / warnings / charts, the agent additionally produces two new
artifacts that downstream features (002 Context Agent, 003 Query Canvas) depend on:

- a **data dictionary** (per-column semantic metadata), and
- a **semantic layer** (grain, entities, measures, dimensions, suggested questions).

Both are persisted to the database (durable, for downstream features) and rendered on the canvas.

---

## 2. Decisions (locked during brainstorming)

| # | Decision | Choice |
|---|----------|--------|
| 1 | LLM | `deepseek/deepseek-v4-flash` via OpenRouter; model id env-configurable (`OPENROUTER_MODEL`) |
| 2 | Agent harness | LangChain `deepagents` (`create_deep_agent`) |
| 3 | Flow | **Agent owns the pipeline**; deterministic profiling/chart functions are exposed as tools |
| 4 | New artifacts | Data dictionary + semantic layer — **persisted to DB AND rendered on canvas** |
| 5 | Progress UX | **Stream agent steps/plan** (deepagents `todos`) to the job; canvas renders a live checklist |
| 6 | Resilience | On agent error/timeout, **fall back to the deterministic baseline** so the user always gets a result |

---

## 3. Architecture & flow

```
upload CSV
  → POST /api/upload         save file, create upload + job (status=pending), schedule BackgroundTask
  → run_autoeda_pipeline (background):
        1. update_job(running)
        2. parse_csv_to_sqlite()          coercion → raw_{upload_id}    (UNCHANGED)
        3. run_autoeda_agent(upload_id):  DeepAgent orchestration
              - agent.astream(stream_mode="values")
              - each step: read state["todos"] → update_job_progress()
              - agent calls tools, composes data dictionary + semantic layer
              - agent calls write_autoeda_result() exactly once at the end
        4. on agent exception / timeout / no-result-written:
              - compute + persist deterministic baseline (status=done)   [FALLBACK]
              - if baseline ALSO fails → update_job(error)
  → GET /api/jobs/{id}        job row + joined upload artifacts + progress
  → frontend polls every 2s   live checklist while running; then stats / charts / dictionary / semantic
```

No new HTTP endpoints (honors the existing project constraint: only `POST /api/upload` and
`GET /api/jobs/{job_id}`).

---

## 4. Model layer

- **New `backend/llm.py`**:
  ```python
  def get_chat_model() -> BaseChatModel:
      return ChatOpenAI(
          model=os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-v4-flash"),
          base_url="https://openrouter.ai/api/v1",
          api_key=os.getenv("OPENROUTER_API_KEY"),
          temperature=0,
      )
  ```
- **`.env`** adds `OPENROUTER_API_KEY` and `OPENROUTER_MODEL=deepseek/deepseek-v4-flash`.
  Existing `OPENAI_API_KEY` is left in place but unused.
- **`requirements.txt`** adds `deepagents` (pulls in `langgraph`; `langchain-openai` already present).

**Early verification gate**: before building the rest, confirm a real tool-call round-trips against
OpenRouter with V4 Flash (the model is marketed for agent workflows; verify, don't assume). Requires
`OPENROUTER_API_KEY` in `.env`.

---

## 5. Tools

The agent is given these tools (plus deepagents' built-in `write_todos` planning tool and virtual filesystem):

| Tool | Source | Purpose |
|------|--------|---------|
| `compute_baseline_canvas(upload_id)` | **NEW** thin wrapper over `build_autoeda_canvas_sync` | Returns the guaranteed deterministic canvas: stat cards, >5% null warnings, outlier warnings, ≤5 charts. The system prompt instructs the agent to call this **first** so FR-006/007/009 are always met regardless of LLM behavior. |
| `get_dataframe_profile(upload_id)` | existing (`tools/dataframe.py`) | shape / dtypes / null counts / nunique / describe stats |
| `run_python_analysis(upload_id, code)` | existing (`tools/python_repl.py`) | sandboxed pandas/numpy/scipy execution for deeper analysis (was dead code; now live) |
| `generate_chart_spec(...)` | existing (`tools/chart.py`) | validate any extra charts the agent designs |
| `write_autoeda_result(upload_id, canvas)` | existing (`tools/autoeda_writer.py`), **extended** | Final persist: writes full `CanvasResponse` (incl. dictionary + semantic) to `jobs.result`, sets status=done, and mirrors dictionary + semantic to the `uploads` columns. |

**Single agent, no subagents** (YAGNI). Subagents (e.g. a dedicated semantic-modeler) are a future option.

System prompt (persona + procedure) instructs the agent to:
1. Call `compute_baseline_canvas` to anchor required stats/warnings/charts.
2. Use `get_dataframe_profile` + `run_python_analysis` to understand the data and add deeper insights.
3. Build a **data dictionary** (one entry per column) and a **semantic layer**.
4. Optionally add up to a few extra charts (respecting the ≤5 total cap) via `generate_chart_spec`.
5. Call `write_autoeda_result` exactly once with the complete payload.

---

## 6. New artifacts

### Pydantic models (`backend/models.py`), mirrored in `frontend/lib/types.ts`

```python
class DataDictionaryEntry(BaseModel):
    column: str
    dtype: str
    semantic_type: Literal["identifier","categorical","numeric","temporal","currency","boolean","text"]
    description: str
    sample_values: list[str]
    null_pct: float
    unit: str | None = None
    is_pii: bool = False

class Measure(BaseModel):
    name: str
    column: str
    aggregation: Literal["sum","avg","count","count_distinct","min","max","median"]
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
    grain: str                       # what one row represents
    entities: list[Entity]
    measures: list[Measure]
    dimensions: list[Dimension]
    time_dimension: str | None = None
    suggested_questions: list[str]   # seeds the downstream Query Canvas

class ProgressItem(BaseModel):
    text: str
    status: Literal["pending","in_progress","completed"]
```

`CanvasResponse` gains:
```python
    data_dictionary: list[DataDictionaryEntry] | None = None
    semantic_layer: SemanticLayer | None = None
```

`JobResponse` gains:
```python
    progress: list[ProgressItem] | None = None
```

### Persistence

- Durable source of truth for downstream features: new `uploads.data_dictionary` and
  `uploads.semantic_layer` TEXT (JSON) columns.
- Render payload: the same artifacts embedded in `jobs.result` (`CanvasResponse`).
- `write_autoeda_result` writes both places in one call.

---

## 7. Database changes (`backend/database.py`)

New columns (added idempotently so an existing `app.db` upgrades without a manual drop):

```sql
ALTER TABLE uploads ADD COLUMN data_dictionary TEXT;   -- JSON
ALTER TABLE uploads ADD COLUMN semantic_layer  TEXT;   -- JSON
ALTER TABLE jobs    ADD COLUMN progress         TEXT;   -- JSON list[ProgressItem]
```

`create_tables()` runs the base `CREATE TABLE IF NOT EXISTS` then attempts each `ADD COLUMN`,
swallowing the "duplicate column name" error so it is safe to run repeatedly.

New / changed helpers:

```python
async def update_job_progress(job_id: str, progress_json: str) -> None
async def update_upload_artifacts(upload_id: str, data_dictionary: str, semantic_layer: str) -> None
async def get_job(job_id: str) -> dict | None   # now LEFT JOINs uploads to attach artifacts
```

---

## 8. Orchestrator (`backend/agents/autoeda.py`, rewritten)

```python
async def run_autoeda_agent(upload_id: str, job_id: str) -> None:
    agent = build_deep_agent()          # cached module-level; model + tools + system prompt
    task = render_task_prompt(upload_id)
    async for state in agent.astream(
        {"messages": [{"role": "user", "content": task}]},
        stream_mode="values",
    ):
        todos = state.get("todos")
        if todos:
            await update_job_progress(job_id, serialize_todos(todos))
    # write_autoeda_result is called by the agent itself; nothing else to persist here.
```

`run_autoeda_agent` takes both `upload_id` (for tools/task) and `job_id` (for progress writes);
`run_autoeda_pipeline` already holds both and passes them through.

`run_autoeda_pipeline` (in `main.py`) wraps the above in `asyncio.wait_for(..., AGENT_TIMEOUT_SEC)`
and a `try/except`. On any failure OR if the job is still not `done` after the agent returns, it
computes `build_autoeda_canvas_sync` and persists it (status=done) as the fallback. Only if the
fallback also raises does it `update_job(error)`.

`AGENT_TIMEOUT_SEC` default raised to **240s**; frontend polling cap already 360s.

---

## 9. Frontend

- `frontend/lib/types.ts` — add `DataDictionaryEntry`, `Measure`, `Dimension`, `Entity`,
  `SemanticLayer`, `ProgressItem`; extend `CanvasResponse` and `JobResponse`.
- **New `frontend/components/AgentProgress.tsx`** — live checklist (todo text + status icon),
  shown on the canvas while `status === "running"`.
- **New `frontend/components/DataDictionary.tsx`** — table: column / semantic_type / description / null%,
  with PII badge.
- **New `frontend/components/SemanticLayer.tsx`** — grain headline, measures + dimensions lists,
  suggested-questions chips.
- `frontend/components/Canvas.tsx` — render `AgentProgress` while running; render the two new
  sections (when present) below charts when done.
- `frontend/lib/hooks.ts` — `usePolling` already returns the whole job; expose `progress` (minor).

---

## 10. Spec divergences (to be reflected in `spec.md`)

1. **FR-014 (60s SLA)** — relaxed. A multi-step agent run does not fit 60s; the deterministic
   fallback keeps worst-case bounded, but the success target becomes "completes within the agent
   timeout (default 240s)".
2. **Assumption "LLM unavailable → job fails, no fallback"** — replaced by the deterministic
   fallback (decision #6).
3. **Assumption "OpenAI GPT-4o"** — replaced by DeepSeek V4 Flash via OpenRouter.

---

## 11. Out of scope

- Subagents / multi-agent delegation (single agent is enough now).
- Multi-table / relational CSVs (unchanged from feature 001 assumptions).
- Caching agent results across re-uploads.
- Surfacing the agent's virtual-filesystem files directly to the user (artifacts come back as
  structured `write_autoeda_result` payload, not raw files).

---

## 12. Affected files

**Backend**
- `backend/llm.py` (new) — OpenRouter model factory
- `backend/agents/autoeda.py` (rewrite) — deepagents orchestrator + progress streaming
- `backend/agents/autoeda_deterministic.py` (kept) — engine for the baseline tool + fallback
- `backend/tools/autoeda_baseline.py` (new) — `compute_baseline_canvas` tool wrapper
- `backend/tools/autoeda_writer.py` (extend) — persist artifacts + new canvas fields
- `backend/tools/dataframe.py`, `tools/python_repl.py`, `tools/chart.py` (reused as agent tools)
- `backend/models.py` (extend) — new artifact + progress models
- `backend/database.py` (extend) — new columns, migration guards, progress/artifact helpers, get_job join
- `backend/main.py` (extend) — fallback wrapper, attach progress/artifacts, bump timeout
- `backend/requirements.txt` (extend) — `deepagents`
- `.env` (extend) — `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`

**Frontend**
- `frontend/lib/types.ts` (extend)
- `frontend/components/AgentProgress.tsx`, `DataDictionary.tsx`, `SemanticLayer.tsx` (new)
- `frontend/components/Canvas.tsx` (extend)
- `frontend/lib/hooks.ts` (minor)
