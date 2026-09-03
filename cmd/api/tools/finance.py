"""Whether an improvement pays for itself, and when — for the improvement coordinator.

This module never imports `aeko` — `cmd/api/main.py` is the single entry point
for the SDK (see `test_only_the_entry_point_imports_the_sdk`), so the wrapping
into an `AekoTool` happens there. What this module hands back is plain
LangChain `Tool` objects, exactly like its neighbour `calculator.py`.

Like the calculator there is nothing on the other end: no child process as in
`cmd/api/mcp/`, no REST call as in `cmd/api/integrations/`. Unlike it, this one
goes to a single agent. Every agent quotes numbers, but only the "Coordenador
de Melhoria Contínua" proposes spending money, and these two tools answer the
two questions that proposal is judged by: is the return worth the capex, and
how long until the capex is back.

The two tools rather than one
-----------------------------
`calculate_roi` and `calculate_payback` share every step but the last, and
they are still two tools because they are two decisions. ROI ranks proposals
against each other; payback answers whether the company can wait that long,
and a project can be excellent on the first and unacceptable on the second.
Splitting them lets the agent ask the question it actually has, and the shared
work is `_parse_request` and `_present_values` below, called by both.

The arithmetic
--------------
Money in month 60 is not money today, so every flow is discounted by the
monthly WACC before anything is compared to the capex::

    VP(Ft)   = Ft / (1 + WACC_mensal) ** t          t = 1 for the first month
    VP_Total = Σ VP(Ft), t = 1..60
    VPL      = VP_Total - CAPEX
    ROI      = (VPL / CAPEX) * 100
    Payback  = first t where Σ VP(Fi), i = 1..t, is at least CAPEX
    Viable   = CAPEX <= VP_Total

The horizon is fixed at 60 months (`ROI_HORIZON_MONTHS`) and the agent does not
choose it: two proposals compared over different horizons are not comparable,
and the whole point of the ROI is to put them side by side. A project that has
not paid the capex back inside those months answers -1 rather than a month
number, because "later than 60" is what is actually known.

Why the request is validated before it is calculated
----------------------------------------------------
The input is written by a language model, and every field here changes the
answer silently when it is wrong: an annual WACC sent as a monthly one turns a
viable project into a rejected one, and a capex of zero is a division by zero
one step later. So each field is checked and refused by name — the same
contract as `_parse_estimate_request` in
`cmd/api/integrations/climatiq_api.py`, because the caller reading the refusal
is an agent writing the next attempt from it.
"""

import json
import math
from typing import Any

from langchain_core.tools import Tool

# The window every proposal is judged over, in months. Fixed rather than a
# parameter: an ROI is a comparison, and it stops being one when two answers
# were calculated over different horizons.
ROI_HORIZON_MONTHS = 60

# What the payback answers when the capex is not recovered inside the horizon.
# A month number would be a guess; this says exactly what is known.
ROI_PAYBACK_NOT_RECOVERED = -1

# Money and percentages as they are quoted, applied once at the end — the
# calculation itself runs at full precision. Two places because that is how a
# currency amount is written.
ROI_DECIMAL_PLACES = 2

# A monthly rate at or above 1 is 100% a month, which nobody's WACC is: what it
# actually is, every time, is the annual figure sent to a monthly field.
ROI_MAX_WACC_MONTHLY = 1

# The two ways of giving the flows, and exactly one of them travels in a
# request: a list for a project whose months differ, a single number for the
# usual case of a constant monthly saving.
ROI_CASH_FLOW_FIELDS = ("cash_flows", "monthly_cash_flow")

ROI_REQUEST_FIELDS = ("capex", "wacc_monthly", *ROI_CASH_FLOW_FIELDS)

# Written once because both tools take exactly the same request, and an agent
# that learns the shape from one tool must find it unchanged in the other.
ROI_REQUEST_DESCRIPTION = (
    'Input is a JSON object string with "capex" (the initial investment, above '
    'zero), "wacc_monthly" (the monthly discount rate as a decimal, so 0.01 is '
    "1% a month — convert an annual rate before sending it) and exactly one of "
    '"monthly_cash_flow" (one net monthly cash flow, repeated over the '
    f'{ROI_HORIZON_MONTHS} months) or "cash_flows" (the monthly flows in order, '
    f"up to {ROI_HORIZON_MONTHS} of them, months left out counting as zero; a "
    "month that costs money is negative) — for example "
    '\'{"capex": 150000, "wacc_monthly": 0.01, "monthly_cash_flow": 5000}\'. '
    f"Each flow is discounted to its present value over a fixed {ROI_HORIZON_MONTHS}"
    "-month horizon."
)

