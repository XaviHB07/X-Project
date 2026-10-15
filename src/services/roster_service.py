"""Casos de uso de la lista del curso (HU-C1): importar desde Excel y
mantener la lista (editar / retirar estudiantes).
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from src.domain.entities import Student
from src.repositories.interfaces import UnitOfWork
from src.services.auth_service import ROLE_STUDENT, hash_password
from src.services.errors import CourseNotFoundError, StudentNotFoundError
from src.services.roster_import import RowError, parse_roster_xlsx

UnitOfWorkFactory = Callable[[], UnitOfWork]

# Prior Beta(1,1) = incertidumbre uniforme, el mismo valor por defecto
# con que la API matricula estudiantes uno a uno.
DEFAULT_ALPHA_INIT = 1.0
DEFAULT_BETA_INIT = 1.0


class RosterAlreadyImportedError(ValueError):
    """El Excel del curso ya fue importado durante su ciclo académico."""


@dataclass
class RosterImportResult:
    total_rows: int
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    errors: List[RowError] = field(default_factory=list)
    warnings: List[RowError] = field(default_factory=list)
    created_accounts: List[dict] = field(default_factory=list)
    updated_accounts: List[dict] = field(default_factory=list)


class RosterService:
    def __init__(self, uow_factory: UnitOfWorkFactory):
        self._uow_factory = uow_factory

    def import_roster(self, course_id: int, xlsx_bytes: bytes) -> RosterImportResult:
        """Importa la lista del curso desde un `.xlsx`.

        - Estructura inválida -> `RosterFormatError` y NO se guarda nada.
        - Filas inválidas -> se informan en `errors`; las filas válidas
          sí se guardan, todas en una única transacción.
        - En cursos vinculados a un ciclo, una carga con filas válidas
          consume la importación única. Los cursos históricos sin ciclo
          mantienen el comportamiento idempotente anterior.
        - Quien NO aparece en el archivo no se toca (retirar es una acción
          explícita).
        """
        parsed = parse_roster_xlsx(xlsx_bytes)  # antes de abrir la transacción

        result = RosterImportResult(total_rows=parsed.total_rows, errors=list(parsed.errors))
        with self._uow_factory() as uow:
            course = uow.courses.get(course_id)
            if course is None:
                raise CourseNotFoundError(f"Curso {course_id} no encontrado.")
            importable_rows = []
            for row in parsed.rows:
                email = row.email.strip().lower() if row.email else None
                email_account = uow.student_accounts.get_by_email(email) if email else None
                username_account = uow.student_accounts.get_by_username(row.external_ref)
                if (
                    email_account is not None
                    and username_account is not None
                    and email_account.id != username_account.id
                ):
                    result.errors.append(
                        RowError(
                            row.row_number,
                            "El correo y el código ya pertenecen a cuentas diferentes; "
                            "la matrícula no se importó.",
                        )
                    )
                    continue
                account = email_account or username_account
                if account is not None and account.role != ROLE_STUDENT:
                    result.errors.append(
                        RowError(
                            row.row_number,
                            "El correo ya pertenece a una cuenta que no es de estudiante; "
                            "la matrícula no se importó.",
                        )
                    )
                    continue
                if account is not None and not account.active:
                    result.errors.append(
                        RowError(
                            row.row_number,
                            "La cuenta de estudiante asociada está inactiva; "
                            "la matrícula no se importó.",
                        )
                    )
                    continue
                if (
                    account is not None
                    and account.email
                    and email
                    and account.email.strip().lower() != email
                ):
                    result.errors.append(
                        RowError(
                            row.row_number,
                            "El código ya pertenece a una cuenta asociada a otro correo; "
                            "la matrícula no se importó.",
                        )
                    )
                    continue
                importable_rows.append(row)
            if (
                course.cycle_id is not None
                and importable_rows
                and not uow.courses.claim_roster_import(course_id)
            ):
                raise RosterAlreadyImportedError(
                    "La lista de estudiantes de este curso ya fue cargada para el ciclo académico."
                )
            for row in importable_rows:
                email = row.email.strip().lower() if row.email else None
                account = (
                    uow.student_accounts.get_by_email(email)
                    if email
                    else None
                ) or uow.student_accounts.get_by_username(row.external_ref)
                if account is None:
                    temporary_password = secrets.token_urlsafe(18)
                    account = uow.student_accounts.create_student(
                        username=row.external_ref,
                        full_name=row.display_name,
                        email=email,
                        password_hash=hash_password(temporary_password),
                    )
                    result.created_accounts.append(
                        {
                            "row_number": row.row_number,
                            "username": account.username,
                            "full_name": account.full_name,
                            "email": account.email,
                            "temporary_password": temporary_password,
                        }
                    )
                elif account.username != row.external_ref:
                    account = uow.student_accounts.update_username(
                        account.id, row.external_ref
                    )
                    result.updated_accounts.append(
                        {
                            "row_number": row.row_number,
                            "username": account.username,
                            "full_name": account.full_name,
                            "email": account.email,
                        }
                    )

                _, status = uow.students.upsert_from_roster(
                    course_id=course_id,
                    external_ref=row.external_ref,
                    display_name=row.display_name,
                    alpha_init=DEFAULT_ALPHA_INIT,
                    beta_init=DEFAULT_BETA_INIT,
                    phone_number=row.phone_number,
                    email=email,
                    user_id=account.id,
                    roster_number=row.roster_number,
                    specialty=row.specialty,
                    student_condition=row.student_condition,
                    times_repeated=row.times_repeated,
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
