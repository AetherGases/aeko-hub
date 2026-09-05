"""Arithmetic limits and investment analysis configuration and tool descriptions.

Load configuration from the repository environment file without overriding process settings.
"""

import ast
import math
import operator
import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=False)

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

CALCULATOR_FUNCTIONS = {
    "abs": abs,
    "log": math.log,
    "max": max,
    "min": min,
    "round": round,
    "sqrt": math.sqrt,
    "sum": sum,
}

CALCULATOR_MAX_EXPRESSION_LENGTH = int(os.environ["CALCULATOR_MAX_EXPRESSION_LENGTH"])

CALCULATOR_MAX_EXPONENT = int(os.environ["CALCULATOR_MAX_EXPONENT"])

CALCULATOR_DECIMAL_PLACES = int(os.environ["CALCULATOR_DECIMAL_PLACES"])

CALCULATOR_MAX_EXACT_INTEGER = int(os.environ["CALCULATOR_MAX_EXACT_INTEGER"])

CALCULATOR_DESCRIPTION = os.environ["CALCULATOR_DESCRIPTION"]

ROI_HORIZON_MONTHS = int(os.environ["ROI_HORIZON_MONTHS"])

ROI_PAYBACK_NOT_RECOVERED = int(os.environ["ROI_PAYBACK_NOT_RECOVERED"])

ROI_DECIMAL_PLACES = int(os.environ["ROI_DECIMAL_PLACES"])

ROI_MAX_WACC_MONTHLY = int(os.environ["ROI_MAX_WACC_MONTHLY"])

ROI_CASH_FLOW_FIELDS = ("cash_flows", "monthly_cash_flow")

ROI_REQUEST_FIELDS = ("capex", "wacc_monthly", *ROI_CASH_FLOW_FIELDS)

ROI_REQUEST_DESCRIPTION = os.environ["ROI_REQUEST_DESCRIPTION"].replace("{ROI_HORIZON_MONTHS}", str(ROI_HORIZON_MONTHS))

ROI_DESCRIPTION = os.environ["ROI_DESCRIPTION"].replace("{ROI_REQUEST_DESCRIPTION}", str(ROI_REQUEST_DESCRIPTION))

PAYBACK_DESCRIPTION = os.environ["PAYBACK_DESCRIPTION"].replace("{ROI_REQUEST_DESCRIPTION}", str(ROI_REQUEST_DESCRIPTION)).replace("{ROI_PAYBACK_NOT_RECOVERED}", str(ROI_PAYBACK_NOT_RECOVERED)).replace("{ROI_HORIZON_MONTHS}", str(ROI_HORIZON_MONTHS))
