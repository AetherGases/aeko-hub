class AgentMetric:
    """What one agent *invocation* of a run consumed.

    One entry per call, not per agent: the output guardrail sends a draft back
    and the graph runs the same agents again, and a turn that paid for four
    routings is not a turn that paid for one. Collapsing them by name would
    turn the retry loop — the single most expensive thing that can happen to a
    request — into the one thing the rows cannot show.
    """

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
    """One SDK run, as the observability dashboard needs it.

    The sibling of `hub_metrics.entity.Metric`, and deliberately not the same
    row: that one is what the *gateway* did with a request — its status, its
    endpoint — while this is what happened inside the one call that reached the
    agents. A request that spent nine of its ten seconds in a single analyst
    looks, over there, exactly like one that spent them in Mongo.

    `id_request` is the field the two are read together by. Unlike its sibling
    it is *not* the `_id`: `hub_metrics` already stores a row under that value,
    and one identifier cannot be the primary key of two collections. Here Mongo
    assigns the `_id` like it does for every other domain.
    """

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
