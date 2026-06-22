# Feature 002 — Connected-Schema Multi-File + Context Agent (Design)

**Date:** 2026-06-22
**Status:** Approved (brainstorming) — pending implementation plans
**Supersedes:** `docs/superpowers/specs/2026-06-22-feature-002-context-agent-design.md` (single-file Context Agent). That earlier doc's single-table assumption is replaced by the global connected-schema model below.
**Builds on:** Feature 001 (Upload + deepagents AutoEDA), which produces, per uploaded CSV, a per-table data dictionary + per-table semantic-layer draft + stats/charts.
**Demo moment:** Upload several related CSVs. Each is profiled into a table; the app shows the whole schema. Then an agent interviews you to confirm the tables, columns, and the **relationships between them**, producing a join-ready connected schema.

---

## 1. Summary

Today each uploaded CSV is an independent dataset and the UI only follows the most recent one. This feature makes **every uploaded CSV a table in one global, implicit schema**, and adds a **schema-level semantic layer that governs cross-table relationships**. A turn-based Context Agent (DeepSeek V4 Flash via OpenRouter) interviews the user to validate and enrich that schema. The output — a per-column catalog across all tables plus a schema semantic layer with relationships — is what feature 003 (text-to-SQL) will consume to generate joins.

**Two phases, one design, one plan each:**
- **Phase 1 — Multi-file → visible global schema.** Upload many CSVs; each runs the existing per-table AutoEDA; the upload screen lists all tables and shows each table's analysis.
- **Phase 2 — Context page over the connected schema.** Heuristic cross-table relationship detection + a Context Agent interview that confirms/enriches tables, columns, and relationships into the schema semantic layer.

---

