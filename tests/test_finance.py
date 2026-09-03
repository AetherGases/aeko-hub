"""Tests for the ROI and payback tools.

`cmd/api/tools/finance.py` gives the "Coordenador de Melhoria Contínua"
the two questions asked of every improvement proposal: is the money worth
committing, and when does it come back. It is the second module in
`cmd/api/tools/`, the package for tools that are neither an MCP server
(`cmd/api/mcp/`) nor a vendor's REST API (`cmd/api/integrations/`): no child
process, no network, only Python. Like every module in the three packages it
never imports `aeko` (see `test_only_the_entry_point_imports_the_sdk` in
`test_e2e.py`) — it hands back plain LangChain `Tool` objects and
`cmd/api/main.py` wraps them as `AekoTool`.

The arithmetic under test is the specification's, not an approximation of it:

    VP(Ft)  = Ft / (1 + WACC_mensal) ** t
    VP_Tot  = Σ VP(Ft), t = 1..60
    VPL     = VP_Total - CAPEX
    ROI     = (VPL / CAPEX) * 100
    Payback = first t where Σ VP(Fi), i = 1..t, is at least CAPEX (-1 if none)
    Viable  = CAPEX <= VP_Total

Most cases below use a monthly WACC of 0.25, because 1.25 and 1.5625 divide
the flows exactly: the expected present values are whole numbers written in
the test rather than the same formula restated, which is what makes them an
independent check.

Concerns:

* `_parse_request` — what the agent sent, before anything is calculated: the
  capex, the rate, and the two mutually exclusive ways of giving the flows.
* `_present_values` — the discounting itself, one factor per month.
* `_calculate_roi` — `func` of the first tool: VP_Total, VPL, ROI, viability.
* `_calculate_payback` — `func` of the second: the first month that pays the
  capex back, and the -1 that says it never happens.
* `get_roi_payback_tools` — the two LangChain `Tool` objects the agent gets.
"""

import json

import pytest
from langchain_core.tools import Tool

from cmd.api.tools import finance

# Capex 150 against flows worth 100 + 100 in present value: viable, paid back
# in the second month, and every number in the answer is exact.
VIABLE_REQUEST = {"capex": 150, "wacc_monthly": 0.25, "cash_flows": [125, 156.25]}


def request_without(field, **overrides):
    """The valid request with one field taken out, for the "missing" cases."""
    request = {key: value for key, value in VIABLE_REQUEST.items() if key != field}
    request.update(overrides)
    return request


# ---------------------------------------------------------------------------
# _parse_request: the request as a whole
# ---------------------------------------------------------------------------
def test_parse_request_reads_a_json_object_string():
    assert finance._parse_request(json.dumps(VIABLE_REQUEST)) == {
        "capex": 150,
        "wacc_monthly": 0.25,
        "cash_flows": [125, 156.25] + [0] * 58,
    }


def test_parse_request_also_takes_the_object_itself():
    """Agents send the object as often as the string, as with Climatiq next door."""
    assert finance._parse_request(dict(VIABLE_REQUEST))["capex"] == 150


@pytest.mark.parametrize(
    "request_input",
    ["", "   ", None, 42, ["capex"], "capex: 150", "[150, 0.25]", '"150"'],
)
def test_parse_request_rejects_anything_that_is_not_a_json_object(request_input):
    with pytest.raises(ValueError) as error:
        finance._parse_request(request_input)

    assert repr(request_input) in str(error.value)


def test_parse_request_rejects_a_field_it_does_not_know_naming_it():
    """The agent corrects the field it invented instead of seeing it ignored."""
    with pytest.raises(ValueError) as error:
        finance._parse_request(dict(VIABLE_REQUEST, discount_rate=0.1, tax=0.3))

    assert "discount_rate" in str(error.value)
    assert "tax" in str(error.value)


# ---------------------------------------------------------------------------
# _parse_request: capex
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("capex", [None, "150", True, [150], float("inf"), float("nan")])
def test_parse_request_rejects_a_capex_that_is_not_a_real_number(capex):
    with pytest.raises(ValueError) as error:
        finance._parse_request(request_without("capex", capex=capex))

    assert "capex" in str(error.value)


@pytest.mark.parametrize("capex", [0, -1, -0.5])
def test_parse_request_rejects_a_capex_that_is_not_above_zero(capex):
    """ROI divides by the capex, and an investment of nothing has no return."""
    with pytest.raises(ValueError) as error:
        finance._parse_request(request_without("capex", capex=capex))

    assert "capex" in str(error.value)


