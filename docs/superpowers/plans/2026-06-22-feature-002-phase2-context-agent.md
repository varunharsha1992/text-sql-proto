# Feature 002 Phase 2 — Context Agent over the Connected Schema (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Screen 2: a turn-based agent that interviews the user to validate and enrich the global connected schema — a per-column catalog across all tables plus a schema-level semantic layer with cross-table relationships.

**Architecture:** Pattern B (synchronous turn-based chat). A deterministic seed (`ensure_schema_seed`) builds the first-draft catalog (from each table's data dictionary) + schema semantic layer (from per-table drafts + heuristic cross-table FK detection). A LangChain/LangGraph tool-calling agent on DeepSeek V4 Flash (via OpenRouter) refines it turn by turn. SQLite is the source of truth.

**Tech Stack:** FastAPI + aiosqlite; LangGraph `create_react_agent` + `langchain-openai` via `backend.llm.get_chat_model()`; pandas (relationship overlap); Next.js 14 / TypeScript / React.

## Global Constraints

- Model: DeepSeek V4 Flash via OpenRouter through `backend.llm.get_chat_model()` (already exists — do NOT reconfigure model/provider).
- One global, implicit schema: all `uploads` rows are its tables. The context endpoints take NO `upload_id` (schema-wide). Tools reference `upload_id` only to identify which table a column belongs to.
- Endpoints: this phase adds exactly THREE — `GET /api/context/schema`, `POST /api/context/chat`, `POST /api/context/complete`. No others.
- Backend imports package-qualified; run Python with `PYTHONPATH=.` from repo root `C:/Dev/text-sql-proto/text-sql-proto`.
- No `Any` in Pydantic models / no `any` in TypeScript.
- `SchemaSemanticLayer` (multi-table) is DISTINCT from feature 001's single-table `SemanticLayer`; do not merge them.
- Tools never raise — they return error strings; the agent reports failures conversationally.
- Verification (NO pytest/jest in this repo — do NOT scaffold one): backend = `python -m py_compile` + inline assertion snippet under `PYTHONPATH=.` against a temp DB; frontend = `npx tsc --noEmit`. Pipe NumPy warnings with `2>/dev/null`. The live agent turn needs a real `OPENROUTER_API_KEY` (already in `.env`).
- Raw data table for an upload is `backend.database.raw_table_name(upload_id)`.
- Catalog seed mapping (`data_dictionary.semantic_type` → `catalog.semantic_role`): `identifier→identifier`, `temporal→datetime`, `currency→measure`, `numeric→measure`, (`categorical`|`boolean`|`text`)→`dimension`.

---

## File Structure

- `backend/database.py` (modify) — `schema_meta`, `catalog`, `context_conversations` tables; helpers.
- `backend/schema_synth.py` (new) — `detect_relationships()`, `ensure_schema_seed()` (no LLM).
- `backend/tools/dataframe.py` (modify) — `sample_column_values`.
- `backend/tools/catalog.py` (new) — the agent's catalog/schema tools.
- `backend/agents/context.py` (new) — the turn-based context agent + `run_context_turn`.
- `backend/models.py` (modify) — schema + catalog + chat models.
- `backend/main.py` (modify) — three context routes.
- `frontend/lib/types.ts`, `frontend/lib/api.ts`, `frontend/lib/hooks.ts` (modify) — types, wrappers, `useChatTurn`.
- `frontend/components/ChatPanel.tsx`, `CatalogTable.tsx`, `RelationshipList.tsx`, `SchemaSemanticView.tsx` (new).
- `frontend/app/context/page.tsx` (new).

---

## Task 1: DB tables + helpers

**Files:**
- Modify: `backend/database.py`

**Interfaces:**
- Produces (all async unless noted): `get_upload(upload_id) -> dict | None`; `get_catalog() -> list[dict]`; `upsert_catalog_entry(upload_id, slug, column_name, updates: dict) -> None`; `catalog_count() -> int`; `get_schema_semantic_layer() -> str | None`; `set_schema_semantic_layer(json_str: str) -> None`; `get_schema_meta() -> dict`; `mark_schema_context_complete() -> None`; `get_conversation() -> list[dict]`; `save_message(role: str, content: str) -> None`.

- [ ] **Step 1: Add the three tables to `create_tables`**

In `backend/database.py`, inside `create_tables`, extend the `executescript` SQL (add these three `CREATE TABLE IF NOT EXISTS` blocks to the existing script string, before the closing `"""`):

```sql
        CREATE TABLE IF NOT EXISTS schema_meta (
            id TEXT PRIMARY KEY DEFAULT 'global',
            semantic_layer TEXT,
            context_complete BOOLEAN DEFAULT FALSE,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS catalog (
            upload_id TEXT NOT NULL,
            slug TEXT NOT NULL,
            column_name TEXT NOT NULL,
            data_type TEXT,
            semantic_role TEXT,
            business_context TEXT,
            description TEXT,
            is_primary_key BOOLEAN DEFAULT FALSE,
            is_foreign_key BOOLEAN DEFAULT FALSE,
            foreign_key_ref TEXT,
            is_pii BOOLEAN DEFAULT FALSE,
            unit TEXT,
            sample_values TEXT,
            null_pct REAL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (upload_id, column_name)
        );

        CREATE TABLE IF NOT EXISTS context_conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
```

- [ ] **Step 2: Add the helpers**

Append to `backend/database.py`:

```python
import json as _json  # local alias; database.py has no json import yet

_CATALOG_FIELDS = (
    "data_type", "semantic_role", "business_context", "description",
    "is_primary_key", "is_foreign_key", "foreign_key_ref", "is_pii",
    "unit", "sample_values", "null_pct",
)


async def get_upload(upload_id: str) -> dict | None:
    db = await get_db()
    try:
        async with db.execute("SELECT * FROM uploads WHERE id = ?", (upload_id,)) as cur:
            row = await cur.fetchone()
        return {k: row[k] for k in row.keys()} if row else None
    finally:
        await db.close()


async def get_catalog() -> list[dict]:
    db = await get_db()
    try:
        async with db.execute(
            "SELECT * FROM catalog ORDER BY slug, column_name"
        ) as cur:
            rows = await cur.fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]
    finally:
        await db.close()


async def catalog_count() -> int:
    db = await get_db()
    try:
        async with db.execute("SELECT COUNT(*) FROM catalog") as cur:
            (n,) = await cur.fetchone()
        return int(n)
    finally:
        await db.close()


async def upsert_catalog_entry(
    upload_id: str, slug: str, column_name: str, updates: dict
) -> None:
    """Insert or update one catalog row. `updates` may contain any of _CATALOG_FIELDS;
    sample_values (a list) is JSON-encoded."""
    clean: dict = {}
    for field in _CATALOG_FIELDS:
        if field in updates and updates[field] is not None:
            val = updates[field]
            if field == "sample_values" and isinstance(val, list):
                val = _json.dumps([str(x) for x in val])
            clean[field] = val
    db = await get_db()
    try:
        # Ensure the row exists (keyed by upload_id, column_name), then patch fields.
        await db.execute(
            "INSERT OR IGNORE INTO catalog (upload_id, slug, column_name) VALUES (?, ?, ?)",
            (upload_id, slug, column_name),
        )
        if clean:
            sets = ", ".join(f"{f} = ?" for f in clean)
            params = list(clean.values()) + [upload_id, column_name]
            await db.execute(
                f"UPDATE catalog SET {sets}, updated_at = CURRENT_TIMESTAMP "
                f"WHERE upload_id = ? AND column_name = ?",
                params,
            )
        await db.commit()
    finally:
        await db.close()


async def _ensure_schema_row(db: aiosqlite.Connection) -> None:
    await db.execute("INSERT OR IGNORE INTO schema_meta (id) VALUES ('global')")


async def get_schema_meta() -> dict:
    db = await get_db()
    try:
        await _ensure_schema_row(db)
        await db.commit()
        async with db.execute("SELECT * FROM schema_meta WHERE id = 'global'") as cur:
            row = await cur.fetchone()
        return {k: row[k] for k in row.keys()}
    finally:
        await db.close()


async def get_schema_semantic_layer() -> str | None:
    meta = await get_schema_meta()
    val = meta.get("semantic_layer")
    return val if isinstance(val, str) else None


async def set_schema_semantic_layer(json_str: str) -> None:
    db = await get_db()
    try:
        await _ensure_schema_row(db)
        await db.execute(
            "UPDATE schema_meta SET semantic_layer = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 'global'",
            (json_str,),
        )
        await db.commit()
    finally:
        await db.close()


async def mark_schema_context_complete() -> None:
    db = await get_db()
    try:
        await _ensure_schema_row(db)
        await db.execute(
            "UPDATE schema_meta SET context_complete = TRUE, updated_at = CURRENT_TIMESTAMP WHERE id = 'global'"
        )
        await db.commit()
    finally:
        await db.close()


async def get_conversation() -> list[dict]:
    db = await get_db()
    try:
        async with db.execute(
            "SELECT role, content FROM context_conversations ORDER BY id"
        ) as cur:
            rows = await cur.fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in rows]
    finally:
        await db.close()


async def save_message(role: str, content: str) -> None:
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO context_conversations (role, content) VALUES (?, ?)",
            (role, content),
        )
        await db.commit()
    finally:
        await db.close()
```

- [ ] **Step 3: Verify**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && python -m py_compile backend/database.py && PYTHONPATH=. python -c "
import asyncio, tempfile, os, json
d=tempfile.mkdtemp(); os.environ['DATABASE_URL']=f'sqlite+aiosqlite:///{d}/t.db'
from backend.database import (get_db, create_tables, create_upload, upsert_catalog_entry,
  get_catalog, catalog_count, set_schema_semantic_layer, get_schema_semantic_layer,
  mark_schema_context_complete, get_schema_meta, save_message, get_conversation, get_upload)
async def main():
    db=await get_db(); await create_tables(db); await db.close()
    await create_upload('u1','orders.csv','orders','/p')
    await upsert_catalog_entry('u1','orders','revenue',{'semantic_role':'measure','sample_values':[1,2],'is_pii':False})
    await upsert_catalog_entry('u1','orders','revenue',{'description':'order revenue'})  # update same row
    cat=await get_catalog()
    print('catalog rows:', await catalog_count(), '| sample_values json:', cat[0]['sample_values'], '| desc:', cat[0]['description'])
    await set_schema_semantic_layer(json.dumps({'tables':[]}))
    print('sl roundtrip:', get_schema_semantic_layer.__name__, json.loads(await get_schema_semantic_layer())=={'tables':[]})
    await mark_schema_context_complete()
    print('complete flag:', (await get_schema_meta())['context_complete'])
    await save_message('user','hi'); await save_message('agent','hello')
    print('conversation:', [m['role'] for m in await get_conversation()])
    print('get_upload slug:', (await get_upload('u1'))['slug'])
asyncio.run(main())
" 2>/dev/null
```

Expected: `catalog rows: 1 | sample_values json: ["1", "2"] | desc: order revenue`, `complete flag: 1`, `conversation: ['user', 'agent']`, `get_upload slug: orders`.

- [ ] **Step 4: Commit**

```bash
git add backend/database.py
git commit -m "feat(context): schema_meta + catalog + conversation tables and helpers"
```

---

## Task 2: `sample_column_values` + heuristic relationship detection

**Files:**
- Modify: `backend/tools/dataframe.py`
- Create: `backend/schema_synth.py`

**Interfaces:**
- Consumes: `database.list_uploads` (Phase 1), `database.get_upload`, `tools.dataframe.load_upload_dataframe_sync`.
- Produces: `dataframe.sample_column_values(upload_id, column_name, n=10) -> list[str]`; `schema_synth.detect_relationships() -> list[dict]` (keys: `from_table, from_column, to_table, to_column, kind, confidence`).

- [ ] **Step 1: Add `sample_column_values` to `dataframe.py`**

In `backend/tools/dataframe.py`, append a plain helper (NOT a tool yet — the tool wrapper lives in `catalog.py`):

```python
def sample_column_values(upload_id: str, column_name: str, n: int = 10) -> list[str]:
    """Up to n random non-null sample values from a column, as strings."""
    df = load_upload_dataframe_sync(upload_id)
    if column_name not in df.columns:
        return []
    series = df[column_name].dropna()
    if series.empty:
        return []
    take = min(n, len(series))
    sampled = series.sample(take, random_state=42) if len(series) > take else series
    return [str(v) for v in sampled.tolist()]
```

- [ ] **Step 2: Create `schema_synth.py` with relationship detection**

Create `backend/schema_synth.py`:

```python
"""Deterministic schema synthesis: cross-table FK detection + first-draft seed.

No LLM. Reads every uploaded table's raw data to propose relationships, and seeds
the catalog + schema semantic layer so the Context screen is never empty.
"""

from __future__ import annotations

import json
import logging

import pandas as pd

from backend.database import (
    catalog_count,
    get_upload,
    list_uploads,
    set_schema_semantic_layer,
    upsert_catalog_entry,
)
from backend.tools.dataframe import load_upload_dataframe_sync

logger = logging.getLogger(__name__)

_OVERLAP_THRESHOLD = 0.8
_SEMANTIC_ROLE = {
    "identifier": "identifier",
    "temporal": "datetime",
    "currency": "measure",
    "numeric": "measure",
    "categorical": "dimension",
    "boolean": "dimension",
    "text": "dimension",
}


def _id_like(name: str) -> bool:
    n = name.lower()
    return n == "id" or n.endswith("id") or n.endswith("_id") or n.endswith("code")


def _value_set(df: pd.DataFrame, col: str) -> set:
    return set(str(v) for v in df[col].dropna().unique())


def detect_relationships() -> list[dict]:
    """Cross-table FK candidates via value-set overlap on id-like / name-matching columns."""
    import asyncio

    uploads = asyncio.run(list_uploads())
    tables: list[tuple[str, str, pd.DataFrame]] = []  # (slug, upload_id, df)
    for u in uploads:
        if u.get("status") != "done":
            continue
        try:
            df = load_upload_dataframe_sync(u["id"])
        except Exception:  # noqa: BLE001 - a missing raw table just skips that table
            continue
        tables.append((u["slug"], u["id"], df))

    rels: list[dict] = []
    for i, (slug_a, _id_a, df_a) in enumerate(tables):
        for slug_b, _id_b, df_b in tables[i + 1:]:
            for col_a in df_a.columns:
                for col_b in df_b.columns:
                    name_match = col_a.lower() == col_b.lower()
                    if not (name_match or (_id_like(col_a) and _id_like(col_b))):
                        continue
                    set_a, set_b = _value_set(df_a, col_a), _value_set(df_b, col_b)
                    if not set_a or not set_b:
                        continue
                    inter = len(set_a & set_b)
                    # child = the side whose values are mostly contained in the other (the parent key)
                    a_into_b = inter / len(set_a)
                    b_into_a = inter / len(set_b)
                    if max(a_into_b, b_into_a) < _OVERLAP_THRESHOLD:
                        continue
                    if a_into_b >= b_into_a:
                        rels.append({
                            "from_table": slug_a, "from_column": col_a,
                            "to_table": slug_b, "to_column": col_b,
                            "kind": "many_to_one", "confidence": round(a_into_b, 2),
                        })
                    else:
                        rels.append({
                            "from_table": slug_b, "from_column": col_b,
                            "to_table": slug_a, "to_column": col_a,
                            "kind": "many_to_one", "confidence": round(b_into_a, 2),
                        })
    logger.info("detect_relationships found %s candidates", len(rels))
    return rels
```

- [ ] **Step 3: Verify relationship math on two synthetic tables**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && python -m py_compile backend/tools/dataframe.py backend/schema_synth.py && PYTHONPATH=. python -c "
import asyncio, tempfile, os, csv
d=tempfile.mkdtemp(); os.environ['DATABASE_URL']=f'sqlite+aiosqlite:///{d}/t.db'; os.environ['UPLOAD_DIR']=d
from backend.database import get_db, create_tables, create_upload, create_job, update_job
from backend.utils.csv_parser import parse_csv_to_sqlite
from backend.schema_synth import detect_relationships
from backend.tools.dataframe import sample_column_values
# customers: id 1..5 ; orders: customer_id in 1..5
cust=os.path.join(d,'c.csv'); ordr=os.path.join(d,'o.csv')
with open(cust,'w',newline='') as f: csv.writer(f).writerows([['id','name']]+[[i,f'c{i}'] for i in range(1,6)])
with open(ordr,'w',newline='') as f: csv.writer(f).writerows([['order_id','customer_id','total']]+[[100+i, (i%5)+1, i*10] for i in range(20)])
async def boot():
    db=await get_db(); await create_tables(db); await db.close()
    for uid,slug,p in [('cu','customers',cust),('or','orders',ordr)]:
        await create_upload(uid,f'{slug}.csv',slug,p); jid=uid+'j'; await create_job(jid,'autoeda',uid); await update_job(jid,'done')
        parse_csv_to_sqlite(uid,slug,p)
asyncio.run(boot())
rels=detect_relationships()
print('relationships:', rels)
print('sample customer_id:', sample_column_values('or','customer_id',3))
" 2>/dev/null
```

Expected: one relationship `orders.customer_id → customers.id` (kind many_to_one, confidence 1.0), and 3 sample values printed.

- [ ] **Step 4: Commit**

```bash
git add backend/tools/dataframe.py backend/schema_synth.py
git commit -m "feat(context): sample_column_values + heuristic cross-table relationship detection"
```

---

## Task 3: `ensure_schema_seed` — first-draft catalog + schema semantic layer

**Files:**
- Modify: `backend/schema_synth.py`

**Interfaces:**
- Consumes: Task 1 helpers, Task 2 `detect_relationships`.
- Produces: `schema_synth.ensure_schema_seed() -> None` (async). Idempotent: does nothing if catalog already has rows.

- [ ] **Step 1: Add `ensure_schema_seed` to `schema_synth.py`**

Append to `backend/schema_synth.py`:

```python
async def ensure_schema_seed() -> None:
    """Idempotent: if the catalog is empty, seed it from every table's data_dictionary
    and build the first-draft schema semantic layer (tables + heuristic relationships)."""
    if await catalog_count() > 0:
        return

    uploads = await list_uploads()
    tables_meta: list[dict] = []
    measures: list[dict] = []
    dimensions: list[dict] = []
    suggested: list[str] = []

    for u in uploads:
        upload = await get_upload(u["id"])
        if upload is None:
            continue
        slug = upload["slug"]
        dd_raw = upload.get("data_dictionary")
        sl_raw = upload.get("semantic_layer")
        entries = json.loads(dd_raw) if isinstance(dd_raw, str) and dd_raw else []
        per_table_sl = json.loads(sl_raw) if isinstance(sl_raw, str) and sl_raw else {}

        # Seed catalog rows from this table's data dictionary.
        for e in entries:
            col = e.get("column")
            if not col:
                continue
            await upsert_catalog_entry(u["id"], slug, col, {
                "data_type": e.get("dtype"),
                "semantic_role": _SEMANTIC_ROLE.get(e.get("semantic_type", ""), "dimension"),
                "description": e.get("description"),
                "sample_values": e.get("sample_values") or [],
                "is_pii": bool(e.get("is_pii", False)),
                "unit": e.get("unit"),
                "null_pct": e.get("null_pct"),
            })

        tables_meta.append({
            "name": slug,
            "grain": str(per_table_sl.get("grain") or ""),
            "description": "",
        })
        for m in per_table_sl.get("measures", []) or []:
            measures.append({
                "name": m.get("name", ""), "table": slug,
                "column": m.get("column", ""),
                "aggregation": m.get("aggregation", "sum"),
                "description": m.get("description", ""),
            })
        for dim in per_table_sl.get("dimensions", []) or []:
            dimensions.append({
                "name": dim.get("name", ""), "table": slug,
                "column": dim.get("column", ""),
                "description": dim.get("description", ""),
            })
        for q in per_table_sl.get("suggested_questions", []) or []:
            if q not in suggested:
                suggested.append(q)

    semantic_layer = {
        "tables": tables_meta,
        "relationships": detect_relationships(),
        "measures": measures,
        "dimensions": dimensions,
        "suggested_questions": suggested[:8],
    }
    await set_schema_semantic_layer(json.dumps(semantic_layer))
    logger.info("Seeded schema: %s tables, %s relationships",
                len(tables_meta), len(semantic_layer["relationships"]))
```

- [ ] **Step 2: Verify seeding (reuses Task 2's synthetic tables + a fake data_dictionary)**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && python -m py_compile backend/schema_synth.py && PYTHONPATH=. python -c "
import asyncio, tempfile, os, csv, json
d=tempfile.mkdtemp(); os.environ['DATABASE_URL']=f'sqlite+aiosqlite:///{d}/t.db'; os.environ['UPLOAD_DIR']=d
from backend.database import (get_db, create_tables, create_upload, create_job, update_job,
  update_upload_artifacts, get_catalog, get_schema_semantic_layer, catalog_count)
from backend.utils.csv_parser import parse_csv_to_sqlite
from backend.schema_synth import ensure_schema_seed
cust=os.path.join(d,'c.csv'); ordr=os.path.join(d,'o.csv')
with open(cust,'w',newline='') as f: csv.writer(f).writerows([['id','name']]+[[i,f'c{i}'] for i in range(1,6)])
with open(ordr,'w',newline='') as f: csv.writer(f).writerows([['order_id','customer_id','total']]+[[100+i,(i%5)+1,i*10] for i in range(20)])
async def main():
    db=await get_db(); await create_tables(db); await db.close()
    for uid,slug,p,dd in [
      ('cu','customers',cust,[{'column':'id','dtype':'int64','semantic_type':'identifier','description':'PK','sample_values':['1'],'null_pct':0.0,'is_pii':False},{'column':'name','dtype':'object','semantic_type':'text','description':'name','sample_values':['c1'],'null_pct':0.0,'is_pii':True}]),
      ('or','orders',ordr,[{'column':'customer_id','dtype':'int64','semantic_type':'identifier','description':'FK','sample_values':['1'],'null_pct':0.0,'is_pii':False},{'column':'total','dtype':'int64','semantic_type':'currency','description':'amt','sample_values':['10'],'null_pct':0.0,'is_pii':False}]),
    ]:
        await create_upload(uid,f'{slug}.csv',slug,p); jid=uid+'j'; await create_job(jid,'autoeda',uid); await update_job(jid,'done')
        parse_csv_to_sqlite(uid,slug,p)
        await update_upload_artifacts(uid, json.dumps(dd), json.dumps({'grain':f'one {slug} row','measures':[],'dimensions':[],'suggested_questions':[]}))
    await ensure_schema_seed()
    await ensure_schema_seed()  # idempotent
    print('catalog rows:', await catalog_count())
    sl=json.loads(await get_schema_semantic_layer())
    print('tables:', [t['name'] for t in sl['tables']])
    print('relationships:', [(r['from_table'],r['from_column'],r['to_table'],r['to_column']) for r in sl['relationships']])
    print('a pii row:', [c['column_name'] for c in await get_catalog() if c['is_pii']])
asyncio.run(main())
" 2>/dev/null
```

Expected: `catalog rows: 4`, `tables: ['customers', 'orders']` (order may vary), one relationship `orders.customer_id → customers.id`, pii row `['name']`.

- [ ] **Step 3: Commit**

```bash
git add backend/schema_synth.py
git commit -m "feat(context): ensure_schema_seed builds first-draft catalog + schema semantic layer"
```

---

## Task 4: Pydantic + TS models

**Files:**
- Modify: `backend/models.py`
- Modify: `frontend/lib/types.ts`

**Interfaces:**
- Produces: `SchemaTable, Relationship, SchemaMeasure, SchemaDimension, SchemaSemanticLayer, CatalogRow, ContextChatRequest, ContextChatResponse, SchemaResponse` (Pydantic + TS mirror).

- [ ] **Step 1: Add the Pydantic models**

In `backend/models.py`, after `ProgressItem` (and before `CanvasResponse`), insert:

```python
# ── Connected-schema context (multi-table) ───────────────────────────────────
class SchemaTable(BaseModel):
    name: str
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
```

Then after `JobResponse`, insert:

```python
class ContextChatRequest(BaseModel):
    message: str


class ContextChatResponse(BaseModel):
    chat: str
    canvas: CanvasResponse
    catalog: list[CatalogRow]
    semantic_layer: SchemaSemanticLayer | None = None
    complete: bool


class SchemaResponse(BaseModel):
    catalog: list[CatalogRow]
    semantic_layer: SchemaSemanticLayer | None = None
```

- [ ] **Step 2: Add the TS mirror**

In `frontend/lib/types.ts`, after `JobResponse`, insert:

```typescript
export interface SchemaTable {
  name: string;
  grain: string;
  description: string;
}

export type RelationshipKind =
  | "one_to_many"
  | "many_to_one"
  | "one_to_one"
  | "many_to_many";

export interface Relationship {
  from_table: string;
  from_column: string;
  to_table: string;
  to_column: string;
  kind?: RelationshipKind | null;
  confidence?: number | null;
}

export interface SchemaMeasure {
  name: string;
  table: string;
  column: string;
  aggregation: Aggregation;
  description: string;
}

export interface SchemaDimension {
  name: string;
  table: string;
  column: string;
  description: string;
}

export interface SchemaSemanticLayer {
  tables: SchemaTable[];
  relationships: Relationship[];
  measures: SchemaMeasure[];
  dimensions: SchemaDimension[];
  suggested_questions: string[];
}

export type CatalogRole = "identifier" | "datetime" | "measure" | "dimension";

export interface CatalogRow {
  upload_id: string;
  slug: string;
  column_name: string;
  data_type?: string | null;
  semantic_role?: CatalogRole | null;
  business_context?: string | null;
  description?: string | null;
  is_primary_key: boolean;
  is_foreign_key: boolean;
  foreign_key_ref?: string | null;
  is_pii: boolean;
  unit?: string | null;
  sample_values: string[];
  null_pct?: number | null;
}

export interface ContextChatRequest {
  message: string;
}

export interface ContextChatResponse {
  chat: string;
  canvas: CanvasResponse;
  catalog: CatalogRow[];
  semantic_layer?: SchemaSemanticLayer | null;
  complete: boolean;
}

export interface SchemaResponse {
  catalog: CatalogRow[];
  semantic_layer?: SchemaSemanticLayer | null;
}
```

(`Aggregation` already exists in `types.ts` from feature 002's earlier types; if it is not present, add `export type Aggregation = "sum" | "avg" | "count" | "count_distinct" | "min" | "max" | "median";` above `SchemaMeasure`.)

- [ ] **Step 3: Verify both sides**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && python -m py_compile backend/models.py && PYTHONPATH=. python -c "
from backend.models import SchemaSemanticLayer, CatalogRow, ContextChatResponse, CanvasResponse
sl=SchemaSemanticLayer(tables=[{'name':'orders','grain':'one order','description':''}], relationships=[{'from_table':'orders','from_column':'customer_id','to_table':'customers','to_column':'id','kind':'many_to_one','confidence':1.0}], measures=[], dimensions=[], suggested_questions=['x'])
row=CatalogRow(upload_id='u',slug='orders',column_name='total',semantic_role='measure',sample_values=['10'],is_primary_key=False,is_foreign_key=False,is_pii=False)
resp=ContextChatResponse(chat='hi', canvas=CanvasResponse(insights=[],charts=[]), catalog=[row], semantic_layer=sl, complete=False)
print('ok:', resp.semantic_layer.relationships[0].to_table, resp.catalog[0].semantic_role)
" 2>/dev/null && cd frontend && npx tsc --noEmit && echo TSC_OK
```

Expected: `ok: customers measure` then `TSC_OK`.

- [ ] **Step 4: Commit**

```bash
git add backend/models.py frontend/lib/types.ts
git commit -m "feat(context): schema + catalog + chat models (backend + TS)"
```

---

## Task 5: Context Agent tools (`backend/tools/catalog.py`)

**Files:**
- Create: `backend/tools/catalog.py`

**Interfaces:**
- Consumes: Task 1 helpers, Task 2 `detect_relationships` + `sample_column_values`, `SchemaSemanticLayer`.
- Produces: `@tool`s `get_schema_overview`, `sample_column_values`, `infer_relationships`, `write_catalog_entry`, `update_schema_semantic_layer`, `mark_context_complete`.

- [ ] **Step 1: Create the tools**

Create `backend/tools/catalog.py`:

```python
"""Context Agent tools: read the schema, refine the catalog + schema semantic layer.

Sync @tools (run in a worker thread by the agent loop, so asyncio.run is safe).
Every tool catches its own errors and returns a string/structure — never raises.
"""

from __future__ import annotations

import asyncio
import json
import logging

from langchain_core.tools import tool
from pydantic import ValidationError

from backend.database import (
    get_catalog,
    get_schema_semantic_layer,
    get_upload,
    mark_schema_context_complete,
    set_schema_semantic_layer,
    upsert_catalog_entry,
)
from backend.models import SchemaSemanticLayer
from backend.schema_synth import detect_relationships
from backend.tools.dataframe import sample_column_values as _sample

logger = logging.getLogger(__name__)

_SL_KEYS = ("tables", "relationships", "measures", "dimensions", "suggested_questions")


@tool
def get_schema_overview() -> dict:
    """Return all tables, their columns (from the catalog), and current relationships.
    Call this FIRST to ground yourself in the schema."""
    catalog = asyncio.run(get_catalog())
    sl_raw = asyncio.run(get_schema_semantic_layer())
    sl = json.loads(sl_raw) if sl_raw else {}
    tables: dict = {}
    for c in catalog:
        tables.setdefault(c["slug"], []).append({
            "upload_id": c["upload_id"],
            "column": c["column_name"],
            "data_type": c.get("data_type"),
            "semantic_role": c.get("semantic_role"),
            "description": c.get("description"),
            "is_pii": bool(c.get("is_pii")),
        })
    return {
        "tables": tables,
        "relationships": sl.get("relationships", []),
        "grain_by_table": {t.get("name"): t.get("grain") for t in sl.get("tables", [])},
    }


@tool
def sample_column_values(upload_id: str, column_name: str, n: int = 10) -> list:
    """Random non-null sample values (as strings) from a column, so questions are specific."""
    try:
        return _sample(upload_id, column_name, n)
    except Exception as exc:  # noqa: BLE001
        return [f"error: {exc}"]


@tool
def infer_relationships() -> list:
    """Heuristic cross-table foreign-key candidates via value-overlap."""
    try:
        return detect_relationships()
    except Exception as exc:  # noqa: BLE001
        return [{"error": str(exc)}]


@tool
def write_catalog_entry(upload_id: str, column_name: str, updates: dict) -> str:
    """Upsert one catalog row. `updates` may include: semantic_role
    (identifier|datetime|measure|dimension), business_context, description,
    is_primary_key, is_foreign_key, foreign_key_ref (e.g. "customers.id"),
    is_pii, unit, sample_values. Returns "ok" or an error string."""
    try:
        upload = asyncio.run(get_upload(upload_id))
        if upload is None:
            return f"No table with upload_id={upload_id!r}."
        asyncio.run(upsert_catalog_entry(upload_id, upload["slug"], column_name, updates))
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}"
    return "ok"


@tool
def update_schema_semantic_layer(updates: dict) -> str:
    """Merge updates into the schema semantic layer. `updates` may include any of:
    tables, relationships, measures, dimensions, suggested_questions. Each provided
    key REPLACES that whole list. Returns "ok" or a validation error to fix and retry."""
    try:
        cur_raw = asyncio.run(get_schema_semantic_layer())
        cur = json.loads(cur_raw) if cur_raw else {k: [] for k in _SL_KEYS}
        for key in _SL_KEYS:
            if key in updates and updates[key] is not None:
                cur[key] = updates[key]
        try:
            SchemaSemanticLayer(**cur)
        except ValidationError as exc:
            return f"schema semantic layer invalid — fix and retry:\n{exc}"
        asyncio.run(set_schema_semantic_layer(json.dumps(cur)))
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}"
    return "ok"


@tool
def mark_context_complete() -> str:
    """Mark the schema-context interview complete. Call when you have enough context."""
    try:
        asyncio.run(mark_schema_context_complete())
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}"
    return "ok"
```

- [ ] **Step 2: Verify the tools against the seeded synthetic DB**

Reuse Task 3's seeding snippet, then exercise the tools. Run:

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && python -m py_compile backend/tools/catalog.py && PYTHONPATH=. python -c "
import asyncio, tempfile, os, csv, json
d=tempfile.mkdtemp(); os.environ['DATABASE_URL']=f'sqlite+aiosqlite:///{d}/t.db'; os.environ['UPLOAD_DIR']=d
from backend.database import get_db, create_tables, create_upload, create_job, update_job, update_upload_artifacts
from backend.utils.csv_parser import parse_csv_to_sqlite
from backend.schema_synth import ensure_schema_seed
from backend.tools.catalog import get_schema_overview, write_catalog_entry, update_schema_semantic_layer, mark_context_complete
cust=os.path.join(d,'c.csv'); ordr=os.path.join(d,'o.csv')
open(cust,'w',newline='').write('id,name\n1,a\n2,b\n')
open(ordr,'w',newline='').write('order_id,customer_id\n9,1\n8,2\n')
async def boot():
    db=await get_db(); await create_tables(db); await db.close()
    for uid,slug,p,dd in [('cu','customers',cust,[{'column':'id','dtype':'int64','semantic_type':'identifier','description':'PK','sample_values':['1'],'null_pct':0.0,'is_pii':False}]),('or','orders',ordr,[{'column':'customer_id','dtype':'int64','semantic_type':'identifier','description':'FK','sample_values':['1'],'null_pct':0.0,'is_pii':False}])]:
        await create_upload(uid,f'{slug}.csv',slug,p); jid=uid+'j'; await create_job(jid,'autoeda',uid); await update_job(jid,'done'); parse_csv_to_sqlite(uid,slug,p)
        await update_upload_artifacts(uid,json.dumps(dd),json.dumps({'grain':'g','measures':[],'dimensions':[],'suggested_questions':[]}))
    await ensure_schema_seed()
asyncio.run(boot())
print('overview tables:', list(get_schema_overview.invoke({}) ['tables'].keys()))
print('write entry:', write_catalog_entry.invoke({'upload_id':'or','column_name':'customer_id','updates':{'is_foreign_key':True,'foreign_key_ref':'customers.id','business_context':'links to customer'}}))
print('update SL ok:', update_schema_semantic_layer.invoke({'updates':{'suggested_questions':['How many orders per customer?']}}))
print('update SL bad:', update_schema_semantic_layer.invoke({'updates':{'tables':[{'name':'x'}]}})[:40])
print('complete:', mark_context_complete.invoke({}))
" 2>/dev/null
```

Expected: tables list `['customers', 'orders']`; `write entry: ok`; `update SL ok: ok`; `update SL bad: schema semantic layer invalid` (missing required `grain`/`description`); `complete: ok`.

- [ ] **Step 3: Commit**

```bash
git add backend/tools/catalog.py
git commit -m "feat(context): agent tools for schema overview, catalog upsert, semantic-layer edits"
```

---

## Task 6: Context Agent (`backend/agents/context.py`)

**Files:**
- Create: `backend/agents/context.py`

**Interfaces:**
- Consumes: `get_chat_model`, the Task 5 tools, Task 1 read helpers, `ensure_schema_seed`.
- Produces: `run_context_turn(message: str) -> dict` (keys: `chat: str`, `catalog: list[dict]`, `semantic_layer: dict | None`, `complete: bool`).

- [ ] **Step 1: Create the agent**

Create `backend/agents/context.py`:

```python
"""Context Agent — turn-based interview over the connected schema (DeepSeek V4 Flash)."""

from __future__ import annotations

import json
import logging

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.prebuilt import create_react_agent

from backend.database import (
    get_catalog,
    get_conversation,
    get_schema_meta,
    get_schema_semantic_layer,
    save_message,
)
from backend.llm import get_chat_model
from backend.schema_synth import ensure_schema_seed
from backend.tools.catalog import (
    get_schema_overview,
    infer_relationships,
    mark_context_complete,
    sample_column_values,
    update_schema_semantic_layer,
    write_catalog_entry,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a senior data analyst onboarding a new multi-table database. \
An automated profiler has already produced a draft: a per-column catalog across all tables \
and a schema semantic layer (tables, relationships, measures, dimensions). Your job is to \
interview the data owner to CONFIRM, CORRECT, and DEEPEN that draft into a complete, \
join-ready schema.

Procedure:
- Call get_schema_overview first to see the tables, columns, and current relationships.
- Call infer_relationships to see candidate cross-table foreign keys.
- Before asking about a column, optionally call sample_column_values for concrete examples.
- After EVERY confirmed fact, persist it: write_catalog_entry for a column (business_context, \
description, is_primary_key, is_foreign_key, foreign_key_ref like "customers.id", is_pii, unit, \
semantic_role), and update_schema_semantic_layer for schema-level facts (relationships, grain in \
tables[], measures, dimensions, suggested_questions).
- When updating the semantic layer, pass FULL lists for the keys you change (they replace the \
current list). Keep existing entries you are not changing.
- Ask at most 2 questions per turn. Never ask about things the draft already states confidently \
(obvious PKs, datetime columns, clear measures) — confirm those silently by writing them.
- Focus especially on RELATIONSHIPS between tables — confirm or correct each candidate FK.
- After ~4-6 exchanges, or when the user says "done"/"that's enough", summarise what you learned, \
call mark_context_complete, and tell the user the context is saved.

Reply in plain conversational text (your chat message to the user). Do not output JSON to the user."""

_AGENT = None


def build_context_agent():
    """Build (once) the compiled tool-calling agent."""
    global _AGENT
    if _AGENT is None:
        _AGENT = create_react_agent(
            get_chat_model(),
            tools=[
                get_schema_overview,
                sample_column_values,
                infer_relationships,
                write_catalog_entry,
                update_schema_semantic_layer,
                mark_context_complete,
            ],
            prompt=SYSTEM_PROMPT,
        )
    return _AGENT


def _to_lc(history: list[dict]) -> list:
    out = []
    for m in history:
        if m["role"] == "user":
            out.append(HumanMessage(m["content"]))
        else:
            out.append(AIMessage(m["content"]))
    return out


async def run_context_turn(message: str) -> dict:
    """Run one interview turn. Persists messages; returns chat + full catalog + semantic layer."""
    await ensure_schema_seed()
    lc = _to_lc(await get_conversation())
    if message == "__INIT__":
        lc.append(HumanMessage(
            "Begin the interview. Use get_schema_overview, then greet me and ask your first "
            "(at most 2) questions about the most ambiguous columns or relationships."
        ))
    else:
        lc.append(HumanMessage(message))

    agent = build_context_agent()
    result = await agent.ainvoke({"messages": lc})
    last = result["messages"][-1]
    reply = last.content if isinstance(last.content, str) else str(last.content)

    if message != "__INIT__":
        await save_message("user", message)
    await save_message("agent", reply)

    sl_raw = await get_schema_semantic_layer()
    return {
        "chat": reply,
        "catalog": await get_catalog(),
        "semantic_layer": json.loads(sl_raw) if sl_raw else None,
        "complete": bool((await get_schema_meta()).get("context_complete")),
    }
```

> **API drift check (like deepagents earlier):** confirm `create_react_agent`'s system-prompt kwarg in the installed `langgraph`:
> `PYTHONPATH=. python -c "import inspect; from langgraph.prebuilt import create_react_agent; print(inspect.signature(create_react_agent))" 2>/dev/null`
> If it is `state_modifier` or `messages_modifier` rather than `prompt`, adapt the keyword (pass the same `SYSTEM_PROMPT`). Do not change the model wiring or tools.

- [ ] **Step 2: Verify it builds offline (no network)**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && python -m py_compile backend/agents/context.py && PYTHONPATH=. python -c "import os; os.environ.setdefault('OPENROUTER_API_KEY','x'); from backend.agents.context import build_context_agent, _to_lc; a=build_context_agent(); print('agent built:', a is not None); print('history map:', [type(m).__name__ for m in _to_lc([{'role':'user','content':'hi'},{'role':'agent','content':'yo'}])])" 2>/dev/null
```

Expected: `agent built: True` then `history map: ['HumanMessage', 'AIMessage']`.

- [ ] **Step 3: Commit**

```bash
git add backend/agents/context.py
git commit -m "feat(context): turn-based context agent (run_context_turn)"
```

---

## Task 7: API routes (`backend/main.py`)

**Files:**
- Modify: `backend/main.py`

**Interfaces:**
- Consumes: `run_context_turn`, `ensure_schema_seed`, `get_catalog`, `get_schema_semantic_layer`, `mark_schema_context_complete`, models.
- Produces: `GET /api/context/schema`, `POST /api/context/chat`, `POST /api/context/complete`.

- [ ] **Step 1: Add imports**

In `backend/main.py`, extend the `backend.database` import group with `get_catalog, get_schema_semantic_layer, mark_schema_context_complete`, add `from backend.schema_synth import ensure_schema_seed`, `from backend.agents.context import run_context_turn`, and extend the `backend.models` import with `CatalogRow, ContextChatRequest, ContextChatResponse, SchemaResponse, SchemaSemanticLayer`.

- [ ] **Step 2: Add a catalog-row mapper + the three routes**

In `backend/main.py`, after `list_uploads_route`, insert:

```python
def _to_catalog_row(d: dict) -> CatalogRow:
    raw_samples = d.get("sample_values")
    samples: list[str] = []
    if isinstance(raw_samples, str) and raw_samples:
        try:
            parsed = json.loads(raw_samples)
            if isinstance(parsed, list):
                samples = [str(x) for x in parsed]
        except json.JSONDecodeError:
            samples = []
    role = d.get("semantic_role")
    return CatalogRow(
        upload_id=_require_str(d["upload_id"], "upload_id"),
        slug=_require_str(d["slug"], "slug"),
        column_name=_require_str(d["column_name"], "column_name"),
        data_type=d.get("data_type") if isinstance(d.get("data_type"), str) else None,
        semantic_role=role if role in ("identifier", "datetime", "measure", "dimension") else None,
        business_context=d.get("business_context") if isinstance(d.get("business_context"), str) else None,
        description=d.get("description") if isinstance(d.get("description"), str) else None,
        is_primary_key=bool(d.get("is_primary_key")),
        is_foreign_key=bool(d.get("is_foreign_key")),
        foreign_key_ref=d.get("foreign_key_ref") if isinstance(d.get("foreign_key_ref"), str) else None,
        is_pii=bool(d.get("is_pii")),
        unit=d.get("unit") if isinstance(d.get("unit"), str) else None,
        sample_values=samples,
        null_pct=d.get("null_pct") if isinstance(d.get("null_pct"), (int, float)) else None,
    )


def _parse_schema_layer(raw: str | None) -> SchemaSemanticLayer | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return SchemaSemanticLayer(**parsed)
    except (json.JSONDecodeError, ValidationError):
        logger.exception("Stored schema semantic layer failed to parse")
        return None


@app.get("/api/context/schema", response_model=SchemaResponse)
async def context_schema() -> SchemaResponse:
    await ensure_schema_seed()
    catalog = [_to_catalog_row(c) for c in await get_catalog()]
    layer = _parse_schema_layer(await get_schema_semantic_layer())
    return SchemaResponse(catalog=catalog, semantic_layer=layer)


@app.post("/api/context/chat", response_model=ContextChatResponse)
async def context_chat(req: ContextChatRequest) -> ContextChatResponse:
    turn = await run_context_turn(req.message)
    catalog = [_to_catalog_row(c) for c in turn["catalog"]]
    sl = turn["semantic_layer"]
    layer: SchemaSemanticLayer | None = None
    if sl is not None:
        try:
            layer = SchemaSemanticLayer(**sl)
        except ValidationError:
            layer = None
    return ContextChatResponse(
        chat=turn["chat"],
        canvas=CanvasResponse(insights=[], charts=[]),
        catalog=catalog,
        semantic_layer=layer,
        complete=bool(turn["complete"]),
    )


@app.post("/api/context/complete")
async def context_complete() -> dict:
    await mark_schema_context_complete()
    return {"ok": True}
```

- [ ] **Step 3: Verify routes are registered + compile**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && python -m py_compile backend/main.py && PYTHONPATH=. python -c "import os; os.environ.setdefault('OPENROUTER_API_KEY','x'); import backend.main as m; print(sorted(r.path for r in m.app.routes if getattr(r,'path','').startswith('/api')))" 2>/dev/null
```

Expected: `['/api/context/chat', '/api/context/complete', '/api/context/schema', '/api/jobs/{job_id}', '/api/upload', '/api/uploads']`.

- [ ] **Step 4: Commit**

```bash
git add backend/main.py
git commit -m "feat(context): GET /context/schema, POST /context/chat, POST /context/complete"
```

---

## Task 8: Frontend API wrappers + chat-turn hook

**Files:**
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/lib/hooks.ts`

**Interfaces:**
- Produces: `getSchema(): Promise<SchemaResponse>`, `postContextChat(message): Promise<ContextChatResponse>`, `postContextComplete(): Promise<{ok: boolean}>`; hook `useChatTurn()`.

- [ ] **Step 1: Add API wrappers**

In `frontend/lib/api.ts`, update the type import to add the new types:

```typescript
import type {
  JobResponse,
  UploadResponse,
  UploadsListResponse,
  SchemaResponse,
  ContextChatResponse,
} from "./types";
```

Append:

```typescript
export async function getSchema(): Promise<SchemaResponse> {
  const res = await fetch(apiPath("/context/schema"));
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Failed to load schema");
  }
  return res.json() as Promise<SchemaResponse>;
}

export async function postContextChat(message: string): Promise<ContextChatResponse> {
  const res = await fetch(apiPath("/context/chat"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Chat failed");
  }
  return res.json() as Promise<ContextChatResponse>;
}

export async function postContextComplete(): Promise<{ ok: boolean }> {
  const res = await fetch(apiPath("/context/complete"), { method: "POST" });
  if (!res.ok) throw new Error("Failed to mark complete");
  return res.json() as Promise<{ ok: boolean }>;
}
```

- [ ] **Step 2: Add the `useChatTurn` hook**

In `frontend/lib/hooks.ts`, extend the type import:

```typescript
import type {
  JobResponse,
  JobStatus,
  UploadSummary,
  CatalogRow,
  SchemaSemanticLayer,
} from "./types";
import { getJob, listUploads, getSchema, postContextChat, postContextComplete } from "./api";
```

Append:

```typescript
// ─── Context interview turn ──────────────────────────────────────────────────

export interface ChatMessage {
  role: "user" | "agent";
  content: string;
}

export function useChatTurn(): {
  messages: ChatMessage[];
  catalog: CatalogRow[];
  semanticLayer: SchemaSemanticLayer | null;
  complete: boolean;
  loading: boolean;
  error: string | null;
  send: (message: string) => Promise<void>;
  markComplete: () => Promise<void>;
} {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [catalog, setCatalog] = useState<CatalogRow[]>([]);
  const [semanticLayer, setSemanticLayer] = useState<SchemaSemanticLayer | null>(null);
  const [complete, setComplete] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const startedRef = useRef(false);

  const runTurn = useCallback(async (message: string, echo: boolean) => {
    setError(null);
    setLoading(true);
    if (echo) setMessages((m) => [...m, { role: "user", content: message }]);
    try {
      const res = await postContextChat(message);
      setMessages((m) => [...m, { role: "agent", content: res.chat }]);
      setCatalog(res.catalog);
      setSemanticLayer(res.semantic_layer ?? null);
      setComplete(res.complete);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Chat failed");
    } finally {
      setLoading(false);
    }
  }, []);

  // Seed the right panel, then fire the opening (__INIT__) turn once.
  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    (async () => {
      try {
        const schema = await getSchema();
        setCatalog(schema.catalog);
        setSemanticLayer(schema.semantic_layer ?? null);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load schema");
      }
      await runTurn("__INIT__", false);
    })();
  }, [runTurn]);

  const send = useCallback((message: string) => runTurn(message, true), [runTurn]);

  const markComplete = useCallback(async () => {
    try {
      await postContextComplete();
      setComplete(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to mark complete");
    }
  }, []);

  return { messages, catalog, semanticLayer, complete, loading, error, send, markComplete };
}
```

- [ ] **Step 3: Verify typecheck**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto/frontend" && npx tsc --noEmit && echo TSC_OK
```

Expected: `TSC_OK`.

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/api.ts frontend/lib/hooks.ts
git commit -m "feat(context): frontend context api wrappers + useChatTurn hook"
```

---

## Task 9: Context panel components

**Files:**
- Create: `frontend/components/ChatPanel.tsx`
- Create: `frontend/components/CatalogTable.tsx`
- Create: `frontend/components/RelationshipList.tsx`
- Create: `frontend/components/SchemaSemanticView.tsx`

**Interfaces:**
- Consumes: `ChatMessage` (from hooks), `CatalogRow`, `Relationship`, `SchemaSemanticLayer` (types).
- Produces: default components `ChatPanel`, `CatalogTable`, `RelationshipList`, `SchemaSemanticView`.

- [ ] **Step 1: Create `ChatPanel.tsx`**

```tsx
"use client";

import { useState } from "react";
import type { ChatMessage } from "@/lib/hooks";

export default function ChatPanel({
  messages,
  loading,
  complete,
  onSend,
  onMarkComplete,
}: {
  messages: ChatMessage[];
  loading: boolean;
  complete: boolean;
  onSend: (msg: string) => void;
  onMarkComplete: () => void;
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
          <div
            key={i}
            className="rounded-lg px-3 py-2 text-[13px] max-w-[90%]"
            style={{
              alignSelf: m.role === "user" ? "flex-end" : "flex-start",
              marginLeft: m.role === "user" ? "auto" : 0,
              background: m.role === "user" ? "var(--accent)" : "var(--bg3)",
              color: m.role === "user" ? "#000" : "var(--text)",
              whiteSpace: "pre-wrap",
            }}
          >
            {m.content}
          </div>
        ))}
        {loading && (
          <div className="text-[12px]" style={{ color: "var(--text3)" }}>
            Thinking…
          </div>
        )}
      </div>

      {complete && (
        <div className="text-[12px] mb-2 px-1" style={{ color: "var(--accent)" }}>
          Context saved — ready for queries.
        </div>
      )}

      <div className="flex gap-2 pt-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          disabled={loading}
          placeholder="Answer the agent…"
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
        <button
          onClick={onMarkComplete}
          className="rounded-lg px-3 py-2 text-[13px] font-medium"
          style={{ background: "var(--accent)", color: "#000" }}
        >
          ✓ Mark Complete
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create `CatalogTable.tsx`** (grouped by table)

```tsx
import type { CatalogRow } from "@/lib/types";

export default function CatalogTable({ rows }: { rows: CatalogRow[] }) {
  if (rows.length === 0) return null;
  const byTable = new Map<string, CatalogRow[]>();
  for (const r of rows) {
    const arr = byTable.get(r.slug) ?? [];
    arr.push(r);
    byTable.set(r.slug, arr);
  }
  return (
    <div className="space-y-4">
      {Array.from(byTable.entries()).map(([slug, cols]) => (
        <div key={slug} className="space-y-1.5">
          <div
            className="text-[11px] font-medium"
            style={{ fontFamily: "'DM Mono', monospace", color: "var(--accent)" }}
          >
            {slug}
          </div>
          <div className="rounded-lg border overflow-hidden" style={{ borderColor: "var(--border)" }}>
            <table className="w-full text-[11px]" style={{ borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ background: "var(--bg3)", color: "var(--text3)" }}>
                  <th className="text-left px-2 py-1 font-medium">Column</th>
                  <th className="text-left px-2 py-1 font-medium">Role</th>
                  <th className="text-left px-2 py-1 font-medium">Description / context</th>
                  <th className="text-left px-2 py-1 font-medium">Key</th>
                </tr>
              </thead>
              <tbody>
                {cols.map((c) => (
                  <tr key={c.column_name} style={{ borderTop: "1px solid var(--border)" }}>
                    <td className="px-2 py-1" style={{ fontFamily: "'DM Mono', monospace", color: "var(--text)" }}>
                      {c.column_name}
                      {c.is_pii && (
                        <span className="ml-1 px-1 rounded text-[9px]" style={{ background: "rgba(248,113,113,0.12)", color: "var(--danger)" }}>
                          PII
                        </span>
                      )}
                    </td>
                    <td className="px-2 py-1" style={{ color: "var(--text2)" }}>{c.semantic_role ?? "—"}</td>
                    <td className="px-2 py-1" style={{ color: "var(--text2)" }}>
                      {c.business_context || c.description || "—"}
                    </td>
                    <td className="px-2 py-1" style={{ color: "var(--text3)" }}>
                      {c.is_primary_key ? "PK" : c.is_foreign_key ? `FK → ${c.foreign_key_ref ?? "?"}` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Create `RelationshipList.tsx`**

```tsx
import type { Relationship } from "@/lib/types";

export default function RelationshipList({ relationships }: { relationships: Relationship[] }) {
  if (relationships.length === 0) return null;
  return (
    <div className="space-y-1.5">
      <div className="text-[10px] uppercase tracking-widest font-medium" style={{ color: "var(--text3)" }}>
        Relationships
      </div>
      <ul className="space-y-1">
        {relationships.map((r, i) => (
          <li key={i} className="text-[11px]" style={{ fontFamily: "'DM Mono', monospace", color: "var(--text2)" }}>
            {r.from_table}.{r.from_column} → {r.to_table}.{r.to_column}
            {r.confidence != null && (
              <span style={{ color: "var(--text3)" }}> ({Math.round(r.confidence * 100)}%)</span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 4: Create `SchemaSemanticView.tsx`** (multi-table; distinct from feature 001's `SemanticLayer.tsx`)

```tsx
import type { SchemaSemanticLayer } from "@/lib/types";

export default function SchemaSemanticView({ layer }: { layer: SchemaSemanticLayer }) {
  return (
    <div className="space-y-3">
      <div className="text-[10px] uppercase tracking-widest font-medium" style={{ color: "var(--text3)" }}>
        Schema Semantic Layer
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <div className="text-[11px] mb-1" style={{ color: "var(--text3)" }}>Measures</div>
          <ul className="space-y-1">
            {layer.measures.map((m, i) => (
              <li key={i} className="text-[11px]" style={{ color: "var(--text2)" }}>
                <span style={{ color: "var(--accent)" }}>{m.aggregation}</span>(
                <span style={{ fontFamily: "'DM Mono', monospace" }}>{m.table}.{m.column}</span>) — {m.name}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <div className="text-[11px] mb-1" style={{ color: "var(--text3)" }}>Dimensions</div>
          <ul className="space-y-1">
            {layer.dimensions.map((d, i) => (
              <li key={i} className="text-[11px]" style={{ color: "var(--text2)" }}>
                <span style={{ fontFamily: "'DM Mono', monospace" }}>{d.table}.{d.column}</span> — {d.name}
              </li>
            ))}
          </ul>
        </div>
      </div>
      {layer.suggested_questions.length > 0 && (
        <div>
          <div className="text-[11px] mb-1" style={{ color: "var(--text3)" }}>Suggested questions</div>
          <div className="flex flex-wrap gap-1.5">
            {layer.suggested_questions.map((q, i) => (
              <span key={i} className="text-[11px] px-2 py-1 rounded-full" style={{ background: "var(--bg3)", color: "var(--text2)" }}>
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

- [ ] **Step 5: Verify typecheck**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto/frontend" && npx tsc --noEmit && echo TSC_OK
```

Expected: `TSC_OK`.

- [ ] **Step 6: Commit**

```bash
git add frontend/components/ChatPanel.tsx frontend/components/CatalogTable.tsx frontend/components/RelationshipList.tsx frontend/components/SchemaSemanticView.tsx
git commit -m "feat(context): chat, catalog, relationship, schema-semantic components"
```

---

## Task 10: Context page + manual smoke test

**Files:**
- Create: `frontend/app/context/page.tsx`

**Interfaces:**
- Consumes: `useChatTurn` (hook), `ChatPanel`, `CatalogTable`, `RelationshipList`, `SchemaSemanticView`.

- [ ] **Step 1: Create `frontend/app/context/page.tsx`**

```tsx
"use client";

import { useChatTurn } from "@/lib/hooks";
import ChatPanel from "@/components/ChatPanel";
import CatalogTable from "@/components/CatalogTable";
import RelationshipList from "@/components/RelationshipList";
import SchemaSemanticView from "@/components/SchemaSemanticView";

export default function ContextPage() {
  const { messages, catalog, semanticLayer, complete, loading, error, send, markComplete } =
    useChatTurn();

  return (
    <div className="flex-1 min-h-0 flex overflow-hidden" style={{ background: "var(--bg)" }}>
      {/* Left — chat (40%) */}
      <section
        className="w-2/5 shrink-0 flex flex-col p-4"
        style={{ borderRight: "1px solid var(--border)", background: "var(--bg2)" }}
      >
        {error && (
          <div className="text-[12px] mb-2" style={{ color: "var(--danger)" }}>
            {error}
          </div>
        )}
        <ChatPanel
          messages={messages}
          loading={loading}
          complete={complete}
          onSend={send}
          onMarkComplete={markComplete}
        />
      </section>

      {/* Right — schema (60%) */}
      <main className="flex-1 min-h-0 overflow-y-auto p-5 space-y-5">
        {semanticLayer && semanticLayer.relationships.length > 0 && (
          <RelationshipList relationships={semanticLayer.relationships} />
        )}
        <CatalogTable rows={catalog} />
        {semanticLayer && <SchemaSemanticView layer={semanticLayer} />}
        {catalog.length === 0 && (
          <div className="text-[12px]" style={{ color: "var(--text3)" }}>
            No schema yet. Upload CSVs on the Upload screen first.
          </div>
        )}
      </main>
    </div>
  );
}
```

(`/context` inherits `NavBar` + `UploadContext` from the root `AppProviders` — no extra layout needed. The page uses `flex-1 min-h-0` to fill the space under the nav, matching the body's `flex flex-col`.)

- [ ] **Step 2: Verify typecheck**

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto/frontend" && npx tsc --noEmit && echo TSC_OK
```

Expected: `TSC_OK`.

- [ ] **Step 3: Commit**

```bash
git add frontend/app/context/page.tsx
git commit -m "feat(context): Screen 2 — connected-schema context page"
```

- [ ] **Step 4: Live smoke test (needs real `OPENROUTER_API_KEY`, already in `.env`)**

Start backend + frontend:

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && PYTHONPATH=. python -m uvicorn backend.main:app --reload --port 8000
# second shell
cd "C:/Dev/text-sql-proto/text-sql-proto/frontend" && npm run dev
```

- [ ] **Step 5: Verify end-to-end in the browser**

1. On `/upload`, upload **two related CSVs** (e.g. an orders file and a customers file sharing a key). Wait for both to reach "Ready". Click "Continue to Context →".
2. On `/context`, before any chat: the catalog (grouped by both tables) renders, plus any detected relationships.
3. The agent's opening message asks ≤2 specific questions.
4. Answer one; confirm the relevant catalog row / relationship / semantic layer updates in the right panel and the agent asks new questions.
5. Drive to completion (or say "that's enough"); "Context saved — ready for queries" shows.
6. Inspect SQLite:

```bash
cd "C:/Dev/text-sql-proto/text-sql-proto" && python -c "
import sqlite3, json
c=sqlite3.connect('data/app.db')
print('catalog rows:', c.execute('SELECT COUNT(*) FROM catalog').fetchone()[0])
print('context_complete:', c.execute(\"SELECT context_complete FROM schema_meta WHERE id='global'\").fetchone())
sl=c.execute(\"SELECT semantic_layer FROM schema_meta WHERE id='global'\").fetchone()[0]
print('relationships:', [ (r['from_table'],r['to_table']) for r in json.loads(sl).get('relationships',[]) ])
print('conversation turns:', c.execute('SELECT COUNT(*) FROM context_conversations').fetchone()[0])
"
```

Expected: catalog rows > 0; `context_complete: (1,)`; one or more relationships; conversation turns > 0.

---

## Self-Review

**Spec coverage (Phase 2 of the design):**
- `schema_meta`, `catalog`, `context_conversations` tables + helpers → Task 1. ✓
- Heuristic cross-table relationship detection → Task 2. ✓
- `ensure_schema_seed` (catalog from dictionaries + schema semantic layer + relationships) → Task 3. ✓
- Multi-table models (`SchemaSemanticLayer` distinct from feature 001's `SemanticLayer`) → Task 4. ✓
- Agent tools (overview, sample, infer, write catalog, update semantic layer, complete) → Task 5. ✓
- Turn-based context agent on DeepSeek V4 Flash, `__INIT__` opening turn → Task 6. ✓
- Three endpoints, no `upload_id` in path → Task 7. ✓
- Frontend types/wrappers/`useChatTurn` → Tasks 4, 8. ✓
- Chat + multi-table catalog + relationships + schema semantic view → Tasks 9, 10. ✓
- Completion state, no navigation → Tasks 9, 10 ("Context saved", disabled/absent Continue). ✓
- Write-time validation + read-path `ValidationError` guard (matching feature 001's fix) → Task 5 (`update_schema_semantic_layer` validates), Task 7 (`_parse_schema_layer`/chat guard). ✓
- Tools never raise → Task 5 (every tool try/except). ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; verification commands have expected output. The one external-API risk (`create_react_agent` kwarg) has an explicit drift-check step (Task 6). ✓

**Type consistency:** DB `catalog` columns (Task 1 `_CATALOG_FIELDS`) ↔ `_to_catalog_row` mapping (Task 7) ↔ `CatalogRow` model (Task 4) ↔ TS `CatalogRow` (Task 4) ↔ `CatalogTable` usage (Task 9). `SchemaSemanticLayer` keys (`tables, relationships, measures, dimensions, suggested_questions`) consistent across `ensure_schema_seed` (Task 3), `update_schema_semantic_layer` (Task 5), the model (Task 4), and `SchemaSemanticView` (Task 9). `run_context_turn` return keys (`chat, catalog, semantic_layer, complete`) match the route's use (Task 7). `useChatTurn` return shape matches `ChatPanel`/page usage (Tasks 9, 10). ✓
