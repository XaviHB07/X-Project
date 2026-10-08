"""Casos de uso de la sesión de clase (HU-S1 y HU-S2).

HU-S1 — iniciar sesión: el docente elige el curso, el sistema propone la
fecha (hoy) y, si hay sílabo cargado, el tema; el docente confirma o
corrige el tema y la sesión queda creada con los estudiantes presentes.

HU-S2 — asistencia: el docente marca quién está presente. Esa marca es
la que usa la selección aleatoria (ver `SelectionService.run_selection`
cuando se la invoca con `class_session_id` y sin `present_student_ids`).

Decisión de diseño: al iniciar la sesión se crea un registro de
asistencia para CADA estudiante activo del curso. Por defecto todos
quedan presentes (es más rápido desmarcar a los 3 ausentes que marcar a
los 37 presentes); si el docente pasa `present_student_ids`, solo esos
quedan presentes. Un estudiante que se matricula DESPUÉS de iniciada la
sesión no tiene registro y cuenta como ausente hasta que se lo marque.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable, Dict, List, Optional, Sequence

from src.domain.entities import ClassSession, Student, SyllabusEntry
from src.repositories.interfaces import UnitOfWork
from src.services.errors import CourseNotFoundError, InvalidAttendanceError, SessionNotFoundError

UnitOfWorkFactory = Callable[[], UnitOfWork]

MAX_TOPIC_LENGTH = 255


def _today() -> date:
    return datetime.now(timezone.utc).date()


@dataclass(frozen=True)
class SessionProposal:
    """Lo que el sistema propone antes de iniciar la sesión (HU-S1)."""

    session_date: date
    suggested_topic: Optional[str]  # None si el curso no tiene sílabo para esa fecha


@dataclass(frozen=True)
class AttendanceEntry:
    student_id: int
    external_ref: str
    display_name: str
    present: bool


@dataclass(frozen=True)
class SessionDetail:
    session: ClassSession
    attendance: List[AttendanceEntry]

    @property
    def present_count(self) -> int:
        return sum(1 for a in self.attendance if a.present)


def _clean_topic(topic: Optional[str]) -> Optional[str]:
    if topic is None:
        return None
    topic = " ".join(topic.split())
    if not topic:
        return None
    if len(topic) > MAX_TOPIC_LENGTH:
        raise ValueError(f"El tema debe tener como máximo {MAX_TOPIC_LENGTH} caracteres.")
    return topic


class SessionService:
    def __init__(self, uow_factory: UnitOfWorkFactory):
        self._uow_factory = uow_factory

    # ------------------------------------------------------------------
    # Sílabo (insumo de la propuesta de tema)
    # ------------------------------------------------------------------
    def set_syllabus_entry(self, course_id: int, session_date: date, topic: str) -> SyllabusEntry:
        cleaned = _clean_topic(topic)
        if cleaned is None:
            raise ValueError("El tema no puede estar vacío.")
        with self._uow_factory() as uow:
            self._require_course(uow, course_id)
            entry = uow.syllabus.upsert(course_id, session_date, cleaned)
            uow.commit()
        return entry

    def list_syllabus(self, course_id: int) -> List[SyllabusEntry]:
        with self._uow_factory() as uow:
            self._require_course(uow, course_id)
            return uow.syllabus.list_by_course(course_id)

    # ------------------------------------------------------------------
    # HU-S1
    # ------------------------------------------------------------------
    def propose(self, course_id: int, session_date: Optional[date] = None) -> SessionProposal:
        session_date = session_date or _today()
        with self._uow_factory() as uow:
            self._require_course(uow, course_id)
            topic = uow.syllabus.get_topic_for_date(course_id, session_date)
        return SessionProposal(session_date=session_date, suggested_topic=topic)

    def start_session(
        self,
        course_id: int,
        topic: Optional[str] = None,
        session_date: Optional[date] = None,
        present_student_ids: Optional[Sequence[int]] = None,
        label: Optional[str] = None,
    ) -> SessionDetail:
        """Inicia una sesión de clase.

        `topic` es el tema CONFIRMADO o corregido por el docente. Si se
        omite (o viene vacío), se usa el del sílabo para esa fecha; si
        tampoco existe, la sesión queda sin tema (no es obligatorio).
        """
        session_date = session_date or _today()
        topic = _clean_topic(topic)

        with self._uow_factory() as uow:
            self._require_course(uow, course_id)
            if topic is None:
                topic = uow.syllabus.get_topic_for_date(course_id, session_date)

            active_students = uow.students.list_by_course(course_id)
            active_ids = {s.id for s in active_students}
            if present_student_ids is None:
                present_set = set(active_ids)
            else:
                present_set = set(present_student_ids)
                unknown = present_set - active_ids
                if unknown:
                    raise InvalidAttendanceError(
                        "Estudiantes que no pertenecen a este curso (o están retirados): "
                        + ", ".join(str(i) for i in sorted(unknown))
                    )

            session = uow.class_sessions.create(
                course_id, label=label, session_date=session_date, topic=topic
            )
            uow.attendance.set_many(session.id, {sid: sid in present_set for sid in active_ids})
            uow.commit()
            return self._detail(uow, session)

    def get_session(self, class_session_id: int) -> SessionDetail:
        with self._uow_factory() as uow:
            session = uow.class_sessions.get(class_session_id)
            if session is None:
                raise SessionNotFoundError(f"La sesión de clase {class_session_id} no existe.")
            return self._detail(uow, session)

    def list_sessions(self, course_id: int) -> List[ClassSession]:
        with self._uow_factory() as uow:
            self._require_course(uow, course_id)
            return uow.class_sessions.list_by_course(course_id)

    # ------------------------------------------------------------------
    # HU-S2
    # ------------------------------------------------------------------
    def set_attendance(self, class_session_id: int, present_by_student: Dict[int, bool]) -> SessionDetail:
        """Marca/desmarca la asistencia de uno o varios estudiantes.

        Solo se aceptan estudiantes ACTIVOS del curso de la sesión; si
        alguno no lo es, no se guarda nada (todo o nada)."""
        if not present_by_student:
            raise InvalidAttendanceError("No se indicó ningún estudiante.")
        with self._uow_factory() as uow:
            session = uow.class_sessions.get(class_session_id)
            if session is None:
                raise SessionNotFoundError(f"La sesión de clase {class_session_id} no existe.")
            active_ids = {s.id for s in uow.students.list_by_course(session.course_id)}
            unknown = set(present_by_student) - active_ids
            if unknown:
                raise InvalidAttendanceError(
                    "Estudiantes que no pertenecen al curso de la sesión (o están retirados): "
                    + ", ".join(str(i) for i in sorted(unknown))
                )
            uow.attendance.set_many(class_session_id, present_by_student)
            uow.commit()
            return self._detail(uow, session)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _require_course(uow: UnitOfWork, course_id: int) -> None:
        if uow.courses.get(course_id) is None:
            raise CourseNotFoundError(f"Curso {course_id} no encontrado.")

    @staticmethod
    def _detail(uow: UnitOfWork, session: ClassSession) -> SessionDetail:
        """Asistencia de TODOS los estudiantes activos del curso: quien no
        tiene registro (se matriculó después) figura como ausente."""
        marks = {r.student_id: r.present for r in uow.attendance.list_for_session(session.id)}
        students: List[Student] = uow.students.list_by_course(session.course_id)
        entries = [
            AttendanceEntry(
                student_id=s.id,
                external_ref=s.external_ref,
                display_name=s.display_name,
                present=marks.get(s.id, False),
            )
            for s in students
        ]
        return SessionDetail(session=session, attendance=entries)
