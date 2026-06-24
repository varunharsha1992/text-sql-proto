from __future__ import annotations

from .config import MCP_HOST, MCP_PORT
from .server import mcp


def main() -> None:
    mcp.run(transport="http", host=MCP_HOST, port=MCP_PORT)


if __name__ == "__main__":
    main()
