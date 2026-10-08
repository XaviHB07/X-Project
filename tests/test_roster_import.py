"""Tests del parser de Excel de la lista de estudiantes (HU-C1).

Son tests puros: construyen un .xlsx en memoria con openpyxl y lo pasan
a `parse_roster_xlsx`, sin base de datos ni HTTP.
"""

import io

import pytest
from openpyxl import Workbook

from src.services.roster_import import RosterFormatError, parse_roster_xlsx


def make_xlsx(rows, include_course_context=True) -> bytes:
    wb = Workbook()
    ws = wb.active
    if include_course_context:
        ws.append(["MATRICULADOS P.A. 2026-2 - TE111-U (INNOVACION Y GESTION TECNOLOGICA)"])
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

    def test_finds_student_headers_after_variable_course_preamble(self):
        data = make_xlsx(
            [
                ["UNIVERSIDAD NACIONAL DE INGENIERÍA"],
                ["DIRECCIÓN DE REGISTRO CENTRAL Y ESTADÍSTICA"],
                ["FACULTAD DE INGENIERÍA INDUSTRIAL Y DE SISTEMAS"],
                [None, None],
                ["MATRICULADOS 2026-2 - TE111-U (INNOVACION Y GESTION TECNOLOGICA)"],
                [None, None],
                ["NRO", "CÓDIGO", "ALUMNO", "ESP", "CONDICION"],
                [1, "20212532K", "ESTUDIANTE DE PRUEBA", "I2", "Normal"],
            ],
            include_course_context=False,
        )

        result = parse_roster_xlsx(data)

        assert [(row.external_ref, row.display_name) for row in result.rows] == [
            ("20212532K", "ESTUDIANTE DE PRUEBA")
        ]
        assert result.rows[0].row_number == 8

    def test_requires_course_context_before_the_header(self):
        data = make_xlsx(
            [["codigo", "nombre"], ["A1", "Ana"]],
            include_course_context=False,
        )
        with pytest.raises(RosterFormatError, match="código o nombre del curso"):
            parse_roster_xlsx(data)

    def test_columns_may_come_in_any_order_with_extra_columns(self):
        data = make_xlsx([["correo", "nombre", "codigo"], ["x@y.z", "Ana", "A1"]])
        result = parse_roster_xlsx(data)
        assert (result.rows[0].external_ref, result.rows[0].display_name) == ("A1", "Ana")

    def test_reads_optional_phone_and_email_columns(self):
        data = make_xlsx(
            [["Celular", "Código", "Correo electrónico", "Alumno"],
             ["987654321", "A1", "ana@example.com", "Ana"]]
        )
        result = parse_roster_xlsx(data)
        assert (result.rows[0].phone_number, result.rows[0].email) == (
            "987654321",
            "ana@example.com",
        )

    def test_leading_blank_rows_before_header_are_skipped(self):
        data = make_xlsx([[None, None], ["codigo", "nombre"], ["A1", "Ana"]])
        result = parse_roster_xlsx(data)
        assert len(result.rows) == 1
        assert result.rows[0].row_number == 4  # fila real en Excel

    def test_numeric_codes_keep_their_value(self):
        data = make_xlsx([["codigo", "alumno"], [20240001, "Ana"], [7.0, "Luis"]])
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
            parse_roster_xlsx(make_xlsx([[None, None]], include_course_context=False))

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
        assert {e.row_number for e in result.errors} == {4, 5, 6}
        assert result.total_rows == 5  # la fila en blanco no cuenta
        repeated = next(e for e in result.errors if e.row_number == 6)
        assert "fila 3" in repeated.message

    def test_overlong_values_are_rejected_per_row(self):
        data = make_xlsx([["codigo", "nombre"], ["A1", "x" * 300], ["A2", "Ana"]])
        result = parse_roster_xlsx(data)
        assert [r.external_ref for r in result.rows] == ["A2"]
        assert result.errors[0].row_number == 3

    def test_whitespace_is_normalized(self):
        data = make_xlsx([["codigo", "nombre"], ["  A1 ", "  Ana   María  Torres "]])
        result = parse_roster_xlsx(data)
        assert result.rows[0].external_ref == "A1"
        assert result.rows[0].display_name == "Ana María Torres"
