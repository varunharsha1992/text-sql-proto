"""SQLite persistence for uploads and jobs using aiosqlite."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import aiosqlite
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./data/app.db"
_SQLITE_AI_PREFIX = "sqlite+aiosqlite:///"


def raw_table_name(upload_id: str) -> str:
    """Per-upload raw data table name, derived from the unique upload_id.

    Uses upload_id (not the filename-derived slug) so two uploads with the same
    filename never collide on the same table. Non-alphanumeric chars (e.g. the
    UUID hyphens) are stripped so the result is a safe SQLite identifier.
    """
    return "raw_" + re.sub(r"[^0-9a-zA-Z]", "", upload_id)


def _sqlite_file_path() -> str:
    url = os.getenv("DATABASE_URL", _DEFAULT_DATABASE_URL)
    if url.startswith(_SQLITE_AI_PREFIX):
        return url[len(_SQLITE_AI_PREFIX) :]
    return url


async def get_db() -> aiosqlite.Connection:
    path = _sqlite_file_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(path)
    conn.row_factory = aiosqlite.Row
    return conn


async def create_tables(db: aiosqlite.Connection) -> None:
    await db.executescript(
        """
        CREATE TABLE IF NOT EXISTS uploads (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            slug TEXT NOT NULL,
            original_path TEXT NOT NULL,
            row_count INTEGER,
            col_count INTEGER,
            uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            context_complete BOOLEAN DEFAULT FALSE
        );

        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            job_type TEXT NOT NULL,
            upload_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            result TEXT,
            error TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    await db.commit()
    logger.info("Ensured database tables: uploads, jobs")


async def create_upload(upload_id: str, filename: str, slug: str, path: str) -> None:
    db = await get_db()
    try:
        await db.execute(
            """
            INSERT INTO uploads (id, filename, slug, original_path)
            VALUES (?, ?, ?, ?)
            """,
            (upload_id, filename, slug, path),
        )
        await db.commit()
        logger.debug("Inserted upload id=%s filename=%s", upload_id, filename)
    finally:
        await db.close()


async def update_upload_counts(upload_id: str, row_count: int, col_count: int) -> None:
    db = await get_db()
    try:
        await db.execute(
            """
            UPDATE uploads
            SET row_count = ?, col_count = ?
            WHERE id = ?
            """,
            (row_count, col_count, upload_id),
        )
        await db.commit()
        logger.debug(
            "Updated upload counts id=%s rows=%s cols=%s",
            upload_id,
            row_count,
            col_count,
        )
    finally:
        await db.close()


async def create_job(job_id: str, job_type: str, upload_id: str) -> None:
    db = await get_db()
    try:
        await db.execute(
            """
            INSERT INTO jobs (job_id, job_type, upload_id)
            VALUES (?, ?, ?)
            """,
            (job_id, job_type, upload_id),
        )
        await db.commit()
        logger.debug("Inserted job job_id=%s type=%s upload_id=%s", job_id, job_type, upload_id)
    finally:
        await db.close()


async def update_job(
    job_id: str,
    status: str,
    result: str | None = None,
    error: str | None = None,
) -> None:
    db = await get_db()
    try:
        await db.execute(
            """
            UPDATE jobs
            SET status = ?, result = ?, error = ?, updated_at = CURRENT_TIMESTAMP
            WHERE job_id = ?
            """,
            (status, result, error, job_id),
        )
        await db.commit()
        logger.debug("Updated job job_id=%s status=%s", job_id, status)
    finally:
        await db.close()


async def get_job(job_id: str) -> dict | None:
    db = await get_db()
    try:
        async with db.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return {key: row[key] for key in row.keys()}
    finally:
        await db.close()
