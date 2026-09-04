"""Arithmetic every agent can reach, so no agent has to predict digits.

This module never imports `aeko` — `cmd/api/main.py` is the single entry point
for the SDK (see `test_only_the_entry_point_imports_the_sdk`), so the wrapping
into an `AekoTool` happens there. What this module hands back is a plain
LangChain `Tool`, exactly like the integrations in the sibling packages.

What is different is that there is nothing on the other end: no child process
as in `cmd/api/mcp/`, no REST call as in `cmd/api/integrations/`. The answer is
computed here, which is why this one goes to every agent instead of one — an
inventory analyst totalling a scope, a pollutant analyst applying a Climatiq
factor and the FAQ converting a unit are all the same failure otherwise. A
language model produces digits by predicting them, and a plausible number is
worse than no number in a GHG inventory: it is wrong in a way nobody catches.

Why the expression is walked and never `eval`ed
-----------------------------------------------
The input is written by a language model, and `eval` on model output is
arbitrary code execution — `__import__('os').system(...)` is one string away,
and an agent can be talked into writing that string by the document it is
reading. So the text is parsed with `ast` into a tree and walked against an
allowlist: the arithmetic operators, numeric literals, and the handful of
functions in `CALCULATOR_FUNCTIONS`. Every other node is refused by name.

An allowlist rather than a blocklist because the escape routes are not
enumerable: `(2).__class__` reaches `object`, a comprehension introduces
names, an f-string evaluates its own contents. What each of those has in
common is a node type this walk does not implement, so refusing everything
unlisted closes the ones nobody has thought of yet.

The two remaining costs are not security but arithmetic itself, and both are
bounded here: `9 ** 9 ** 9` occupies the worker for hours (`CALCULATOR_MAX_EXPONENT`),
and a float that overflows quietly becomes `inf` rather than raising.
"""

import ast
import math
import operator

from langchain_core.tools import Tool

from shared import Module, logged

# The whole grammar. `**` is included because emission maths uses it (GWP over
# a horizon, compounding), and bounded below.
CALCULATOR_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

CALCULATOR_UNARY_OPERATORS = {ast.UAdd: operator.pos, ast.USub: operator.neg}

# Named functions the agent may call. Every one is pure, takes numbers and
# returns a number — which is what makes calling them safe to allow at all.
# `log` takes an optional base, so `log(100, 10)` reads as it is written.
CALCULATOR_FUNCTIONS = {
    "abs": abs,
    "log": math.log,
    "max": max,
    "min": min,
    "round": round,
    "sqrt": math.sqrt,
    "sum": sum,
}

# A model that starts repeating itself produces one enormous string. Parsing it
# is wasted work, and 500 characters is far past any real inventory sum.
CALCULATOR_MAX_EXPRESSION_LENGTH = 500

# `2 ** 100000000` is valid arithmetic and never comes back. Python computes
# integer powers exactly, so the cost is in the digits, not in the operator.
CALCULATOR_MAX_EXPONENT = 1000

# Binary floating point makes `1200 * 2.68` come out as 3216.0000000000005.
# Rounding here is presentation, applied once at the end: the calculation
# itself runs at full precision, and ten places is finer than any emission
# factor Climatiq publishes.
CALCULATOR_DECIMAL_PLACES = 10

# Past 2**53 a float has no exact integer left to be shown as, so a whole
# result stops being written without its decimal point.
CALCULATOR_MAX_EXACT_INTEGER = 2**53

CALCULATOR_DESCRIPTION = (
    "Calculates an arithmetic expression exactly. Use it for every number you "
    "report — totals, emission factors applied to activity data, unit "
    "conversions, percentages and differences — instead of working the "
    "arithmetic out yourself. Input is the expression alone, as text, with no "
    "words around it: for example '(1200 * 2.68) / 1000'. It understands "
    "numbers, the operators + - * / // % ** and parentheses, and these "
    "functions: abs, log, max, min, round, sqrt, sum (for example "
    "'round(sum([120.5, 340.2, 78.9]), 2)'). It answers with the number alone. "
    "It has no variables and no units, so substitute the values yourself and "
    "keep track of the unit."
)


def _refusal(node: ast.AST) -> str:
    """Why a node was refused, in terms of what the agent may write instead."""

    return (
        f"{ast.unparse(node)!r} is not arithmetic. The calculator takes numbers, "
        f"the operators + - * / // % ** and parentheses, and these functions: "
        f"{', '.join(sorted(CALCULATOR_FUNCTIONS))}"
    )


def _number(value: object) -> int | float:
    """A literal, which must be a plain real number.

    `bool` is excluded although it is an `int` in Python: `True + True` is 2,
    which is arithmetic nobody meant to write.
    """

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{value!r} is not a number the calculator can use")

    return value


def _real(result: object, node: ast.AST) -> int | float:
    """What a computed step is allowed to be.

    Two ways an operation leaves the real numbers without raising anything:
    `(-8) ** 0.5` is complex in Python, and a float that overflows becomes
    `inf`. Either would travel to the agent as a confident answer.
    """

    if isinstance(result, complex):
        raise ValueError(f"{ast.unparse(node)!r} has no real number as its answer")

    if isinstance(result, float) and not math.isfinite(result):
        raise ValueError(f"{ast.unparse(node)!r} is too large a number to represent")

    return result


