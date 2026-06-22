"""Tool: compute_baseline_canvas — guaranteed deterministic stats/warnings/charts.

The agent is instructed to call this FIRST so the spec's required stat cards,
>5% null warnings, outlier warnings, and <=5 charts are always present even if
the LLM does nothing else useful.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from backend.agents.autoeda_deterministic import build_autoeda_canvas_sync


def baseline_canvas(upload_id: str) -> dict[str, Any]:
    """Plain callable: deterministic CanvasResponse dict (insights/charts/table)."""
    return build_autoeda_canvas_sync(upload_id)


@tool
def compute_baseline_canvas(upload_id: str) -> dict:
    """Compute the guaranteed baseline analysis for an upload.

    Returns a dict with keys: insights (stat cards + null/outlier warnings),
    charts (up to 5, auto-selected), and table (null). Call this FIRST, then
    build the data dictionary and semantic layer on top of it.
    """
    return baseline_canvas(upload_id)