## 2. Decisions (locked during brainstorming)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Multi-file model | **One global connected schema** — every uploaded CSV is a table in it. No dataset grouping, no library/switcher, no named projects. |
| 2 | Per-table AutoEDA | **Unchanged** (feature 001 stays as-is). The schema-level semantic layer is a NEW artifact built on top, not a rewrite of the per-table one. |
| 3 | Relationships | **Heuristic detection + agent confirmation.** Value-overlap FK detection proposes; the interview confirms/corrects. |
| 4 | Agent stack | **Turn-based LangChain tool-calling agent** on `get_chat_model()` (DeepSeek V4 Flash). Not deepagents. |
| 5 | Delivery | **One combined design (this doc) + two phased implementation plans.** |
| 6 | Completion | Completion state, **no navigation** (feature 003 / Query screen doesn't exist yet). |

---

## 3. Architecture (global connected schema)

```
THE SCHEMA  (implicit, global — everything uploaded belongs to it)
├── tables: every row in `uploads`   (one CSV = one table = raw_{upload_id})
│     each keeps its per-table data_dictionary + per-table semantic_layer draft + stats/charts   [feature 001, unchanged]
│
└── schema_meta (singleton)  →  schema semantic layer (governs the whole schema)
      ├── tables[]          (name, grain, description)
      ├── relationships[]   (from_table.col → to_table.col, kind, confidence)
      ├── measures[]        (name, table, column, aggregation, description)
      ├── dimensions[]      (name, table, column, description)
      └── suggested_questions[]

catalog (per-column, ALL tables)  ←  seeded from each table's data_dictionary; refined by the interview
context_conversations (global)    ←  the single schema interview
```

Phase 1 delivers the left/table side (multi-file upload + browse). Phase 2 delivers `schema_meta`, `catalog`, relationships, and the agent.

---

## 4. Data layer (`backend/database.py`)

### Existing (unchanged): `uploads`
Each row = one table. `raw_{upload_id}`, `row_count`, `col_count`, per-table `data_dictionary`, per-table `semantic_layer` (draft) all stay. The set of all `uploads` rows IS the schema's table list.

### New: `schema_meta` (singleton — the global schema)
```sql
CREATE TABLE IF NOT EXISTS schema_meta (
    id               TEXT PRIMARY KEY DEFAULT 'global',  -- always 'global'
    semantic_layer   TEXT,                                -- JSON: SchemaSemanticLayer
    context_complete BOOLEAN DEFAULT FALSE,
    updated_at       DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### New: `catalog` (per-column, across all tables)
```sql
CREATE TABLE IF NOT EXISTS catalog (
    upload_id        TEXT NOT NULL,    -- which table
    slug             TEXT NOT NULL,    -- table display name
    column_name      TEXT NOT NULL,
    data_type        TEXT,             -- TEXT | INTEGER | REAL | DATETIME
    semantic_role    TEXT,             -- identifier | datetime | measure | dimension
    business_context TEXT,
    description      TEXT,
    is_primary_key   BOOLEAN DEFAULT FALSE,
    is_foreign_key   BOOLEAN DEFAULT FALSE,
    foreign_key_ref  TEXT,             -- "other_table.other_column" (nullable)
    is_pii           BOOLEAN DEFAULT FALSE,
    unit             TEXT,
    sample_values    TEXT,             -- JSON array of strings
    null_pct         REAL,
    updated_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (upload_id, column_name)
);
```

### New: `context_conversations` (global interview)
```sql
CREATE TABLE IF NOT EXISTS context_conversations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    role       TEXT NOT NULL,          -- "user" | "agent"
    content    TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```
(Single global schema → one conversation; no scoping column needed.)

All three created via idempotent `CREATE TABLE IF NOT EXISTS` in `create_tables()`.

### Helpers (async, `aiosqlite`)
- `list_uploads() -> list[dict]` — every table with its latest job id + status + counts (join `uploads`↔`jobs`). *(Phase 1)*
- `ensure_schema_seed() -> None` — if `schema_meta.semantic_layer` is null, synthesize it (Section 6) and seed `catalog` rows from every table's `data_dictionary`. Idempotent. *(Phase 2)*
- `get_catalog() -> list[dict]` — all catalog rows (all tables). *(Phase 2)*
- `upsert_catalog_entry(upload_id, slug, column_name, updates) -> None` *(Phase 2)*
- `get_schema_semantic_layer() -> str | None` / `update_schema_semantic_layer(json_str) -> None` *(Phase 2)*
- `mark_schema_context_complete() -> None` — `schema_meta.context_complete = TRUE`. *(Phase 2)*
- `get_conversation() -> list[dict]` / `save_message(role, content) -> None`. *(Phase 2)*

---

## 5. Models & types

### Phase 1
**`backend/models.py`:** `UploadSummary` — `{ upload_id, slug, filename, row_count: int | None, col_count: int | None, job_id: str, status: Literal["pending","running","done","error"] }`. `UploadsListResponse` — `{ uploads: list[UploadSummary] }`.
**`frontend/lib/types.ts`:** mirror `UploadSummary`, `UploadsListResponse`.

### Phase 2 (multi-table; distinct from feature 001's single-table `SemanticLayer`, which stays for per-table drafts)
**`backend/models.py`** (Pydantic v2, no `Any`):
```python
class SchemaTable(BaseModel):
    name: str          # table slug
    grain: str
    description: str

class Relationship(BaseModel):
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    kind: Literal["one_to_many", "many_to_one", "one_to_one", "many_to_many"] | None = None
    confidence: float | None = None

class SchemaMeasure(BaseModel):
    name: str
    table: str
    column: str
    aggregation: Literal["sum", "avg", "count", "count_distinct", "min", "max", "median"]
    description: str

class SchemaDimension(BaseModel):
    name: str
    table: str
    column: str
    description: str

class SchemaSemanticLayer(BaseModel):
    tables: list[SchemaTable]
    relationships: list[Relationship]
    measures: list[SchemaMeasure]
    dimensions: list[SchemaDimension]
    suggested_questions: list[str]

class CatalogRow(BaseModel):
    upload_id: str
    slug: str
    column_name: str
    data_type: str | None = None
    semantic_role: Literal["identifier", "datetime", "measure", "dimension"] | None = None
    business_context: str | None = None
    description: str | None = None
    is_primary_key: bool = False
    is_foreign_key: bool = False
    foreign_key_ref: str | None = None
    is_pii: bool = False
    unit: str | None = None
    sample_values: list[str] = []
    null_pct: float | None = None

class ContextChatRequest(BaseModel):
    message: str

class ContextChatResponse(BaseModel):
    chat: str
    canvas: CanvasResponse          # empty for this screen; shared contract
    catalog: list[CatalogRow]
    semantic_layer: SchemaSemanticLayer | None = None
    complete: bool

class SchemaResponse(BaseModel):
    catalog: list[CatalogRow]
    semantic_layer: SchemaSemanticLayer | None = None
```
Same validation hardening as feature 001's fix applies: the write tool validates against these models and returns errors to the agent; reasonable variants are coerced; read paths catch `ValidationError`.

**`frontend/lib/types.ts`** — mirror `SchemaTable`, `Relationship`, `SchemaMeasure`, `SchemaDimension`, `SchemaSemanticLayer`, `CatalogRow`, `ContextChatRequest`, `ContextChatResponse`, `SchemaResponse`. No `any`.

---

## 6. Schema synthesis & relationship detection (Phase 2, no LLM)

`ensure_schema_seed()` builds the first draft deterministically so the screen is never empty and the agent has something to refine:

1. **Seed catalog** — one row per (table, column) from each table's `data_dictionary` (mapping as in the superseded doc: `semantic_type → semantic_role`, carry description/sample_values/is_pii/unit/null_pct; leave business_context / PK / FK empty).
2. **Detect relationships (heuristic FK)** — for each pair of columns across *different* tables, compute value-set overlap on non-null values. Propose a relationship when:
   - the column names match or are id-like (`*_id`, `id`, shared stem), AND
   - the overlap of the (likely child) column's values into the (likely parent) column's values exceeds a threshold (e.g. ≥ 0.8).
   Record `{from_table, from_column, to_table, to_column, kind (guessed), confidence (overlap)}`. Cap candidates to avoid O(n²) blowups on wide schemas (only id-like / name-matching columns).
3. **Seed schema semantic layer** — `tables` from each table's per-table draft (name=slug, grain from per-table semantic_layer if present else ""), `relationships` from step 2, `measures`/`dimensions` lifted from per-table drafts and table-qualified, `suggested_questions` merged from per-table drafts. Persist to `schema_meta`.

---

## 7. Context Agent (`backend/agents/context.py`, Phase 2)

LangChain tool-calling agent on `get_chat_model()`. Synchronous per turn (`ainvoke`); full `context_conversations` history passed each turn; `__INIT__` triggers the opening turn (no user prompt). Persona = senior analyst onboarding a multi-table database, already holding the draft schema, interviewing to confirm/correct/deepen — especially relationships. ≤2 questions per turn; never asks what the draft states confidently.

### Tools (`backend/tools/catalog.py`, extending `tools/dataframe.py`)
| Tool | Signature | Notes |
|---|---|---|
| `get_schema_overview` | `() -> dict` | All tables + their columns/dictionaries + current relationships. Grounds the agent. |
| `sample_column_values` | `(upload_id, column_name, n=10) -> list` | Specific questions. |
| `infer_relationships` | `() -> list[dict]` | Cross-table heuristic FK candidates (Section 6 step 2). |
| `write_catalog_entry` | `(upload_id, column_name, updates: dict) -> str` | Upsert one catalog row; drives the live panel. |
| `update_schema_semantic_layer` | `(updates: dict) -> str` | Merge updates into the schema semantic layer (tables, relationships, measures, dimensions, suggested_questions). Validates against `SchemaSemanticLayer`; returns errors to self-correct. |
| `mark_context_complete` | `() -> str` | `schema_meta.context_complete = TRUE`. |

Every tool catches its own exceptions and returns an error string — a bad call degrades the turn, never crashes the request. Sync `@tool`s using `asyncio.run` internally (run in a worker thread by the agent loop, per feature 001 convention).

### Turn response contract
```json
{
  "chat": "Confirmed: orders.CUSTOMERID joins customers.ID. Next: is one order ever split across multiple shipments?",
  "canvas": { "insights": [], "charts": [], "table": null },
  "catalog": [ CatalogRow, ... ],
  "semantic_layer": SchemaSemanticLayer,
  "complete": false
}
```
`catalog` and `semantic_layer` are the FULL current state; the frontend replaces the right panel each turn. `complete: true` once `mark_context_complete` is called.

---

## 8. API endpoints (`backend/main.py`)

**Phase 1**
```
GET /api/uploads
  Response: { uploads: UploadSummary[] }   -- all tables in the schema + per-table job status
```

**Phase 2**
```
GET  /api/context/schema
  Response: { catalog: CatalogRow[], semantic_layer: SchemaSemanticLayer | null }
  Effects:  ensure_schema_seed() then return current catalog + schema semantic layer.

POST /api/context/chat
  Body:     { message: string }            -- "__INIT__" for the opening turn
  Response: { chat, canvas, catalog, semantic_layer, complete }
  Effects:  read history → run agent (sync) → agent upserts catalog + schema semantic layer
            → save user + agent messages.

POST /api/context/complete
  Response: { ok: true }
  Effects:  mark_schema_context_complete() (idempotent).
```
Total new endpoints: 4 (1 in Phase 1, 3 in Phase 2). Existing feature-001 endpoints (`POST /api/upload`, `GET /api/jobs/{job_id}`) unchanged.

---

## 9. Frontend

### Phase 1 — upload screen becomes schema-aware (`frontend/app/upload/page.tsx`)
- Accept **multiple** files (drop several or add more); call `uploadFile` per file; each starts its own job.
- **Table list** (new `TableList.tsx`): every table from `GET /api/uploads` with name, row/col counts, and per-table status badge (polls in-progress ones). Selecting a table shows that table's EDA via the existing `Canvas` (fetch its `job_id`).
- Frontend stops tracking a single `upload_id`; it tracks the **schema** (the list). `useUploadId` is generalized or replaced by a `useSchema()` that lists uploads. "Continue to Context →" enables when at least one table's analysis is `done`.

### Phase 2 — context screen (`frontend/app/context/page.tsx`)
- Left 40% chat (`ChatPanel.tsx`, new), right 60% schema:
  - **Multi-table catalog** (`CatalogTable.tsx`, new) — grouped by table, one row per column; updates live each turn.
  - **Relationships** (`RelationshipList.tsx`, new) — `from_table.col → to_table.col` list (graph optional/deferred).
  - **Schema semantic layer** — reuse/extend `SemanticLayer.tsx` for the multi-table shape (tables, measures, dimensions, suggested questions).
- Completion state ("Context saved — ready for queries") with a **disabled** Continue (feature 003 not built).
- API wrappers in `api.ts` (`listUploads`, `getSchema`, `postContextChat`, `postContextComplete`); `useChatTurn` hook in `hooks.ts`. No raw `fetch` in components.
- Guard: if there are no uploads, prompt to upload first (link to `/upload`).

---

## 10. Error handling
- Tools never raise — they return error strings; the agent reports failures conversationally; existing catalog/schema state is preserved.
- A failed LLM turn returns a graceful `chat` error; the right panel is unchanged.
- Frontend wraps each request in try/catch; network errors show inline retry without losing the conversation.
- Relationship detection is best-effort: zero detected relationships is valid (single-table schema or no overlaps).

---

## 11. Testing
Per project convention (demo build) — no automated suite. Verify with `python -m py_compile` + inline assertion snippets (DB helpers, seed mapping, relationship overlap math), `npx tsc --noEmit`, and manual smoke tests per phase:
- **Phase 1:** upload 2+ CSVs; both appear as tables with `done` status; each table's canvas renders; counts populate.
- **Phase 2:** open `/context`; catalog (all tables) + any detected relationships render before chat; opening message asks ≤2 specific questions; answering updates the relevant catalog row / relationship / semantic layer; drive to completion → `schema_meta.context_complete = TRUE`, populated `catalog`, refined schema `semantic_layer`, `context_conversations` rows.

---

## 12. Out of scope (deferred)
- Dataset grouping / library / multiple separate schemas (global schema only).
- Direct table-cell editing (interview is conversational).
- Relationship **graph** visualization (list is enough; graph optional later).
- Confidence/muted styling; navigation to the Query screen (feature 003).
- Any endpoint beyond those listed.

---

## 13. Affected files

**Phase 1**
- `backend/database.py` — `list_uploads()`.
- `backend/models.py` — `UploadSummary`, `UploadsListResponse`.
- `backend/main.py` — `GET /api/uploads`.
- `frontend/lib/types.ts`, `frontend/lib/api.ts`, `frontend/lib/hooks.ts` — list types/wrapper/`useSchema`.
- `frontend/components/TableList.tsx` (new); `frontend/app/upload/page.tsx` (multi-file + list).

**Phase 2**
- `backend/database.py` — `schema_meta`, `catalog`, `context_conversations` tables + helpers + `ensure_schema_seed`.
- `backend/tools/dataframe.py` — `sample_column_values`.
- `backend/tools/catalog.py` (new) — `get_schema_overview`, `infer_relationships`, `write_catalog_entry`, `update_schema_semantic_layer`, `mark_context_complete`.
- `backend/agents/context.py` (new) — turn-based context agent.
- `backend/models.py` — schema + catalog + chat models.
- `backend/main.py` — `GET /api/context/schema`, `POST /api/context/chat`, `POST /api/context/complete`.
- `frontend/lib/types.ts`, `api.ts`, `hooks.ts` — context types/wrappers/`useChatTurn`.
- `frontend/components/ChatPanel.tsx`, `CatalogTable.tsx`, `RelationshipList.tsx` (new); extend `SemanticLayer.tsx`; `frontend/app/context/page.tsx` (new).
