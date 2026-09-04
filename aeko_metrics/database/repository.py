from aeko_metrics.aeko_metrics import IRepository
from aeko_metrics.database import query as q
from aeko_metrics.entity import AgentMetric, Metric
from shared import Module, logged

COLLECTION = "aeko_metrics"


class Repository(IRepository):
    def __init__(self, db):
        self.db = db

    @logged(Module.DATABASE, "aeko_metrics.create_metric")
    def create_metric(self, metric: Metric) -> Metric:
        try:
            result = self.db[COLLECTION].insert_one(q.create_metric_query(metric))
            metric.id = str(result.inserted_id)
            return metric
        except Exception as e:
            raise RuntimeError(f"Error creating aeko metric in database: {e}")

    @logged(Module.DATABASE, "aeko_metrics.get_all_metrics")
    def get_all_metrics(self) -> list[Metric]:
        try:
            query, projection = q.get_all_metrics_query()
            return [metric_from_data(data) for data in self.db[COLLECTION].find(query, projection)]
        except Exception as e:
            raise RuntimeError(f"Error fetching aeko metrics from database: {e}")


def agent_metric_from_data(data: dict) -> AgentMetric:
    return AgentMetric(
        name=data.get("name", ""),
        input_tokens=data.get("input_tokens", 0),
        output_tokens=data.get("output_tokens", 0),
        llm=data.get("llm", ""),
        used_tools=data.get("used_tools", []),
    )


def metric_from_data(data: dict) -> Metric:
    """Defaults rather than `data[...]`, for the reason its sibling has them:
    a dashboard that stops answering because one old row predates a field is
    worse than a row with a blank in it."""
    return Metric(
        id=str(data.get("_id")) if data.get("_id") is not None else None,
        id_request=data.get("id_request", ""),
        latency=data.get("latency", 0),
        error_description=data.get("error_description"),
        flow=data.get("flow", ""),
        used_agents=[agent_metric_from_data(agent) for agent in data.get("used_agents", [])],
    )
