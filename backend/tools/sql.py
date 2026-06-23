"""Query Canvas SQL execution + history persistence tools."""

from __future__ import annotations

import concurrent.futures
import logging
import re
import sqlite3
from pathlib import Path

from langchain_core.tools import tool

from backend.database import _sqlite_file_path, save_query_turn
from backend.models import CanvasResponse
from backend.tools.chart import normalize_chart_data

logger = logging.getLogger(__name__)

_LAST_SQL_RESULT: dict | None = None
_LAST_QUERY_TURN: dict | None = None

_BANNED = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|DETACH|PRAGMA|REPLACE|TRUNCATE)\b",
    re.IGNORECASE,
)
_LIMIT_RE = re.compile(r"\blimit\b", re.IGNORECASE)


def _run_sync(coro):
    """Run async code from sync tool (safe when an event loop is already running)."""
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _is_read_only_sql(sql: str) -> bool:
    stripped = sql.strip().rstrip(";").strip()
    upper = stripped.upper()
    if not (upper.startswith("SELECT") or upper.startswith("WITH")):
        return False
    return _BANNED.search(stripped) is None


def _ensure_limit(sql: str, cap: int = 500) -> str:
    if _LIMIT_RE.search(sql):
        return sql
    return f"{sql.rstrip().rstrip(';')} LIMIT {cap}"


def _sync_query(sql: str) -> dict:
    path = _sqlite_file_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        cur = conn.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        serializable = []
        for row in rows:
            serializable.append([None if v is None else v for v in row])
        return {
            "columns": cols,
            "rows": serializable,
            "row_count": len(serializable),
        }
    finally:
        conn.close()


def _sql_result_to_table(result: dict | None) -> dict | None:
    """Build TableData dict from execute_sql output — server-side, not LLM-copied."""
    if not result or result.get("error"):
        return None
    cols = result.get("columns") or []
    rows = result.get("rows") or []
    if not cols:
        return None
    return {"columns": cols, "rows": rows}


@tool
def execute_sql(sql: str) -> dict:
    """Run read-only SQL against SQLite raw tables (raw_{upload_id}). LIMIT 500 enforced if absent."""
    global _LAST_SQL_RESULT
    try:
        if not _is_read_only_sql(sql):
            return {
                "error": "Only read-only SELECT/WITH queries are allowed.",
                "columns": [],
                "rows": [],
                "row_count": 0,
            }
        safe_sql = _ensure_limit(sql)
        result = _sync_query(safe_sql)
        _LAST_SQL_RESULT = result
        return result
    except Exception as exc:  # noqa: BLE001
        err = {"error": str(exc), "columns": [], "rows": [], "row_count": 0}
        _LAST_SQL_RESULT = err
        return err


@tool
def get_last_sql_result() -> dict:
    """Return the most recent execute_sql result in this orchestrator run (for EDA after SQL)."""
    if _LAST_SQL_RESULT is None:
        return {"error": "No SQL result yet in this turn."}
    return _LAST_SQL_RESULT


@tool
def write_query_result(
    user_query: str,
    route: str,
    route_reason: str,
    chat_response: str,
    canvas_response: dict,
    sql_query: str | None = None,
) -> str:
    """Persist one query turn to global query_history. Call EXACTLY ONCE at end of orchestration.

    For route sql|both, table is attached server-side from the last execute_sql result —
    the model must NOT paste row data into canvas_response.table."""
    global _LAST_QUERY_TURN
    try:
        if route not in ("sql", "eda", "both"):
            return f"error: invalid route {route!r}"
        canvas = dict(canvas_response or {})
        if route in ("sql", "both"):
            server_table = _sql_result_to_table(_LAST_SQL_RESULT)
            if server_table is not None:
                canvas["table"] = server_table
        charts = canvas.get("charts")
        if isinstance(charts, list):
            for ch in charts:
                if isinstance(ch, dict) and isinstance(ch.get("data"), list):
                    ch["data"] = normalize_chart_data(ch["data"])
        validated = CanvasResponse(**canvas)
        canvas_json = validated.model_dump_json()
        row_id = _run_sync(
            save_query_turn(
                user_query=user_query,
                route=route,
                route_reason=route_reason,
                sql_query=sql_query,
                chat_response=chat_response,
                canvas_json=canvas_json,
            )
        )
        _LAST_QUERY_TURN = {
            "id": row_id,
            "user_query": user_query,
            "route": route,
            "route_reason": route_reason,
            "sql_query": sql_query,
            "chat": chat_response,
            "canvas": validated.model_dump(),
        }
        return "ok"
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}"
