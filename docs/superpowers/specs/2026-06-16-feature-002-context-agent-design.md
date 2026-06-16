# Feature 002 — Context Agent (Design)

**Date:** 2026-06-16
**Status:** Approved for planning
**Builds on:** Feature 001 (Upload + Auto EDA), `docs/superpowers/specs/2026-04-17-group2-context-agent.md`
**Demo moment:** An agent reads your dataset and interviews you. The semantic catalog fills in live on the right as each answer is given.

---

## Decisions (locked)

| Decision | Choice | Rationale |
|---|---|---|
| Conversation engine | **Real LLM** — LangGraph + OpenAI GPT-4o tool-calling agent | The feature *is* a conversational interview; a scripted agent undercuts the core demo moment. A real `OPENAI_API_KEY` is present in `.env`. |
| Scope | **Must-haves only** | FK linked badges, confidence/muted styling, and multi-table dropdown are explicitly deferred. |
| "Mark Complete" navigation | **Completion state, no navigation** | The Query screen (feature 003) does not exist yet. Avoid a dead link; show a "Context saved — ready for queries" state with a disabled Continue button. Wire navigation to `/query` when 003 lands. |
| Starter catalog timing | **Lazy + idempotent** via `ensure_starter_catalog()` on `GET /catalog` | Feature 001 is already shipped and existing uploads have no catalog rows. Building lazily works for already-uploaded datasets and leaves the shipped upload pipeline untouched. |

---

## Architecture

Pattern B (turn-based JSON, synchronous) per `datalens-architecture.md`. Each user message → one POST → one response carrying both the chat reply and the full current catalog. SQLite is the source of truth. No background jobs, no polling, no WebSockets.

```
Frontend (context/page.tsx)
  GET  /api/context/{id}/catalog   → starter catalog (right panel)
  POST /api/context/{id}/chat      → { chat, canvas, catalog, complete }
  POST /api/context/{id}/complete  → { ok: true }
        │
        ▼
FastAPI (main.py, thin routes)
        │  context_agent.ainvoke() — synchronous per turn (<5s)
        ▼
LangGraph Context Agent (agents/context.py)
        │  5 tools (tools/catalog.py + tools/dataframe.py)
        ▼
SQLite: catalog, context_conversations, uploads.context_complete, raw_{slug}
```

---

## Data Layer (`backend/database.py`)

### New table: `catalog`
One row per column. Composite primary key `(upload_id, column_name)` so writes are idempotent upserts.

