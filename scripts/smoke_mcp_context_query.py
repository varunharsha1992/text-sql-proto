"""Steps 3-4 only: context_chat + query_chat (after analyze already done)."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from datalens_mcp.server import context_chat, query_chat


class MockCtx:
    async def report_progress(self, progress: float = 0, total: float | None = None, message: str | None = None) -> None:
        if message:
            print(f"  [progress] {message}")


async def main() -> None:
    ctx = MockCtx()

    print("=== 3/4 context_chat __INIT__ ===")
    r3 = await context_chat(ctx, message="__INIT__")
    d3 = json.loads(r3)
    assert d3.get("chat"), "empty context chat"
    assert d3.get("semantic_layer") is not None, "missing semantic_layer"
    print(f"  chat preview: {d3['chat'][:200]}")
    print(f"  catalog_column_count={d3.get('catalog_column_count')}")

    print("=== 4/4 query_chat revenue by country ===")
    r4 = await query_chat(ctx, message="What is total order revenue by customer country?")
    d4 = json.loads(r4)
    assert d4.get("route") in ("sql", "eda", "both"), d4.get("route")
    assert d4.get("chat"), "empty query chat"
    canvas = d4.get("canvas") or {}
    table = canvas.get("table")
    row_count = len(table.get("rows", [])) if table else 0
    print(f"  route={d4.get('route')} sql={bool(d4.get('sql_query'))} table_rows={row_count}")
    if d4.get("sql_query"):
        print(f"  sql: {d4['sql_query']}")
    print("\n=== STEPS 3-4 PASS ===")


if __name__ == "__main__":
    asyncio.run(main())
