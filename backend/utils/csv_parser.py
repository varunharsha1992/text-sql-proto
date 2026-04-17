"""CSV ingestion: coercion rules and SQLite raw table persistence."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path

import aiosqlite
import numpy as np
import pandas as pd
from dotenv import load_dotenv

from backend.database import update_upload_counts

load_dotenv()

logger = logging.getLogger(__name__)

_DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./data/app.db"
_SQLITE_AI_PREFIX = "sqlite+aiosqlite:///"

_CURRENCY_CHARS = frozenset("$€£¥")

_ISO_DATE_START = re.compile(r"^\d{4}-\d{2}-\d{2}")
_DD_MM_YYYY = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
_YYYY_SLASH = re.compile(r"^\d{4}/\d{2}/\d{2}$")


def _sqlite_file_path() -> str:
    """Resolve SQLite file path from DATABASE_URL."""
    url = os.getenv("DATABASE_URL", _DEFAULT_DATABASE_URL)
    if url.startswith(_SQLITE_AI_PREFIX):
        return url[len(_SQLITE_AI_PREFIX) :]
    return url


def _quote_ident(name: str) -> str:
    """Double-quote a SQLite identifier, escaping embedded quotes."""
    return '"' + name.replace('"', '""') + '"'


def _sql_scalar(value: object) -> object:
    """Convert a pandas cell value to a SQLite-friendly Python scalar."""
    if value is None:
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        fv = float(value)
        if np.isnan(fv):
            return None
        return fv
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, str):
        return value
    try:
        if bool(pd.isna(value)):
            return None
    except (ValueError, TypeError):
        pass
    return value


def _strip_whitespace_series(series: pd.Series) -> pd.Series:
    """Rule (a): strip leading/trailing whitespace on string/object cells."""
    if not (pd.api.types.is_object_dtype(series.dtype) or pd.api.types.is_string_dtype(series.dtype)):
        return series
    out = series.copy()

    def _strip_one(val: object) -> object:
        if isinstance(val, str):
            return val.strip()
        return val

    return out.map(_strip_one)


def _numericish_after_strip(s: str) -> bool:
    """True if the string looks like a number after removing currency and commas."""
    cleaned = "".join(ch for ch in s if ch not in _CURRENCY_CHARS).replace(",", "").strip()
    if cleaned in {"", "-", "+", ".", "-.", "+."}:
        return False
    return bool(re.fullmatch(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", cleaned))


def _currency_strip_cell(val: object) -> object:
    """Rule (b): strip currency symbols and thousands commas for numeric-like strings."""
    if not isinstance(val, str):
        return val
    if not _numericish_after_strip(val):
        return val
    cleaned = "".join(ch for ch in val if ch not in _CURRENCY_CHARS).replace(",", "").strip()
    return cleaned


def _currency_strip_series(series: pd.Series) -> pd.Series:
    return series.map(_currency_strip_cell)


def _is_date_like_string(val: object) -> bool:
    if not isinstance(val, str):
        return False
    s = val.strip()
    if not s:
        return False
    if _ISO_DATE_START.match(s):
        return True
    if _DD_MM_YYYY.match(s):
        return True
    if _YYYY_SLASH.match(s):
        return True
    return False


def _date_match_fraction(series: pd.Series) -> float:
    non_null = series.dropna()
    if non_null.empty:
        return 0.0
    matches = sum(1 for v in non_null if _is_date_like_string(v))
    return matches / len(non_null)


def _to_datetime_series(series: pd.Series) -> pd.Series:
    try:
        return pd.to_datetime(  # type: ignore[call-overload]
            series,
            infer_datetime_format=True,
            errors="coerce",
            dayfirst=True,
        )
    except TypeError:
        return pd.to_datetime(series, errors="coerce", dayfirst=True)  # type: ignore[call-overload]


def _date_normalise_series(series: pd.Series) -> pd.Series:
    """Rule (c): normalise date-like columns to YYYY-MM-DD strings when thresholds pass."""
    non_null = series.dropna()
    if non_null.empty:
        return series
    if _date_match_fraction(series) <= 0.6:
        return series
    parsed = _to_datetime_series(series)
    parsed_ok = parsed.notna()
    original_ok = series.notna()
    if original_ok.sum() == 0:
        return series
    success_rate = float(parsed_ok.sum()) / float(original_ok.sum())
    if success_rate <= 0.6:
        return series
    out = series.copy()
    out.loc[parsed_ok] = parsed.loc[parsed_ok].dt.strftime("%Y-%m-%d")
    return out


def _numeric_coerce_series(series: pd.Series) -> pd.Series:
    """Rule (d): coerce to float when >80% of non-null values parse as numeric."""
    if pd.api.types.is_float_dtype(series.dtype) and not pd.api.types.is_object_dtype(series.dtype):
        return series
    if pd.api.types.is_integer_dtype(series.dtype):
        return series
    non_null = series.dropna()
    if non_null.empty:
        return series
    coerced = pd.to_numeric(series, errors="coerce")
    coerced_ok = coerced.notna() & series.notna()
    rate = float(coerced_ok.sum()) / float(series.notna().sum())
    if rate > 0.8:
        return coerced.astype("float64")
    return series


def _apply_coercions(df: pd.DataFrame) -> pd.DataFrame:
    """Apply coercion rules (a)–(e) in order, column by column."""
    out = df.copy()
    for col in out.columns:
        s = out[col]
        logger.debug("Coercion start column=%s dtype=%s", col, s.dtype)
        s = _strip_whitespace_series(s)
        s = _currency_strip_series(s)
        s = _date_normalise_series(s)
        s = _numeric_coerce_series(s)
        out[col] = s
    logger.info("Applied coercion pipeline to %s columns", len(out.columns))
    return out


def _sqlite_type_for_dtype(dtype: object) -> str:
    if pd.api.types.is_integer_dtype(dtype):
        return "INTEGER"
    if pd.api.types.is_float_dtype(dtype):
        return "REAL"
    return "TEXT"


def _rows_for_executemany(df: pd.DataFrame) -> list[tuple[object, ...]]:
    rows: list[tuple[object, ...]] = []
    for _, row in df.iterrows():
        rows.append(tuple(_sql_scalar(v) for v in row.tolist()))
    return rows


async def _write_raw_table_and_update_counts(
    upload_id: str,
    df: pd.DataFrame,
) -> None:
    db_path = _sqlite_file_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    table = f"raw_{upload_id}"
    table_ident = _quote_ident(table)

    col_defs: list[str] = []
    col_idents: list[str] = []
    for col in df.columns:
        col_name = str(col)
        col_idents.append(_quote_ident(col_name))
        sql_t = _sqlite_type_for_dtype(df[col_name].dtype)
        col_defs.append(f"{_quote_ident(col_name)} {sql_t}")

    create_sql = f"CREATE TABLE {table_ident} ({', '.join(col_defs)})"
    placeholders = ", ".join("?" * len(df.columns))
    insert_sql = f"INSERT INTO {table_ident} ({', '.join(col_idents)}) VALUES ({placeholders})"

    row_count = int(len(df))
    col_count = int(len(df.columns))
    rows = _rows_for_executemany(df)

    logger.info(
        "Writing raw table upload_id=%s path=%s rows=%s cols=%s",
        upload_id,
        db_path,
        row_count,
        col_count,
    )

    async with aiosqlite.connect(db_path) as db:
        await db.execute(f"DROP TABLE IF EXISTS {table_ident}")
        await db.execute(create_sql)
        await db.executemany(insert_sql, rows)
        await db.commit()

    logger.info("Finished SQLite insert for table=%s", table)
    await update_upload_counts(upload_id, row_count, col_count)
    logger.info("Updated upload counts upload_id=%s", upload_id)


def parse_csv_to_sqlite(upload_id: str, file_path: str) -> None:
    """Read CSV, apply coercion rules, persist to `raw_{upload_id}`, update upload metadata."""
    logger.info("parse_csv_to_sqlite start upload_id=%s file=%s", upload_id, file_path)
    df = pd.read_csv(file_path)
    logger.info("Loaded CSV rows=%s cols=%s", len(df), len(df.columns))
    coerced = _apply_coercions(df)
    asyncio.run(_write_raw_table_and_update_counts(upload_id, coerced))
    logger.info("parse_csv_to_sqlite complete upload_id=%s", upload_id)
