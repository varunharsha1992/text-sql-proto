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


async def ensure_schema_seed() -> None:
    """Idempotent: seed the catalog from every table's data_dictionary and build the
    first-draft schema semantic layer. Safe to re-run — catalog upserts are idempotent,
    and a prior run that crashed mid-way (or never stored a layer) is completed on the
    next call. The guard only short-circuits once a seed has FULLY completed."""
    if await catalog_count() > 0 and await get_schema_semantic_layer():
        return

    uploads = await list_uploads()
    tables_meta: list[dict] = []
    measures: list[dict] = []
    dimensions: list[dict] = []
    suggested: list[str] = []

    for u in uploads:
        # A malformed dictionary/semantic-layer JSON for one table must not abort the whole
        # seed (which, before, left every remaining table permanently uncatalogued).
        try:
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
        except Exception:  # noqa: BLE001
            logger.exception("Skipping table %s during schema seed", u.get("id"))
            continue

    try:
        relationships = detect_relationships()
    except Exception:  # noqa: BLE001
        logger.exception("Relationship detection failed during seed; continuing without")
        relationships = []

    candidate = {
        "tables": tables_meta,
        "relationships": relationships,
        "measures": measures,
        "dimensions": dimensions,
        "suggested_questions": suggested[:8],
    }
    await set_schema_semantic_layer(_validated_layer_json(candidate, tables_meta, suggested))
    logger.info("Seeded schema: %s tables, %s relationships",
                len(tables_meta), len(relationships))
