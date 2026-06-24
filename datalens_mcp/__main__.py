from __future__ import annotations

from datalens_mcp.config import MCP_HOST, MCP_PORT
from datalens_mcp.server import mcp


def main() -> None:
    mcp.run(transport="http", host=MCP_HOST, port=MCP_PORT)


if __name__ == "__main__":
    main()
