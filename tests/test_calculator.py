"""Tests for the calculator tool.

`cmd/api/tools/calculator.py` gives every agent one arithmetic tool. It is the
first module in `cmd/api/tools/`, the package for tools that are neither an MCP
server (`cmd/api/mcp/`) nor a vendor's REST API (`cmd/api/integrations/`):
there is no child process and no network here, only Python. Like both siblings
it never imports `aeko` (see `test_only_the_entry_point_imports_the_sdk` in
`test_e2e.py`) — it hands back a plain LangChain `Tool` and `cmd/api/main.py`
wraps it as an `AekoTool`.

Why an expression evaluator and not `eval`
------------------------------------------
The input is written by a language model, and `eval` on model output is
arbitrary code execution: `__import__('os').system(...)` is one string away.
So the expression is parsed with `ast` and walked against an allowlist — the
arithmetic operators, numeric literals and a handful of maths functions. Every
other node is refused by name, which is what the refusal tests below pin: not
that "it is safe", but that each escape route an agent could take is closed.

The second reason to walk the tree is that an LLM is bad at arithmetic and
good at algebra. It gets to write `(1200 * 2.68) / 1000` and be handed the
number, instead of predicting the digits token by token.

Concerns:

* `_parse_expression` — what the agent typed, before anything parses it.
* `_evaluate` — the allowlist walk itself: what it computes, and what it
  refuses. Given an `ast` node, so the tests build one with `ast.parse`.
* `_calculate` — the tool's `func`: parse, evaluate, format, and turn every
  failure into one message naming the expression the agent sent.
* `get_calculator_tools` — the LangChain `Tool` every agent receives.
"""

import ast

import pytest
from langchain_core.tools import Tool

from cmd.api.tools import calculator


def evaluate(expression):
    """`_evaluate` takes a node, so the tests hand it one."""
    return calculator._evaluate(ast.parse(expression, mode="eval").body)


# ---------------------------------------------------------------------------
# _parse_expression
# ---------------------------------------------------------------------------
def test_parse_expression_drops_surrounding_whitespace():
    assert calculator._parse_expression("  2 + 2  ") == "2 + 2"


def test_parse_expression_accepts_an_expression_spelled_over_several_lines():
    """Agents wrap long sums; the parser reads the newline as whitespace."""
    assert calculator._parse_expression("(1200 * 2.68)\n+ 300") == "(1200 * 2.68)\n+ 300"


@pytest.mark.parametrize("expression", ["", "   ", "\n", None, 42, ["2 + 2"]])
def test_parse_expression_rejects_anything_that_is_not_an_expression(expression):
    with pytest.raises(ValueError) as error:
        calculator._parse_expression(expression)

    assert repr(expression) in str(error.value)


def test_parse_expression_rejects_an_expression_longer_than_the_cap():
    """A model that loops produces one enormous string; parsing it is wasted work."""
    with pytest.raises(ValueError) as error:
        calculator._parse_expression("1+" * calculator.CALCULATOR_MAX_EXPRESSION_LENGTH)

    assert str(calculator.CALCULATOR_MAX_EXPRESSION_LENGTH) in str(error.value)


def test_parse_expression_accepts_an_expression_exactly_at_the_cap():
    expression = "1" * calculator.CALCULATOR_MAX_EXPRESSION_LENGTH

    assert calculator._parse_expression(expression) == expression


# ---------------------------------------------------------------------------
# _evaluate — the arithmetic itself
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "expression,expected",
    [
        ("2 + 3", 5),
        ("10 - 4", 6),
        ("6 * 7", 42),
        ("9 / 2", 4.5),
        ("9 // 2", 4),
        ("9 % 2", 1),
        ("2 ** 10", 1024),
    ],
)
def test_evaluate_computes_every_allowed_operator(expression, expected):
    assert evaluate(expression) == expected


def test_evaluate_respects_precedence_and_parentheses():
    assert evaluate("2 + 3 * 4") == 14
    assert evaluate("(2 + 3) * 4") == 20


def test_evaluate_handles_the_unary_signs():
    assert evaluate("-5") == -5
    assert evaluate("+5") == 5
    assert evaluate("-(2 + 3)") == -5


def test_evaluate_reads_decimals_and_scientific_notation():
    assert evaluate("2.5 * 4") == 10.0
    assert evaluate("1.2e3") == 1200.0


