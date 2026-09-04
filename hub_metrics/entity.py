class Metric:
    """One request, as a dashboard needs it.

    `id` is Mongo's `_id`, and unlike every other entity here it is usually
    known *before* the row is written: it was answered to the caller in the
    `x-request-id` header while the request was still open. The other three
    fields are what the request already told `shared/request_log.py` — the
    difference is that these survive the process.
    """

    id: str | None
    latency: str
    response_status: int
    endpoint: str

    def __init__(self, latency: str, response_status: int, endpoint: str, id: str | None = None):
        self.id = id
        self.latency = latency
        self.response_status = response_status
        self.endpoint = endpoint
