"""SQLite persistence for uploads and jobs using aiosqlite."""

from __future__ import annotations

import json as _json
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

        CREATE TABLE IF NOT EXISTS schema_meta (
            id TEXT PRIMARY KEY DEFAULT 'global',
            semantic_layer TEXT,
            context_complete BOOLEAN DEFAULT FALSE,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS catalog (
            upload_id TEXT NOT NULL,
            slug TEXT NOT NULL,
            column_name TEXT NOT NULL,
            data_type TEXT,
            semantic_role TEXT,
            business_context TEXT,
            description TEXT,
            is_primary_key BOOLEAN DEFAULT FALSE,
            is_foreign_key BOOLEAN DEFAULT FALSE,
            foreign_key_ref TEXT,
            is_pii BOOLEAN DEFAULT FALSE,
            unit TEXT,
            sample_values TEXT,
            null_pct REAL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (upload_id, column_name)
        );

        CREATE TABLE IF NOT EXISTS context_conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS query_history (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            user_query     TEXT NOT NULL,
            route          TEXT NOT NULL,
            route_reason   TEXT,
            sql_query      TEXT,
            chat_response  TEXT NOT NULL,
            canvas_json    TEXT NOT NULL,
            created_at     DATETIME DEFAULT CURRENT_TIMESTAMP
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


_CATALOG_FIELDS = (
    "data_type", "semantic_role", "business_context", "description",
    "is_primary_key", "is_foreign_key", "foreign_key_ref", "is_pii",
    "unit", "sample_values", "null_pct",
)


async def get_upload(upload_id: str) -> dict | None:
    db = await get_db()
    try:
        async with db.execute("SELECT * FROM uploads WHERE id = ?", (upload_id,)) as cur:
            row = await cur.fetchone()
        return {k: row[k] for k in row.keys()} if row else None
    finally:
        await db.close()


async def get_catalog() -> list[dict]:
    db = await get_db()
    try:
        async with db.execute(
            "SELECT * FROM catalog ORDER BY slug, column_name"
        ) as cur:
            rows = await cur.fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]
    finally:
        await db.close()


async def catalog_count() -> int:
    db = await get_db()
    try:
        async with db.execute("SELECT COUNT(*) FROM catalog") as cur:
            (n,) = await cur.fetchone()
        return int(n)
    finally:
        await db.close()


async def upsert_catalog_entry(
    upload_id: str, slug: str, column_name: str, updates: dict
) -> None:
    """Insert or update one catalog row. `updates` may contain any of _CATALOG_FIELDS;
    sample_values (a list) is JSON-encoded."""
    clean: dict = {}
    for field in _CATALOG_FIELDS:
        if field in updates and updates[field] is not None:
            val = updates[field]
            if field == "sample_values" and isinstance(val, list):
                val = _json.dumps([str(x) for x in val])
            clean[field] = val
    db = await get_db()
    try:
        # Ensure the row exists (keyed by upload_id, column_name), then patch fields.
        await db.execute(
            "INSERT OR IGNORE INTO catalog (upload_id, slug, column_name) VALUES (?, ?, ?)",
            (upload_id, slug, column_name),
        )
        if clean:
            sets = ", ".join(f"{f} = ?" for f in clean)
            params = list(clean.values()) + [upload_id, column_name]
            await db.execute(
                f"UPDATE catalog SET {sets}, updated_at = CURRENT_TIMESTAMP "
                f"WHERE upload_id = ? AND column_name = ?",
                params,
            )
        await db.commit()
    finally:
        await db.close()


async def _ensure_schema_row(db: aiosqlite.Connection) -> None:
    await db.execute("INSERT OR IGNORE INTO schema_meta (id) VALUES ('global')")


async def get_schema_meta() -> dict:
    db = await get_db()
    try:
        await _ensure_schema_row(db)
        await db.commit()
        async with db.execute("SELECT * FROM schema_meta WHERE id = 'global'") as cur:
            row = await cur.fetchone()
        return {k: row[k] for k in row.keys()}
    finally:
        await db.close()


async def get_schema_semantic_layer() -> str | None:
    meta = await get_schema_meta()
    val = meta.get("semantic_layer")
    return val if isinstance(val, str) else None


async def set_schema_semantic_layer(json_str: str) -> None:
    db = await get_db()
    try:
        await _ensure_schema_row(db)
        await db.execute(
            "UPDATE schema_meta SET semantic_layer = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 'global'",
            (json_str,),
        )
        await db.commit()
    finally:
        await db.close()


async def mark_schema_context_complete() -> None:
    db = await get_db()
    try:
        await _ensure_schema_row(db)
        await db.execute(
            "UPDATE schema_meta SET context_complete = TRUE, updated_at = CURRENT_TIMESTAMP WHERE id = 'global'"
        )
        await db.commit()
    finally:
        await db.close()


async def get_conversation() -> list[dict]:
    db = await get_db()
    try:
        async with db.execute(
            "SELECT role, content FROM context_conversations ORDER BY id"
        ) as cur:
            rows = await cur.fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in rows]
    finally:
        await db.close()


async def save_message(role: str, content: str) -> None:
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO context_conversations (role, content) VALUES (?, ?)",
            (role, content),
        )
        await db.commit()
    finally:
        await db.close()


async def any_upload_done() -> bool:
    """True when at least one upload has a latest job with status='done'."""
    for row in await list_uploads():
        if row.get("status") == "done":
            return True
    return False


async def save_query_turn(
    user_query: str,
    route: str,
    route_reason: str | None,
    sql_query: str | None,
    chat_response: str,
    canvas_json: str,
) -> int:
    db = await get_db()
    try:
        cur = await db.execute(
            """
            INSERT INTO query_history
                (user_query, route, route_reason, sql_query, chat_response, canvas_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_query, route, route_reason, sql_query, chat_response, canvas_json),
        )
        await db.commit()
        return int(cur.lastrowid)
    finally:
        await db.close()


async def get_query_history() -> list[dict]:
    db = await get_db()
    try:
        async with db.execute(
            "SELECT * FROM query_history ORDER BY id ASC"
        ) as cur:
            rows = await cur.fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]
    finally:
        await db.close()
