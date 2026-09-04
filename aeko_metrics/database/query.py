from aeko_metrics.entity import Metric


def create_metric_query(metric: Metric) -> dict:
    """The document itself, and never an `_id`.

    The one difference from `hub_metrics`, which stores its row under the
    identifier the caller was answered with: that value is already the primary
    key of a row over there, and two collections cannot own one. Here the
    request is a *field*, so both bases can be read by it, and the `_id` is
    Mongo's — the same arrangement every other domain in this API has.

    The agents are stored in call order, one entry per invocation, because that
    order is what the guardrail's retry loop looks like from the outside.
    """

    return {
        "id_request": metric.id_request,
        "latency": metric.latency,
        "error_description": metric.error_description,
        "flow": metric.flow,
        "used_agents": [
            {
                "name": agent.name,
                "input_tokens": agent.input_tokens,
                "output_tokens": agent.output_tokens,
                "llm": agent.llm,
                "used_tools": list(agent.used_tools),
            }
            for agent in metric.used_agents
        ],
    }


def get_all_metrics_query() -> tuple[dict, dict]:
    """Every row, every field: the dashboard is the one reading this."""
    return {}, {}
