"""In-memory stand-in for the real `aeko` package.

The SDK is an external dependency that is not installed in the test
environment. `conftest.py` registers this module under the name `aeko` in
`sys.modules` before any application module is imported, so production code
keeps its plain `from aeko import ...` at the entry point.

The surface mirrors the SDK's README exactly — same names, same signatures,
same response fields. In particular `MessageResponse` deliberately carries no
`llm`/`input_tokens`/`output_tokens`, because the real one does not either.
"""

from dataclasses import dataclass, field
from typing import Any, Sequence

AGENT_NAMES = (
    "Roteador",
    "FAQ",
    "Orquestrador",
    "Guardrail de Saída",
    "Análista de inventários",
    "Analista de Poluentes",
    "Analista de Gases Verdes",
    "Coordenador de Melhoria Contínua",
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class AekoError(Exception):
    """Base class for every SDK error."""


class AekoNotConfiguredError(AekoError):
    """`Aeko.config()` was never called, or the key is empty/not a string."""


class SessionNotPreparedError(AekoError):
    """`send_message()` ran before `prepare()`."""


class UnknownAgentError(AekoError):
    """`set_tools()` got a key that is not an agent name."""

    def __init__(self, agent, known_agents=AGENT_NAMES):
        """Build the error, carrying the bad name and the valid ones."""
        super().__init__(f"Unknown agent: {agent!r}")
        self.agent = agent
        self.known_agents = tuple(known_agents)


# ---------------------------------------------------------------------------
# Data objects (frozen dataclasses, as documented)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AekoTool:
    tool: Any
    description: str = ""


@dataclass(frozen=True)
class SessionInfo:
    session_id: str
    turns: int


@dataclass(frozen=True)
class MessageResponse:
    session_id: str
    answer: str
    agents_called: list = field(default_factory=list)
    approved: bool = True
    guardrail_retries: int = 0


@dataclass(frozen=True)
class InventoryAnalysisResponse:
    answer: str
    agents_called: list = field(default_factory=list)
    context_used: bool = False


# ---------------------------------------------------------------------------
# Configuration facade
# ---------------------------------------------------------------------------
class Aeko:
    """Records every configuration call so tests can assert startup wiring."""

    config_calls: list = []
    _api_key = None

    @classmethod
    def config(cls, api_key, *, fast_model=None, slow_model=None, max_tokens=None, report_max_tokens=None):
        """Record the configuration and mark the SDK ready.

        Raises:
            AekoNotConfiguredError: the key is empty or not a string.
        """
        if not isinstance(api_key, str) or not api_key:
            raise AekoNotConfiguredError("An API key is required to configure Aeko.")
        cls._api_key = api_key
        cls.config_calls.append(
            {
                "api_key": api_key,
                "fast_model": fast_model,
                "slow_model": slow_model,
                "max_tokens": max_tokens,
                "report_max_tokens": report_max_tokens,
            }
        )

    @classmethod
    def is_configured(cls) -> bool:
        """Report whether a key was ever supplied."""
        return bool(cls._api_key)

    @classmethod
    def reset(cls) -> None:
        """Restore every default and clear the recorded calls and tools."""
        cls._api_key = None
        cls.config_calls = []
        AekoMessenger.tools = None
        AekoMessenger.instances = []
        AekoMessenger.reject_next = False
        AekoInventoryAnalyzer.instances = []


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------
class AekoMessenger:
    """Records the per-request calls the API makes against it."""

    tools = None
    instances: list = []
    # Test hook: makes the next run come back rejected by the output guardrail.
    reject_next = False

    @classmethod
    def set_tools(cls, tools: dict) -> None:
        """Register tools per agent, process-wide.

        Raises:
            UnknownAgentError: a key is not an agent name.
        """
        for agent in tools:
            if agent not in AGENT_NAMES:
                raise UnknownAgentError(agent)
        cls.tools = tools

    def __init__(self):
        """Register this messenger so tests can assert on it afterwards."""
        self.prepared_with = None
        self.sent_inputs = []
        AekoMessenger.instances.append(self)

    def prepare(self, session_id: str, user_info: str, history: Sequence[Any] | None = None) -> SessionInfo:
        """Record the session, context and history, and report the turn count."""
        turns = list(history or [])
        self.prepared_with = {"session_id": session_id, "user_info": user_info, "history": turns}
        return SessionInfo(session_id=session_id, turns=len(turns))

    def send_message(self, message: str) -> MessageResponse:
        """Echo the message back, or return a rejected draft when asked to.

        Raises:
            AekoNotConfiguredError: the SDK was never configured.
            SessionNotPreparedError: `prepare()` never ran.
        """
        if not Aeko.is_configured():
            raise AekoNotConfiguredError("Aeko.config() was never called.")
        if self.prepared_with is None:
            raise SessionNotPreparedError("prepare() must run before send_message().")

        self.sent_inputs.append(message)
        session_id = self.prepared_with["session_id"]

        if AekoMessenger.reject_next:
            return MessageResponse(
                session_id=session_id,
                answer="",
                agents_called=["Roteador", "Orquestrador", "Guardrail de Saída"],
                approved=False,
                guardrail_retries=3,
            )

        return MessageResponse(
            session_id=session_id,
            answer=f"echo: {message}",
            agents_called=["Roteador", "FAQ"],
            approved=True,
            guardrail_retries=0,
        )


class AekoInventoryAnalyzer:
    """Records the context and the Markdown payload it is handed."""

    instances: list = []

    def __init__(self):
        """Register this analyzer so tests can assert on it afterwards."""
        self.context = None
        self.analyzed_markdown = None
        AekoInventoryAnalyzer.instances.append(self)

    def set_context(self, context: str) -> None:
        """Record the previous report handed in as context."""
        self.context = context

    def analyze(self, inventory: str) -> InventoryAnalysisResponse:
        """Record the Markdown and return a plan derived from it.

        Raises:
            AekoNotConfiguredError: the SDK was never configured.
        """
        if not Aeko.is_configured():
            raise AekoNotConfiguredError("Aeko.config() was never called.")
        self.analyzed_markdown = inventory
        return InventoryAnalysisResponse(
            answer=f"plan for: {inventory}",
            agents_called=["Análista de inventários", "Coordenador de Melhoria Contínua"],
            context_used=self.context is not None,
        )
