"""One module per tool that runs here, in this process.

This is the third of three packages that produce agent tools, and the rule
that separates them is what is on the other end of the call:

* `cmd/api/mcp/` — a child process speaking MCP over stdio.
* `cmd/api/integrations/` — a vendor's REST API, over HTTPS.
* this package — nothing. No process, no socket, no credential. The answer is
  computed by Python, here, and a call costs microseconds instead of seconds.

That is worth its own package because it changes what the modules have to
worry about: there is no server to pin, no schema to drift underneath us and
no key to be missing. What replaces those concerns is the input itself, which
is written by a language model — see the allowlist in `calculator.py`.

What all three share is the rule that matters: no module here imports `aeko`.
`cmd/api/main.py` is the single entry point for the SDK (see
`test_only_the_entry_point_imports_the_sdk`), so what these modules hand back
is plain LangChain `Tool` objects, and `main.py` wraps them as `AekoTool`.
"""