def test_parse_request_keeps_the_capex_as_it_was_given():
    parsed = finance._parse_request(request_without("capex", capex=1234.56))

    assert parsed["capex"] == 1234.56


# ---------------------------------------------------------------------------
# _parse_request: wacc_monthly
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("wacc", [None, "0.01", True, float("inf")])
def test_parse_request_rejects_a_wacc_that_is_not_a_real_number(wacc):
    with pytest.raises(ValueError) as error:
        finance._parse_request(request_without("wacc_monthly", wacc_monthly=wacc))

    assert "wacc_monthly" in str(error.value)


@pytest.mark.parametrize("wacc", [-0.01, 1, 1.5, 12])
def test_parse_request_rejects_a_wacc_outside_the_monthly_range(wacc):
    """A rate at or above 1 is an annual figure sent as a monthly one."""
    with pytest.raises(ValueError) as error:
        finance._parse_request(request_without("wacc_monthly", wacc_monthly=wacc))

    assert "wacc_monthly" in str(error.value)


def test_parse_request_accepts_a_wacc_of_zero():
    """No discounting is a real answer, not a missing one: the flows count whole."""
    parsed = finance._parse_request(request_without("wacc_monthly", wacc_monthly=0))

    assert parsed["wacc_monthly"] == 0


# ---------------------------------------------------------------------------
# _parse_request: the cash flows
# ---------------------------------------------------------------------------
def test_parse_request_pads_a_short_list_of_flows_to_the_horizon():
    """Months the agent left out are months without a flow, not months without a place."""
    parsed = finance._parse_request(request_without("cash_flows", cash_flows=[125, 156.25]))

    assert len(parsed["cash_flows"]) == finance.ROI_HORIZON_MONTHS
    assert parsed["cash_flows"][:2] == [125, 156.25]
    assert set(parsed["cash_flows"][2:]) == {0}


def test_parse_request_repeats_a_single_monthly_flow_over_the_horizon():
    parsed = finance._parse_request(request_without("cash_flows", monthly_cash_flow=5000))

    assert parsed["cash_flows"] == [5000] * finance.ROI_HORIZON_MONTHS


def test_parse_request_accepts_a_full_horizon_of_flows():
    flows = list(range(1, finance.ROI_HORIZON_MONTHS + 1))

    parsed = finance._parse_request(request_without("cash_flows", cash_flows=flows))

    assert parsed["cash_flows"] == flows


def test_parse_request_accepts_a_negative_flow():
    """A month can cost money — an overhaul, a replaced part — and still be a month."""
    parsed = finance._parse_request(request_without("cash_flows", cash_flows=[-500, 125]))

    assert parsed["cash_flows"][:2] == [-500, 125]


def test_parse_request_rejects_both_ways_of_giving_the_flows_at_once():
    """Two answers to the same question, and no rule says which one wins."""
    with pytest.raises(ValueError) as error:
        finance._parse_request(dict(VIABLE_REQUEST, monthly_cash_flow=5000))

    assert "cash_flows" in str(error.value)
    assert "monthly_cash_flow" in str(error.value)


def test_parse_request_rejects_a_request_with_no_flows_at_all():
    with pytest.raises(ValueError) as error:
        finance._parse_request(request_without("cash_flows"))

    assert "cash_flows" in str(error.value)
    assert "monthly_cash_flow" in str(error.value)


@pytest.mark.parametrize("flows", [[], "125, 156.25", 125, {"1": 125}])
def test_parse_request_rejects_flows_that_are_not_a_non_empty_list(flows):
    with pytest.raises(ValueError) as error:
        finance._parse_request(request_without("cash_flows", cash_flows=flows))

    assert "cash_flows" in str(error.value)


def test_parse_request_rejects_more_flows_than_months_in_the_horizon():
    flows = [1] * (finance.ROI_HORIZON_MONTHS + 1)

    with pytest.raises(ValueError) as error:
        finance._parse_request(request_without("cash_flows", cash_flows=flows))

    assert str(finance.ROI_HORIZON_MONTHS) in str(error.value)


@pytest.mark.parametrize("flow", ["125", None, True, [125], float("inf")])
def test_parse_request_rejects_a_flow_that_is_not_a_real_number(flow):
    with pytest.raises(ValueError) as error:
        finance._parse_request(request_without("cash_flows", cash_flows=[125, flow]))

    assert "cash_flows" in str(error.value)


