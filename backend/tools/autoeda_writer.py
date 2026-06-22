"""Tool: write_autoeda_result — persists CanvasResponse JSON to jobs table."""

from __future__ import annotations

import asyncio
import json
import logging
import os

import aiosqlite
from dotenv import load_dotenv
from langchain_core.tools import tool
from pydantic import ValidationError

from backend.database import update_job, update_upload_artifacts
from backend.models import CanvasResponse

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


async def persist_autoeda_canvas(upload_id: str, canvas_response: dict) -> None:
    """Write CanvasResponse JSON to the latest job (status=done) and mirror
    data_dictionary + semantic_layer to the uploads row for downstream features."""
    job_id = await _find_job_id(upload_id)
    if job_id is None:
        raise ValueError(f"No job found for upload_id={upload_id!r}")
    json_str = json.dumps(canvas_response)
    await update_job(job_id, "done", result=json_str)
    dd = canvas_response.get("data_dictionary")
    sl = canvas_response.get("semantic_layer")
    await update_upload_artifacts(
        upload_id,
        json.dumps(dd) if dd is not None else None,
        json.dumps(sl) if sl is not None else None,
    )
    logger.info("AutoEDA result persisted for upload_id=%s job_id=%s", upload_id, job_id)


@tool
def write_autoeda_result(upload_id: str, canvas_response: dict) -> str:
    """Persists the final CanvasResponse JSON to jobs.result and sets status=done.
    Returns "ok" on success, or a validation/error message you must fix and retry.
    """
    # Tolerate the model passing the object as a JSON string.
    if isinstance(canvas_response, str):
        try:
            canvas_response = json.loads(canvas_response)
        except json.JSONDecodeError as exc:
            return f"canvas_response was not valid JSON: {exc}. Pass a JSON object and retry."
    if not isinstance(canvas_response, dict):
        return "canvas_response must be a JSON object. Pass an object and retry."

    # Validate against the contract BEFORE persisting. On failure, hand the
    # errors back to the agent so it can correct the shape and call again.
    try:
        validated = CanvasResponse(**canvas_response)
    except ValidationError as exc:
        return (
            "canvas_response does not match the required schema. "
            "Fix these errors and call write_autoeda_result again:\n"
            f"{exc}"
        )

    try:
        # Safe: LangGraph runs sync tools in a worker thread, so no event loop is running here.
        # Persist the normalized (validated) form so jobs.result always round-trips.
        asyncio.run(persist_autoeda_canvas(upload_id, validated.model_dump()))
    except Exception as exc:
        return f"Error persisting AutoEDA result: {exc}"
    return "ok"
