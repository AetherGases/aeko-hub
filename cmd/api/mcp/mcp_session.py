"""One long-lived MCP session per server, shared by every tool call.

Without this, each tool call cost two server spawns. `MultiServerMCPClient`'s
own `get_tools()` says so in its docstring — "a new session will be created for
each tool call" — so listing the tools spawned the server once and invoking the
chosen one spawned it again, and every spawn paid the server's whole start-up.
For the `npx` servers that was a few seconds; for the Chroma server, which
imports torch and loads a 768-dimension model, it measured 103 seconds for a
query whose real work takes two.

So the session is opened once and kept open. Two consequences shape the code
below:

* It needs an event loop that outlives a single call. The synchronous bridge
  each integration used (`asyncio.run(...)`) closes its loop on the way out,
  which would leave a cached session bound to a dead loop, so this module runs
  a loop of its own on a daemon thread and hands work to it with
  `run_coroutine_threadsafe`.
* The session must be entered and exited by the same task, which is why the
  `async with` lives inside a single long-running coroutine that then parks on
  an event until close.

A call that outlives `call_timeout` raises instead of hanging, and a session
that has died is rebuilt once before the call is given up on — a server process
can be killed from outside at any time.
"""

import asyncio
import concurrent.futures
import threading
from typing import Any, Callable

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

# Generous on purpose: a cold server still has to import torch and load model
# weights, and a timeout firing during a legitimate start-up would look exactly
# like the bug this module exists to remove.
DEFAULT_STARTUP_TIMEOUT = 300.0

# A warm call is seconds. This is the "something is wrong" line, not a budget.
DEFAULT_CALL_TIMEOUT = 120.0

# How long a shutdown waits for the server to go quietly. A child that ignores
# it is abandoned rather than allowed to hold the application open.
DEFAULT_CLOSE_TIMEOUT = 30.0


class MCPSessionError(RuntimeError):
    """Raised when a tool call cannot be completed over the MCP session."""


class PersistentMCPSession:
    """A single MCP session, opened on first use and reused by every caller.

    `build_client` is called lazily rather than held as an already-built
    client, so an integration keeps raising its own "credential is not set"
    error at call time, and so a test can replace the factory on the module.
    """

    def __init__(
        self,
        server_name: str,
        build_client: Callable[[], MultiServerMCPClient],
        call_timeout: float = DEFAULT_CALL_TIMEOUT,
        startup_timeout: float = DEFAULT_STARTUP_TIMEOUT,
        close_timeout: float = DEFAULT_CLOSE_TIMEOUT,
    ) -> None:
        self.name = server_name
        self._server_name = server_name
        self._build_client = build_client
        self._call_timeout = call_timeout
        self._startup_timeout = startup_timeout
        self._close_timeout = close_timeout

        self._lock = threading.RLock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._tools: dict[str, BaseTool] | None = None
        self._closing: asyncio.Event | None = None
        self._keeper: concurrent.futures.Future | None = None

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        """Open the session if it is not open yet.

        Safe to call from anywhere, which is the point of exposing it: whoever
        calls it first pays the server's cold start, and every caller after
        that finds it warm. The application calls it at start-up so that the
        first user question is never the one paying.
        """

        self._ensure_started()

    def close(self) -> None:
        """Close the session and stop the loop, ending the server process.

        Without this the child outlives the application, still holding the
        model it loaded.
        """

        with self._lock:
            loop, keeper, closing = self._loop, self._keeper, self._closing
            self._loop = self._thread = self._tools = self._closing = self._keeper = None

        if loop is None:
            return

        if closing is not None:
            loop.call_soon_threadsafe(closing.set)

        if keeper is not None:
            try:
                keeper.result(timeout=self._close_timeout)
            except Exception:
                # A child that will not go quietly is abandoned: the loop is
                # stopped below either way, and shutdown must not stall on it.
                pass

        loop.call_soon_threadsafe(loop.stop)

    # -- calling -----------------------------------------------------------
    def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        """Run one MCP tool over the shared session, synchronously.

        The retry is not optimism: the server process can be killed from
        outside, and the first call to notice is the one holding a session
        whose pipe is already closed.
        """

        last_error: Exception | None = None
        for attempt in (1, 2):
            tool = self._resolve_tool(tool_name)
            try:
                return self._run(tool.ainvoke(kwargs))
            except MCPSessionError:
                raise
            except Exception as exc:
                last_error = exc
                self.close()

        raise MCPSessionError(
            f"'{tool_name}' failed on the {self._server_name} MCP server: {last_error}"
        ) from last_error

    def _run(self, coroutine: Any) -> Any:
        loop = self._loop
        if loop is None:  # closed underneath us by another thread
            raise ConnectionError("the MCP session was closed")

        future = asyncio.run_coroutine_threadsafe(coroutine, loop)
        try:
            return future.result(timeout=self._call_timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            self.close()
            raise MCPSessionError(
                f"the {self._server_name} MCP server did not answer within "
                f"{self._call_timeout:.0f}s. The session was dropped; the next "
                f"call starts a new server."
            ) from None

    def _resolve_tool(self, tool_name: str) -> BaseTool:
        tools = self._ensure_started()
        if tool_name in tools:
            return tools[tool_name]

        # `LookupError`, not `MCPSessionError`: a missing tool is a naming
        # mistake on this side, not a sick session, and the integrations have
        # always reported it that way.
        known = ", ".join(sorted(tools))
        raise LookupError(
            f"'{tool_name}' is not exposed by the {self._server_name} MCP server. "
            f"Available tools: {known}."
        )

    # -- the loop thread, and the session that lives on it -----------------
    def _ensure_started(self) -> dict[str, BaseTool]:
        with self._lock:
            if self._tools is not None:
                return self._tools

            client = self._build_client()
            loop = asyncio.new_event_loop()
            thread = threading.Thread(
                target=self._run_loop,
                args=(loop,),
                name=f"mcp-{self._server_name}",
                daemon=True,
            )
            thread.start()

            ready: concurrent.futures.Future = concurrent.futures.Future()
            keeper = asyncio.run_coroutine_threadsafe(self._keep_open(client, ready), loop)

            try:
                tools = ready.result(timeout=self._startup_timeout)
            except Exception as exc:
                keeper.cancel()
                loop.call_soon_threadsafe(loop.stop)
                raise MCPSessionError(
                    f"could not open a session with the {self._server_name} "
                    f"MCP server: {exc}"
                ) from exc

            self._loop, self._thread, self._tools, self._keeper = loop, thread, tools, keeper
            return tools

    @staticmethod
    def _run_loop(loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        try:
            loop.run_forever()
        finally:
            loop.close()

    async def _keep_open(
        self,
        client: MultiServerMCPClient,
        ready: concurrent.futures.Future,
    ) -> None:
        """Hold the session open until `close()`, on one task end to end."""

        closing = asyncio.Event()
        self._closing = closing
        try:
            async with client.session(self._server_name) as session:
                tools = await load_mcp_tools(session)
                ready.set_result({tool.name: tool for tool in tools})
                await closing.wait()
        except BaseException as exc:
            # Before start-up this is how the caller learns the server never
            # came up; after it, it only means the session is gone and the
            # next call will rebuild it.
            if not ready.done():
                ready.set_exception(exc)
