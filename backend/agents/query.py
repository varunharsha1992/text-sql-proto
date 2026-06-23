"""Query Canvas — DeepAgents orchestrator with Text2SQL + EDA subagents."""

from __future__ import annotations

import logging

from deepagents import create_deep_agent
from deepagents.middleware.subagents import SubAgent
from langchain_core.messages import AIMessage

from backend.llm import get_chat_model
from backend.tools.catalog import get_schema_overview
from backend.tools.chart import generate_chart_spec
from backend.tools.dataframe import sample_column_values
from backend.tools.python_repl import run_python_analysis
from backend.tools.query_schema import (
    get_catalog_column,
    get_data_dictionary,
    get_semantic_layer,
    list_tables,
    resolve_table,
)
from backend.tools.sql import (
    execute_sql,
    get_last_sql_result,
    write_query_result,
)

logger = logging.getLogger(__name__)

ORCHESTRATOR_PROMPT = """You are the Query Canvas orchestrator for a multi-table SQLite schema.

Procedure:
1. Read the user's business question.
2. Optionally call list_tables or get_schema_overview for lightweight grounding.
3. Decide route:
   - text2sql subagent: factual tabular answers, aggregations, JOINs, filters
   - eda subagent: distributions, correlations, patterns, statistical insight
   - both: SQL first (tabular result), then EDA to interpret/visualize
4. Delegate to the appropriate subagent(s) using your subagent tools.
5. Merge outputs when route=both: combined chat, merged canvas (insights+charts from EDA, table from SQL).
6. Call write_query_result EXACTLY ONCE with: user_query, route, route_reason, chat_response, canvas_response (insights + charts only — omit table rows), sql_query (nullable).

Canvas contract: { insights: InsightItem[], charts: ChartSpec[], table: null in your canvas_response }.
For sql/both routes, write_query_result attaches the results table server-side from execute_sql — do NOT copy rows into canvas_response.
Reply conversationally in chat_response — no raw JSON to the user."""

TEXT2SQL_PROMPT = """You are a senior analytics engineer writing multi-table SQLite SQL.

Rules:
- Call get_schema_overview and/or get_catalog_column / get_semantic_layer('relationships') BEFORE writing SQL.
- Use resolve_table(slug) to map slugs to raw_{upload_id} table names in SQL.
- Prefer catalog FK fields and schema relationships over guessing joins.
- Only SELECT/WITH. Always handle NULLs. Fix failed SQL up to 2 times via execute_sql errors.
- Call execute_sql to run the query; do NOT paste result rows into canvas_response — the server attaches the table.
- Optional: generate_chart_spec for a simple viz from results.
- Return structured output to orchestrator: chat_response, canvas_response (insights/charts only), sql_query."""

EDA_PROMPT = """You are a senior data scientist doing exploratory analysis across uploaded tables.

Rules:
- Call get_schema_overview or get_catalog_column before analysis.
- Use run_python_analysis(upload_id, code) with pandas/numpy/scipy.stats.
- sample_column_values helps ground questions.
- If SQL ran earlier in the turn, call get_last_sql_result to analyze those rows.
- generate_chart_spec for validated charts (max 5 total in canvas).
- Return chat_response + canvas_response (insights, charts; table usually null unless you tabulate in Python)."""

_AGENT = None


def build_query_agent():
    global _AGENT
    if _AGENT is None:
        text2sql = SubAgent(
            name="text2sql",
            description="Multi-table SQL generation and execution for business questions.",
            system_prompt=TEXT2SQL_PROMPT,
            tools=[
                get_schema_overview,
                get_catalog_column,
                get_semantic_layer,
                get_data_dictionary,
                resolve_table,
                execute_sql,
                generate_chart_spec,
            ],
        )
        eda = SubAgent(
            name="eda",
            description="Exploratory data analysis: patterns, stats, charts.",
            system_prompt=EDA_PROMPT,
            tools=[
                get_schema_overview,
                get_catalog_column,
                get_semantic_layer,
                get_data_dictionary,
                list_tables,
                resolve_table,
                sample_column_values,
                run_python_analysis,
                generate_chart_spec,
                get_last_sql_result,
            ],
        )
        _AGENT = create_deep_agent(
            model=get_chat_model(),
            tools=[list_tables, get_schema_overview, write_query_result],
            subagents=[text2sql, eda],
            system_prompt=ORCHESTRATOR_PROMPT,
        )
    return _AGENT


def _last_ai_text(state: dict) -> str:
    msgs = state.get("messages") or []
    for m in reversed(msgs):
        if isinstance(m, AIMessage):
            content = m.content
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = [p.get("text", "") if isinstance(p, dict) else str(p) for p in content]
                return "".join(parts)
    return ""


async def run_query_turn(message: str) -> dict:
    """Run one query turn synchronously. Returns QueryChatResponse-shaped dict."""
    from backend.tools import sql as sql_tools

    sql_tools._LAST_QUERY_TURN = None
    sql_tools._LAST_SQL_RESULT = None

    agent = build_query_agent()
    prompt = (
        f"User question: {message}\n\n"
        "Finish by calling write_query_result with the full turn payload."
    )
    try:
        final_state = await agent.ainvoke({"messages": [{"role": "user", "content": prompt}]})
    except Exception:  # noqa: BLE001
        logger.exception("Query agent turn failed")
        return {
            "chat": (
                "Sorry — I couldn't reach the analysis model just now. "
                "Please try again in a moment."
            ),
            "canvas": {"insights": [], "charts": [], "table": None},
            "route": "eda",
            "route_reason": "Model unavailable.",
            "sql_query": None,
        }

    if sql_tools._LAST_QUERY_TURN:
        t = sql_tools._LAST_QUERY_TURN
        return {
            "chat": t["chat"],
            "canvas": t["canvas"],
            "route": t["route"],
            "route_reason": t["route_reason"] or "",
            "sql_query": t.get("sql_query"),
        }

    fallback_chat = _last_ai_text(final_state if isinstance(final_state, dict) else {})
    return {
        "chat": fallback_chat or "I couldn't complete that query. Please try rephrasing.",
        "canvas": {"insights": [], "charts": [], "table": None},
        "route": "eda",
        "route_reason": "Agent did not persist a structured result.",
        "sql_query": None,
    }
