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
    # Idempotent column migrations for existing databases.
    _migrations = [
        "ALTER TABLE uploads ADD COLUMN data_dictionary TEXT",
        "ALTER TABLE uploads ADD COLUMN semantic_layer TEXT",
        "ALTER TABLE jobs ADD COLUMN progress TEXT",
    ]
    for stmt in _migrations:
        try:
            await db.execute(stmt)
        except Exception as exc:  # noqa: BLE001 - "duplicate column name" is expected on re-run
            if "duplicate column name" not in str(exc).lower():
                raise
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


async def update_job_progress(job_id: str, progress_json: str) -> None:
    db = await get_db()
    try:
        await db.execute(
            "UPDATE jobs SET progress = ?, updated_at = CURRENT_TIMESTAMP WHERE job_id = ?",
            (progress_json, job_id),
        )
        await db.commit()
    finally:
        await db.close()


async def update_upload_artifacts(
    upload_id: str,
    data_dictionary: str | None,
    semantic_layer: str | None,
) -> None:
    db = await get_db()
    try:
        await db.execute(
            "UPDATE uploads SET data_dictionary = ?, semantic_layer = ? WHERE id = ?",
            (data_dictionary, semantic_layer, upload_id),
        )
        await db.commit()
    finally:
        await db.close()


async def get_job(job_id: str) -> dict | None:
    db = await get_db()
    try:
        async with db.execute(
            """
            SELECT j.*, u.data_dictionary AS data_dictionary, u.semantic_layer AS semantic_layer
            FROM jobs j
            LEFT JOIN uploads u ON u.id = j.upload_id
            WHERE j.job_id = ?
            """,
            (job_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return {key: row[key] for key in row.keys()}
    finally:
        await db.close()


async def list_uploads() -> list[dict]:
    """Every uploaded table with its latest job id + status. Newest first."""
    db = await get_db()
    try:
        async with db.execute(
            """
            SELECT
                u.id        AS id,
                u.slug      AS slug,
                u.filename  AS filename,
                u.row_count AS row_count,
                u.col_count AS col_count,
                (SELECT job_id FROM jobs WHERE upload_id = u.id
                 ORDER BY created_at DESC LIMIT 1) AS job_id,
                (SELECT status FROM jobs WHERE upload_id = u.id
                 ORDER BY created_at DESC LIMIT 1) AS status
            FROM uploads u
            ORDER BY u.uploaded_at DESC
            """
        ) as cursor:
            rows = await cursor.fetchall()
        return [{key: row[key] for key in row.keys()} for row in rows]
    finally:
        await db.close()