def test_evaluate_computes_an_emission_the_way_an_analyst_writes_it():
    """The shape this tool exists for: activity data times a factor, into tonnes."""
    assert evaluate("(1200 * 2.68) / 1000") == pytest.approx(3.216)


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("abs(-7)", 7),
        ("round(3.14159, 2)", 3.14),
        ("min(4, 2, 9)", 2),
        ("max(4, 2, 9)", 9),
        ("sum([1, 2, 3])", 6),
        ("sqrt(16)", 4.0),
        ("log(100, 10)", pytest.approx(2.0)),
    ],
)
def test_evaluate_computes_every_allowed_function(expression, expected):
    assert evaluate(expression) == expected


def test_evaluate_sums_a_tuple_as_well_as_a_list():
    assert evaluate("sum((1, 2, 3))") == 6


def test_evaluate_nests_functions_inside_arithmetic():
    assert evaluate("round(sum([10.4, 20.6]) / 2, 1)") == 15.5


def test_evaluate_rounds_the_way_python_rounds():
    """`round` breaks a tie towards the even digit, and 15.45 is under the tie
    in binary anyway. Pinned because it surprises whoever reads the number,
    not because it is wrong: this is the arithmetic the tool promises."""
    assert evaluate("round(15.45, 1)") == 15.4


# ---------------------------------------------------------------------------
# _evaluate — what it refuses
# ---------------------------------------------------------------------------
def test_evaluate_refuses_a_bare_name():
    """`eval` would resolve it; the walk has no namespace to resolve it from."""
    with pytest.raises(ValueError) as error:
        evaluate("pi * 2")

    assert "pi" in str(error.value)


def test_evaluate_refuses_an_attribute_lookup():
    """`().__class__` is the first step of every sandbox escape written for `eval`."""
    with pytest.raises(ValueError) as error:
        evaluate("(2).__class__")

    assert "__class__" in str(error.value)


def test_evaluate_refuses_a_function_it_does_not_know():
    with pytest.raises(ValueError) as error:
        evaluate("__import__('os')")

    assert "__import__" in str(error.value)


def test_evaluate_refuses_a_dotted_call():
    with pytest.raises(ValueError) as error:
        evaluate("math.sqrt(2)")

    assert "math.sqrt" in str(error.value)


def test_evaluate_naming_a_refused_function_lists_the_ones_it_knows():
    """The agent can only correct itself if it is told what is on offer."""
    with pytest.raises(ValueError) as error:
        evaluate("factorial(5)")

    message = str(error.value)
    assert all(name in message for name in calculator.CALCULATOR_FUNCTIONS)


def test_evaluate_refuses_keyword_arguments():
    with pytest.raises(ValueError) as error:
        evaluate("round(3.14159, ndigits=2)")

    assert "ndigits" in str(error.value)


@pytest.mark.parametrize(
    "expression",
    [
        "'os'",
        "True",
        "None",
        "[1, 2]",
        "{'a': 1}",
        "{1, 2}",
        "1 if 2 else 3",
        "2 > 1",
        "1 and 2",
        "not 1",
        "1 & 2",
        "[x for x in [1]]",
        "lambda: 1",
        "(y := 2)",
        "f'{1}'",
        "...",
    ],
)
def test_evaluate_refuses_everything_that_is_not_arithmetic(expression):
    with pytest.raises(ValueError):
        evaluate(expression)


def test_evaluate_refuses_a_division_by_zero():
    with pytest.raises(ValueError) as error:
        evaluate("1 / 0")

    assert "zero" in str(error.value)


def test_evaluate_refuses_an_exponent_that_would_not_finish():
    """`9 ** 9 ** 9` is a few characters that hang the worker for hours."""
    with pytest.raises(ValueError) as error:
        evaluate(f"2 ** {calculator.CALCULATOR_MAX_EXPONENT + 1}")

    assert str(calculator.CALCULATOR_MAX_EXPONENT) in str(error.value)


def test_evaluate_allows_an_exponent_at_the_cap():
    assert evaluate(f"1 ** {calculator.CALCULATOR_MAX_EXPONENT}") == 1


def test_evaluate_refuses_a_result_that_left_the_real_numbers():
    """`(-8) ** 0.5` is complex in Python, and means nothing in an inventory."""
    with pytest.raises(ValueError) as error:
        evaluate("(-8) ** 0.5")

    assert "real" in str(error.value)


def test_evaluate_refuses_a_result_too_large_to_represent():
    """Float overflow does not raise in Python — it quietly becomes `inf`."""
    with pytest.raises(ValueError) as error:
        evaluate("1.5e308 * 10")

    assert "large" in str(error.value)


def test_evaluate_refuses_a_power_that_overflows_the_float():
    """This one does raise, below the exponent cap, so it needs its own answer."""
    with pytest.raises(ValueError) as error:
        evaluate("10.0 ** 400")

    assert "large" in str(error.value)


