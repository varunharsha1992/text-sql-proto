"""Horizon / FastMCP entrypoint at repo root.

Either `mcp_server.py:mcp` or `datalens_mcp/server.py:mcp` works; server.py bootstraps sys.path.
"""

from datalens_mcp.server import mcp

__all__ = ["mcp"]
