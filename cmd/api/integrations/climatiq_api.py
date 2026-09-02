"""Turns Climatiq's emission factor API into LangChain tools for the pollutant analyst.

This module never imports `aeko` — `cmd/api/main.py` is the single entry
point for the SDK (see `test_only_the_entry_point_imports_the_sdk`), so the
wrapping into an `AekoTool` happens there. What this module hands back is
plain LangChain `Tool` objects, exactly like the MCP integrations next door.

What is different is the transport: two documented, versioned REST endpoints
reached with `requests`, rather than a child process speaking MCP. Climatiq
publishes no MCP server of its own, and this project has already been broken
twice by a third-party MCP package changing its tool schema underneath us.

Which endpoints, and why not the AI ones
----------------------------------------
This started on Climatiq's Mapping Agent (`/mapping-agent/v1/*`), the AI that
reads a free-text activity and picks the emission factor itself. That surface
is paid: our key answered 403, which Climatiq defines as a valid key used for
an operation it is not entitled to — not a bad key (401), not a bad request
(400), not an exhausted quota (429). Without a paid plan the API is limited to
general search and general estimates, which is what these two tools use:

* `climatiq_search` — `GET /data/v1/search`. Free-text in, candidate emission
  factors out, each with the `activity_id` and `unit_type` the estimate needs.
* `climatiq_estimate` — `POST /data/v1/estimate`. One `activity_id` plus how
  much of the activity, back comes kg CO2e.

What was lost with the Mapping Agent is the automatic text-to-factor matching.
That step now happens between the two calls, in the agent — which is a language
model, so choosing the row that matches "cimento portland" is work it is
already good at. What it must not do is the arithmetic, and it does not: the
factor is applied by Climatiq, in the second call.
"""

import json
import os
from typing import Any

import requests
from langchain_core.tools import Tool

CLIMATIQ_API_KEY_ENV_VAR = "CLIMATIQ_API_KEY"

# Versioned in the path by Climatiq itself, which is what makes pinning a
# package unnecessary here: `v1` cannot change its schema underneath us.
CLIMATIQ_BASE_URL = "https://api.climatiq.io/data/v1"
CLIMATIQ_SEARCH_URL = f"{CLIMATIQ_BASE_URL}/search"
CLIMATIQ_ESTIMATE_URL = f"{CLIMATIQ_BASE_URL}/estimate"

# The data release, which both endpoints require and the agent never chooses.
# The caret is Climatiq's own production recommendation: it takes corrections
# that stay compatible with release 37, and never a change that would break the
# request. Moving to 38 is a line and a test, reviewable in a diff — the same
# reasoning as the pinned MCP packages in `cmd/api/mcp/`.
CLIMATIQ_DATA_VERSION = "^37"

# A tool call happens inside the agent's turn, and a request with no timeout
# waits forever by default in `requests` — the user would watch the chat hang.
CLIMATIQ_REQUEST_TIMEOUT = 60.0

# Climatiq allows 500 per page. Five is what an analyst can actually weigh, and
# every extra factor is context spent on rows nobody chose.
CLIMATIQ_RESULTS_PER_PAGE = 5

# The `emission_factor` selector's optional fields — everything that narrows
# *which* factor is used. They travel inside the selector, not beside it.
CLIMATIQ_SELECTOR_FIELDS = (
    "source",
    "source_dataset",
    "region",
    "region_fallback",
    "year",
    "year_fallback",
    "scope",
    "source_lca_activity",
    "calculation_method",
)

# Optional fields of the estimate itself. `apply_inflation_adjustment` restates
# the money spent in another year's terms, so it qualifies the activity data
# rather than the factor, and Climatiq takes it at the top level.
CLIMATIQ_ESTIMATE_FIELDS = ("apply_inflation_adjustment",)

