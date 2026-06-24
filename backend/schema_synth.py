"""Deterministic schema synthesis: cross-table FK detection + first-draft seed.

No LLM. Reads every uploaded table's raw data to propose relationships, and seeds
the catalog + schema semantic layer so the Context screen is never empty.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging

import pandas as pd
from pydantic import ValidationError

from backend.database import (
    catalog_count,
    get_catalog,
    get_schema_semantic_layer,
    get_upload,
    list_uploads,
    set_schema_semantic_layer,
    upsert_catalog_entry,
)
from backend.models import SchemaSemanticLayer
from backend.tools.dataframe import _load_dataframe

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


def _rel_key(rel: dict) -> tuple[str, str, str, str]:
    return (
        rel.get("from_table", ""),
        rel.get("from_column", ""),
        rel.get("to_table", ""),
        rel.get("to_column", ""),
    )


def _catalog_key(row: dict) -> tuple[str, str]:
    return (row["upload_id"], row["column_name"])


def _user_catalog_fields_set(row: dict) -> bool:
    if row.get("business_context"):
        return True
    if row.get("foreign_key_ref"):
        return True
    if row.get("is_primary_key"):
        return True
    if row.get("is_foreign_key"):
        return True
    return False


def _merge_relationships(existing: list[dict], detected: list[dict]) -> list[dict]:
    seen = {_rel_key(r) for r in existing}
    merged = list(existing)
    for rel in detected:
        key = _rel_key(rel)
        if key not in seen:
            merged.append(rel)
            seen.add(key)
    return merged


def _profiler_catalog_updates(entry: dict) -> dict:
    return {
        "data_type": entry.get("dtype"),
        "semantic_role": _SEMANTIC_ROLE.get(entry.get("semantic_type", ""), "dimension"),
        "description": entry.get("description"),
        "sample_values": entry.get("sample_values") or [],
        "is_pii": bool(entry.get("is_pii", False)),
        "unit": entry.get("unit"),
        "null_pct": entry.get("null_pct"),
    }


def _id_like(name: str) -> bool:
    n = name.lower()
    return n == "id" or n.endswith("id") or n.endswith("_id") or n.endswith("code")


def _value_set(df: pd.DataFrame, col: str) -> set:
    return set(str(v) for v in df[col].dropna().unique())


def _run_sync(coro):
    """Run an async coroutine from sync code (safe when an event loop is already running)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def detect_relationships() -> list[dict]:
    """Cross-table FK candidates via value-set overlap on id-like / name-matching columns."""
    uploads = _run_sync(list_uploads())
    tables: list[tuple[str, str, pd.DataFrame]] = []  # (slug, upload_id, df)
    for u in uploads:
        if u.get("status") != "done":
            continue
        try:
            df = _run_sync(_load_dataframe(u["id"]))
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


def _validated_layer_json(candidate: dict, tables_meta: list[dict], suggested: list[str]) -> str:
    """Return JSON for the best schema layer that validates against SchemaSemanticLayer.

    Degrades gracefully so a single bad LLM-produced measure/dimension can never make the
    whole layer unstorable (which would make GET /context/schema return semantic_layer: null
    even though good data exists). Tries the full candidate, then drops the optional lists,
    then falls back to an empty-but-valid layer."""
    fallbacks = (
        candidate,
        {"tables": tables_meta, "relationships": [], "measures": [],
         "dimensions": [], "suggested_questions": suggested[:8]},
        {"tables": [], "relationships": [], "measures": [],
         "dimensions": [], "suggested_questions": []},
    )
    for attempt in fallbacks:
        try:
            return json.dumps(SchemaSemanticLayer(**attempt).model_dump())
        except ValidationError:
            logger.exception("Schema seed layer failed validation; degrading")
    # The all-empty layer above is guaranteed valid, so this is unreachable in practice.
    return json.dumps({"tables": [], "relationships": [], "measures": [],
                       "dimensions": [], "suggested_questions": []})


async def sync_connected_schema() -> dict:
    """Incremental idempotent merge of all done uploads into catalog + global semantic layer.

    Returns dict with keys: tables_synced (list[str]), catalog (list[dict]), semantic_layer (dict|None).
    """
    existing_catalog = await get_catalog()
    catalog_by_key = {_catalog_key(c): c for c in existing_catalog}

    existing_layer_raw = await get_schema_semantic_layer()
    existing_layer: dict = {}
    if existing_layer_raw:
        try:
            existing_layer = json.loads(existing_layer_raw)
        except json.JSONDecodeError:
            existing_layer = {}

    existing_tables = {
        t.get("name", ""): t
        for t in (existing_layer.get("tables") or [])
        if isinstance(t, dict)
    }

    uploads = await list_uploads()
    tables_meta: list[dict] = []
    measures: list[dict] = []
    dimensions: list[dict] = []
    suggested: list[str] = []
    tables_synced: list[str] = []

    for u in uploads:
        if u.get("status") != "done":
            continue
        try:
            upload = await get_upload(u["id"])
            if upload is None:
                continue
            slug = upload["slug"]
            dd_raw = upload.get("data_dictionary")
            sl_raw = upload.get("semantic_layer")
            entries = json.loads(dd_raw) if isinstance(dd_raw, str) and dd_raw else []
            if not entries:
                continue
            per_table_sl = json.loads(sl_raw) if isinstance(sl_raw, str) and sl_raw else {}

            for e in entries:
                col = e.get("column")
                if not col:
                    continue
                updates = _profiler_catalog_updates(e)
                existing_row = catalog_by_key.get((u["id"], col))
                if existing_row and _user_catalog_fields_set(existing_row):
                    pass  # preserve interview fields — only patch profiler keys
                await upsert_catalog_entry(u["id"], slug, col, updates)

            prev_desc = ""
            if slug in existing_tables:
                prev_desc = str(existing_tables[slug].get("description") or "")
            tables_meta.append({
                "name": slug,
                "grain": str(per_table_sl.get("grain") or ""),
                "description": prev_desc,
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
                if q and q not in suggested:
                    suggested.append(q)
            tables_synced.append(slug)
        except Exception:  # noqa: BLE001
            logger.exception("Skipping table %s during schema sync", u.get("id"))
            continue

    try:
        detected = detect_relationships()
    except Exception:  # noqa: BLE001
        logger.exception("Relationship detection failed during sync; continuing without")
        detected = []

    existing_rels = existing_layer.get("relationships") or []
    if not isinstance(existing_rels, list):
        existing_rels = []
    relationships = _merge_relationships(
        [r for r in existing_rels if isinstance(r, dict)],
        detected,
    )

    candidate = {
        "tables": tables_meta,
        "relationships": relationships,
        "measures": measures,
        "dimensions": dimensions,
        "suggested_questions": suggested[:8],
    }
    layer_json = _validated_layer_json(candidate, tables_meta, suggested)
    await set_schema_semantic_layer(layer_json)
    logger.info("Synced schema: %s tables, %s relationships", len(tables_meta), len(relationships))

    refreshed_catalog = await get_catalog()
    layer_parsed = None
    try:
        layer_parsed = json.loads(layer_json)
    except json.JSONDecodeError:
        layer_parsed = None

    return {
        "tables_synced": tables_synced,
        "catalog": refreshed_catalog,
        "semantic_layer": layer_parsed,
    }


async def ensure_schema_seed() -> None:
    """Idempotent first-time seed. Short-circuits once catalog + layer exist."""
    if await catalog_count() > 0 and await get_schema_semantic_layer():
        return
    await sync_connected_schema()
