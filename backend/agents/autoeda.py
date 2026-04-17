"""AutoEDA LangGraph agent — single-node ReAct loop for exploratory data analysis."""

from __future__ import annotations

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from backend.tools.autoeda_writer import write_autoeda_result
from backend.tools.chart import generate_chart_spec
from backend.tools.dataframe import get_dataframe_profile
from backend.tools.python_repl import run_python_analysis

load_dotenv()

SYSTEM_PROMPT = """You are a senior data scientist doing a first-pass exploratory analysis of a new dataset.
Your job is to quickly understand the shape, quality, and key distributions of the data before any cleaning or modeling.
You produce a structured summary and a set of charts that give the analyst an immediate feel for what they're working with.

You MUST run all 7 analyses below using the available tools, then produce charts, then save results.

REQUIRED ANALYSES (run all 7 via run_python_analysis):
1. Row count, column count, memory size
2. Null percentage per column — flag any column >5% nulls as warning insight
3. Duplicate row count — flag if >0 as warning
4. For each numeric column: skew, min, max, mean, median
5. For each categorical column with cardinality ≤20: value counts
6. Top 3 pairwise correlations (absolute value) among numeric columns
7. Datetime columns: min/max date range

CHART SELECTION RULES (max 5 charts total):
- Numeric column, cardinality >20 → histogram
- Categorical column, cardinality ≤10 → bar chart
- Two numeric columns with |correlation| >0.5 → scatter
- Datetime + numeric column → line chart
- ≥4 numeric columns → correlation heatmap

OUTPUT: Call write_autoeda_result with a CanvasResponse dict:
{
  "insights": [
    {"type": "stat", "label": "Rows", "value": "N"},
    {"type": "stat", "label": "Columns", "value": "N"},
    {"type": "stat", "label": "Duplicates", "value": "N", "color": "amber"},
    {"type": "warning", "content": "column_name: X% null values"}
  ],
  "charts": [...],
  "table": null
}

Include the Duplicates stat only if duplicates > 0. Include a warning insight for every column with >5% null values.
"""

_tools = [get_dataframe_profile, run_python_analysis, generate_chart_spec, write_autoeda_result]

_llm = ChatOpenAI(model="gpt-4o", temperature=0)
_llm_with_tools = _llm.bind_tools(_tools)


def _agent_node(state: MessagesState) -> dict:
    response = _llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}


_builder = StateGraph(MessagesState)
_builder.add_node("agent", _agent_node)
_builder.add_node("tools", ToolNode(_tools))
_builder.set_entry_point("agent")
_builder.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
_builder.add_edge("tools", "agent")

app = _builder.compile()


async def run_autoeda_agent(upload_id: str) -> None:
    """Fire-and-forget entry point; result is persisted via write_autoeda_result tool."""
    await app.ainvoke(
        {
            "messages": [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(
                    content=(
                        f"Analyse upload_id='{upload_id}'. "
                        "Call get_dataframe_profile first, then run all 7 analyses, "
                        "then generate charts, then call write_autoeda_result."
                    )
                ),
            ]
        }
    )
