# Research: CSV Upload and Auto EDA

**Branch**: `001-upload-auto-eda` | **Date**: 2026-04-17  
**Status**: Complete — no open questions. All decisions sourced from `project-guidelines.mdc` and the agreed architecture spec.

---

## Decision 1: Async Pattern for Upload + EDA

**Decision**: Pattern A — Fire & Poll  
**Rationale**: The EDA agent may take 10–30s to complete. Blocking the HTTP response would cause client timeouts and give a poor UX. BackgroundTasks runs the pipeline asynchronously; the frontend polls `GET /api/jobs/{job_id}` every 2s. When `status = "done"`, the result is read from `jobs.result` and rendered. This pattern is reusable — identical polling logic is used for any future async agent work.  
**Alternatives considered**:
- Server-Sent Events (SSE) — rejected per project guidelines (no SSE/WebSockets allowed)
- Streaming tokens — rejected per guidelines (polling is sufficient for demo)
- Synchronous response — rejected (latency too high for a 50MB CSV + LLM calls)

---

## Decision 2: CSV Parsing + Type Coercion

**Decision**: Custom utility function `csv_parser.py` using pandas. Five coercion rules applied in sequence. No LLM involved.  
**Rationale**: Coercion is a deterministic transformation, not an intelligent decision. Using an LLM for this would be slow, expensive, and unpredictable. Pandas handles this in milliseconds. The five rules (whitespace strip, currency strip, date normalisation, numeric coercion, null preservation) cover all known issues in the demo dataset.  
**Rules (in application order)**:
1. Strip leading/trailing whitespace from all string values
2. Strip currency symbols (`$`, `€`, `£`) and thousands separators (`,`) from numeric-looking strings
3. Parse mixed date format columns to ISO 8601 (handles `DD/MM/YYYY` and `YYYY-MM-DD`)
4. Coerce columns where >80% of non-null values parse as numeric → store as REAL in SQLite
5. Preserve rows with unconvertible values as TEXT — never drop rows during coercion

**Alternatives considered**:
- Cleanup agent for coercion — rejected (cleanup is removed from scope for this prototype; coercion is rule-based, not LLM-decision-based)

---

## Decision 3: AutoEDA Agent Architecture

**Decision**: LangGraph `StateGraph` with a single node. Tool-calling loop pattern.  
**Rationale**: Single-node graph is the simplest LangGraph pattern. The agent has one job: run 7 fixed analyses and produce a `CanvasResponse`. No routing, no multi-step planning needed. Tool-calling loop allows the agent to call `run_python_analysis` multiple times (once per analysis) without re-invoking the LLM unnecessarily.  
**Tools**: 4 tools bound to the agent — `get_dataframe_profile`, `run_python_analysis`, `generate_chart_spec`, `write_autoeda_result`.  
**Alternatives considered**:
- Plain LangChain agent (not LangGraph) — rejected to maintain consistency; all agents in this project use LangGraph
- Running analyses in a fixed Python pipeline (no LLM) — rejected; the agent's role is to interpret results and write human-readable insight strings and select chart types intelligently

---

## Decision 4: Python REPL Sandbox

**Decision**: Restricted `exec()` environment using a controlled globals dict. Allowed imports: `pandas`, `numpy`, `scipy.stats`, `datetime`. Timeout: 30s (from `PYTHON_REPL_TIMEOUT_SEC` env var).  
**Rationale**: The agent writes arbitrary Python to analyse data. Without sandboxing, it could read files, make network calls, or execute system commands. Restricting the import namespace prevents this. A 30s timeout prevents runaway computations.  
**Implementation note**: The restricted exec approach is per project guidelines. Production hardening (e.g. `seccomp`, containerised REPL) is explicitly out of scope for this demo build.

---

## Decision 5: Chart Specification — Normalised Contract

**Decision**: `generate_chart_spec` tool validates and normalises chart data into the `ChartSpec` interface before returning. The tool does not render — it only validates and structures.  
**Rationale**: Separating spec generation from rendering decouples the agent (Python/backend) from the renderer (Recharts/frontend). The contract is the `ChartSpec` interface defined in `types.ts`. Any change to rendering logic never requires touching the agent.  
**Chart types supported**: `bar`, `line`, `histogram`, `scatter`, `heatmap`, `boxplot`  
**Maximum charts per response**: 5 (agent selects the most informative)

---

## Decision 6: Upload Identifier Strategy

**Decision**: `upload_id` = UUID4 (primary key, used in all table names and API paths). `slug` = filename-derived human-readable string (e.g. `orders_2024`), stored in `uploads` table and returned in the upload response.  
**Rationale**: UUID prevents collisions and is safe for use in dynamic table names (`raw_{upload_id}`). The slug is for human readability in the NavBar and during development — it does not need to be unique. Both are set at upload time and persisted.  
**Slug derivation rule**: lowercase filename, strip extension, replace non-alphanumeric chars with `_`, collapse consecutive `_`.

---

## Decision 7: Frontend State Management

**Decision**: `upload_id` and `slug` stored in React context (`useUploadId` hook in `lib/hooks.ts`) backed by `localStorage`. All other state fetched from SQLite on demand.  
**Rationale**: `localStorage` persistence means the user can refresh the page without losing their session. There is no server-side session management (per guidelines). The context is minimal — only the two identifiers needed to reconstruct state from the API.  
**Alternatives considered**:
- URL params (`/upload?id=xxx`) — not chosen as the flow is linear and the ID is an implementation detail the user shouldn't see in the URL
- Zustand/Redux — rejected (overkill for two fields)
