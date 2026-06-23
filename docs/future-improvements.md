# Future Improvements — Feature 002 (Connected Schema + Context Agent)

Deferred, **non-breaking** findings from the Phase 2 code review (2026-06-23). The
breaking issues (seed atomicity, swallowed schema-load error, Mark-Complete race,
catalog duplicate keys, agent-failure 500 / lost user message) were fixed in commit
`fix(context): harden breaking issues …`. Everything below is a quality / robustness /
efficiency improvement, ordered by priority.

## High priority (data-integrity hardening — fix before heavy multi-user use)

- **`update_schema_semantic_layer` replaces whole lists** (`backend/tools/catalog.py:92`).
  Each provided key overwrites the entire list. If the agent writes a single new
  relationship without first fetching current state, all prior confirmed relationships
  are silently lost. Today this is mitigated only by the system prompt instructing the
  agent to call `get_schema_overview` first. **Fix:** make list updates merge/upsert by a
  natural key (e.g. relationship = `from_table.from_column → to_table.to_column`; measure/
  dimension = `table.name`) instead of replace, or have the tool fetch-merge internally.

- **Granular seed-layer degradation** (`backend/schema_synth.py`, `_validated_layer_json`).
  When any single measure/dimension fails validation (e.g. a bad `aggregation` enum), the
  current fallback drops *all* measures and dimensions. **Fix:** validate each measure/
  dimension individually and keep the valid ones, dropping only the offenders.

- **Agent can't clear a catalog field to NULL** (`backend/database.py:318`,
  `upsert_catalog_entry`). `None` values are treated as "no change", so the agent can never
  blank a stale `description`/`foreign_key_ref`/`unit`. **Fix:** use a sentinel to
  distinguish "omit" from "set NULL", or add an explicit `clear_catalog_field` path.

## Medium priority (robustness / correctness)

- **`postContextComplete` discards the server error body** (`frontend/lib/api.ts:81`).
  Unlike every other wrapper it throws a generic message. **Fix:** apply the same
  `res.json().catch(() => ({ detail: res.statusText }))` pattern used in `getSchema` /
  `postContextChat`.

- **Context agent marks complete too eagerly.** In live testing the agent called
  `mark_context_complete` after a single `__INIT__` turn on a small schema. Not a code
  defect — prompt behavior. **Fix:** tune `SYSTEM_PROMPT` (`backend/agents/context.py`) to
  require a minimum number of confirmed facts / user exchanges before completing.

- **No `AbortController` on context fetches** (`frontend/lib/hooks.ts` init effect, and the
  `useUploads` poll in `frontend/lib/hooks.ts`). Navigating away mid-request wastes an
  in-flight LLM round-trip and sets state on an unmounted component (React 18 ignores it,
  but it's wasteful). **Fix:** thread an `AbortSignal` into the fetch wrappers and abort in
  effect cleanup.

## Low priority (efficiency / maintainability)

- **`sample_column_values` loads the whole table** (`backend/tools/dataframe.py:100`) via a
  full DataFrame load to return ≤10 values. **Fix:** push projection + limit into SQL:
  `SELECT "{col}" FROM {table} WHERE "{col}" IS NOT NULL ORDER BY RANDOM() LIMIT {n}`.

- **`detect_relationships` recomputes value sets per pair** (`backend/schema_synth.py:79`).
  `_value_set(df_a, col_a)` is recomputed for each candidate `col_b`. **Fix:** precompute a
  `{col: value_set}` dict per table before the inner loop.

- **`_SL_KEYS` can drift from the model** (`backend/tools/catalog.py:30`). Hand-maintained
  tuple. **Fix:** `tuple(SchemaSemanticLayer.model_fields)`.

- **Private cross-module import** (`backend/schema_synth.py:23` imports `_load_dataframe`).
  **Fix:** use the public `load_upload_dataframe_sync` wrapper in `backend/tools/dataframe.py`.

- **`"__INIT__"` magic sentinel crosses the HTTP boundary** with no shared constant
  (`frontend/lib/hooks.ts` ↔ `backend/agents/context.py`). A rename on one side silently
  breaks the opening turn. **Fix:** a dedicated `init: bool` field on the chat request, or a
  shared exported constant.

- **`CatalogTable` groups distinct uploads that share a slug** (`frontend/components/CatalogTable.tsx`).
  The duplicate-key crash is fixed (row key now `upload_id:column_name`), but two uploads
  with the same filename still merge under one slug header. **Fix:** group by `upload_id`
  and show the filename to disambiguate.

## Carried over from Phase 1 (multi-file upload page)

- Inline drag handlers in `frontend/app/upload/page.tsx` aren't wrapped in `useCallback`
  (minor inconsistency with the rest of the file).
- `useUploads` poll fetch has no `AbortController` (same as above).