@pytest.mark.parametrize("flow", ["5000", None, True])
def test_parse_request_rejects_a_single_monthly_flow_that_is_not_a_number(flow):
    with pytest.raises(ValueError) as error:
        finance._parse_request(request_without("cash_flows", monthly_cash_flow=flow))

    assert "monthly_cash_flow" in str(error.value)


# ---------------------------------------------------------------------------
# _present_values: VP(Ft) = Ft / (1 + WACC_mensal) ** t
# ---------------------------------------------------------------------------
def test_present_values_discounts_each_month_by_its_own_factor():
    """1.25 and 1.5625 divide these flows exactly, so the answer is written out."""
    assert finance._present_values([125, 156.25], 0.25) == [100.0, 100.0]


def test_present_values_starts_the_exponent_at_the_first_month():
    """t = 1 for the first flow: a flow one month out is already discounted."""
    assert finance._present_values([125], 0.25) == [100.0]


def test_present_values_leaves_the_flows_alone_when_the_wacc_is_zero():
    assert finance._present_values([100, 200, 300], 0) == [100, 200, 300]


def test_present_values_discounts_a_negative_flow_the_same_way():
    assert finance._present_values([-125], 0.25) == [-100.0]


def test_present_values_of_no_flows_is_no_present_values():
    assert finance._present_values([], 0.25) == []


def test_present_values_matches_the_formula_over_the_whole_horizon():
    flows = [1000] * finance.ROI_HORIZON_MONTHS

    present_values = finance._present_values(flows, 0.01)

    assert present_values == pytest.approx(
        [1000 / 1.01**month for month in range(1, finance.ROI_HORIZON_MONTHS + 1)]
    )


# ---------------------------------------------------------------------------
# _calculate_roi
# ---------------------------------------------------------------------------
def test_calculate_roi_answers_the_whole_calculation():
    """150 invested against 200 in present value: VPL 50, a third of the capex back."""
    assert finance._calculate_roi(json.dumps(VIABLE_REQUEST)) == {
        "capex": 150,
        "wacc_monthly": 0.25,
        "months": finance.ROI_HORIZON_MONTHS,
        "vp_total": 200.0,
        "vpl": 50.0,
        "roi_percent": 33.33,
        "viable": True,
    }


def test_calculate_roi_reports_a_project_that_does_not_pay_for_itself():
    answer = finance._calculate_roi(dict(VIABLE_REQUEST, capex=250))

    assert answer["vpl"] == -50.0
    assert answer["roi_percent"] == -20.0
    assert answer["viable"] is False


def test_calculate_roi_calls_a_project_viable_when_the_capex_is_matched_exactly():
    """`CAPEX <= VP_Total` — the boundary belongs to the viable side."""
    answer = finance._calculate_roi({"capex": 100, "wacc_monthly": 0.25, "cash_flows": [125]})

    assert answer["vp_total"] == 100.0
    assert answer["roi_percent"] == 0.0
    assert answer["viable"] is True


def test_calculate_roi_discounts_over_sixty_months_and_not_the_months_given():
    """One flow written, sixty months calculated: the horizon is the tool's, not the agent's."""
    answer = finance._calculate_roi(
        {"capex": 150000, "wacc_monthly": 0.01, "monthly_cash_flow": 5000}
    )
    expected = sum(5000 / 1.01**month for month in range(1, 61))

    assert answer["months"] == 60
    assert answer["vp_total"] == pytest.approx(round(expected, 2))
    assert answer["vpl"] == pytest.approx(round(expected - 150000, 2))
    assert answer["viable"] is True


def test_calculate_roi_rounds_the_money_it_reports():
    """The calculation runs at full precision; only what is quoted is rounded."""
    answer = finance._calculate_roi(
        {"capex": 1000, "wacc_monthly": 0.01, "cash_flows": [333.333]}
    )

    assert answer["vp_total"] == 330.03
    assert answer["vpl"] == -669.97


def test_calculate_roi_refuses_a_request_it_cannot_read():
    with pytest.raises(ValueError) as error:
        finance._calculate_roi("{}")

    assert "capex" in str(error.value)


