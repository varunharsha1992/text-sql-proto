"""FastAPI application — Upload and Auto EDA endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from uuid import uuid4

import aiosqlite
from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from backend.agents.autoeda import run_autoeda_agent
from backend.database import (
    create_job,
    create_tables,
    create_upload,
    get_db,
    get_job,
    update_job,
)
from backend.tools.autoeda_baseline import baseline_canvas
from backend.tools.autoeda_writer import persist_autoeda_canvas
from backend.models import CanvasResponse, JobResponse, UploadResponse
from backend.utils.csv_parser import parse_csv_to_sqlite

logger = logging.getLogger(__name__)

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./data/uploads")
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
AGENT_TIMEOUT_SEC = int(os.getenv("AGENT_TIMEOUT_SEC", "240"))  # agent run cap


def generate_slug(filename: str) -> str:
    """Convert filename to slug: 'orders_2024.csv' → 'orders_2024'"""
    stem = Path(filename).stem  # strip extension
    slug = re.sub(r"[^a-z0-9_-]", "_", stem.lower())
    return slug[:64]


def _parse_job_status(value: str) -> Literal["pending", "running", "done", "error"]:
    if value in ("pending", "running", "done", "error"):
        return value
    raise HTTPException(status_code=500, detail=f"Invalid job status: {value}")


def _require_str(value: object, field: str) -> str:
    if isinstance(value, str):
        return value
    raise HTTPException(status_code=500, detail=f"Invalid job field: {field}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db: aiosqlite.Connection = await get_db()
    await create_tables(db)
    await db.close()
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _persist_fallback(upload_id: str, job_id: str) -> None:
    """Persist the deterministic baseline so the user always gets a result."""
    canvas = await asyncio.to_thread(baseline_canvas, upload_id)
    await persist_autoeda_canvas(upload_id, canvas)
    logger.info("Persisted deterministic fallback for upload_id=%s", upload_id)


async def run_autoeda_pipeline(upload_id: str, job_id: str, slug: str) -> None:
    """Background task: parse CSV → run agent → fallback to baseline on failure."""
    file_path = str(Path(UPLOAD_DIR) / f"{upload_id}.csv")
    try:
        await update_job(job_id, "running")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, parse_csv_to_sqlite, upload_id, slug, file_path)
        await asyncio.wait_for(
            run_autoeda_agent(upload_id, job_id), timeout=AGENT_TIMEOUT_SEC
        )
        # The agent should have called write_autoeda_result. If not, fall back.
        row = await get_job(job_id)
        if row is None or row.get("status") != "done":
            logger.warning("Agent left job not done; using baseline. job_id=%s", job_id)
            await _persist_fallback(upload_id, job_id)
    except asyncio.CancelledError:
        raise
    except BaseException as exc:  # noqa: BLE001 - includes TimeoutError + agent/tool escapes
        logger.exception("AutoEDA agent failed; attempting baseline fallback. job_id=%s", job_id)
        try:
            await _persist_fallback(upload_id, job_id)
        except Exception:
            logger.exception("Baseline fallback also failed for job_id=%s", job_id)
            await update_job(job_id, "error", error=str(exc))


@app.post("/api/upload", response_model=UploadResponse)
async def upload_csv(file: UploadFile, background_tasks: BackgroundTasks) -> UploadResponse:
    filename = file.filename or ""
    content_type = file.content_type or ""
    is_csv = content_type == "text/csv" or filename.lower().endswith(".csv")
    if not is_csv:
        raise HTTPException(status_code=400, detail="File must be CSV (text/csv or .csv extension).")

    content = await file.read()
    max_bytes = MAX_FILE_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds maximum size of {MAX_FILE_SIZE_MB} MB.",
        )

    upload_id = str(uuid4())
    job_id = str(uuid4())
    slug = generate_slug(filename or "upload.csv")

    upload_root = Path(UPLOAD_DIR)
    upload_root.mkdir(parents=True, exist_ok=True)
    file_path = str(upload_root / f"{upload_id}.csv")
    Path(file_path).write_bytes(content)

    await create_upload(upload_id, filename or "upload.csv", slug, file_path)
    await create_job(job_id, "autoeda", upload_id)
    background_tasks.add_task(run_autoeda_pipeline, upload_id, job_id, slug)

    return UploadResponse(upload_id=upload_id, job_id=job_id, slug=slug)


@app.get("/api/jobs/{job_id}", response_model=JobResponse)
async def get_job_status(job_id: str) -> JobResponse:
    row = await get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found.")

    resolved_job_id = _require_str(row["job_id"], "job_id")
    status = _parse_job_status(_require_str(row["status"], "status"))

    raw_result = row.get("result")
    canvas_response: CanvasResponse | None = None
    if raw_result is not None:
        if not isinstance(raw_result, str):
            raise HTTPException(status_code=500, detail="Invalid job result type.")
        try:
            parsed: object = json.loads(raw_result)
        except json.JSONDecodeError:
            canvas_response = None
        else:
            if not isinstance(parsed, dict):
                raise HTTPException(status_code=500, detail="Job result is not a JSON object.")
            try:
                canvas_response = CanvasResponse(**parsed)
            except ValidationError:
                # A malformed/legacy row degrades to no-result rather than 500-ing the poll.
                logger.exception("Stored job result failed CanvasResponse validation job_id=%s", job_id)
                canvas_response = None

    raw_error = row.get("error")
    error_msg: str | None = raw_error if isinstance(raw_error, str) else None

    raw_progress = row.get("progress")
    progress_items = None
    if isinstance(raw_progress, str) and raw_progress:
        try:
            parsed_progress: object = json.loads(raw_progress)
        except json.JSONDecodeError:
            progress_items = None
        else:
            if isinstance(parsed_progress, list):
                progress_items = parsed_progress

    return JobResponse(
        job_id=resolved_job_id,
        status=status,
        result=canvas_response,
        error=error_msg,
        progress=progress_items,
    )
