"""Tool: run_python_analysis — sandboxed Python exec against raw_{upload_id} DataFrame."""

from __future__ import annotations

import asyncio
import contextlib
import io
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

import aiosqlite
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from langchain_core.tools import tool

load_dotenv()

_DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./data/app.db"
_SQLITE_PREFIX = "sqlite+aiosqlite:///"
_ALLOWED_IMPORTS = {"pandas", "pd", "numpy", "np", "scipy.stats", "datetime"}


def _sqlite_file_path() -> str:
    url = os.getenv("DATABASE_URL", _DEFAULT_DATABASE_URL)
    if url.startswith(_SQLITE_PREFIX):
        return url[len(_SQLITE_PREFIX):]
    return url


async def _load_dataframe(upload_id: str) -> pd.DataFrame:
    path = _sqlite_file_path()
    async with aiosqlite.connect(path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(f"SELECT * FROM raw_{upload_id}") as cursor:
            rows = await cursor.fetchall()
            if not rows:
                return pd.DataFrame()
            columns = [description[0] for description in cursor.description]
    return pd.DataFrame([dict(row) for row in rows], columns=columns)


def _has_forbidden_imports(code: str) -> str | None:
    """Returns the offending import name if a forbidden import is found, else None."""
    for line in code.splitlines():
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            # Extract the module name
            parts = stripped.split()
            if stripped.startswith("from "):
                module = parts[1] if len(parts) > 1 else ""
            else:
                module = parts[1].split(".")[0] if len(parts) > 1 else ""

            top_level = module.split(".")[0]
            if top_level not in _ALLOWED_IMPORTS:
                return module
    return None


def _exec_code(df: pd.DataFrame, code: str) -> str:
    stdout_buffer = io.StringIO()
    exec_globals: dict = {"df": df, "pd": pd, "np": np}
    with contextlib.redirect_stdout(stdout_buffer):
        exec(code, exec_globals)  # noqa: S102
    return stdout_buffer.getvalue()


@tool
def run_python_analysis(upload_id: str, code: str) -> str:
    """Executes Python code against the raw_{upload_id} dataframe.
    Returns stdout output or error message. Never raises.
    Allowed imports: pandas, numpy, scipy.stats, datetime only.
    Timeout: PYTHON_REPL_TIMEOUT_SEC env var (default 30s).
    """
    forbidden = _has_forbidden_imports(code)
    if forbidden is not None:
        return f"Error: import '{forbidden}' is not allowed. Permitted: pandas, numpy, scipy.stats, datetime."

    try:
        df = asyncio.run(_load_dataframe(upload_id))
    except Exception as exc:
        return f"Error loading data for upload_id='{upload_id}': {exc}"

    timeout = int(os.getenv("PYTHON_REPL_TIMEOUT_SEC", "30"))

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_exec_code, df, code)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeoutError:
            return f"Error: execution timed out after {timeout}s."
        except Exception as exc:
            return f"Error during execution: {exc}"
