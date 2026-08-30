"""In-memory stand-in for the real `aeko` package, version 2.

The SDK is an external dependency that is not installed in the test
environment. `conftest.py` registers this module under the name `aeko`
in `sys.modules` before any application module is imported, so production
code keeps its plain `from aeko import ...` at the entry point.

Everything here mirrors the 2.0 README field for field: the DTOs are the same
Pydantic models over the same MongoDB collections, `Aeko.config()` and
`AekoMessenger.set_tools()` write to one process-wide runtime, and
`send_message()` updates the `AekoSession` it is handed in place. What is faked
is only the agent graph — a run's answer is scripted by the test instead of
being produced by Gemini.

Every fake records the calls it receives so tests can assert that the API
wires the SDK correctly (configuration at startup, DTOs per request).
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

from pydantic import BaseModel, ConfigDict, Field

__version__ = "2.0.0"

# The routing keys of the agent graph, exactly as the README spells them,
# accents included.
AGENT_NAMES: tuple[str, ...] = (
    "Roteador",
    "FAQ",
    "Orquestrador",
    "Guardrail de Saída",
    "Análista de inventários",
    "Analista de Poluentes",
    "Analista de Gases Verdes",
    "Coordenador de Melhoria Contínua",
)

DEFAULT_FAST_MODEL = "gemini-3.1-flash-lite"
DEFAULT_SLOW_MODEL = "gemini-3.5-flash"
DEFAULT_MAX_TOKENS = 1024
DEFAULT_REPORT_MAX_TOKENS = 8192


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class AekoError(Exception):
    """Base class for every error raised by the Aeko SDK."""


class AekoNotConfiguredError(AekoError):
    """Raised when the SDK is used before `Aeko.config()` supplies an API key."""


class MalformedAgentOutputError(AekoError):
    """Raised when an agent's answer does not match the shape its prompt demands."""


class UnknownAgentError(AekoError):
    """Raised when tools are registered for an agent name that doesn't exist."""

    def __init__(self, agent: str, known_agents: tuple[str, ...]):
        self.agent = agent
        self.known_agents = known_agents
        super().__init__(
            f"'{agent}' is not a known agent. Valid names: {', '.join(known_agents)}."
        )


# ---------------------------------------------------------------------------
# Data objects — one per MongoDB collection
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AekoTool:
    tool: Any
    description: str = ""

    @property
    def name(self) -> str:
        return getattr(self.tool, "name", type(self.tool).__name__)

    def to_prompt_line(self) -> str:
        description = self.description or getattr(self.tool, "description", "")
        return f"{self.name} - {description}".rstrip(" -")

    @classmethod
    def wrap(cls, tool: "AekoTool | Any") -> "AekoTool":
        return tool if isinstance(tool, cls) else cls(tool=tool)