```sql
CREATE TABLE IF NOT EXISTS catalog (
    upload_id        TEXT NOT NULL,
    slug             TEXT NOT NULL,
    column_name      TEXT NOT NULL,
    data_type        TEXT,            -- TEXT | INTEGER | REAL | DATETIME
    inferred_role    TEXT,            -- identifier | datetime | measure | dimension
    business_context TEXT,            -- free text from the interview ("pre-tax USD")
    description      TEXT,
    is_primary_key   BOOLEAN DEFAULT FALSE,
    is_foreign_key   BOOLEAN DEFAULT FALSE,
    foreign_key_ref  TEXT,            -- e.g. "orders.user_id" (nullable)
    sample_values    TEXT,            -- JSON array of strings
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

`uploads.context_complete` already exists (added in feature 001) — no migration needed.

### New helpers (all async, `aiosqlite`)
- `ensure_starter_catalog(upload_id, slug)` — if no catalog rows exist for `upload_id`, build them from the raw profile (no LLM). Idempotent.
- `get_catalog(upload_id) -> list[CatalogRow dict]`
- `upsert_catalog_entry(upload_id, slug, column_name, updates: dict) -> None`
- `mark_context_complete(upload_id) -> None`
- `get_conversation(upload_id) -> list[{role, content}]`
- `save_message(upload_id, role, content) -> None`

### Starter catalog inference (heuristic, no LLM)
Built from the raw profile (`get_dataframe_profile`):
- **column_name** — CSV header
- **data_type** — pandas-inferred (TEXT / INTEGER / REAL / DATETIME)
- **sample_values** — 3 random non-null values
- **inferred_role**:
  - name ends in `_id` or equals `id` → `identifier`
  - dtype datetime → `datetime`
  - dtype numeric and name contains `revenue|amount|count|price|qty|total` → `measure`
  - otherwise → `dimension`
- `business_context` / `description` left empty for the agent to fill.

---

## Backend Agent (`backend/agents/context.py`)

LangGraph single-node tool-calling agent. GPT-4o via `langchain-openai`. Runs synchronously per turn. Full conversation history (from `context_conversations`) is passed on every invocation. The `__INIT__` sentinel message triggers the opening turn (agent profiles the data and asks its first ≤2 questions with no user prompt).

### Role persona (from group2 spec)
> "You are a senior data analyst onboarding a new dataset for the first time. Your job is to interview the data owner to build a complete semantic catalog — understanding not just what columns are named, but what they mean, how they relate, what business concepts they represent, and what quirks exist. You ask precise, targeted questions. You never ask more than 2 questions at a time. You update the catalog as you learn. You never ask about things you can confidently infer."

### Tools (`backend/tools/catalog.py`, extending `backend/tools/dataframe.py`)
| Tool | Signature | Notes |
|---|---|---|
| `get_dataframe_profile` | `(upload_id) -> dict` | Already exists from 001; reused. Called once to ground the agent. |
| `sample_column_values` | `(upload_id, column_name, n=10) -> list` | New (add to `dataframe.py`). Random non-null samples so questions are specific. |
| `infer_relationships` | `(upload_id) -> list[dict]` | New. Heuristic FK detection via value-set overlap: `[{col_a, col_b, overlap_pct, suggested_relation}]`. |
| `write_catalog_entry` | `(upload_id, column_name, updates: dict) -> bool` | New. Upserts one catalog row; drives the live right-panel update. |
| `mark_catalog_complete` | `(upload_id) -> bool` | New. Sets `uploads.context_complete = TRUE`. |

**Robustness:** every tool catches its own exceptions and returns an error string / `False` rather than raising — a bad tool call degrades the turn, it never crashes the request.

### Conversation flow
1. **Opening turn (`__INIT__`)**: agent calls `get_dataframe_profile` + `infer_relationships`, writes confidently-inferable entries to the catalog, then asks exactly 2 questions about the most ambiguous columns.
2. **Each turn**: `write_catalog_entry` for everything confirmed, optionally `sample_column_values` on a new column, ask ≤2 new questions.
3. **Completion** (after ~4–6 exchanges or when the user says "done"/"that's enough"): summarise, call `mark_catalog_complete`, return a completion message.

### Turn response contract
```json
{
  "chat": "Got it — revenue is pre-tax USD. Next: is customer_id unique per customer, or can one customer have multiple IDs across orders?",
  "canvas": { "insights": [], "charts": [], "table": null },
  "catalog": [ { "column_name": "revenue", "data_type": "REAL", "inferred_role": "measure", "business_context": "pre-tax USD", "description": "Total order revenue before tax", "is_primary_key": false, "is_foreign_key": false, "foreign_key_ref": null, "sample_values": ["120.00", "340.50", "89.99"] } ],
  "complete": false
}
```
- `catalog` is the **full** current catalog (all columns), returned alongside `canvas` (not inside it) to keep the shared `CanvasResponse` contract clean. Frontend replaces the right panel on every response.
- `canvas` stays empty for this screen (the contract is shared with other screens).
- `complete: true` once `mark_catalog_complete` has been called.

---

## API Endpoints (`backend/main.py`)

```
POST /api/context/{upload_id}/chat
  Body:     { message: string }            -- "__INIT__" for the opening turn
  Response: { chat, canvas, catalog, complete }
  Effects:  read history → run agent (sync) → agent upserts catalog
            → save user message + agent reply to context_conversations
  404 if upload_id unknown.

GET /api/context/{upload_id}/catalog
  Response: { slug, columns: CatalogRow[] }
  Effects:  calls ensure_starter_catalog() then returns current catalog.
  404 if upload_id unknown.

POST /api/context/{upload_id}/complete
  Response: { ok: true }
  Effects:  mark_context_complete() (idempotent; agent may have set it already).