def test_evaluate_refuses_a_maths_call_outside_its_domain():
    with pytest.raises(ValueError) as error:
        evaluate("sqrt(-1)")

    assert "sqrt" in str(error.value)


def test_evaluate_refuses_a_maths_call_with_the_wrong_number_of_arguments():
    with pytest.raises(ValueError) as error:
        evaluate("round(1, 2, 3)")

    assert "round" in str(error.value)


# ---------------------------------------------------------------------------
# _calculate — the tool's own func
# ---------------------------------------------------------------------------
def test_calculate_answers_with_the_number_as_text():
    assert calculator._calculate("2 + 2") == "4"


def test_calculate_hides_binary_floating_point_noise():
    """`1200 * 2.68` is 3216.0000000000005 in binary; no analyst wants to read that."""
    assert calculator._calculate("1200 * 2.68") == "3216"


def test_calculate_keeps_the_decimals_that_carry_meaning():
    assert calculator._calculate("1 / 3") == "0.3333333333"


def test_calculate_rounds_to_the_documented_number_of_places():
    places = calculator.CALCULATOR_DECIMAL_PLACES
    answer = calculator._calculate("2 / 3")

    assert len(answer.split(".")[1]) == places


def test_calculate_keeps_a_whole_result_whole():
    assert calculator._calculate("10 / 2") == "5"


def test_calculate_keeps_a_negative_result_negative():
    assert calculator._calculate("2 - 5") == "-3"


def test_calculate_does_not_turn_a_huge_whole_float_into_an_integer():
    """Past 2**53 a float has no exact integer to be turned into."""
    assert calculator._calculate("1e17") == "1e+17"


def test_calculate_accepts_the_expression_with_whitespace_around_it():
    assert calculator._calculate("  7 * 6  ") == "42"


def test_calculate_names_the_expression_when_the_syntax_is_broken():
    with pytest.raises(ValueError) as error:
        calculator._calculate("2 +")

    assert "'2 +'" in str(error.value)


def test_calculate_names_the_expression_when_the_arithmetic_fails():
    with pytest.raises(ValueError) as error:
        calculator._calculate("10 / 0")

    message = str(error.value)
    assert "'10 / 0'" in message
    assert "zero" in message


def test_calculate_names_the_expression_when_it_is_not_arithmetic_at_all():
    """Agents narrate; the tool must say what it wanted instead of a stack trace."""
    with pytest.raises(ValueError) as error:
        calculator._calculate("Calculate 1200 times 2.68 for me")

    assert repr("Calculate 1200 times 2.68 for me") in str(error.value)


def test_calculate_refuses_an_expression_that_is_a_statement():
    with pytest.raises(ValueError) as error:
        calculator._calculate("x = 2 + 2")

    assert "'x = 2 + 2'" in str(error.value)


def test_calculate_refuses_more_than_one_expression():
    with pytest.raises(ValueError):
        calculator._calculate("2 + 2; __import__('os')")


@pytest.mark.parametrize("expression", ["", "   ", None])
def test_calculate_rejects_an_empty_expression_before_parsing(expression):
    with pytest.raises(ValueError) as error:
        calculator._calculate(expression)

    assert repr(expression) in str(error.value)


# ---------------------------------------------------------------------------
# get_calculator_tools
# ---------------------------------------------------------------------------
def test_get_calculator_tools_returns_one_langchain_tool():
    tools = calculator.get_calculator_tools()

    assert [type(tool) for tool in tools] == [Tool]
    assert [tool.name for tool in tools] == ["calculator"]


def test_get_calculator_tools_describes_the_tool_for_the_agent():
    tool = calculator.get_calculator_tools()[0]

    assert tool.description == calculator.CALCULATOR_DESCRIPTION


def test_the_description_tells_the_agent_what_it_may_write():
    """Everything the allowlist accepts has to be discoverable from the prompt."""
    description = calculator.CALCULATOR_DESCRIPTION

    assert all(name in description for name in calculator.CALCULATOR_FUNCTIONS)


def test_get_calculator_tools_entry_is_backed_by_the_calculation():
    tool = calculator.get_calculator_tools()[0]

    assert tool.func("(1200 * 2.68) / 1000") == "3.216"


def test_get_calculator_tools_builds_a_fresh_tool_each_time():
    """`main.py` calls this once, but a shared mutable tool would be a trap."""
    assert calculator.get_calculator_tools()[0] is not calculator.get_calculator_tools()[0]