class AekoUser(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str | None = Field(default=None, alias="_id")
    id_external_user: int
    role: str
    usecase: str = ""


class AekoUserMemory(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str | None = Field(default=None, alias="_id")
    id_user: str | None = None
    field: str
    description: str
    created_at: datetime | None = None
    expires_at: datetime | None = None

    def to_prompt_line(self) -> str:
        return f"{self.field}: {self.description}"


class AekoMessage(BaseModel):
    input: str
    output: str = ""
    submitted_at: datetime = Field(default_factory=_now)
    llm: str = ""
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class AekoSession(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str | None = Field(default=None, alias="_id")
    id_user: str | None = None
    name: str = ""
    messages: list[AekoMessage] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AekoMessageResponse(BaseModel):
    message: AekoMessage
    id_session: str | None = None
    id_user: str | None = None
    agents_called: list[str] = Field(default_factory=list)
    approved: bool = False
    guardrail_retries: int = Field(default=0, ge=0)


class AekoImprovementPlan(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str | None = Field(default=None, alias="_id")
    id_external_inventory: int
    defined_problem: str
    method: str
    reasoning: str
    updated_at: datetime = Field(default_factory=_now)


# ---------------------------------------------------------------------------
# The process-wide runtime `Aeko.config()` and `set_tools()` write to
# ---------------------------------------------------------------------------
class _Runtime:
    def __init__(self):
        self.reset()

    def reset(self):
        self.api_key = None
        self.fast_model = DEFAULT_FAST_MODEL
        self.slow_model = DEFAULT_SLOW_MODEL
        self.max_tokens = DEFAULT_MAX_TOKENS
        self.report_max_tokens = DEFAULT_REPORT_MAX_TOKENS
        self.tools = {}
        self.config_calls = []
        self.set_tools_calls = []

    def require_api_key(self):
        if not self.api_key:
            raise AekoNotConfiguredError(
                "Aeko is not configured. Call Aeko.config() with a Gemini API key."
            )
        return self.api_key


RUNTIME = _Runtime()


class Aeko:
    """Configuration facade. Nothing here reads the environment."""

    @staticmethod
    def config(api_key: str, *, fast_model: str | None = None, slow_model: str | None = None,
               max_tokens: int | None = None, report_max_tokens: int | None = None) -> None:
        if not api_key or not isinstance(api_key, str):
            raise AekoNotConfiguredError("Aeko.config() requires a non-empty API key.")

        RUNTIME.config_calls.append(
            {
                "api_key": api_key,
                "fast_model": fast_model,
                "slow_model": slow_model,
                "max_tokens": max_tokens,
                "report_max_tokens": report_max_tokens,
            }
        )

        RUNTIME.api_key = api_key
        if fast_model is not None:
            RUNTIME.fast_model = fast_model
        if slow_model is not None:
            RUNTIME.slow_model = slow_model
        if max_tokens is not None:
            RUNTIME.max_tokens = max_tokens
        if report_max_tokens is not None:
            RUNTIME.report_max_tokens = report_max_tokens

    @staticmethod
    def is_configured() -> bool:
        return bool(RUNTIME.api_key)

    @staticmethod
    def reset() -> None:
        RUNTIME.reset()
        AekoMessenger.reset_script()
        AekoInventoryAnalyzer.reset_script()


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------
class AekoMessenger:
    """Conversational entry point, scripted instead of routed through Gemini."""

    # Every messenger built during a test, so a suite can reach the instance
    # the API created per request.
    instances: list["AekoMessenger"] = []

    # What the next run answers. Tests assign these; `Aeko.reset()` clears them.
    next_output: str | None = None
    next_approved: bool = True
    next_agents: tuple[str, ...] = ("FAQ",)
    next_guardrail_retries: int = 0
    next_error: Exception | None = None

    def __init__(self, user: AekoUser, memories: Sequence[AekoUserMemory] | None = None):
        if not isinstance(user, AekoUser):
            raise TypeError(f"AekoMessenger takes an AekoUser, got {type(user).__name__}.")

        memories = list(memories or [])
        for memory in memories:
            if not isinstance(memory, AekoUserMemory):
                raise TypeError(
                    f"AekoMessenger takes AekoUserMemory objects, got {type(memory).__name__}."
                )

        self.user = user
        self.memories = memories
        self.sent = []
        AekoMessenger.instances.append(self)

    @classmethod
    def reset_script(cls):
        cls.instances = []
        cls.next_output = None
        cls.next_approved = True
        cls.next_agents = ("FAQ",)
        cls.next_guardrail_retries = 0
        cls.next_error = None

    @classmethod
    def set_tools(cls, tools: dict[str, list[Any]]) -> None:
        normalized = {}
        for agent, agent_tools in tools.items():
            if agent not in AGENT_NAMES:
                raise UnknownAgentError(agent, AGENT_NAMES)
            normalized[agent] = [AekoTool.wrap(tool) for tool in agent_tools]

        RUNTIME.set_tools_calls.append(dict(tools))
        RUNTIME.tools = normalized

    def send_message(self, message: str, session: AekoSession) -> AekoMessageResponse:
        RUNTIME.require_api_key()

        if not isinstance(session, AekoSession):
            raise TypeError(
                f"send_message() takes an AekoSession, got {type(session).__name__}."
            )

        self.sent.append((message, session))

        if type(self).next_error is not None:
            raise type(self).next_error

        output = type(self).next_output
        if output is None:
            output = f"echo: {message}" if type(self).next_approved else ""

        turn = AekoMessage(
            input=message,
            output=output,
            llm="fake-fast,fake-slow",
            input_tokens=11,
            output_tokens=22,
        )

        # Only a final result is recorded: a rejected draft never becomes
        # context for the next question.
        if output:
            session.messages.append(turn)
            session.updated_at = turn.submitted_at

        return AekoMessageResponse(
            message=turn,
            id_session=session.id,
            id_user=session.id_user,
            agents_called=list(type(self).next_agents),
            approved=bool(output) and type(self).next_approved,
            guardrail_retries=type(self).next_guardrail_retries,
        )


class AekoInventoryAnalyzer:
    """Report entry point, scripted instead of routed through Gemini."""

    instances: list["AekoInventoryAnalyzer"] = []

    next_plan_fields: dict[str, str] = {}
    next_error: Exception | None = None

    def __init__(self):
        self.context = ""
        self.analyzed = []
        AekoInventoryAnalyzer.instances.append(self)

    @classmethod
    def reset_script(cls):
        cls.instances = []
        cls.next_plan_fields = {}
        cls.next_error = None

    def set_context(self, context: str) -> None:
        if not isinstance(context, str):
            raise TypeError(f"set_context() takes a string, got {type(context).__name__}.")
        self.context = context or ""

    def analyze(self, inventory: str, *, id_external_inventory: int) -> AekoImprovementPlan:
        RUNTIME.require_api_key()

        if not isinstance(inventory, str):
            raise TypeError(
                f"analyze() takes the inventory as Markdown text, got {type(inventory).__name__}."
            )
        if not isinstance(id_external_inventory, int):
            raise TypeError(
                "analyze() takes id_external_inventory as an int, "
                f"got {type(id_external_inventory).__name__}."
            )

        self.analyzed.append((inventory, id_external_inventory))

        if type(self).next_error is not None:
            raise type(self).next_error

        fields = {
            "defined_problem": "high scope 1 emissions",
            "method": "replace the boiler fleet",
            "reasoning": "direct combustion dominates the inventory",
            **type(self).next_plan_fields,
        }

        return AekoImprovementPlan(id_external_inventory=id_external_inventory, **fields)
