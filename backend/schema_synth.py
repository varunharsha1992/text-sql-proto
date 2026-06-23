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
