"""Build MongoDB filters and documents for SDK run metrics."""

from aeko_metrics.entity import Metric


def create_metric_query(metric: Metric) -> dict:
    """Build a run metric document with a request reference and ordered agent invocations."""

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
    """Return a filter and projection that include all metric documents and fields."""
    return {}, {}
