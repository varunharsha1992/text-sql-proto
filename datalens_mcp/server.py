from __future__ import annotations

import json
from pathlib import Path

import httpx
from fastmcp import Context, FastMCP

from .client import DataLensClient, format_connect_error, format_http_error
from .config import API_URL, POLL_INTERVAL_SEC
from .progress import poll_job_until_done

mcp = FastMCP("DataLens")
_client = DataLensClient()


def _read_csv_bytes(file_path: str | None, csv_content: str | None, filename: str | None) -> tuple[str, bytes]:
    has_path = bool(file_path and file_path.strip())
    has_content = bool(csv_content is not None and csv_content != "")
    if has_path == has_content:
        raise ValueError("Provide exactly one of file_path OR (csv_content + filename).")
    if has_path:
        p = Path(file_path)  # type: ignore[arg-type]
        if not p.is_file():
            raise ValueError(f"file_path not found: {file_path}")
        return p.name, p.read_bytes()
    if not filename or not filename.strip():
        raise ValueError("filename is required when using csv_content.")
    return filename.strip(), csv_content.encode("utf-8")  # type: ignore[union-attr]


@mcp.tool
async def analyze_csv(
    ctx: Context,
    file_path: str | None = None,
    csv_content: str | None = None,
    filename: str | None = None,
    poll_interval_sec: float = POLL_INTERVAL_SEC,
) -> str:
    """Upload one CSV, run AutoEDA (blocking), sync connected schema, return canvas + metadata."""
    try:
        fname, content = _read_csv_bytes(file_path, csv_content, filename)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc

    try:
        upload = await _client.upload_csv(fname, content)
    except httpx.ConnectError as exc:
        raise RuntimeError(format_connect_error(API_URL)) from exc
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(format_http_error(exc)) from exc

    job_id = upload["job_id"]
    upload_id = upload["upload_id"]
    slug = upload["slug"]

    await ctx.report_progress(progress=0, message=f"Uploaded {fname}, job queued…")

    try:
        job = await poll_job_until_done(
            lambda: _client.get_job(job_id),
            ctx=ctx,
            poll_interval_sec=poll_interval_sec,
        )
    except (TimeoutError, RuntimeError):
        raise
    except httpx.ConnectError as exc:
        raise RuntimeError(format_connect_error(API_URL)) from exc

    canvas = job.get("result") or {}
    try:
        sync = await _client.schema_sync()
    except httpx.ConnectError as exc:
        raise RuntimeError(format_connect_error(API_URL)) from exc
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(format_http_error(exc)) from exc

    layer = sync.get("semantic_layer") or {}
    relationships = layer.get("relationships") or []
    out = {
        "upload_id": upload_id,
        "job_id": job_id,
        "slug": slug,
        "filename": fname,
        "canvas": canvas,
        "schema_sync": {
            "tables_synced": sync.get("tables_synced") or [],
            "catalog_column_count": len(sync.get("catalog") or []),
            "relationship_count": len(relationships),
        },
    }
    return json.dumps(out, indent=2)


@mcp.tool
async def context_chat(ctx: Context, message: str) -> str:
    """One context-interview turn. Use message='__INIT__' to start."""
    await ctx.report_progress(progress=0, message="Starting context turn…")
    try:
        raw = await _client.context_chat(message)
    except httpx.ConnectError as exc:
        raise RuntimeError(format_connect_error(API_URL)) from exc
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(format_http_error(exc)) from exc

    catalog = raw.get("catalog") or []
    out = {
        "chat": raw.get("chat", ""),
        "complete": bool(raw.get("complete")),
        "catalog_column_count": len(catalog),
        "semantic_layer": raw.get("semantic_layer"),
        "catalog_preview": catalog[:5],
    }
    return json.dumps(out, indent=2)


@mcp.tool
async def query_chat(ctx: Context, message: str) -> str:
    """One schema-wide query turn (SQL / EDA / both)."""
    await ctx.report_progress(progress=0, message="Running query…")
    try:
        raw = await _client.query_chat(message)
    except httpx.ConnectError as exc:
        raise RuntimeError(format_connect_error(API_URL)) from exc
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(format_http_error(exc)) from exc

    out = {
        "chat": raw.get("chat", ""),
        "route": raw.get("route"),
        "route_reason": raw.get("route_reason"),
        "sql_query": raw.get("sql_query"),
        "canvas": raw.get("canvas"),
    }
    return json.dumps(out, indent=2)
