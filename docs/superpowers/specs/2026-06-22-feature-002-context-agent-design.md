# Feature 002 — Context Agent (Design, revised)

**Date:** 2026-06-22
**Status:** Approved (brainstorming) — pending implementation plan
**Supersedes:** `docs/superpowers/specs/2026-06-16-feature-002-context-agent-design.md` (which predated the deepagents AutoEDA and assumed GPT-4o + heuristic starter catalog)
**Builds on:** Feature 001 (Upload + deepagents AutoEDA), which now persists `uploads.data_dictionary` and `uploads.semantic_layer`.
**Demo moment:** An agent reads your dataset — already armed with the AI-generated data dictionary and semantic layer — and interviews you to confirm and enrich it. The catalog and semantic layer refine live on the right as each answer is given.

---

## 1. Summary

Screen 2 is a turn-based conversational interview that turns the *machine-generated* context from AutoEDA into a *user-validated* semantic store. Instead of rebuilding a thin starter catalog from heuristics (the old 002 plan), the Context Agent **seeds from the data dictionary + semantic layer** AutoEDA already produced, then asks sharp, targeted questions to confirm meaning, fill gaps, and capture relationships. The validated result — a per-column `catalog` table plus a refined dataset-level `semantic_layer` — is the context feature 003 (Query Canvas / text-to-SQL) will consume.

---

## 2. Decisions (locked during brainstorming)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Foundation | **Seed from AutoEDA artifacts** (`uploads.data_dictionary` + `uploads.semantic_layer`), not heuristic rebuild. Heuristic fallback only for older uploads with no dictionary. |
| 2 | Agent stack | **Turn-based LangChain tool-calling agent** on `get_chat_model()` (DeepSeek V4 Flash via OpenRouter). Not deepagents — no planning/fs needed for a Q&A turn. |
| 3 | Storage | **`catalog` table (per-column) + the agent refines `uploads.semantic_layer`** (dataset-level). Both get user-validated. |
| 4 | Interview style | **Conversational only** — no direct table-cell editing (out of scope). |
| 5 | Completion | **Completion state, no navigation** — Query screen (003) doesn't exist yet; show "Context saved — ready for queries" with a disabled Continue. |

---

## 3. Architecture & flow

Pattern B (turn-based JSON, synchronous) per `docs/datalens-architecture.md`. One user message → one POST → one agent turn (tool-calling loop) → one response carrying the chat reply **and** the full current catalog + semantic layer. SQLite is the source of truth. No background jobs, polling, or WebSockets.

```
upload → AutoEDA (deepagents) writes uploads.data_dictionary + uploads.semantic_layer   [feature 001]
   │
   ▼
Frontend (app/context/page.tsx)
   GET  /api/context/{id}/catalog   → ensure_catalog_seed() then { slug, columns, semantic_layer }
   POST /api/context/{id}/chat      → { chat, canvas, catalog, semantic_layer, complete }
   POST /api/context/{id}/complete  → { ok: true }
   │  context_agent.ainvoke() — synchronous per turn (<5s target)
   ▼
LangChain Context Agent (backend/agents/context.py)  — DeepSeek V4 Flash via get_chat_model()
   │  6 tools (tools/catalog.py + tools/dataframe.py)
   ▼
SQLite: catalog, context_conversations, uploads.semantic_layer, uploads.context_complete, raw_{upload_id}
```

---

## 4. Seeding (the central change vs. the superseded 002)

`ensure_catalog_seed(upload_id)` runs once (idempotent — does nothing if catalog rows already exist for the upload), invoked on `GET /catalog`:

1. **Primary path** — `uploads.data_dictionary` is present (normal post-AutoEDA upload): build one catalog row per `DataDictionaryEntry`, mapping:
   - `column` → `column_name`
   - `dtype` → `data_type`
   - `semantic_type` → `semantic_role` via: `identifier→identifier`, `temporal→datetime`, `currency→measure`, `numeric→measure`, (`categorical`|`boolean`|`text`)→`dimension`
   - `description` → `description`
   - `sample_values` → `sample_values`
   - `is_pii` → `is_pii`, `unit` → `unit`, `null_pct` → `null_pct`
   - `business_context`, `is_primary_key`, `is_foreign_key`, `foreign_key_ref` left empty for the interview to fill.
2. **Fallback path** — no `data_dictionary` (pre-deepagents upload): build minimal rows from the raw profile (`get_dataframe_profile`): column_name, data_type, 3 sample values, `semantic_role` via the simple name/dtype heuristic (`*_id`/`id`→identifier; datetime→datetime; numeric & name∈{revenue,amount,count,price,qty,total}→measure; else dimension). Ensures the screen never renders empty.