CLIMATIQ_SEARCH_DESCRIPTION = (
    "Searches Climatiq's emission factor database for a material, product, "
    "fuel or activity. Input is the description in plain text (e.g. 'cimento "
    "portland'). Returns candidate emission factors, each with its "
    "'activity_id', its 'unit_type' (which says whether it is measured by "
    "weight, money, energy or distance), its region and its year. Use this "
    "first to find the right factor, then pass the chosen 'activity_id' to "
    "climatiq_estimate to get the emissions."
)
CLIMATIQ_ESTIMATE_DESCRIPTION = (
    "Calculates the carbon emissions of an activity, using an emission factor "
    "found with climatiq_search. Input is a JSON object string with "
    '"activity_id" (from the search results) and "parameters" (how much of '
    "the activity, as the value and its unit) — for example "
    '\'{"activity_id": "building_materials-type_cement", "parameters": '
    '{"weight": 100, "weight_unit": "t"}}\'. The parameter name must match the '
    "factor's unit_type: weight/weight_unit, money/money_unit, "
    'energy/energy_unit or distance/distance_unit. Optional: "region", '
    '"year", "source", "region_fallback", "year_fallback". Returns kg CO2e '
    "together with the emission factor that produced it."
)


class ClimatiqError(RuntimeError):
    """Raised when a call to the Climatiq API cannot be completed."""


def _api_key(api_key: str | None = None) -> str:
    """The Climatiq credential, from the caller or the environment."""

    if api_key is None:
        api_key = os.environ.get(CLIMATIQ_API_KEY_ENV_VAR, "")

    if api_key == "":
        raise RuntimeError(
            f"{CLIMATIQ_API_KEY_ENV_VAR} is not set. Please set it in the environment or pass it to _request()."
        )

    return api_key


def _error_detail(response: Any) -> str:
    """What Climatiq said about a failure, in the shape its docs promise.

    A failure between us and Climatiq — a proxy, a gateway — answers HTML
    rather than the documented `error_code`/`message` body, so the raw text is
    the fallback. Either way the agent sees something it can act on.
    """

    try:
        body = response.json()
    except ValueError:
        return response.text.strip()

    return " - ".join(
        str(body[field]) for field in ("error_code", "message") if field in body
    ) or response.text.strip()


def _request(method: str, url: str, api_key: str | None = None, **kwargs: Any) -> Any:
    """The one place that talks HTTP, and the one place failures are shaped.

    Every way this can go wrong — no credential, no network, a rejected
    request, an answer that is not JSON — leaves as a single readable error,
    because the caller on the other end is an agent reading the text.
    """

    headers = {"Authorization": f"Bearer {_api_key(api_key)}"}

    try:
        response = requests.request(
            method, url, headers=headers, timeout=CLIMATIQ_REQUEST_TIMEOUT, **kwargs
        )
    except requests.RequestException as exc:
        raise ClimatiqError(f"Could not reach the Climatiq API at {url}: {exc}") from exc

    if response.status_code >= 400:
        raise ClimatiqError(
            f"The Climatiq API answered {response.status_code} for {url}: "
            f"{_error_detail(response)}"
        )

    try:
        return response.json()
    except ValueError as exc:
        raise ClimatiqError(
            f"The Climatiq API answered {response.status_code} for {url} with "
            f"something that is not JSON: {response.text.strip()!r}"
        ) from exc


def _as_object(request_input: str | dict[str, Any] | None) -> dict[str, Any]:
    """Turn the agent's input into the JSON object the endpoint takes.

    Agents are asked for a JSON object string and also send the object itself;
    both are accepted, mirroring `_parse_filter` in `cmd/api/mcp/mongo_mcp.py`.
    Anything else is rejected carrying the text the agent actually sent, so it
    can correct itself instead of seeing a bare `JSONDecodeError`.
    """

    if isinstance(request_input, dict):
        return request_input

    if not isinstance(request_input, str) or request_input.strip() == "":
        raise ValueError(
            f"The request must be a JSON object string, got {request_input!r}."
        )

    try:
        parsed = json.loads(request_input)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"The request must be a JSON object string, got {request_input!r}."
        ) from exc

    if not isinstance(parsed, dict):
        raise ValueError(
            f"The request must be a JSON object string, got {request_input!r}."
        )

    return parsed


