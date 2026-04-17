"""Tool: write_autoeda_result — persists CanvasResponse JSON to jobs table."""

from __future__ import annotations

import asyncio
import json
import logging
import os

import aiosqlite
from dotenv import load_dotenv
from langchain_core.tools import tool

from backend.database import update_job

load_dotenv()

logger = logging.getLogger(__name__)

_DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./data/app.db"
_SQLITE_PREFIX = "sqlite+aiosqlite:///"


def _sqlite_file_path() -> str:
    url = os.getenv("DATABASE_URL", _DEFAULT_DATABASE_URL)
    if url.startswith(_SQLITE_PREFIX):
        return url[len(_SQLITE_PREFIX):]
    return url


async def _find_job_id(upload_id: str) -> str | None:
    path = _sqlite_file_path()
    async with aiosqlite.connect(path) as conn:
        async with conn.execute(
            "SELECT job_id FROM jobs WHERE upload_id = ? ORDER BY created_at DESC LIMIT 1",
            (upload_id,),
        ) as cursor:
            row = await cursor.fetchone()
    return row[0] if row else None


@tool
def write_autoeda_result(upload_id: str, canvas_response: dict) -> str:
    """Persists the final CanvasResponse JSON to jobs.result and sets status=done.
    Returns "ok" on success, error message on failure.
    """
    try:
        job_id = asyncio.run(_find_job_id(upload_id))
    except Exception as exc:
        return f"Error finding job for upload_id='{upload_id}': {exc}"

    if job_id is None:
        return f"Error: no job found for upload_id='{upload_id}'."

    try:
        json_str = json.dumps(canvas_response)
    except (TypeError, ValueError) as exc:
        return f"Error serialising canvas_response: {exc}"

    try:
        asyncio.run(update_job(job_id, "done", result=json_str))
    except Exception as exc:
        return f"Error updating job job_id='{job_id}': {exc}"

    logger.info("AutoEDA result persisted for upload_id=%s job_id=%s", upload_id, job_id)
    return "ok"
