"""Notas de exposiciones grupales.

Cuando la ruleta o el bolillero eligen un GRUPO expositor, el docente
registra una nota grupal y una nota individual por integrante. Es el
equivalente, para grupos, de `student_participations` en la selección
individual (ver `ParticipationRepository`).

Reglas que valida este servicio (la API solo traduce errores a HTTP):

* Las notas usan la misma escala que la participación individual
  (`MIN_SCORE` a `MAX_SCORE`), para que ambas se puedan comparar o
  promediar más adelante sin conversiones.
* Todos los integrantes deben estar matriculados en el curso y no se
  pueden repetir.
* Un integrante presente debe tener nota individual; uno ausente puede
  quedar sin nota (se guarda vacío, no como cero).
* Si se indica una sesión de clase o una propuesta de grupos, deben
  pertenecer al mismo curso.
"""

from __future__ import annotations

import math
from typing import Callable, List, Optional, Sequence

from src.domain.entities import GroupExposition, GroupExpositionMemberEntry
from src.repositories.interfaces import UnitOfWork
from src.services.errors import CourseNotFoundError, SessionNotFoundError

UnitOfWorkFactory = Callable[[], UnitOfWork]

MIN_SCORE = 0.0
MAX_SCORE = 5.0
MAX_GROUP_NAME_LENGTH = 255
MAX_COMMENT_LENGTH = 1000
MAX_MEMBERS = 1000
MAX_DURATION_SECONDS = 24 * 60 * 60


class GroupExpositionNotFoundError(LookupError):
    """La exposición no existe o no pertenece al curso indicado."""


class InvalidGroupExpositionError(ValueError):
    """Los datos de la exposición no cumplen las reglas de registro."""


