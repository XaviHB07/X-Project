"""Tests del parser de Excel de la lista de estudiantes (HU-C1).

Son tests puros: construyen un .xlsx en memoria con openpyxl y lo pasan
a `parse_roster_xlsx`, sin base de datos ni HTTP.
"""

import io

import pytest
from openpyxl import Workbook

from src.services.roster_import import RosterFormatError, parse_roster_xlsx


def make_xlsx(rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


class TestEstructura:
    def test_reads_valid_file(self):
        data = make_xlsx([["codigo", "nombre"], ["2024-001", "Ana Torres"], ["2024-002", "Luis Pérez"]])
        result = parse_roster_xlsx(data)
        assert [(r.external_ref, r.display_name) for r in result.rows] == [
            ("2024-001", "Ana Torres"),
            ("2024-002", "Luis Pérez"),
        ]
        assert result.errors == []
        assert result.total_rows == 2

    def test_headers_ignore_case_accents_and_aliases(self):
        data = make_xlsx([["  Código de Matrícula ", "Apellidos y Nombres"], ["A1", "Ana"]])
        result = parse_roster_xlsx(data)
        assert result.rows[0].external_ref == "A1"
        assert result.rows[0].display_name == "Ana"

    def test_columns_may_come_in_any_order_with_extra_columns(self):
        data = make_xlsx([["correo", "nombre", "codigo"], ["x@y.z", "Ana", "A1"]])
        result = parse_roster_xlsx(data)
        assert (result.rows[0].external_ref, result.rows[0].display_name) == ("A1", "Ana")

    def test_leading_blank_rows_before_header_are_skipped(self):
        data = make_xlsx([[None, None], ["codigo", "nombre"], ["A1", "Ana"]])
        result = parse_roster_xlsx(data)
        assert len(result.rows) == 1
        assert result.rows[0].row_number == 3  # fila real en Excel

    def test_numeric_codes_keep_their_value(self):
        data = make_xlsx([["codigo", "nombre"], [20240001, "Ana"], [7.0, "Luis"]])
        result = parse_roster_xlsx(data)
        assert [r.external_ref for r in result.rows] == ["20240001", "7"]

    def test_missing_required_column_raises(self):
        data = make_xlsx([["codigo", "correo"], ["A1", "x@y.z"]])
        with pytest.raises(RosterFormatError) as exc:
            parse_roster_xlsx(data)
        assert "nombre" in str(exc.value)

    def test_header_only_raises(self):
        with pytest.raises(RosterFormatError):
            parse_roster_xlsx(make_xlsx([["codigo", "nombre"]]))

    def test_empty_sheet_raises(self):
        with pytest.raises(RosterFormatError):
            parse_roster_xlsx(make_xlsx([[None, None]]))

    def test_not_an_xlsx_raises(self):
        with pytest.raises(RosterFormatError):
            parse_roster_xlsx(b"esto no es un excel")

    def test_empty_bytes_raises(self):
        with pytest.raises(RosterFormatError):
            parse_roster_xlsx(b"")


class TestRegistrosInvalidos:
    def test_invalid_rows_are_reported_with_excel_row_number_and_valid_ones_kept(self):
        data = make_xlsx(
            [
                ["codigo", "nombre"],
                ["A1", "Ana"],        # fila 2: ok
                ["A2", None],         # fila 3: falta nombre
                [None, "Sin código"], # fila 4: falta código
                ["A1", "Repetida"],   # fila 5: código repetido
                [None, None],         # fila 6: en blanco, se ignora
                ["A3", "Luis"],       # fila 7: ok
            ]
        )
        result = parse_roster_xlsx(data)

        assert [r.external_ref for r in result.rows] == ["A1", "A3"]
        assert {e.row_number for e in result.errors} == {3, 4, 5}
        assert result.total_rows == 5  # la fila en blanco no cuenta
        repeated = next(e for e in result.errors if e.row_number == 5)
        assert "fila 2" in repeated.message

    def test_overlong_values_are_rejected_per_row(self):
        data = make_xlsx([["codigo", "nombre"], ["A1", "x" * 300], ["A2", "Ana"]])
        result = parse_roster_xlsx(data)
        assert [r.external_ref for r in result.rows] == ["A2"]
        assert result.errors[0].row_number == 2

    def test_whitespace_is_normalized(self):
        data = make_xlsx([["codigo", "nombre"], ["  A1 ", "  Ana   María  Torres "]])
        result = parse_roster_xlsx(data)
        assert result.rows[0].external_ref == "A1"
        assert result.rows[0].display_name == "Ana María Torres"