# ---------------------------------------------------------------------------
# _calculate_payback
# ---------------------------------------------------------------------------
def test_calculate_payback_answers_the_first_month_that_covers_the_capex():
    """100 accumulated in month 1 is not 150; 200 in month 2 is."""
    assert finance._calculate_payback(json.dumps(VIABLE_REQUEST)) == {
        "capex": 150,
        "wacc_monthly": 0.25,
        "months": finance.ROI_HORIZON_MONTHS,
        "vp_total": 200.0,
        "payback_months": 2,
        "viable": True,
    }


def test_calculate_payback_counts_a_month_that_matches_the_capex_exactly():
    """`VP_Acumulado(t) >= CAPEX` — again the boundary counts as recovered."""
    answer = finance._calculate_payback(
        {"capex": 100, "wacc_monthly": 0.25, "cash_flows": [125]}
    )

    assert answer["payback_months"] == 1


def test_calculate_payback_answers_minus_one_when_the_capex_never_comes_back():
    answer = finance._calculate_payback(dict(VIABLE_REQUEST, capex=250))

    assert answer["payback_months"] == finance.ROI_PAYBACK_NOT_RECOVERED
    assert answer["payback_months"] == -1
    assert answer["viable"] is False


def test_calculate_payback_does_not_discount_when_the_wacc_is_zero():
    answer = finance._calculate_payback(
        {"capex": 250, "wacc_monthly": 0, "cash_flows": [100, 200, 300]}
    )

    assert answer["payback_months"] == 2
    assert answer["vp_total"] == 600.0


def test_calculate_payback_waits_for_the_accumulated_value_and_not_the_monthly_one():
    """No single month covers the capex; the third month together with the first two does."""
    answer = finance._calculate_payback(
        {"capex": 290, "wacc_monthly": 0, "cash_flows": [100, 100, 100]}
    )

    assert answer["payback_months"] == 3


def test_calculate_payback_reaches_the_last_month_of_the_horizon():
    """The month a constant flow pays 150000 back, counted the long way."""
    answer = finance._calculate_payback(
        {"capex": 150000, "wacc_monthly": 0.01, "monthly_cash_flow": 5000}
    )
    accumulated = 0.0
    expected = -1
    for month in range(1, 61):
        accumulated += 5000 / 1.01**month
        if accumulated >= 150000:
            expected = month
            break

    assert answer["payback_months"] == expected


def test_calculate_payback_can_find_a_month_in_a_project_that_is_not_viable():
    """The one way the two answers disagree: paid back in month 30, short by month 60.

    A month that costs money takes the accumulated value back below the capex
    after it had already covered it. The disagreement only goes this way — a
    payback of -1 means the accumulated value never reached the capex, and the
    accumulated value of the last month is the `vp_total` viability compares.
    """
    flows = [200] * 30 + [-6000] + [200] * 29

    answer = finance._calculate_payback(
        {"capex": 5900, "wacc_monthly": 0, "cash_flows": flows}
    )

    assert answer["payback_months"] == 30
    assert answer["vp_total"] == 5800.0
    assert answer["viable"] is False


def test_calculate_payback_refuses_a_request_it_cannot_read():
    with pytest.raises(ValueError) as error:
        finance._calculate_payback("{}")

    assert "capex" in str(error.value)


# ---------------------------------------------------------------------------
# get_roi_payback_tools
# ---------------------------------------------------------------------------
def test_get_roi_payback_tools_returns_the_two_tools_in_workflow_order():
    tools = finance.get_roi_payback_tools()

    assert [tool.name for tool in tools] == ["calculate_roi", "calculate_payback"]
    assert all(isinstance(tool, Tool) for tool in tools)


def test_the_tools_carry_the_functions_that_calculate():
    roi, payback = finance.get_roi_payback_tools()

    assert roi.func is finance._calculate_roi
    assert payback.func is finance._calculate_payback


def test_the_tool_descriptions_tell_the_agent_what_to_send_and_what_comes_back():
    roi, payback = finance.get_roi_payback_tools()

    for description in (roi.description, payback.description):
        assert "capex" in description
        assert "wacc_monthly" in description
        assert "monthly_cash_flow" in description
        assert str(finance.ROI_HORIZON_MONTHS) in description

    assert "-1" in payback.description


def test_the_tools_calculate_end_to_end_from_the_string_an_agent_writes():
    roi, payback = finance.get_roi_payback_tools()
    request = '{"capex": 150, "wacc_monthly": 0.25, "cash_flows": [125, 156.25]}'

    assert roi.func(request)["roi_percent"] == 33.33
    assert payback.func(request)["payback_months"] == 2
