"""Casos de uso de la lista del curso (HU-C1): importar desde Excel y
mantener la lista (editar / retirar estudiantes).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from src.domain.entities import Student
from src.repositories.interfaces import UnitOfWork
from src.services.errors import CourseNotFoundError, StudentNotFoundError
from src.services.roster_import import RowError, parse_roster_xlsx

UnitOfWorkFactory = Callable[[], UnitOfWork]

# Prior Beta(1,1) = incertidumbre uniforme, el mismo valor por defecto
# con que la API matricula estudiantes uno a uno.
DEFAULT_ALPHA_INIT = 1.0
DEFAULT_BETA_INIT = 1.0


@dataclass
class RosterImportResult:
    total_rows: int
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    errors: List[RowError] = field(default_factory=list)


class RosterService:
    def __init__(self, uow_factory: UnitOfWorkFactory):
        self._uow_factory = uow_factory

    def import_roster(self, course_id: int, xlsx_bytes: bytes) -> RosterImportResult:
        """Importa (o re-importa) la lista del curso desde un `.xlsx`.

        - Estructura inválida -> `RosterFormatError` y NO se guarda nada.
        - Filas inválidas -> se informan en `errors`; las filas válidas
          sí se guardan, todas en una única transacción.
        - Es idempotente: re-cargar el mismo archivo no duplica a nadie;
          si cambió un nombre, se actualiza; un estudiante retirado que
          reaparece en el archivo se reactiva. Quien NO aparece en el
          nuevo archivo no se toca (retirar es una acción explícita).
        """
        parsed = parse_roster_xlsx(xlsx_bytes)  # antes de abrir la transacción

        result = RosterImportResult(total_rows=parsed.total_rows, errors=list(parsed.errors))
        with self._uow_factory() as uow:
            if uow.courses.get(course_id) is None:
                raise CourseNotFoundError(f"Curso {course_id} no encontrado.")
            for row in parsed.rows:
                _, status = uow.students.upsert_from_roster(
                    course_id=course_id,
                    external_ref=row.external_ref,
                    display_name=row.display_name,
                    alpha_init=DEFAULT_ALPHA_INIT,
                    beta_init=DEFAULT_BETA_INIT,
                    phone_number=row.phone_number,
                    email=row.email,
                )
                if status == "created":
                    result.created += 1
                elif status == "updated":
                    result.updated += 1
                else:
                    result.unchanged += 1
            uow.commit()
        return result

    def update_student(
        self,
        student_id: int,
        external_ref: Optional[str] = None,
        display_name: Optional[str] = None,
        active: Optional[bool] = None,
        phone_number: Optional[str] = None,
        email: Optional[str] = None,
    ) -> Student:
        """Edita nombre/código o retira (`active=False`) / reincorpora a un
        estudiante. Lanza `StudentNotFoundError` o `DuplicateStudentError`."""
        with self._uow_factory() as uow:
            student = uow.students.update(
                student_id,
                external_ref=external_ref,
                display_name=display_name,
                active=active,
                phone_number=phone_number,
                email=email,
            )
            if student is None:
                raise StudentNotFoundError(f"Estudiante {student_id} no encontrado.")
            uow.commit()
        return student
