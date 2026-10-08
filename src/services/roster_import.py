"""Lectura y validación del Excel de la lista de estudiantes (HU-C1).

Este módulo es PURO: recibe los bytes de un `.xlsx` y devuelve filas ya
validadas más una lista de errores por fila. No toca la base de datos ni
FastAPI, así que se prueba sin infraestructura (ver
`tests/test_roster_import.py`).

Formato esperado: el encabezado se busca en la hoja y no tiene que estar
en una fila fija. Antes debe aparecer el código o nombre del curso.

    | codigo   | nombre        |
    | 2024-001 | Ana Torres    |
    | 2024-002 | Luis Pérez    |

Encabezados aceptados (sin distinguir mayúsculas, tildes, espacios ni
guiones bajos):

    - código:  codigo, código, matricula, matrícula, external_ref, dni, id
    - nombre:  nombre, nombres, nombre completo, apellidos y nombres,
               estudiante, alumno, display_name
    - teléfono: teléfono, celular, phone, phone_number (opcional)
    - correo:   correo, email, e-mail (opcional)

Dos niveles de problema, a propósito:

    * Errores de ESTRUCTURA (archivo que no es .xlsx, vacío, sin las
      columnas requeridas, demasiado grande): `RosterFormatError`. No se
      puede interpretar nada, así que no se importa nada.
    * Errores de REGISTRO (fila sin nombre, código repetido, texto
      demasiado largo): se devuelven en `RosterParseResult.errors` con
      su número de fila de Excel; las demás filas siguen siendo válidas.
"""

from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from openpyxl import load_workbook

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000
MAX_FIELD_LENGTH = 255

_CODE_HEADERS = {"codigo", "matricula", "externalref", "dni", "id", "codigodematricula"}
_NAME_HEADERS = {
    "nombre", "nombres", "nombrecompleto", "apellidosynombres", "estudiante", "alumno",
    "alumnos", "displayname",
}
_PHONE_HEADERS = {"telefono", "celular", "movil", "phone", "phonenumber", "numerotelefono"}
_EMAIL_HEADERS = {"correo", "email", "emailaddress", "correoelectronico"}
_COURSE_CODE_PATTERN = re.compile(r"\b[A-Z]{1,10}[- ]?\d{1,5}[A-Z]{0,3}\b", re.IGNORECASE)
_COURSE_NAME_PATTERN = re.compile(
    r"\b(?:curso|asignatura|course|subject)\s*[:\-]\s*\S+", re.IGNORECASE
)


class RosterFormatError(ValueError):
    """El archivo no se puede interpretar como lista de estudiantes."""


@dataclass(frozen=True)
class RosterRow:
    row_number: int  # número de fila tal como lo ve el docente en Excel
    external_ref: str
    display_name: str
    phone_number: Optional[str] = None
    email: Optional[str] = None


@dataclass(frozen=True)
class RowError:
    row_number: int
    message: str


@dataclass
class RosterParseResult:
    rows: List[RosterRow] = field(default_factory=list)
    errors: List[RowError] = field(default_factory=list)
    total_rows: int = 0  # filas de datos no vacías leídas


def _normalize_header(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or "").strip().lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return "".join(ch for ch in text if ch.isalnum())