The semantic layer is already present from AutoEDA (or `null` on the fallback path); the agent refines it during the interview.

---

## 5. Data layer (`backend/database.py`)

### New table: `catalog`
One row per column. Composite PK so writes are idempotent upserts.

```sql
CREATE TABLE IF NOT EXISTS catalog (
    upload_id        TEXT NOT NULL,
    slug             TEXT NOT NULL,
    column_name      TEXT NOT NULL,
    data_type        TEXT,            -- TEXT | INTEGER | REAL | DATETIME
    semantic_role    TEXT,            -- identifier | datetime | measure | dimension
    business_context TEXT,            -- free text from the interview ("pre-tax USD")
    description      TEXT,
    is_primary_key   BOOLEAN DEFAULT FALSE,
    is_foreign_key   BOOLEAN DEFAULT FALSE,
    foreign_key_ref  TEXT,            -- e.g. "orders.user_id" (nullable)
    is_pii           BOOLEAN DEFAULT FALSE,
    unit             TEXT,            -- e.g. "USD" (nullable)
    sample_values    TEXT,            -- JSON array of strings
    null_pct         REAL,
    updated_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (upload_id, column_name)
);
```

### New table: `context_conversations`
```sql
CREATE TABLE IF NOT EXISTS context_conversations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    upload_id  TEXT NOT NULL,
    role       TEXT NOT NULL,         -- "user" | "agent"
    content    TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

Both created via idempotent `CREATE TABLE IF NOT EXISTS` added to `create_tables()`. `uploads.context_complete` and `uploads.semantic_layer` already exist (feature 001) — no migration needed.

### New helpers (all async, `aiosqlite`, following the existing `get_db()/try/finally close()` pattern)
- `ensure_catalog_seed(upload_id: str) -> None` — seed catalog once (Section 4). Idempotent.
- `get_catalog(upload_id: str) -> list[dict]` — all catalog rows for the upload (sample_values parsed from JSON).
- `upsert_catalog_entry(upload_id: str, slug: str, column_name: str, updates: dict) -> None` — insert-or-update one row (sample_values dumped to JSON if present).
- `update_semantic_layer(upload_id: str, semantic_layer_json: str) -> None` — overwrite `uploads.semantic_layer`. (Distinct from feature 001's `update_upload_artifacts`, which writes both columns together.)
- `get_semantic_layer(upload_id: str) -> str | None` — raw JSON for read-back.
- `mark_context_complete(upload_id: str) -> None` — sets `uploads.context_complete = TRUE`.
- `get_conversation(upload_id: str) -> list[dict]` — `[{role, content}]` ordered by `created_at`.
- `save_message(upload_id: str, role: str, content: str) -> None`.
- `get_upload(upload_id: str) -> dict | None` — needed to resolve `slug` and read `data_dictionary` for seeding (add if not present).

---

## 6. Agent (`backend/agents/context.py`)

LangChain tool-calling agent (LangGraph `create_react_agent` or equivalent prebuilt loop) on `get_chat_model()`. Synchronous per turn via `ainvoke`. Full conversation history (from `context_conversations`) is passed on every invocation; the `__INIT__` sentinel message triggers the opening turn (agent grounds on the seeded catalog + semantic layer and asks its first ≤2 questions with no user prompt).

### Role persona (from group2 spec, lightly adapted)
> "You are a senior data analyst onboarding a new dataset. An automated profiler has already produced a draft data dictionary and semantic layer — you can see them. Your job is to interview the data owner to **confirm, correct, and deepen** that draft into a complete semantic catalog: what columns mean, how they relate, what business concepts they represent, and what quirks exist. Ask precise, targeted questions. Never ask more than 2 questions at a time. Update the catalog and semantic layer as you learn. Never ask about things the draft already states confidently — confirm them silently or only when genuinely ambiguous."

### Tools (`backend/tools/catalog.py`, extending `backend/tools/dataframe.py`)
| Tool | Signature | Notes |
|---|---|---|
| `get_dataframe_profile` | `(upload_id) -> dict` | Reused from 001. Grounds the agent. |
| `sample_column_values` | `(upload_id, column_name, n=10) -> list` | **New** (add to `dataframe.py`). Random non-null samples so questions are specific. |
| `infer_relationships` | `(upload_id) -> list[dict]` | **New.** Heuristic FK detection via value-set overlap → `[{col_a, col_b, overlap_pct, suggested_relation}]`. (Single-table CSV: overlaps are within-column-name conventions; still useful to propose PK/FK semantics.) |
| `write_catalog_entry` | `(upload_id, column_name, updates: dict) -> str` | **New.** Upserts one catalog row; drives the live right-panel update. Returns "ok"/error string. |
| `update_semantic_layer` | `(upload_id, updates: dict) -> str` | **New.** Merges updates into `uploads.semantic_layer` (grain, relationships, measures, dimensions, time_dimension, suggested_questions). Returns "ok"/error string. |
| `mark_context_complete` | `(upload_id) -> str` | **New.** Sets `uploads.context_complete = TRUE`. |

**Robustness:** every tool catches its own exceptions and returns an error string rather than raising — a bad tool call degrades the turn, never crashes the request. Tools are sync `@tool`s using `asyncio.run` internally (executed in a worker thread by the agent loop, consistent with feature 001 tools).

### Conversation flow
1. **Opening turn (`__INIT__`)**: agent reads the seeded catalog + semantic layer (via `get_dataframe_profile` + reading current state), optionally `infer_relationships`, confirms obvious entries silently, then asks exactly 2 questions about the most ambiguous/high-value columns or an unconfirmed grain/relationship.
2. **Each turn**: `write_catalog_entry` for everything confirmed; `update_semantic_layer` when a dataset-level fact is learned (grain, an FK, a measure definition, a good example question); optionally `sample_column_values` before asking about a new column; ask ≤2 new questions.
3. **Completion** (~4–6 exchanges or when the user says "done"/"that's enough"): summarise, call `mark_context_complete`, return a completion message.

### Turn response contract
```json
{
  "chat": "Got it — revenue is pre-tax USD. Next: is customer_id unique per customer, or can one customer have multiple IDs across orders?",
  "canvas": { "insights": [], "charts": [], "table": null },
  "catalog": [ { "column_name": "revenue", "data_type": "REAL", "semantic_role": "measure", "business_context": "pre-tax USD", "description": "Total order revenue before tax", "is_primary_key": false, "is_foreign_key": false, "foreign_key_ref": null, "is_pii": false, "unit": "USD", "sample_values": ["120.00", "340.50", "89.99"], "null_pct": 8.5 } ],
  "semantic_layer": { "grain": "one order line", "entities": [], "measures": [{"name":"Total revenue","column":"revenue","aggregation":"sum","description":"Pre-tax USD"}], "dimensions": [], "time_dimension": "order_date", "suggested_questions": ["Total revenue by region?"] },
  "complete": false
}
```
- `catalog` is the **full** current catalog (all columns); `semantic_layer` is the full current dataset-level object. Both returned alongside `canvas` (not inside it) to keep the shared `CanvasResponse` contract clean. Frontend replaces the right panel on every response.
- `canvas` stays empty for this screen (shared contract with other screens).
- `complete: true` once `mark_context_complete` has been called.

---

## 7. API endpoints (`backend/main.py`)

```
POST /api/context/{upload_id}/chat
  Body:     { message: string }            -- "__INIT__" for the opening turn
  Response: { chat, canvas, catalog, semantic_layer, complete }
  Effects:  read history → run agent (sync) → agent upserts catalog + semantic_layer
            → save user message + agent reply to context_conversations
  404 if upload_id unknown.

