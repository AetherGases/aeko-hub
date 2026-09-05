"""Define the domain entities for SDK run metrics."""

class AgentMetric:
    """What one agent *invocation* of a run consumed."""

    name: str
    input_tokens: int
    output_tokens: int
    llm: str
    used_tools: list[str]

    def __init__(self, name: str, input_tokens: int = 0, output_tokens: int = 0,
                 llm: str = "", used_tools: list[str] | None = None):
        self.name = name
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.llm = llm
        self.used_tools = list(used_tools or [])


class Metric:
    """One SDK run, as the observability dashboard needs it."""

    id: str | None
    id_request: str
    latency: int
    error_description: str | None
    flow: str
    used_agents: list[AgentMetric]

    def __init__(self, id_request: str, latency: int, flow: str,
                 used_agents: list[AgentMetric] | None = None,
                 error_description: str | None = None, id: str | None = None):
        self.id = id
        self.id_request = id_request
        self.latency = latency
        self.error_description = error_description
        self.flow = flow
        self.used_agents = list(used_agents or [])
