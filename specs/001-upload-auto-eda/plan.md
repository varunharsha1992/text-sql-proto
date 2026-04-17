# Implementation Plan: CSV Upload and Auto EDA

**Branch**: `001-upload-auto-eda` | **Date**: 2026-04-17 | **Spec**: [spec.md](./spec.md)  
**Input**: Feature specification from `/specs/001-upload-auto-eda/spec.md`

---

## Summary

Users upload a CSV file via a drag-and-drop interface. The system parses it, applies light type coercion (currency stripping, date normalisation), then fires an AutoEDA LangGraph agent that profiles the dataset using 7 fixed analyses and produces a structured `CanvasResponse` (stat cards, up to 5 charts, quality warnings). The frontend polls the job status every 2s and renders the canvas when complete. This is **Pattern A (Fire & Poll)** — the interaction pattern shared by all async agent work in the application.

---

## Technical Context

**Language/Version**: Python 3.11 (backend) · TypeScript strict (frontend)  
**Primary Dependencies**: FastAPI (async routes, BackgroundTasks) · LangGraph + LangChain · OpenAI GPT-4o · aiosqlite · pandas · Next.js 14 (App Router) · Tailwind CSS · Recharts  
**Storage**: SQLite via aiosqlite — file `data/app.db`. Dynamic table `raw_{upload_id}` per upload.  
**Testing**: No automated test suite in scope for this demo build. Manual validation against demo CSV.  
**Target Platform**: Local development machine (single user, no deployment)  
**Project Type**: Full-stack web application — FastAPI backend + Next.js frontend  
**Performance Goals**: EDA analysis completes and canvas renders within 60 seconds of upload for files up to 50MB  
**Constraints**: No WebSockets/SSE (plain HTTP polling only). No Redis/Celery (BackgroundTasks only). No auth. No Docker.  
**Scale/Scope**: Single user, single upload session at a time. Demo build.

---

## Constitution Check

*The project constitution file is not yet populated. The de facto constitution for this project is `.cursor/rules/project-guidelines.mdc`. All gates below are derived from that file.*

| Rule | Status | Notes |
|------|--------|-------|
| All routes `async def` | ✅ PASS | Required by guidelines |
| All DB ops via `aiosqlite` — no `sqlite3` | ✅ PASS | Required by guidelines |
| Pattern A: `BackgroundTasks` only, no `asyncio.create_task` | ✅ PASS | Applied to upload route |
| Agent code only in `backend/agents/` | ✅ PASS | `autoeda.py` lives there |
| Tools only write to SQLite — agents never write directly | ✅ PASS | `write_autoeda_result` tool handles the write |
| All tools decorated with `@tool`, full type hints, docstring | ✅ PASS | Enforced in tools/ |
| Tools return error strings, never raise | ✅ PASS | Error handling convention followed |
| No WebSockets, no SSE | ✅ PASS | Polling pattern used |
| `CanvasResponse` contract: `insights`, `charts`, `table` only | ✅ PASS | AutoEDA agent outputs this shape |
| `LIMIT 500` on all SQL — N/A for this feature (no SQL queries) | N/A | AutoEDA uses Python analysis, not SQL |
| No additional endpoints beyond the agreed set | ✅ PASS | Only `POST /api/upload` + `GET /api/jobs/{job_id}` added |
| System prompt as `SYSTEM_PROMPT` constant at top of agent file | ✅ PASS | Required by guidelines |
| Frontend: no `any`, no inline styles, custom hooks only | ✅ PASS | Enforced in frontend guidelines |

**Result**: No violations. No complexity justification required.

---

## Project Structure

### Documentation (this feature)

```text
specs/001-upload-auto-eda/
├── plan.md              # This file
├── research.md          # Phase 0 — confirmed decisions
├── data-model.md        # Phase 1 — SQLite tables + entities
├── quickstart.md        # Phase 1 — local setup guide
├── contracts/
│   ├── POST_api_upload.md
│   └── GET_api_jobs_jobid.md
└── tasks.md             # Phase 2 — created by /speckit.tasks
```

### Source Code (repository root)

