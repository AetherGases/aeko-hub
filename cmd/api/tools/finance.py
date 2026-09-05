"""Calculate discounted ROI and payback over a fixed 60-month horizon.

Monthly cash flows are discounted by monthly WACC. ROI is net present value
divided by CAPEX as a percentage. Payback is the first month covering CAPEX,
or -1 when the investment is not recovered within the horizon.
"""

import json
import math
from typing import Any

from langchain_core.tools import Tool

from internal.shared import Module, logged


ROI_HORIZON_MONTHS = 60


ROI_PAYBACK_NOT_RECOVERED = -1


ROI_DECIMAL_PLACES = 2


ROI_MAX_WACC_MONTHLY = 1


ROI_CASH_FLOW_FIELDS = ("cash_flows", "monthly_cash_flow")

ROI_REQUEST_FIELDS = ("capex", "wacc_monthly", *ROI_CASH_FLOW_FIELDS)


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
    """Accept a dictionary or decode a JSON object string, rejecting other input."""

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
    """Validate a real numeric input, rejecting booleans and unsupported values."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'"{field}" must be a number, got {value!r}.')

    if not math.isfinite(value):
        raise ValueError(f'"{field}" must be a number, got {value!r}.')

    return value


def _parse_capex(request: dict[str, Any]) -> int | float:
    """Validate that the initial investment is a positive real amount."""

    capex = _number(request.get("capex"), "capex")

    if capex <= 0:
        raise ValueError(
            f'"capex" must be the initial investment, above zero, got {capex!r}.'
        )

    return capex


def _parse_wacc(request: dict[str, Any]) -> int | float:
    """Validate that monthly WACC is at least zero and less than one."""

    wacc = _number(request.get("wacc_monthly"), "wacc_monthly")

    if not 0 <= wacc < ROI_MAX_WACC_MONTHLY:
        raise ValueError(
            f'"wacc_monthly" must be the monthly discount rate as a decimal '
            f"between 0 and {ROI_MAX_WACC_MONTHLY} (0.01 is 1% a month), got "
            f"{wacc!r}. An annual rate must be converted before it is sent."
        )

    return wacc


def _parse_cash_flows(request: dict[str, Any]) -> list[int | float]:
    """Normalize monthly cash flows to the fixed investment horizon."""

    given = [field for field in ROI_CASH_FLOW_FIELDS if field in request]

    if len(given) != 1:
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

    return flows + [0] * (ROI_HORIZON_MONTHS - len(flows))


def _parse_request(request_input: str | dict[str, Any] | None) -> dict[str, Any]:
    """Validate investment fields and return CAPEX, monthly WACC, and cash flows."""

    request = _as_object(request_input)

    unknown = sorted(set(request) - set(ROI_REQUEST_FIELDS))
    if unknown != []:
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
    """Discount each monthly cash flow to its present value."""

    return [
        flow / (1 + wacc_monthly) ** month
        for month, flow in enumerate(cash_flows, start=1)
    ]


def _round(value: int | float) -> float:
    """Round a final financial result to the configured decimal precision."""

    return round(value, ROI_DECIMAL_PLACES)


def _payback_month(present_values: list[int | float], capex: int | float) -> int:
    """Return the first month covering CAPEX, or -1 if it is not recovered."""

    accumulated = 0.0

    for month, present_value in enumerate(present_values, start=1):
        accumulated += present_value

        if accumulated >= capex:
            return month

    return ROI_PAYBACK_NOT_RECOVERED


@logged(Module.TOOL, "calculate_roi")
def _calculate_roi(request_input: str | dict[str, Any] | None = "") -> dict[str, Any]:
    """Calculate discounted value, net present value, ROI percentage, and viability."""

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

        "viable": capex <= vp_total,
    }


@logged(Module.TOOL, "calculate_payback")
def _calculate_payback(
    request_input: str | dict[str, Any] | None = "",
) -> dict[str, Any]:
    """Calculate discounted payback month, present value, and viability."""

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

        "viable": capex <= vp_total,
    }


def get_roi_payback_tools() -> list[Tool]:
    """Return discounted ROI and payback tools for investment analysis."""

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
