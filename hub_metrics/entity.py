"""Define the domain entities for HTTP request metrics."""

class Metric:
    """One request, as a dashboard needs it."""

    id: str | None
    latency: str
    response_status: int
    endpoint: str

    def __init__(self, latency: str, response_status: int, endpoint: str, id: str | None = None):
        self.id = id
        self.latency = latency
        self.response_status = response_status
        self.endpoint = endpoint
