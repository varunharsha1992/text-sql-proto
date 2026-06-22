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

SYSTEM_PROMPT = """You are AutoEDA, an expert data analyst agent. Given an uploaded dataset (one CSV table), you profile it, surface data-quality issues, build charts, and produce a data dictionary and a semantic layer.

PROCEDURE (follow in order):
1. Call compute_baseline_canvas(upload_id) FIRST. It returns guaranteed stat cards, null/outlier warnings, and up to 5 charts. Keep ALL of these items in your final output.
2. Call get_dataframe_profile(upload_id) to understand columns, dtypes, and stats.
3. Use run_python_analysis(upload_id, code) for deeper analysis when it adds insight (correlations, segment breakdowns, anomalies). Add the most useful findings as extra insight items (type "text"). Do not exceed 5 charts total.
4. Build a DATA DICTIONARY: exactly one entry per column in the dataset.
5. Build a SEMANTIC LAYER describing the dataset as a whole.
6. Use the write_todos planning tool to track your steps so the user sees progress.
7. Call write_autoeda_result(upload_id, canvas_response) EXACTLY ONCE with the complete object described in the OUTPUT CONTRACT below.

OUTPUT CONTRACT - canvas_response MUST be a JSON object with EXACTLY these keys and shapes. Field names are case-sensitive. Do not add, rename, or omit fields.

canvas_response = {
  "insights": [ InsightItem, ... ],
  "charts":   [ ChartSpec, ... ],            // 1 to 5 items
  "table":    null,                          // always null
  "data_dictionary": [ DataDictionaryEntry, ... ],   // one per column
  "semantic_layer": SemanticLayer
}

InsightItem = {
  "type": one of "stat" | "text" | "warning" | "badge",   // required
  "label": string,    // required when type="stat", else omit
  "value": string,    // required when type="stat", else omit
  "content": string,  // required when type is "text" | "warning" | "badge", else omit
  "color": one of "green" | "amber" | "red"   // optional
}

ChartSpec = {
  "type": one of "bar" | "line" | "histogram" | "scatter" | "heatmap" | "boxplot",  // required
  "title": string, "x_label": string, "y_label": string,   // all required
  "data": [ { "x": string-or-number, "y": number }, ... ]   // required, non-empty
}

DataDictionaryEntry = {
  "column": string,            // required, exact column name
  "dtype": string,             // required, e.g. "float64", "object", "int64"
  "semantic_type": one of "identifier" | "categorical" | "numeric" | "temporal" | "currency" | "boolean" | "text",  // required
  "description": string,       // required
  "sample_values": [ string, ... ],   // required, array of STRINGS (stringify numbers/dates)
  "null_pct": number,          // required
  "unit": string or null,      // optional; use null if not applicable
  "is_pii": true or false      // required boolean
}

SemanticLayer = {
  "grain": string,             // required, what one row represents
  "entities":   [ Entity, ... ],     // required (use [] if none)
  "measures":   [ Measure, ... ],    // required (use [] if none)
  "dimensions": [ Dimension, ... ],  // required (use [] if none)
  "time_dimension": string or null,  // required; a SINGLE column-name string, or null. NEVER an object.
  "suggested_questions": [ string, ... ]   // required, 3 to 6 items
}

Entity =    { "name": string, "description": string, "key_columns": [ string, ... ] }   // key_columns required, always an array (use [] if none)
Measure =   { "name": string, "column": string, "aggregation": one of "sum" | "avg" | "count" | "count_distinct" | "min" | "max" | "median", "description": string }
Dimension = { "name": string, "column": string, "description": string }

DO:
- Include every required field of every object, with the exact field names and casing above.
- Use ONLY the allowed enum values listed for "type", "semantic_type", "aggregation", and "color".
- Make "key_columns" an array of column-name strings on every Entity; use [] when there is no key, never omit it.
- Make "time_dimension" a single column-name string (e.g. "ORDERDATE") or null.
- Make "sample_values" an array of strings; convert numbers and dates to strings.
- Make "is_pii" a boolean (true/false), and "null_pct" a number.
- Emit exactly one DataDictionaryEntry per column in the dataset.
- Preserve every insight and chart returned by compute_baseline_canvas; you may add to them, up to 5 charts total.
- Pass canvas_response to write_autoeda_result as a JSON object (not a string).

DON'T:
- Do NOT emit "time_dimension" as an object such as {"name": ..., "column": ..., "description": ...}. It must be a string or null.
- Do NOT omit "key_columns", "description", or any other required field.
- Do NOT invent fields that are not in the contract.
- Do NOT wrap the JSON in markdown code fences or add explanatory prose around it.
- Do NOT use enum values outside the allowed sets.

If write_autoeda_result returns a validation error, fix exactly what it reports and call it again."""


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
