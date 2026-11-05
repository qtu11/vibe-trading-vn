"""Packaged entrypoint for the separate, account-bound forex MCP server."""
from src.trading.forex.mcp_server import main

if __name__ == "__main__":
    raise SystemExit(main())