def _binary(node: ast.BinOp) -> int | float:
    """One operator applied to two numbers, with the ways it can go wrong."""

    left = _evaluate(node.left)
    right = _evaluate(node.right)

    if isinstance(node.op, ast.Pow) and abs(right) > CALCULATOR_MAX_EXPONENT:
        raise ValueError(
            f"an exponent above {CALCULATOR_MAX_EXPONENT} would not finish in "
            f"time, got {right!r}"
        )

    try:
        result = CALCULATOR_OPERATORS[type(node.op)](left, right)
    except ZeroDivisionError as exc:
        raise ValueError(f"{ast.unparse(node)!r} divides by zero") from exc
    except OverflowError as exc:
        raise ValueError(f"{ast.unparse(node)!r} is too large a number to represent") from exc

    return _real(result, node)


def _argument(node: ast.AST) -> int | float | list:
    """One argument of a call.

    The only place a sequence is allowed: `sum([1, 2, 3])` is how the agent
    totals a column, and its elements are still walked one by one. Outside a
    call a list is not arithmetic and `_evaluate` refuses it.
    """

    if isinstance(node, (ast.List, ast.Tuple)):
        return [_evaluate(element) for element in node.elts]

    return _evaluate(node)


def _call(node: ast.Call) -> int | float:
    """One of `CALCULATOR_FUNCTIONS`, and nothing else that looks like a call.

    The name is checked before the arguments are evaluated, so nothing inside
    `__import__('os')` runs on the way to refusing it.
    """

    name = node.func.id if isinstance(node.func, ast.Name) else ast.unparse(node.func)

    if name not in CALCULATOR_FUNCTIONS:
        raise ValueError(
            f"{name!r} is not a function the calculator knows. It knows: "
            f"{', '.join(sorted(CALCULATOR_FUNCTIONS))}"
        )

    if node.keywords != []:
        raise ValueError(
            f"{name!r} takes its arguments in order, so {node.keywords[0].arg!r} "
            f"cannot be given by name"
        )

    try:
        result = CALCULATOR_FUNCTIONS[name](*[_argument(argument) for argument in node.args])
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{ast.unparse(node)!r} could not be calculated: {exc}") from exc

    return _real(result, node)


def _evaluate(node: ast.AST) -> int | float:
    """The allowlist walk: one branch per node type this calculator implements.

    Anything that falls through is refused, which is what makes the list of
    branches above the whole of what an agent can express here.
    """

    if isinstance(node, ast.Constant):
        return _number(node.value)

    if isinstance(node, ast.UnaryOp) and type(node.op) in CALCULATOR_UNARY_OPERATORS:
        return CALCULATOR_UNARY_OPERATORS[type(node.op)](_evaluate(node.operand))

    if isinstance(node, ast.BinOp) and type(node.op) in CALCULATOR_OPERATORS:
        return _binary(node)

    if isinstance(node, ast.Call):
        return _call(node)

    if isinstance(node, ast.Name):
        # There is no namespace to resolve it in, which is the point: `pi` and
        # `os` fail the same way, and neither reaches a lookup.
        raise ValueError(f"{node.id!r} is not a number the calculator knows")

    raise ValueError(_refusal(node))


def _parse_expression(expression: str | None) -> str:
    """The text the agent wants calculated, before anything parses it."""

    if not isinstance(expression, str) or expression.strip() == "":
        raise ValueError(
            f"The expression must be the arithmetic to calculate, got {expression!r}."
        )

    expression = expression.strip()

    if len(expression) > CALCULATOR_MAX_EXPRESSION_LENGTH:
        raise ValueError(
            f"The expression must be at most {CALCULATOR_MAX_EXPRESSION_LENGTH} "
            f"characters, got {len(expression)}."
        )

    return expression


def _format_result(value: int | float) -> str:
    """The number as the agent should quote it, without the binary noise."""

    if isinstance(value, int):
        return str(value)

    value = round(value, CALCULATOR_DECIMAL_PLACES)

    if value.is_integer() and abs(value) < CALCULATOR_MAX_EXACT_INTEGER:
        return str(int(value))

    return repr(value)


@logged(Module.TOOL, "calculator")
def _calculate(expression: str | None = "") -> str:
    """The tool's `func`: text in, one number out.

    Every failure leaves as a `ValueError` naming the expression the agent
    sent, because the caller on the other end is an agent reading the text and
    writing the next attempt from it — the same contract as
    `_parse_estimate_request` in `cmd/api/integrations/climatiq_api.py`.
    """

    text = _parse_expression(expression)

    try:
        # `mode="eval"` accepts a single expression and nothing else, so an
        # assignment or a second statement after a semicolon never parses.
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ValueError(
            f"{expression!r} is not an expression the calculator can read: {exc.msg}. "
            f"Send the arithmetic alone, with no words around it."
        ) from exc

    try:
        value = _evaluate(tree.body)
    except ValueError as exc:
        raise ValueError(f"{expression!r} could not be calculated: {exc}.") from exc

    return _format_result(value)


def get_calculator_tools() -> list[Tool]:
    """The one tool every agent gets, whatever else it is given."""

    return [
        Tool(
            name="calculator",
            description=CALCULATOR_DESCRIPTION,
            func=_calculate,
        )
    ]
