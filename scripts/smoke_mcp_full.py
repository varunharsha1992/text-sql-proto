"""Full MCP smoke: analyze_csv x2, context_chat, query_chat. Run with backend on :8000."""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

# Windows console safe printing
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from datalens_mcp.server import analyze_csv, context_chat, query_chat

SMOKE = ROOT / "test-data" / "smoke"


class MockCtx:
    async def report_progress(self, progress: float = 0, total: float | None = None, message: str | None = None) -> None:
        if message:
            print(f"  [progress] {message}")


async def main() -> None:
    ctx = MockCtx()
    t0 = time.time()
    results: dict[str, str] = {}

    print("=== 1/4 analyze_csv smoke_customers.csv ===")
    r1 = await analyze_csv(ctx, file_path=str(SMOKE / "smoke_customers.csv"))
    d1 = json.loads(r1)
    synced1 = d1.get("schema_sync", {}).get("tables_synced", [])
    assert "smoke_customers" in synced1, synced1
    results["analyze_customers"] = "PASS"
    print(f"  slug={d1['slug']} tables_synced includes smoke_customers")

    print("=== 2/4 analyze_csv smoke_orders.csv ===")
    r2 = await analyze_csv(ctx, file_path=str(SMOKE / "smoke_orders.csv"))
    d2 = json.loads(r2)
    synced2 = d2.get("schema_sync", {}).get("tables_synced", [])
    assert "smoke_orders" in synced2 and "smoke_customers" in synced2, synced2
    results["analyze_orders"] = "PASS"
    print(f"  slug={d2['slug']} both smoke tables in schema_sync")

    print("=== 3/4 context_chat __INIT__ ===")
    r3 = await context_chat(ctx, message="__INIT__")
    d3 = json.loads(r3)
    assert d3.get("chat"), "empty context chat"
    assert d3.get("semantic_layer") is not None, "missing semantic_layer"
    results["context_init"] = "PASS"
    print(f"  chat preview: {d3['chat'][:120]}...")
    print(f"  catalog_column_count={d3.get('catalog_column_count')}")

    print("=== 4/4 query_chat revenue by country ===")
    r4 = await query_chat(ctx, message="What is total order revenue by customer country?")
    d4 = json.loads(r4)
    assert d4.get("route") in ("sql", "eda", "both"), d4.get("route")
    assert d4.get("chat"), "empty query chat"
    canvas = d4.get("canvas") or {}
    table = canvas.get("table")
    row_count = len(table.get("rows", [])) if table else 0
    results["query_chat"] = "PASS"
    print(f"  route={d4.get('route')} sql={bool(d4.get('sql_query'))} table_rows={row_count}")
    if d4.get("sql_query"):
        print(f"  sql preview: {d4['sql_query'][:100]}...")

    elapsed = int(time.time() - t0)
    print(f"\n=== ALL PASS ({elapsed}s) ===")
    for k, v in results.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(main())