class GroupExpositionService:
    def __init__(self, uow_factory: UnitOfWorkFactory):
        self._uow_factory = uow_factory

    def record(
        self,
        course_id: int,
        group_name: str,
        group_score: float,
        members: Sequence[GroupExpositionMemberEntry],
        class_session_id: Optional[int] = None,
        group_plan_id: Optional[int] = None,
        comment: Optional[str] = None,
        duration_seconds: Optional[int] = None,
    ) -> GroupExposition:
        """Registra la nota grupal y las notas individuales de un grupo."""
        cleaned_name = " ".join((group_name or "").split())
        if not cleaned_name or len(cleaned_name) > MAX_GROUP_NAME_LENGTH:
            raise InvalidGroupExpositionError(
                f"El nombre del grupo debe tener entre 1 y {MAX_GROUP_NAME_LENGTH} caracteres."
            )
        self._validate_score(group_score, "La nota grupal")
        cleaned_comment = self._clean_comment(comment)
        self._validate_duration(duration_seconds)
        with self._uow_factory() as uow:
            self._require_course(uow, course_id)
            entries = self._validate_members(uow, course_id, members)
            if class_session_id is not None:
                session = uow.class_sessions.get(class_session_id)
                if session is None or session.course_id != course_id:
                    raise SessionNotFoundError(
                        f"La sesión {class_session_id} no existe en el curso {course_id}."
                    )
            plan_name = None
            if group_plan_id is not None:
                plan = uow.group_plans.get(group_plan_id)
                if plan is None or plan.course_id != course_id:
                    raise InvalidGroupExpositionError(
                        f"La propuesta de grupos {group_plan_id} no existe en el curso {course_id}."
                    )
                plan_name = plan.name
            exposition = uow.group_expositions.create(
                course_id=course_id,
                group_name=cleaned_name,
                group_score=float(group_score),
                members=entries,
                class_session_id=class_session_id,
                group_plan_id=group_plan_id,
                plan_name=plan_name,
                comment=cleaned_comment,
                duration_seconds=duration_seconds,
            )
            uow.commit()
            return exposition

    def update(
        self,
        course_id: int,
        exposition_id: int,
        group_score: float,
        members: Sequence[GroupExpositionMemberEntry],
        comment: Optional[str] = None,
        duration_seconds: Optional[int] = None,
    ) -> GroupExposition:
        """Corrige las notas de una exposición ya registrada."""
        self._validate_score(group_score, "La nota grupal")
        cleaned_comment = self._clean_comment(comment)
        self._validate_duration(duration_seconds)
        with self._uow_factory() as uow:
            self._require_course(uow, course_id)
            self._require_exposition(uow, course_id, exposition_id)
            entries = self._validate_members(uow, course_id, members)
            exposition = uow.group_expositions.update(
                exposition_id,
                group_score=float(group_score),
                members=entries,
                comment=cleaned_comment,
                duration_seconds=duration_seconds,
            )
            uow.commit()
            return exposition

    def get(self, course_id: int, exposition_id: int) -> GroupExposition:
        with self._uow_factory() as uow:
            self._require_course(uow, course_id)
            return self._require_exposition(uow, course_id, exposition_id)

    def list_for_course(self, course_id: int, limit: int = 200) -> List[GroupExposition]:
        with self._uow_factory() as uow:
            self._require_course(uow, course_id)
            return uow.group_expositions.list_by_course(course_id, limit=limit)

    @staticmethod
    def _require_course(uow: UnitOfWork, course_id: int) -> None:
        if uow.courses.get(course_id) is None:
            raise CourseNotFoundError(f"Curso {course_id} no encontrado.")

    @staticmethod
    def _require_exposition(
        uow: UnitOfWork, course_id: int, exposition_id: int
    ) -> GroupExposition:
        exposition = uow.group_expositions.get(exposition_id)
        if exposition is None or exposition.course_id != course_id:
            raise GroupExpositionNotFoundError(
                f"La exposición {exposition_id} no existe en el curso {course_id}."
            )
        return exposition

    @staticmethod
    def _validate_score(score: float, label: str) -> None:
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(score)
            or not MIN_SCORE <= score <= MAX_SCORE
        ):
            raise InvalidGroupExpositionError(
                f"{label} debe ser un número entre {MIN_SCORE:g} y {MAX_SCORE:g}."
            )

    @staticmethod
    def _clean_comment(comment: Optional[str]) -> Optional[str]:
        cleaned = (comment or "").strip()
        if len(cleaned) > MAX_COMMENT_LENGTH:
            raise InvalidGroupExpositionError(
                f"El comentario no puede superar los {MAX_COMMENT_LENGTH} caracteres."
            )
        return cleaned or None

    @staticmethod
    def _validate_duration(duration_seconds: Optional[int]) -> None:
        if duration_seconds is not None and not 0 <= duration_seconds <= MAX_DURATION_SECONDS:
            raise InvalidGroupExpositionError("La duración de la exposición no es válida.")

    def _validate_members(
        self,
        uow: UnitOfWork,
        course_id: int,
        members: Sequence[GroupExpositionMemberEntry],
    ) -> List[GroupExpositionMemberEntry]:
        if not members or len(members) > MAX_MEMBERS:
            raise InvalidGroupExpositionError(
                "Registra al menos a un integrante del grupo."
            )
        student_ids = [entry.student_id for entry in members]
        if len(student_ids) != len(set(student_ids)):
            raise InvalidGroupExpositionError(
                "No repitas un integrante en la misma exposición."
            )
        # Se incluyen los retirados: una nota ya registrada se puede corregir
        # aunque el estudiante haya dejado el curso después.
        course_student_ids = {
            student.id for student in uow.students.list_by_course(course_id, include_inactive=True)
        }
        if not set(student_ids) <= course_student_ids:
            raise InvalidGroupExpositionError(
                "Todos los integrantes deben estar matriculados en este curso."
            )
        entries = []
        for entry in members:
            if entry.score is None:
                if entry.present:
                    raise InvalidGroupExpositionError(
                        "Cada integrante presente debe tener una nota individual."
                    )
            else:
                self._validate_score(entry.score, "Cada nota individual")
            if entry.position is not None and entry.position < 1:
                raise InvalidGroupExpositionError("El orden de exposición empieza en 1.")
            entries.append(
                GroupExpositionMemberEntry(
                    student_id=entry.student_id,
                    present=bool(entry.present),
                    score=None if entry.score is None else float(entry.score),
                    position=entry.position,
                )
            )
        return entries
