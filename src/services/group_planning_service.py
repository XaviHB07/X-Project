"""Generación y edición de propuestas de grupos por curso."""

from __future__ import annotations

import math
import secrets
from datetime import datetime, timezone
from typing import Callable, List, Optional, Sequence

from src.domain.entities import CourseGroupPlan, StudentGroup
from src.repositories.interfaces import UnitOfWork
from src.services.errors import CourseNotFoundError

UnitOfWorkFactory = Callable[[], UnitOfWork]
MAX_GROUPS = 100
MAX_GROUP_SIZE = 1000


class GroupPlanNotFoundError(LookupError):
    """La propuesta solicitada no existe en el curso indicado."""


class InvalidGroupPlanError(ValueError):
    """La distribución propuesta no cumple las reglas del curso."""


class GroupPlanningService:
    def __init__(self, uow_factory: UnitOfWorkFactory):
        self._uow_factory = uow_factory

    def list_plans(self, course_id: int) -> List[CourseGroupPlan]:
        with self._uow_factory() as uow:
            self._require_course(uow, course_id)
            return uow.group_plans.list_by_course(course_id)

    def generate(
        self, course_id: int, max_group_size: int, name: Optional[str] = None
    ) -> CourseGroupPlan:
        self._validate_max_group_size(max_group_size)
        cleaned_name = self._clean_name(name) if name else datetime.now(
            timezone.utc
        ).strftime("Propuesta aleatoria %Y-%m-%d %H:%M UTC")
        with self._uow_factory() as uow:
            self._require_course(uow, course_id)
            students = uow.students.list_by_course(course_id)
            if not students:
                raise InvalidGroupPlanError(
                    "Matricula al menos un estudiante activo antes de generar grupos."
                )
            shuffled = list(students)
            secrets.SystemRandom().shuffle(shuffled)
            group_count = math.ceil(len(shuffled) / max_group_size)
            base_size, extra = divmod(len(shuffled), group_count)
            groups = []
            offset = 0
            for index in range(group_count):
                size = base_size + (1 if index < extra else 0)
                groups.append(
                    StudentGroup(
                        name=f"Grupo {index + 1}",
                        student_ids=[student.id for student in shuffled[offset : offset + size]],
                    )
                )
                offset += size
            plan = uow.group_plans.create(
                course_id, cleaned_name, max_group_size, groups
            )
            uow.commit()
            return plan

    def create_manual(
        self, course_id: int, group_count: int, name: Optional[str] = None
    ) -> CourseGroupPlan:
        if not 1 <= group_count <= MAX_GROUPS:
            raise InvalidGroupPlanError(
                f"La cantidad de grupos debe estar entre 1 y {MAX_GROUPS}."
            )
        cleaned_name = self._clean_name(name) if name else datetime.now(
            timezone.utc
        ).strftime("Distribución manual %Y-%m-%d %H:%M UTC")
        with self._uow_factory() as uow:
            self._require_course(uow, course_id)
            students = uow.students.list_by_course(course_id)
            if not students:
                raise InvalidGroupPlanError(
                    "Matricula al menos un estudiante activo antes de crear grupos."
                )
            if group_count > len(students):
                raise InvalidGroupPlanError(
                    "No puedes crear más grupos que estudiantes activos."
                )
            base_size, extra = divmod(len(students), group_count)
            groups = []
            start = 0
            for index in range(group_count):
                size = base_size + (1 if index < extra else 0)
                groups.append(StudentGroup(
                    name=f"Grupo {index + 1}",
                    student_ids=[student.id for student in students[start : start + size]],
                ))
                start += size
            max_group_size = base_size + (1 if extra else 0)
            plan = uow.group_plans.create(
                course_id, cleaned_name, max_group_size, groups
            )
            uow.commit()
            return plan

    def update(
        self,
        course_id: int,
        plan_id: int,
        name: str,
        max_group_size: int,
        groups: Sequence[StudentGroup],
    ) -> CourseGroupPlan:
        cleaned_name = self._clean_name(name)
        self._validate_max_group_size(max_group_size)
        if not groups or len(groups) > MAX_GROUPS:
            raise InvalidGroupPlanError(
                f"La propuesta debe tener entre 1 y {MAX_GROUPS} grupos."
            )
        names = [group.name.strip() for group in groups]
        if any(not name for name in names):
            raise InvalidGroupPlanError("Cada grupo debe tener un nombre.")
        if len(set(name.casefold() for name in names)) != len(names):
            raise InvalidGroupPlanError("Los nombres de los grupos no se pueden repetir.")

        assigned_ids = [student_id for group in groups for student_id in group.student_ids]
        if len(assigned_ids) != len(set(assigned_ids)):
            raise InvalidGroupPlanError("Cada estudiante debe pertenecer a un solo grupo.")

        with self._uow_factory() as uow:
            self._require_course(uow, course_id)
            existing = uow.group_plans.get(plan_id)
            if existing is None or existing.course_id != course_id:
                raise GroupPlanNotFoundError(
                    f"La propuesta de grupos {plan_id} no existe en el curso {course_id}."
                )
            active_ids = {student.id for student in uow.students.list_by_course(course_id)}
            if not set(assigned_ids).issubset(active_ids):
                raise InvalidGroupPlanError(
                    "La distribución solo puede incluir estudiantes activos matriculados en el curso."
                )
            normalized_groups = [
                StudentGroup(name=group.name.strip(), student_ids=list(group.student_ids))
                for group in groups
            ]
            updated = uow.group_plans.update(
                plan_id, cleaned_name, max_group_size, normalized_groups
            )
            if updated is None:
                raise GroupPlanNotFoundError(
                    f"La propuesta de grupos {plan_id} no existe en el curso {course_id}."
                )
            uow.commit()
            return updated

    def delete(self, course_id: int, plan_id: int) -> None:
        with self._uow_factory() as uow:
            self._require_course(uow, course_id)
            existing = uow.group_plans.get(plan_id)
            if existing is None or existing.course_id != course_id:
                raise GroupPlanNotFoundError(
                    f"La propuesta de grupos {plan_id} no existe en el curso {course_id}."
                )
            uow.group_plans.delete(plan_id)
            uow.commit()

    @staticmethod
    def _clean_name(name: str) -> str:
        cleaned = " ".join(name.split())
        if not cleaned or len(cleaned) > 255:
            raise InvalidGroupPlanError(
                "El nombre de la propuesta debe tener entre 1 y 255 caracteres."
            )
        return cleaned

    @staticmethod
    def _validate_max_group_size(max_group_size: int) -> None:
        if not 1 <= max_group_size <= MAX_GROUP_SIZE:
            raise InvalidGroupPlanError(
                f"El tamaño máximo debe estar entre 1 y {MAX_GROUP_SIZE}."
            )

    @staticmethod
    def _require_course(uow: UnitOfWork, course_id: int) -> None:
        if uow.courses.get(course_id) is None:
            raise CourseNotFoundError(f"Curso {course_id} no encontrado.")
