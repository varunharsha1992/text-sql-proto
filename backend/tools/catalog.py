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
