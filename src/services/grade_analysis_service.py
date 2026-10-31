"""Resumen semanal de notas para docentes."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Callable

from src.repositories.interfaces import UnitOfWork
from src.services.errors import CourseNotFoundError

UnitOfWorkFactory = Callable[[], UnitOfWork]
WEEK_COUNT = 15


class GradeAnalysisError(ValueError):
    """El análisis no puede generarse con los filtros recibidos."""


class GradeAnalysisService:
    def __init__(self, uow_factory: UnitOfWorkFactory):
        self._uow_factory = uow_factory

    def weekly_matrix(self, course_id: int, cycle_id: int) -> dict:
        with self._uow_factory() as uow:
            course = uow.courses.get(course_id)
            if course is None:
                raise CourseNotFoundError(f"Curso {course_id} no encontrado.")
            if course.cycle_id != cycle_id:
                raise GradeAnalysisError(
                    "El curso seleccionado no pertenece al ciclo académico indicado."
                )
            cycle = uow.cycles.get(cycle_id)
            if cycle is None:
                raise GradeAnalysisError(
                    "El ciclo académico seleccionado no existe."
                )
            if cycle.starts_on is None:
                raise GradeAnalysisError(
                    "Configura la fecha de inicio del ciclo antes de consultar el análisis."
                )

            start_on = cycle.starts_on
            end_on = start_on + timedelta(days=WEEK_COUNT * 7 - 1)
            students = uow.students.list_by_course(course_id)
            averages = uow.participations.weekly_score_averages(
                course_id, start_on, end_on
            )

        totals: dict[tuple[int, int], tuple[float, int]] = {}
        for student_id, session_date, average, count in averages:
            week = ((session_date - start_on).days // 7) + 1
            if 1 <= week <= WEEK_COUNT:
                key = (student_id, week)
                total, previous_count = totals.get(key, (0.0, 0))
                totals[key] = (total + average * count, previous_count + count)
        by_student_week = {
            key: total / count for key, (total, count) in totals.items()
        }

        weeks = [
            {
                "number": week,
                "label": f"Semana {week}",
                "start_on": start_on + timedelta(days=(week - 1) * 7),
                "end_on": start_on + timedelta(days=week * 7 - 1),
            }
            for week in range(1, WEEK_COUNT + 1)
        ]
        return {
            "course_id": course_id,
            "cycle_id": cycle_id,
            "weeks": weeks,
            "students": [
                {
                    "student_id": student.id,
                    "external_ref": student.external_ref,
                    "display_name": student.display_name,
                    "averages": [
                        by_student_week.get((student.id, week))
                        for week in range(1, WEEK_COUNT + 1)
                    ],
                }
                for student in students
            ],
        }

    def weekly_participation_details(
        self, course_id: int, cycle_id: int, student_id: int, week: int
    ) -> dict:
        if not 1 <= week <= WEEK_COUNT:
            raise GradeAnalysisError("La semana debe estar entre 1 y 15.")
        with self._uow_factory() as uow:
            course = uow.courses.get(course_id)
            if course is None:
                raise CourseNotFoundError(f"Curso {course_id} no encontrado.")
            if course.cycle_id != cycle_id:
                raise GradeAnalysisError(
                    "El curso seleccionado no pertenece al ciclo académico indicado."
                )
            cycle = uow.cycles.get(cycle_id)
            if cycle is None or cycle.starts_on is None:
                raise GradeAnalysisError(
                    "Configura la fecha de inicio del ciclo antes de consultar el detalle."
                )
            student = next(
                (item for item in uow.students.list_by_course(course_id)
                 if item.id == student_id),
                None,
            )
            if student is None:
                raise GradeAnalysisError(
                    "El estudiante no pertenece al curso o no está activo."
                )
            start_on = cycle.starts_on + timedelta(days=(week - 1) * 7)
            end_on = start_on + timedelta(days=6)
            details = uow.participations.weekly_details(
                course_id, student_id, start_on, end_on
            )
        return {
            "course_id": course_id,
            "cycle_id": cycle_id,
            "student_id": student_id,
            "student_name": student.display_name,
            "week": week,
            "start_on": start_on,
            "end_on": end_on,
            "total": len(details),
            "participations": [
                {
                    "id": record.id,
                    "session_date": session_date,
                    "occurred_at": occurred_at,
                    "question": record.question,
                    "score": record.score,
                    "comment": record.comment,
                    "present": record.present,
                }
                for record, session_date, occurred_at in details
            ],
        }