```

These are 3 of the 9 endpoints in the overall architecture. Per project guidelines, no endpoints beyond these are added in this feature.

---

## Models & Types

**`backend/models.py`** (Pydantic v2, strict, no `Any`):
- `CatalogRow` — mirrors the catalog table row (sample_values as `list[str]`).
- `ContextChatRequest` — `{ message: str }`
- `ContextChatResponse` — `{ chat: str, canvas: CanvasResponse, catalog: list[CatalogRow], complete: bool }`
- `CatalogResponse` — `{ slug: str, columns: list[CatalogRow] }`

**`frontend/lib/types.ts`** — mirror exactly: `CatalogRow`, `ContextChatRequest`, `ContextChatResponse`, `CatalogResponse`. No `any`.

---

## Frontend — Screen 2 (`frontend/app/context/page.tsx`)

### Layout (matches prototype design system)
```
┌─────────────────────┬──────────────────────────────────┐
│  LEFT (40%) — Chat  │  RIGHT (60%) — Catalog            │
│  Agent + user msgs  │  Slug label: "sales_data_sample"   │
│  Input (disabled    │  Table: Column | Type | Role |     │
│   while agent runs) │         Description | PK | FK |     │
│  [✓ Mark Complete]  │         Sample Values              │
└─────────────────────┴──────────────────────────────────┘
```

### Components
- `frontend/components/ChatPanel.tsx` — message list + input box; input disabled while a turn is in flight; hosts the "Mark Complete" button.
- `frontend/components/CatalogTable.tsx` — slug label + one row per column; re-renders from the `catalog` array on every response.
- Reuse existing `NavBar.tsx` — step 2 unlocked/active once on this page; step 2 marked done after completion.

### Hook (`frontend/lib/hooks.ts`)
```typescript
function useChatTurn(uploadId: string) {
  // POSTs to /api/context/{uploadId}/chat
  // returns { send(msg), messages, catalog, loading, complete }
}
```
Plus `getCatalog`, `postContextChat`, `postContextComplete` typed wrappers in `frontend/lib/api.ts` (no raw `fetch` in components).

### State flow
1. Page load → `GET /catalog` → populate right panel with starter catalog.
2. Auto-fire `POST { message: "__INIT__" }` → render the agent's opening message.
3. User types → POST chat → show loading → on response: append messages, replace catalog panel.
4. Repeat until a response has `complete: true` → "Mark Complete" button activates.
5. Click "Mark Complete" → `POST /complete` → show **completion state** ("Context saved — ready for queries") with a **disabled** Continue button (no navigation; Query screen is feature 003).

### Guard
If no `upload_id` is in context/localStorage (user navigated directly), show a prompt to upload first with a link back to `/upload`.

---

## Error Handling
- Tools never raise — they return error strings / `False`; the agent reports tool failures conversationally and preserves existing catalog state.
- A failed LLM turn returns a graceful `chat` error message; the catalog panel is unchanged.
- Frontend wraps each POST in try/catch; on network error, shows an inline retry without losing the conversation.
- `__INIT__` is idempotent enough for a demo: re-firing produces a fresh opening turn (conversation history makes the agent aware of prior context).

---

## Testing
Per project convention (demo build) — no automated test suite. Validation is a manual smoke test (quickstart):
1. Start backend + frontend; open `/context` with a known `upload_id` (the existing `raw_sales_data_sample` table is already in the DB).
2. Verify the starter catalog renders before any chat.
3. Verify the agent's opening message asks ≤2 specific questions.
4. Answer; verify the catalog row updates and the reply asks new questions.
5. Drive to completion; verify "Mark Complete" activates, completion state shows, and `uploads.context_complete = TRUE` + populated `catalog` / `context_conversations` rows in SQLite.

---

## Out of Scope (deferred)
- FK entries as linked badges (`→ orders.user_id`)
- Confidence styling (muted/italic for un-asked inferences)
- Multi-table dropdown for CSVs mapping to multiple logical tables
- Navigation to the Query screen (feature 003)
- Any endpoint beyond the three listed above
