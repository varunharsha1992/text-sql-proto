"""Context Agent — turn-based interview over the connected schema (DeepSeek V4 Flash)."""

from __future__ import annotations

import json
import logging

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.prebuilt import create_react_agent

from backend.database import (
    get_catalog,
    get_conversation,
    get_schema_meta,
    get_schema_semantic_layer,
    save_message,
)
from backend.llm import get_chat_model
from backend.schema_synth import ensure_schema_seed
from backend.tools.catalog import (
    get_schema_overview,
    infer_relationships,
    mark_context_complete,
    sample_column_values,
    update_schema_semantic_layer,
    write_catalog_entry,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a senior data analyst onboarding a new multi-table database. \
An automated profiler has already produced a draft: a per-column catalog across all tables \
and a schema semantic layer (tables, relationships, measures, dimensions). Your job is to \
interview the data owner to CONFIRM, CORRECT, and DEEPEN that draft into a complete, \
join-ready schema.

Procedure:
- Call get_schema_overview first to see the tables, columns, and current relationships.
- Call infer_relationships to see candidate cross-table foreign keys.
- Before asking about a column, optionally call sample_column_values for concrete examples.
- After EVERY confirmed fact, persist it: write_catalog_entry for a column (business_context, \
description, is_primary_key, is_foreign_key, foreign_key_ref like "customers.id", is_pii, unit, \
semantic_role), and update_schema_semantic_layer for schema-level facts (relationships, grain in \
tables[], measures, dimensions, suggested_questions).
- When updating the semantic layer, pass FULL lists for the keys you change (they replace the \
current list). Keep existing entries you are not changing.
- Ask at most 2 questions per turn. Never ask about things the draft already states confidently \
(obvious PKs, datetime columns, clear measures) — confirm those silently by writing them.
- Focus especially on RELATIONSHIPS between tables — confirm or correct each candidate FK.
- After ~4-6 exchanges, or when the user says "done"/"that's enough", summarise what you learned, \
call mark_context_complete, and tell the user the context is saved.

Reply in plain conversational text (your chat message to the user). Do not output JSON to the user."""

_AGENT = None


def build_context_agent():
    """Build (once) the compiled tool-calling agent."""
    global _AGENT
    if _AGENT is None:
        _AGENT = create_react_agent(
            get_chat_model(),
            tools=[
                get_schema_overview,
                sample_column_values,
                infer_relationships,
                write_catalog_entry,
                update_schema_semantic_layer,
                mark_context_complete,
            ],
            prompt=SYSTEM_PROMPT,
        )
    return _AGENT


def _to_lc(history: list[dict]) -> list:
    out = []
    for m in history:
        if m["role"] == "user":
            out.append(HumanMessage(m["content"]))
        else:
            out.append(AIMessage(m["content"]))
    return out


async def run_context_turn(message: str) -> dict:
    """Run one interview turn. Persists messages; returns chat + full catalog + semantic layer."""
    await ensure_schema_seed()
    lc = _to_lc(await get_conversation())
    if message == "__INIT__":
        lc.append(HumanMessage(
            "Begin the interview. Use get_schema_overview, then greet me and ask your first "
            "(at most 2) questions about the most ambiguous columns or relationships."
        ))
    else:
        lc.append(HumanMessage(message))

    agent = build_context_agent()
    result = await agent.ainvoke({"messages": lc})
    last = result["messages"][-1]
    reply = last.content if isinstance(last.content, str) else str(last.content)

    if message != "__INIT__":
        await save_message("user", message)
    await save_message("agent", reply)

    sl_raw = await get_schema_semantic_layer()
    return {
        "chat": reply,
        "catalog": await get_catalog(),
        "semantic_layer": json.loads(sl_raw) if sl_raw else None,
        "complete": bool((await get_schema_meta()).get("context_complete")),
    }