This feature introduces the foundational file structure. Subsequent features will add to — not replace — this layout.

```text
backend/
├── main.py                    ← POST /api/upload + GET /api/jobs/{job_id}
├── database.py                ← create_tables(), create_job(), update_job(), get_job()
├── models.py                  ← UploadResponse, JobResponse, CanvasResponse (Pydantic)
├── agents/
│   └── autoeda.py             ← AutoEDA LangGraph single-node agent
├── tools/
│   ├── dataframe.py           ← get_dataframe_profile, sample_column_values (read-only)
│   ├── python_repl.py         ← run_python_analysis (sandboxed exec)
│   ├── chart.py               ← generate_chart_spec (validation + normalisation)
│   └── autoeda_writer.py      ← write_autoeda_result (SQLite write via tool)
└── utils/
    └── csv_parser.py          ← parse_csv_to_sqlite() + light type coercion

frontend/
├── app/
│   ├── page.tsx               ← root redirect to /upload
│   └── upload/
│       └── page.tsx           ← Screen 1 (upload zone + canvas)
├── components/
│   ├── NavBar.tsx             ← step progress (1→2→3), disabled states
│   ├── Canvas.tsx             ← shared CanvasResponse renderer
│   ├── ChartRenderer.tsx      ← Recharts wrapper for ChartSpec
│   └── InsightCards.tsx       ← stat/text/warning/badge cards
└── lib/
    ├── api.ts                 ← uploadFile(), getJob() typed wrappers
    ├── types.ts               ← CanvasResponse, ChartSpec, InsightItem, TableData
    └── hooks.ts               ← usePolling(), useUploadId()

data/
├── app.db                     ← SQLite database (created on first run)
└── uploads/                   ← raw CSV files (created on first run)

.env                           ← OPENAI_API_KEY, DATABASE_URL, UPLOAD_DIR, etc.
```

**Structure Decision**: Web application layout (Option 2). Backend and frontend are fully separate. All backend agent code lives under `backend/agents/`, tools under `backend/tools/`. This is the canonical layout for all three feature groups — subsequent features add files to existing directories, never create new top-level directories.

---

## Implementation Phases

### Phase 0 — Research & Decisions

All decisions confirmed. See [research.md](./research.md).

No unknowns to resolve. No dependencies requiring investigation beyond what is already documented in `project-guidelines.mdc` and the architecture spec.

### Phase 1 — Design & Contracts

See:
- [data-model.md](./data-model.md) — SQLite schema + entity definitions
- [contracts/POST_api_upload.md](./contracts/POST_api_upload.md) — upload endpoint contract
- [contracts/GET_api_jobs_jobid.md](./contracts/GET_api_jobs_jobid.md) — job polling endpoint contract
- [quickstart.md](./quickstart.md) — local development setup

### Phase 2 — Implementation Tasks

*Created by `/speckit.tasks` — see tasks.md once generated.*

Logical implementation order (sequenced by dependency):

1. **Foundation** — `.env`, `database.py` (schema + helper fns), `models.py` (Pydantic types), `data/` directories
2. **CSV Parser** — `utils/csv_parser.py`: parse CSV → `raw_{upload_id}` table + 5-rule coercion pass
3. **AutoEDA Tools** — `tools/dataframe.py`, `tools/python_repl.py`, `tools/chart.py`, `tools/autoeda_writer.py`
4. **AutoEDA Agent** — `backend/agents/autoeda.py`: LangGraph node + system prompt + 7 fixed analyses
5. **Backend Routes** — `backend/main.py`: `POST /api/upload` + `GET /api/jobs/{job_id}`
6. **Frontend Types + Hooks** — `lib/types.ts`, `lib/api.ts`, `lib/hooks.ts`
7. **Frontend Components** — `InsightCards.tsx`, `ChartRenderer.tsx`, `Canvas.tsx`, `NavBar.tsx`
8. **Screen 1** — `app/upload/page.tsx`: upload zone + polling + canvas render + "Continue" button
9. **Smoke Test** — upload demo CSV, verify EDA completes, canvas renders with charts and warnings