def _parse_search_query(query: str | None) -> str:
    """The free text `/search` matches emission factors against.

    An empty search has no sensible default, so it is rejected here rather
    than spending a request to be told the same thing.
    """

    if not isinstance(query, str) or query.strip() == "":
        raise ValueError(
            f"The query must be the activity or material to look up, got {query!r}."
        )

    return query.strip()


def _parse_estimate_request(request_input: str | dict[str, Any] | None) -> dict[str, Any]:
    """Validate the agent's input and build the `/estimate` body from it.

    Built rather than forwarded: the payload that reaches Climatiq carries only
    fields Climatiq documents, in the two places it expects them — the factor
    selector and the estimate itself — whatever the agent decided to attach.
    """

    request = _as_object(request_input)

    activity_id = request.get("activity_id")
    if not isinstance(activity_id, str) or activity_id.strip() == "":
        # Free text belongs to `climatiq_search`, one step earlier: this
        # endpoint matches nothing itself, which is what the Mapping Agent did
        # and what our plan does not include.
        raise ValueError(
            f'"activity_id" must be an emission factor id from climatiq_search, '
            f"got {activity_id!r}."
        )

    parameters = request.get("parameters")
    if not isinstance(parameters, dict) or parameters == {}:
        raise ValueError(
            f'"parameters" must carry the quantity and its unit (for example '
            f'{{"weight": 100, "weight_unit": "t"}}), got {parameters!r}.'
        )

    known = {"activity_id", "parameters", *CLIMATIQ_SELECTOR_FIELDS, *CLIMATIQ_ESTIMATE_FIELDS}
    unknown = sorted(set(request) - known)
    if unknown != []:
        accepted = ", ".join((*CLIMATIQ_SELECTOR_FIELDS, *CLIMATIQ_ESTIMATE_FIELDS))
        raise ValueError(
            f"The Climatiq estimate takes no {', '.join(unknown)}. Besides "
            f'"activity_id" and "parameters" it accepts: {accepted}.'
        )

    selector: dict[str, Any] = {
        "activity_id": activity_id.strip(),
        "data_version": CLIMATIQ_DATA_VERSION,
    }
    selector.update(
        {field: request[field] for field in CLIMATIQ_SELECTOR_FIELDS if field in request}
    )

    payload: dict[str, Any] = {"emission_factor": selector, "parameters": parameters}
    payload.update(
        {field: request[field] for field in CLIMATIQ_ESTIMATE_FIELDS if field in request}
    )

    return payload


def _climatiq_search(query: str | None = "") -> Any:
    """The emission factors Climatiq has for a material, without calculating."""

    return _request(
        "GET",
        CLIMATIQ_SEARCH_URL,
        params={
            "data_version": CLIMATIQ_DATA_VERSION,
            "query": _parse_search_query(query),
            "results_per_page": CLIMATIQ_RESULTS_PER_PAGE,
        },
    )


def _climatiq_estimate(request_input: str | dict[str, Any] | None = "") -> Any:
    """Emissions for one activity, from an emission factor the agent chose."""

    return _request("POST", CLIMATIQ_ESTIMATE_URL, json=_parse_estimate_request(request_input))


def get_climatiq_tools() -> list[Tool]:
    """Climatiq's factor search and calculator, for the "Analista de Poluentes".

    In workflow order: the agent searches for the factor, then estimates with
    the one it chose.
    """

    return [
        Tool(
            name="climatiq_search",
            description=CLIMATIQ_SEARCH_DESCRIPTION,
            func=_climatiq_search,
        ),
        Tool(
            name="climatiq_estimate",
            description=CLIMATIQ_ESTIMATE_DESCRIPTION,
            func=_climatiq_estimate,
        ),
    ]