GET /api/context/{upload_id}/catalog
  Response: { slug, columns: CatalogRow[], semantic_layer: SemanticLayer | null }
  Effects:  ensure_catalog_seed() then return current catalog + semantic_layer.
  404 if upload_id unknown.

POST /api/context/{upload_id}/complete
  Response: { ok: true }
  Effects:  mark_context_complete() (idempotent; agent may have set it already).
```

These are 3 endpoints specific to this feature; per project guidelines no others are added here. (Feature 001's `POST /api/upload` and `GET /api/jobs/{job_id}` remain.)

---

## 8. Models & types

**`backend/models.py`** (Pydantic v2, strict, no `Any`):
- `CatalogRow` — mirrors the catalog table row (`sample_values: list[str]`, booleans, `null_pct: float`, nullable `unit`/`foreign_key_ref`/`business_context`).
- `ContextChatRequest` — `{ message: str }`
- `ContextChatResponse` — `{ chat: str, canvas: CanvasResponse, catalog: list[CatalogRow], semantic_layer: SemanticLayer | None, complete: bool }`
- `CatalogResponse` — `{ slug: str, columns: list[CatalogRow], semantic_layer: SemanticLayer | None }`

(`SemanticLayer` and `CanvasResponse` already exist from feature 001 — reused.)

**`frontend/lib/types.ts`** — mirror exactly: `CatalogRow`, `ContextChatRequest`, `ContextChatResponse`, `CatalogResponse`. No `any`. (`SemanticLayer`, `CanvasResponse` already exist.)

---

## 9. Frontend — Screen 2 (`frontend/app/context/page.tsx`)

### Layout
```
┌─────────────────────┬──────────────────────────────────┐
│  LEFT (40%) — Chat  │  RIGHT (60%) — Context            │
│  Agent + user msgs  │  Slug label                       │
│  Input (disabled    │  Catalog table (per-column,        │
│   while turn runs)  │   updates live each turn)          │
│  [✓ Mark Complete]  │  Semantic layer summary            │
│                     │   (grain / measures / dims / Qs)   │
└─────────────────────┴──────────────────────────────────┘
```

### Components
- **`frontend/components/ChatPanel.tsx`** (new) — message list + input box; input disabled while a turn is in flight; hosts the "Mark Complete" button.
- **`frontend/components/CatalogTable.tsx`** (new) — slug label + one row per column (Column | Type | Role | Description | Business context | PK | FK | PII | Samples); re-renders from the `catalog` array on every response.
- **Reuse `frontend/components/SemanticLayer.tsx`** (built in feature 001) for the dataset-level section, fed the live `semantic_layer`.
- Reuse `NavBar.tsx` — step 2 active on this page; marked done after completion.

### Hook + API (`frontend/lib/hooks.ts`, `frontend/lib/api.ts`)
```typescript
function useChatTurn(uploadId: string) {
  // POSTs to /api/context/{uploadId}/chat
  // returns { send(msg), messages, catalog, semanticLayer, loading, complete }
}
```
Plus typed wrappers `getCatalog`, `postContextChat`, `postContextComplete` in `api.ts` (no raw `fetch` in components). Reuse `useUploadId()` for the upload id.

### State flow
1. Page load → `GET /catalog` → populate catalog table + semantic layer (seeded).
2. Auto-fire `POST { message: "__INIT__" }` → render the agent's opening message.
3. User types → POST chat → show loading → on response: append messages, replace catalog + semantic layer.
4. Repeat until a response has `complete: true` → "Mark Complete" activates.
5. Click "Mark Complete" → `POST /complete` → show **completion state** ("Context saved — ready for queries") with a **disabled** Continue (navigation wired when feature 003 lands).

### Guard
If no `upload_id` in context/localStorage (direct navigation), show a prompt to upload first with a link to `/upload`.

---

## 10. Error handling
- Tools never raise — they return error strings; the agent reports failures conversationally and preserves existing catalog/semantic state.
- A failed LLM turn returns a graceful `chat` error message; the right panel is unchanged.
- Frontend wraps each POST in try/catch; on network error, inline retry without losing the conversation.
- `__INIT__` re-firing produces a fresh opening turn (history makes the agent aware of prior context); safe for the demo.

---

## 11. Testing
Per project convention (demo build) — no automated suite. Verification: `python -m py_compile` + inline assertion snippets for DB helpers/seed mapping; `npx tsc --noEmit` for frontend; manual smoke test:
1. Start backend + frontend; open `/context` for an upload that has been through AutoEDA.
2. Verify the catalog table + semantic layer render (seeded) **before** any chat.
3. Verify the opening message asks ≤2 specific questions informed by the seed.
4. Answer; verify the relevant catalog row and/or semantic layer updates and the reply asks new questions.
5. Drive to completion; verify "Mark Complete" activates, completion state shows, and `uploads.context_complete = TRUE` + populated `catalog` / `context_conversations` rows + refined `uploads.semantic_layer` in SQLite.

---

## 12. Out of scope (deferred)
- Direct table-cell editing (interview is conversational only).
- FK entries as linked badges; confidence/muted styling for un-asked inferences; multi-table dropdown.
- Navigation to the Query screen (feature 003).
- Any endpoint beyond the three listed above.

---

## 13. Affected files

**Backend**
- `backend/database.py` (modify) — `catalog` + `context_conversations` tables; seed + helper functions.
- `backend/tools/dataframe.py` (modify) — add `sample_column_values`.
- `backend/tools/catalog.py` (new) — `infer_relationships`, `write_catalog_entry`, `update_semantic_layer`, `mark_context_complete`.
- `backend/agents/context.py` (new) — the turn-based context agent + prompts.
- `backend/models.py` (modify) — `CatalogRow`, `ContextChatRequest`, `ContextChatResponse`, `CatalogResponse`.
- `backend/main.py` (modify) — the 3 context routes (thin).

**Frontend**
- `frontend/lib/types.ts` (modify) — mirror new models.
- `frontend/lib/api.ts` (modify) — `getCatalog`, `postContextChat`, `postContextComplete`.
- `frontend/lib/hooks.ts` (modify) — `useChatTurn`.
- `frontend/components/ChatPanel.tsx`, `CatalogTable.tsx` (new); reuse `SemanticLayer.tsx`, `NavBar.tsx`.
- `frontend/app/context/page.tsx` (new/replace scaffold).
