"""AutoEDA agent — DeepSeek V4 Flash via OpenRouter, orchestrated by deepagents.

The agent owns the pipeline: it calls compute_baseline_canvas first (guaranteed
stats/warnings/charts), profiles the data, runs deeper analysis, builds a data
dictionary + semantic layer, and persists everything via write_autoeda_result.
Progress (the agent's todo list) is streamed to jobs.progress for the UI.
"""

from __future__ import annotations

import json
import logging

from deepagents import create_deep_agent

from backend.database import update_job_progress
from backend.llm import get_chat_model
from backend.tools.autoeda_baseline import compute_baseline_canvas
from backend.tools.autoeda_writer import write_autoeda_result
from backend.tools.chart import generate_chart_spec
from backend.tools.dataframe import get_dataframe_profile
from backend.tools.python_repl import run_python_analysis

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are AutoEDA, an expert data analyst agent. Given an uploaded \
dataset (one CSV table), you profile it, surface data-quality issues, build charts, \
and produce a data dictionary and a semantic layer.

Procedure (follow in order):
1. Call compute_baseline_canvas(upload_id) FIRST. This returns guaranteed stat cards, \
null/outlier warnings, and up to 5 charts. Keep ALL of these in your final output.
2. Call get_dataframe_profile(upload_id) to understand columns, dtypes, and stats.
3. Use run_python_analysis(upload_id, code) for deeper analysis when it adds insight \
(correlations, segment breakdowns, anomalies). Add the most useful findings as \
extra insight items (type "text"). Do not exceed 5 charts total.
4. Build a DATA DICTIONARY: one entry per column with column, dtype, semantic_type \
(one of identifier|categorical|numeric|temporal|currency|boolean|text), a concise \
description, up to 5 sample_values (as strings), null_pct (number), optional unit, \
and is_pii (true for names/emails/phones/addresses).
5. Build a SEMANTIC LAYER: grain (what one row represents), entities, measures \
(name, column, aggregation in sum|avg|count|count_distinct|min|max|median, \
description), dimensions (name, column, description), time_dimension (or null), \
and 3-6 suggested_questions a business user might ask.
6. Call write_autoeda_result(upload_id, canvas_response) EXACTLY ONCE with the \
complete object. canvas_response must be a JSON object with keys: insights (list), \
charts (list, <=5), table (null), data_dictionary (list), semantic_layer (object).

Use the write_todos planning tool to track your steps so the user sees progress. \
Keep the baseline insights and charts intact; only add to them."""


def _task_prompt(upload_id: str) -> str:
    return (
        f"Analyze the uploaded dataset with upload_id='{upload_id}'. "
        f"Pass this exact upload_id to every tool call. Follow the procedure and "
        f"finish by calling write_autoeda_result exactly once."
    )


_AGENT = None


def build_deep_agent():
    """Build (once) and return the compiled deep agent."""
    global _AGENT
    if _AGENT is None:
        _AGENT = create_deep_agent(
            model=get_chat_model(),
            tools=[
                compute_baseline_canvas,
                get_dataframe_profile,
                run_python_analysis,
                generate_chart_spec,
                write_autoeda_result,
            ],
            system_prompt=SYSTEM_PROMPT,
        )
    return _AGENT


def _todos_to_progress(todos: list) -> list[dict]:
    """Map deepagents todo dicts to ProgressItem-shaped dicts."""
    out: list[dict] = []
    for t in todos:
        if isinstance(t, dict):
            text = str(t.get("content") or t.get("text") or "")
            status = str(t.get("status") or "pending")
        else:
            text, status = str(t), "pending"
        if status not in ("pending", "in_progress", "completed"):
            status = "pending"
        if text:
            out.append({"text": text, "status": status})
    return out


async def run_autoeda_agent(upload_id: str, job_id: str) -> None:
    """Run the agent, streaming its todo list to jobs.progress as it goes.

    The agent persists the final CanvasResponse itself via write_autoeda_result.
    """
    logger.info("AutoEDA agent start upload_id=%s job_id=%s", upload_id, job_id)
    agent = build_deep_agent()
    last_serialized = ""
    async for state in agent.astream(
        {"messages": [{"role": "user", "content": _task_prompt(upload_id)}]},
        stream_mode="values",
    ):
        todos = state.get("todos") if isinstance(state, dict) else None
        if todos:
            progress = _todos_to_progress(todos)
            serialized = json.dumps(progress)
            if serialized != last_serialized:
                await update_job_progress(job_id, serialized)
                last_serialized = serialized
    logger.info("AutoEDA agent finished upload_id=%s job_id=%s", upload_id, job_id)
