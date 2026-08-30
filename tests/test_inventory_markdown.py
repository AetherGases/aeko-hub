"""Unit tests for the spreadsheet-to-Markdown rendering.

`AekoInventoryAnalyzer.analyze()` expects the inventory rendered as Markdown —
"a table is the natural shape", per the SDK README — while the repository reads
an `.xlsx` out of S3. This module is that bridge, so it is tested against real
workbook bytes rather than a double.
"""

from io import BytesIO

import pytest
from openpyxl import Workbook

from inventory_analysis.inventory_markdown import inventory_markdown_from_xlsx


def workbook_bytes(sheets):
    """`sheets` maps a sheet title to its rows."""
    workbook = Workbook()
    workbook.remove(workbook.active)
    for title, rows in sheets.items():
        worksheet = workbook.create_sheet(title=title)
        for row in rows:
            worksheet.append(row)

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


SIMPLE = {
    "Escopo 1": [
        ["Fonte", "tCO2e"],
        ["Caldeira", 12400],
        ["Frota", 830],
    ]
}


def test_renders_the_rows_as_a_markdown_table():
    markdown = inventory_markdown_from_xlsx(workbook_bytes(SIMPLE))

    assert markdown.splitlines() == [
        "## Escopo 1",
        "",
        "| Fonte | tCO2e |",
        "| --- | --- |",
        "| Caldeira | 12400 |",
        "| Frota | 830 |",
    ]


def test_renders_every_sheet_of_the_workbook():
    markdown = inventory_markdown_from_xlsx(
        workbook_bytes({**SIMPLE, "Escopo 2": [["Fonte", "tCO2e"], ["Energia", 410]]})
    )

    assert "## Escopo 1" in markdown
    assert "## Escopo 2" in markdown
    assert "| Energia | 410 |" in markdown


def test_renders_an_empty_cell_as_an_empty_column():
    markdown = inventory_markdown_from_xlsx(
        workbook_bytes({"Escopo 1": [["Fonte", "tCO2e"], ["Caldeira", None]]})
    )

    assert "| Caldeira |  |" in markdown


def test_escapes_a_pipe_so_it_cannot_break_the_table():
    markdown = inventory_markdown_from_xlsx(
        workbook_bytes({"Escopo 1": [["Fonte", "tCO2e"], ["Caldeira | reserva", 1]]})
    )

    assert r"| Caldeira \| reserva | 1 |" in markdown


def test_flattens_a_line_break_inside_a_cell():
    markdown = inventory_markdown_from_xlsx(
        workbook_bytes({"Escopo 1": [["Fonte", "Nota"], ["Caldeira", "linha 1\nlinha 2"]]})
    )

    assert "| Caldeira | linha 1 linha 2 |" in markdown


def test_skips_a_sheet_that_holds_nothing():
    markdown = inventory_markdown_from_xlsx(workbook_bytes({**SIMPLE, "Vazia": []}))

    assert "## Vazia" not in markdown


def test_skips_a_row_that_holds_nothing():
    markdown = inventory_markdown_from_xlsx(
        workbook_bytes({"Escopo 1": [["Fonte", "tCO2e"], [None, None], ["Frota", 830]]})
    )

    assert markdown.count("\n|") == 3  # header, separator, one data row


def test_pads_a_row_shorter_than_the_header():
    markdown = inventory_markdown_from_xlsx(
        workbook_bytes({"Escopo 1": [["Fonte", "tCO2e", "Nota"], ["Caldeira", 12400]]})
    )

    assert "| Caldeira | 12400 |  |" in markdown


def test_rejects_a_workbook_without_a_single_row():
    with pytest.raises(ValueError, match="no data"):
        inventory_markdown_from_xlsx(workbook_bytes({"Vazia": []}))


def test_rejects_bytes_that_are_not_a_workbook():
    with pytest.raises(ValueError, match="not a readable .xlsx"):
        inventory_markdown_from_xlsx(b"this is a PDF, actually")
