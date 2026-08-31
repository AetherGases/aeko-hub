"""One module per MCP server integration (see `tavily_mcp.py`).

Each module here turns one MCP server into plain LangChain tools, never
importing `aeko` itself — `cmd/api/main.py` is the single entry point for the
SDK, and is where each module's tools get wrapped as `AekoTool`.
"""
