"""AutoEDA entry point — deterministic pandas pipeline (no LLM, no LangGraph tool loop).

The previous ReAct + tool-calling agent could exceed AGENT_TIMEOUT_SEC on large CSVs
because each LLM round-trip and each sandboxed exec added latency. This path runs a
single bounded pandas workload in a worker thread, then persists once.
"""

from __future__ import annotations

import asyncio
import logging

from backend.agents.autoeda_deterministic import build_autoeda_canvas_sync
from backend.tools.autoeda_writer import persist_autoeda_canvas

logger = logging.getLogger(__name__)


async def run_autoeda_agent(upload_id: str) -> None:
    """Build CanvasResponse in a thread pool, then write jobs.result (one DB update)."""
    logger.info("AutoEDA start (deterministic) upload_id=%s", upload_id)
    canvas = await asyncio.to_thread(build_autoeda_canvas_sync, upload_id)
    await persist_autoeda_canvas(upload_id, canvas)
    logger.info("AutoEDA done upload_id=%s", upload_id)
