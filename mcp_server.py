"""Horizon / FastMCP entrypoint at repo root.

Horizon loads the entrypoint file with its directory on sys.path (/app).
Use `mcp_server.py:mcp` — not `datalens_mcp/server.py:mcp` — so `datalens_mcp` imports resolve.
"""

from datalens_mcp.server import mcp

__all__ = ["mcp"]
