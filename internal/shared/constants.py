"""Logging formats, status thresholds, and request tracking identifiers.

Load configuration from the repository environment file without overriding process settings.
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

APP_NAME = os.environ["APP_NAME"]

TIMESTAMP_FORMAT = os.environ["TIMESTAMP_FORMAT"]

BLUE = json.loads(os.environ["BLUE"])

RED = json.loads(os.environ["RED"])

RESET = json.loads(os.environ["RESET"])

TRUE_VALUES = set(json.loads(os.environ["TRUE_VALUES"]))

FALSE_VALUES = set(json.loads(os.environ["FALSE_VALUES"]))

CRASHED_STATUS = int(os.environ["CRASHED_STATUS"])

UNKNOWN_ENDPOINT = os.environ["UNKNOWN_ENDPOINT"]

REQUEST_ID_HEADER = os.environ["REQUEST_ID_HEADER"]

_HEADER_NAME = REQUEST_ID_HEADER.encode("ascii")

UVICORN_ACCESS_LOGGER = os.environ["UVICORN_ACCESS_LOGGER"]

INDENT = os.environ["INDENT"]

FAILING_STATUS = int(os.environ["FAILING_STATUS"])
