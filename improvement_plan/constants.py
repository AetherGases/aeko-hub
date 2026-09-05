"""Improvement-plan analysis configuration.

Load configuration from the repository environment file without overriding process settings.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

PREVIOUS_PLANS_FOR_CONTEXT = int(os.environ["PREVIOUS_PLANS_FOR_CONTEXT"])
