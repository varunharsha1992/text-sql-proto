"""Query Canvas schema read tools — on-demand, never context-injected."""

from __future__ import annotations

import asyncio
import json
import logging

from langchain_core.tools import tool

from backend.database import get_catalog, get_schema_semantic_layer, get_upload, list_uploads, raw_table_name
from backend.models import DataDictionaryEntry, SchemaSemanticLayer

logger = logging.getLogger(__name__)

_SL_KEYS = ("tables", "relationships", "measures", "dimensions", "suggested_questions")


@tool
def list_tables() -> list[dict]:
    """List queryable tables (AutoEDA done only): slug, upload_id, row_count, col_count, status."""
    try:
        rows = asyncio.run(list_uploads())
        out = []
        for r in rows:
            if r.get("status") != "done":
                continue
            out.append({
                "slug": r["slug"],
                "upload_id": r["id"],
                "row_count": r.get("row_count"),
                "col_count": r.get("col_count"),
                "status": r.get("status"),
            })
        return out
    except Exception as exc:  # noqa: BLE001
        return [{"error": str(exc)}]


@tool
def get_catalog_column(slug: str, column_name: str) -> dict:
    """Full catalog row for one column: roles, FK ref, business_context, sample_values, null_pct, upload_id."""
    try:
        catalog = asyncio.run(get_catalog())
        for c in catalog:
            if c.get("slug") == slug and c.get("column_name") == column_name:
                samples = c.get("sample_values")
                if isinstance(samples, str):
                    try:
                        samples = json.loads(samples)
                    except json.JSONDecodeError:
                        samples = []
                return {
                    "upload_id": c.get("upload_id"),
                    "slug": slug,
                    "column_name": column_name,
                    "data_type": c.get("data_type"),
                    "semantic_role": c.get("semantic_role"),
                    "business_context": c.get("business_context"),
                    "description": c.get("description"),
                    "is_primary_key": bool(c.get("is_primary_key")),
                    "is_foreign_key": bool(c.get("is_foreign_key")),
                    "foreign_key_ref": c.get("foreign_key_ref"),
                    "is_pii": bool(c.get("is_pii")),
                    "unit": c.get("unit"),
                    "sample_values": samples if isinstance(samples, list) else [],
                    "null_pct": c.get("null_pct"),
                }
        return {"error": f"No catalog row for {slug}.{column_name}"}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@tool
def get_semantic_layer(section: str | None = None) -> dict:
    """Full or partial schema semantic layer. section: tables|relationships|measures|dimensions|suggested_questions or null for all."""
    try:
        raw = asyncio.run(get_schema_semantic_layer())
        data = json.loads(raw) if raw else {k: [] for k in _SL_KEYS}
        SchemaSemanticLayer(**data)
        if section and section in _SL_KEYS:
            return {section: data.get(section, [])}
        return data
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@tool
def get_data_dictionary(slug: str) -> list[dict]:
    """Per-table AutoEDA data dictionary entries from uploads.data_dictionary. Empty list if missing."""
    try:
        rows = asyncio.run(list_uploads())
        upload_id = next((r["id"] for r in rows if r.get("slug") == slug), None)
        if not upload_id:
            return [{"error": f"No upload with slug={slug!r}"}]
        upload = asyncio.run(get_upload(upload_id))
        if not upload:
            return []
        raw = upload.get("data_dictionary")
        if not raw:
            return []
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        out = []
        for item in parsed:
            try:
                out.append(DataDictionaryEntry(**item).model_dump())
            except Exception:
                continue
        return out
    except Exception as exc:  # noqa: BLE001
        return [{"error": str(exc)}]


@tool
def resolve_table(slug: str) -> dict:
    """Map human slug to SQLite raw table name: { upload_id, slug, raw_table }."""
    try:
        rows = asyncio.run(list_uploads())
        match = next((r for r in rows if r.get("slug") == slug), None)
        if not match:
            return {"error": f"No table with slug={slug!r}"}
        uid = match["id"]
        return {"upload_id": uid, "slug": slug, "raw_table": raw_table_name(uid)}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
