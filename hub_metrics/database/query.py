from hub_metrics.entity import Metric
from internal.database.object_id import normalize_id


def create_metric_query(metric: Metric) -> dict:
    """The document itself, `_id` included when the request already has one.

    Included, unlike every sibling domain, because this identifier was not
    invented after the write: it was answered to the caller in the
    `x-request-id` header while the request was still open, and the row has to
    be findable under exactly that value. It is stored as an `ObjectId` so the
    collection has the `_id` every other collection here has.

    A metric that arrives without one still writes — Mongo assigns it, and the
    row is worth more than the identifier nobody was given.
    """

    document = {
        "latency": metric.latency,
        "response_status": metric.response_status,
        "endpoint": metric.endpoint,
    }

    if metric.id is not None:
        document["_id"] = normalize_id(metric.id)

    return document


def get_all_metrics_query() -> tuple[dict, dict]:
    """Every row, every field: the dashboard is the one reading this."""
    return {}, {}