ROI_DESCRIPTION = (
    "Calculates the return on investment (ROI) of an improvement project. "
    + ROI_REQUEST_DESCRIPTION
    + ' Answers "vp_total" (the present value of all the flows), "vpl" (that '
    'minus the capex), "roi_percent" and "viable" (true when the capex is at '
    "most the present value). Use it to decide whether a proposal is worth "
    "making and to rank proposals against each other."
)

PAYBACK_DESCRIPTION = (
    "Calculates the payback of an improvement project: the first month in "
    "which the discounted cash flows accumulated so far have paid the capex "
    "back. " + ROI_REQUEST_DESCRIPTION + ' Answers "payback_months", which is '
    f"{ROI_PAYBACK_NOT_RECOVERED} when the capex is not recovered within the "
    f"{ROI_HORIZON_MONTHS} months, together with \"vp_total\" and \"viable\". "
    "Use it to say how long the company waits, which is a different question "
    "from whether the project pays — calculate_roi answers that one."
)


def _as_object(request_input: str | dict[str, Any] | None) -> dict[str, Any]:
    """Turn the agent's input into the request object.

    Agents are asked for a JSON object string and also send the object itself;
    both are accepted, mirroring `_as_object` in
    `cmd/api/integrations/climatiq_api.py`. Anything else is refused carrying
    the text the agent actually sent, so it can correct itself instead of
    seeing a bare `JSONDecodeError`.
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


def _number(value: object, field: str) -> int | float:
    """One field that must be a real number, named so the agent can fix it.

    `bool` is excluded although it is an `int` in Python, and `inf`/`nan` are
    excluded although they are `float`s: JSON spells both (`Infinity`, `NaN`)
    and either would travel through the whole calculation without raising,
    coming back out as a confident answer.
    """

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'"{field}" must be a number, got {value!r}.')

    if not math.isfinite(value):
        raise ValueError(f'"{field}" must be a number, got {value!r}.')

    return value


def _parse_capex(request: dict[str, Any]) -> int | float:
    """The initial investment, which the ROI is a proportion of."""

    capex = _number(request.get("capex"), "capex")

    if capex <= 0:
        # `ROI = VPL / CAPEX` divides by this, and an investment of nothing has
        # no return to express as a percentage of it.
        raise ValueError(
            f'"capex" must be the initial investment, above zero, got {capex!r}.'
        )

    return capex


def _parse_wacc(request: dict[str, Any]) -> int | float:
    """The monthly discount rate, and the yearly figure it is so often given as."""

    wacc = _number(request.get("wacc_monthly"), "wacc_monthly")

    if not 0 <= wacc < ROI_MAX_WACC_MONTHLY:
        raise ValueError(
            f'"wacc_monthly" must be the monthly discount rate as a decimal '
            f"between 0 and {ROI_MAX_WACC_MONTHLY} (0.01 is 1% a month), got "
            f"{wacc!r}. An annual rate must be converted before it is sent."
        )

    return wacc


def _parse_cash_flows(request: dict[str, Any]) -> list[int | float]:
    """The flows of the horizon, however the agent chose to write them.

    Both spellings leave here as the same thing: one flow per month of the
    horizon, so nothing downstream has to know which one was sent.
    """

    given = [field for field in ROI_CASH_FLOW_FIELDS if field in request]

    if len(given) != 1:
        # Two spellings of the same months have no rule saying which wins, and
        # none at all is a request with nothing to discount.
        raise ValueError(
            f'The request must carry exactly one of "cash_flows" (the monthly '
            f'flows, up to {ROI_HORIZON_MONTHS}) or "monthly_cash_flow" (one '
            f"flow repeated over the {ROI_HORIZON_MONTHS} months), got "
            f"{' and '.join(given) if given else 'neither'}."
        )

    if given == ["monthly_cash_flow"]:
        flow = _number(request["monthly_cash_flow"], "monthly_cash_flow")
        return [flow] * ROI_HORIZON_MONTHS

    flows = request["cash_flows"]

    if not isinstance(flows, list) or flows == []:
        raise ValueError(
            f'"cash_flows" must be a list of monthly cash flows, oldest first, '
            f"got {flows!r}."
        )

    if len(flows) > ROI_HORIZON_MONTHS:
        raise ValueError(
            f'"cash_flows" must carry at most {ROI_HORIZON_MONTHS} monthly '
            f"flows, one per month of the horizon, got {len(flows)}."
        )

    flows = [_number(flow, f"cash_flows[{month}]") for month, flow in enumerate(flows)]

    # A month the agent did not write is a month without a flow, not a month
    # outside the horizon: the discounting still walks over it.
    return flows + [0] * (ROI_HORIZON_MONTHS - len(flows))


def _parse_request(request_input: str | dict[str, Any] | None) -> dict[str, Any]:
    """Everything both tools need, validated before anything is calculated."""

    request = _as_object(request_input)

    unknown = sorted(set(request) - set(ROI_REQUEST_FIELDS))
    if unknown != []:
        # Named rather than ignored: a field silently dropped is an agent that
        # believes its rate, its horizon or its tax was taken into account.
        raise ValueError(
            f"The request takes no {', '.join(unknown)}. It accepts: "
            f"{', '.join(ROI_REQUEST_FIELDS)}."
        )

    return {
        "capex": _parse_capex(request),
        "wacc_monthly": _parse_wacc(request),
        "cash_flows": _parse_cash_flows(request),
    }


def _present_values(
    cash_flows: list[int | float], wacc_monthly: int | float
) -> list[int | float]:
    """`VP(Ft) = Ft / (1 + WACC_mensal) ** t`, one value per month.

    `t` starts at 1: the first flow arrives a month out and is already worth
    less than its face value. Starting at 0 would count that month as today
    and overstate every project by one month of discounting.
    """

    return [
        flow / (1 + wacc_monthly) ** month
        for month, flow in enumerate(cash_flows, start=1)
    ]


def _round(value: int | float) -> float:
    """A number as it is quoted, once the calculation behind it is finished."""

    return round(value, ROI_DECIMAL_PLACES)


def _payback_month(present_values: list[int | float], capex: int | float) -> int:
    """The first month whose accumulated present value covers the capex.

    Walked month by month rather than solved, because the accumulated value is
    not always growing: a month that costs money takes it back down, and a
    project can cross the capex and fall below it again before the horizon ends.
    """

    accumulated = 0.0

    for month, present_value in enumerate(present_values, start=1):
        accumulated += present_value

        if accumulated >= capex:
            return month

    return ROI_PAYBACK_NOT_RECOVERED


def _calculate_roi(request_input: str | dict[str, Any] | None = "") -> dict[str, Any]:
    """`func` of `calculate_roi`: what the project returns on what it costs."""

    request = _parse_request(request_input)
    capex = request["capex"]

    vp_total = sum(_present_values(request["cash_flows"], request["wacc_monthly"]))
    npv = vp_total - capex

    return {
        "capex": capex,
        "wacc_monthly": request["wacc_monthly"],
        "months": ROI_HORIZON_MONTHS,
        "vp_total": _round(vp_total),
        "vpl": _round(npv),
        "roi_percent": _round(npv / capex * 100),
        # Compared before rounding: a project that covers its capex to the cent
        # is viable, and `CAPEX <= VP_Total` puts the boundary on that side.
        "viable": capex <= vp_total,
    }


def _calculate_payback(
    request_input: str | dict[str, Any] | None = "",
) -> dict[str, Any]:
    """`func` of `calculate_payback`: the month the capex is back."""

    request = _parse_request(request_input)
    capex = request["capex"]

    present_values = _present_values(request["cash_flows"], request["wacc_monthly"])
    vp_total = sum(present_values)

    return {
        "capex": capex,
        "wacc_monthly": request["wacc_monthly"],
        "months": ROI_HORIZON_MONTHS,
        "vp_total": _round(vp_total),
        "payback_months": _payback_month(present_values, capex),
        # Kept beside the payback because the two can disagree, in one
        # direction: flows that dip below the capex after covering it answer a
        # payback month and still end the horizon short of viable. The reverse
        # cannot happen — the accumulated value of the last month is `vp_total`,
        # so a payback of -1 always means the capex was never covered.
        "viable": capex <= vp_total,
    }


def get_roi_payback_tools() -> list[Tool]:
    """The two tools of the "Coordenador de Melhoria Contínua", in the order asked.

    Whether the project pays comes first; how long it takes to pay is the
    question that follows it.
    """

    return [
        Tool(
            name="calculate_roi",
            description=ROI_DESCRIPTION,
            func=_calculate_roi,
        ),
        Tool(
            name="calculate_payback",
            description=PAYBACK_DESCRIPTION,
            func=_calculate_payback,
        ),
    ]