def _cell_text(value: Any) -> str:
    """Convierte una celda a texto limpio. Los códigos numéricos de Excel
    (p. ej. 20240001) llegan como int/float: se pasan a texto sin el
    ".0" final para no cambiar el código del estudiante."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return " ".join(str(value).split())


def _header_columns(
    cells: tuple,
) -> tuple[Optional[int], Optional[int], Optional[int], Optional[int]]:
    code_col = name_col = phone_col = email_col = None
    for index, cell in enumerate(cells):
        key = _normalize_header(cell)
        if code_col is None and key in _CODE_HEADERS:
            code_col = index
        if name_col is None and key in _NAME_HEADERS:
            name_col = index
        if phone_col is None and key in _PHONE_HEADERS:
            phone_col = index
        if email_col is None and key in _EMAIL_HEADERS:
            email_col = index
    return code_col, name_col, phone_col, email_col


def _has_course_context(rows: List[tuple]) -> bool:
    for cells in rows:
        values = [_cell_text(cell) for cell in cells]
        row_text = " ".join(values)
        if _COURSE_CODE_PATTERN.search(row_text) or _COURSE_NAME_PATTERN.search(row_text):
            return True

        normalized = [_normalize_header(value) for value in values]
        for index, value in enumerate(normalized):
            if value in {"curso", "asignatura", "course", "subject"} and any(
                other for other_index, other in enumerate(values) if other_index != index
            ):
                return True
    return False


def parse_roster_xlsx(data: bytes) -> RosterParseResult:
    if not data:
        raise RosterFormatError("El archivo está vacío.")
    if len(data) > MAX_FILE_BYTES:
        raise RosterFormatError(
            f"El archivo supera el máximo permitido ({MAX_FILE_BYTES // (1024 * 1024)} MB)."
        )

    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl lanza tipos distintos según el daño del archivo
        raise RosterFormatError(
            "No se pudo leer el archivo. Debe ser un Excel en formato .xlsx."
        ) from exc

    try:
        sheet = workbook.active
        if sheet is None:
            raise RosterFormatError("El Excel no tiene hojas.")
        row_iter = sheet.iter_rows(values_only=True)

        header_cells: Optional[tuple] = None
        code_col = name_col = phone_col = email_col = None
        preamble_rows: List[tuple] = []
        for header_row_number, cells in enumerate(row_iter, start=1):
            code_col, name_col, phone_col, email_col = _header_columns(cells)
            if code_col is not None and name_col is not None:
                header_cells = cells
                break
            if any(_cell_text(c) for c in cells):
                preamble_rows.append(cells)
        if header_cells is None:
            if not preamble_rows:
                raise RosterFormatError("El Excel no tiene datos.")
            raise RosterFormatError(
                "No se encontró una fila de encabezado con las columnas obligatorias: "
                "código (codigo / matrícula) y nombre (nombre / alumno)."
            )
        if not _has_course_context(preamble_rows):
            raise RosterFormatError(
                "No se encontró el código o nombre del curso antes del encabezado. "
                "Incluye una fila de identificación del curso (por ejemplo, 'Curso: TE111-U')."
            )

        result = RosterParseResult()
        seen: Dict[str, int] = {}
        for current_row, cells in enumerate(row_iter, start=header_row_number + 1):
            code = _cell_text(cells[code_col]) if code_col < len(cells) else ""
            name = _cell_text(cells[name_col]) if name_col < len(cells) else ""
            phone = (
                _cell_text(cells[phone_col]) or None
                if phone_col is not None and phone_col < len(cells)
                else None
            )
            email = (
                _cell_text(cells[email_col]) or None
                if email_col is not None and email_col < len(cells)
                else None
            )
            if not code and not name:
                continue  # fila en blanco: se ignora sin reportarla
            result.total_rows += 1
            if result.total_rows > MAX_ROWS:
                raise RosterFormatError(f"El Excel supera el máximo de {MAX_ROWS} estudiantes.")

            problem = None
            if not code:
                problem = "Falta el código del estudiante."
            elif not name:
                problem = "Falta el nombre del estudiante."
            elif (
                len(code) > MAX_FIELD_LENGTH
                or len(name) > MAX_FIELD_LENGTH
                or (phone is not None and len(phone) > 32)
                or (email is not None and len(email) > MAX_FIELD_LENGTH)
            ):
                problem = (
                    f"El código, nombre y correo admiten hasta {MAX_FIELD_LENGTH} caracteres "
                    "y el teléfono hasta 32."
                )
            elif code in seen:
                problem = f"El código {code!r} ya aparece en la fila {seen[code]}."
            if problem:
                result.errors.append(RowError(current_row, problem))
                continue

            seen[code] = current_row
            result.rows.append(RosterRow(current_row, code, name, phone, email))

        if result.total_rows == 0:
            raise RosterFormatError("El Excel solo tiene encabezado: no hay estudiantes para cargar.")
        return result
    finally:
        workbook.close()
