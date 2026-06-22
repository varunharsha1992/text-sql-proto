"""Tool: get_dataframe_profile — returns shape, dtypes, and stats for a raw_{slug} table."""

from __future__ import annotations

import asyncio
import os

import aiosqlite
import pandas as pd
from dotenv import load_dotenv
from langchain_core.tools import tool

from backend.database import raw_table_name

load_dotenv()

_DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./data/app.db"
_SQLITE_PREFIX = "sqlite+aiosqlite:///"


def _sqlite_file_path() -> str:
    url = os.getenv("DATABASE_URL", _DEFAULT_DATABASE_URL)
    if url.startswith(_SQLITE_PREFIX):
        return url[len(_SQLITE_PREFIX):]
    return url


async def _load_dataframe(upload_id: str) -> pd.DataFrame:
    table = raw_table_name(upload_id)
    path = _sqlite_file_path()
    async with aiosqlite.connect(path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(f"SELECT * FROM {table}") as cursor:
            rows = await cursor.fetchall()
            if not rows:
                return pd.DataFrame()
            columns = [description[0] for description in cursor.description]
    return pd.DataFrame([dict(row) for row in rows], columns=columns)


def load_upload_dataframe_sync(upload_id: str) -> pd.DataFrame:
    """Load `raw_{slug}` for this upload (blocking). Used by deterministic AutoEDA."""
    return asyncio.run(_load_dataframe(upload_id))


@tool
def get_dataframe_profile(upload_id: str) -> dict:
    """Returns shape, dtypes, null counts, nunique, describe stats for the raw data table.
    The table is named raw_{upload_id} (non-alphanumeric chars stripped).
    Called once at the start of AutoEDA. Returns a dict with keys:
    shape (rows, cols), columns (list of name/dtype/null_count/nunique/stats dicts).
    """
    df: pd.DataFrame = asyncio.run(_load_dataframe(upload_id))

    rows, cols = df.shape
    column_profiles: list[dict] = []

    for col in df.columns:
        series = df[col]
        null_count = int(series.isna().sum())
        null_pct = round(null_count / rows * 100, 2) if rows > 0 else 0.0
        nunique = int(series.nunique(dropna=True))
        dtype = str(series.dtype)

        if pd.api.types.is_numeric_dtype(series):
            desc = series.describe()
            col_profile: dict = {
                "name": col,
                "dtype": dtype,
                "null_count": null_count,
                "null_pct": null_pct,
                "nunique": nunique,
                "min": float(desc["min"]) if "min" in desc else None,
                "max": float(desc["max"]) if "max" in desc else None,
                "mean": float(desc["mean"]) if "mean" in desc else None,
                "std": float(desc["std"]) if "std" in desc else None,
                "median": float(series.median()),
            }
        else:
            col_profile = {
                "name": col,
                "dtype": dtype,
                "null_count": null_count,
                "null_pct": null_pct,
                "nunique": nunique,
                "min": None,
                "max": None,
                "mean": None,
                "std": None,
                "median": None,
            }

        column_profiles.append(col_profile)

    return {"shape": [rows, cols], "columns": column_profiles}
