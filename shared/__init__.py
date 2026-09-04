"""Cross-cutting concerns, owned by no package and used by all of them.

Today that is observability, in four files:

* `shared/logger.py` — the shape of a line, and its colour.
* `shared/operation.py` — one record per operation, with its outcome and its
  duration.
* `shared/request_log.py` — the block a request closes with, carrying the
  operations it ran, in place of uvicorn's access line.
* `shared/event_tracking.py` — the one row per request that outlives the
  process, for a dashboard to read. It holds an injected sink rather than a
  domain, which is what keeps the rule below true.

Like every module outside `cmd/api/main.py`, this package never imports `aeko`.
And, like the two above it, it never imports one of this application's own
domains either: everything here is imported *by* them.
"""

from shared.event_tracking import (
    CRASHED_STATUS,
    REQUEST_ID_HEADER,
    Event,
    answer_with_id_request,
    endpoint_of,
    new_id_request,
    record_event,
    set_event_sink,
)
from shared.logger import (
    APP_NAME,
    BLUE,
    COLOR_ENV_VAR,
    RED,
    RESET,
    TIMESTAMP_FORMAT,
    Module,
    color_enabled,
    elapsed_since,
    format_entry,
    log_failure,
    log_success,
    paint,
    write,
)
from shared.operation import logged, operation
from shared.request_log import (
    STREAM_ENV_VAR,
    Record,
    RequestLogMiddleware,
    silence_uvicorn_access_log,
    streaming,
)

__all__ = [
    "APP_NAME",
    "BLUE",
    "COLOR_ENV_VAR",
    "CRASHED_STATUS",
    "Event",
    "Module",
    "RED",
    "REQUEST_ID_HEADER",
    "RESET",
    "STREAM_ENV_VAR",
    "Record",
    "RequestLogMiddleware",
    "TIMESTAMP_FORMAT",
    "answer_with_id_request",
    "color_enabled",
    "elapsed_since",
    "endpoint_of",
    "format_entry",
    "log_failure",
    "log_success",
    "logged",
    "new_id_request",
    "operation",
    "paint",
    "record_event",
    "set_event_sink",
    "silence_uvicorn_access_log",
    "streaming",
    "write",
]
