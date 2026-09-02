"""One module per external HTTP integration turned into LangChain tools.

The sibling package `cmd/api/mcp/` holds integrations that speak MCP to a
server process. The ones here speak plain HTTP to a vendor's REST API, because
the vendor publishes no MCP server of its own — wrapping one ourselves would
buy a child process and a stdio transport for what is a single POST.

What both packages share is the rule that matters: no module here imports
`aeko`. `cmd/api/main.py` is the single entry point for the SDK (see
`test_only_the_entry_point_imports_the_sdk`), so what these modules hand back
is plain LangChain `Tool` objects, and `main.py` wraps them as `AekoTool`.
"""
