from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Callable, Awaitable

from .config import JOB_TIMEOUT_SEC, POLL_INTERVAL_SEC, PROGRESS_HEARTBEAT_SEC

if TYPE_CHECKING:
    from fastmcp import Context


async def poll_job_until_done(
    get_job: Callable[[], Awaitable[dict]],
    *,
    ctx: Context | None = None,
    timeout_sec: float = JOB_TIMEOUT_SEC,
    poll_interval_sec: float = POLL_INTERVAL_SEC,
) -> dict:
    """Poll job status; emit MCP progress from status + progress[] items."""
    start = time.monotonic()
    last_heartbeat = start
    last_progress_sig = ""
    tick = 0

    while True:
        job = await get_job()
        status = job.get("status", "pending")
        progress_items = job.get("progress") or []

        if ctx is not None:
            if status == "pending":
                await ctx.report_progress(progress=tick, message="Queued AutoEDA…")
            elif status == "running":
                if progress_items:
                    for item in progress_items:
                        sig = f"{item.get('text')}:{item.get('status')}"
                        if sig != last_progress_sig:
                            await ctx.report_progress(
                                progress=tick,
                                message=str(item.get("text") or "Running AutoEDA…"),
                            )
                            last_progress_sig = sig
                else:
                    await ctx.report_progress(progress=tick, message="Running AutoEDA…")
            tick += 1

        if status == "done":
            if ctx is not None:
                await ctx.report_progress(progress=tick, message="AutoEDA complete")
            return job
        if status == "error":
            err = job.get("error") or "AutoEDA job failed"
            raise RuntimeError(str(err))

        elapsed = time.monotonic() - start
        if elapsed >= timeout_sec:
            raise TimeoutError(
                f"Job poll timeout after {int(elapsed)}s (job_id={job.get('job_id')}, status={status})"
            )

        now = time.monotonic()
        if ctx is not None and (now - last_heartbeat) >= PROGRESS_HEARTBEAT_SEC:
            await ctx.report_progress(progress=tick, message=f"Still {status}… ({int(elapsed)}s)")
            last_heartbeat = now

        await asyncio.sleep(poll_interval_sec)
