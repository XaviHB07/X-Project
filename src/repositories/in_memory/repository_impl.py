"""Implementaciones in-memory de los repositorios + una "base de datos"
en proceso (`InMemoryDatabase`) que las respalda a todas.

El punto de diseño más importante de este archivo es `write_lock`: un
`threading.Lock` que `get_candidates_for_update` adquiere y que solo se
libera cuando la unidad de trabajo hace `commit()` o `rollback()`. Esto
reproduce, de forma simplificada, la misma garantía que
`SELECT ... FOR UPDATE` da en una base de datos real: mientras una
"transacción" tiene el candado, ninguna otra puede leer-para-actualizar
ni escribir el estado, así que no hay forma de que se pierda una
actualización por una carrera entre threads. `tests/test_concurrency.py`
lo demuestra lanzando varios threads a competir por los mismos
estudiantes.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from dataclasses import replace
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from src.domain.entities import (
    AttendanceRecord,
    ClassSession,
    Course,
    DecisionRun,
    Participation,
    Student,
    SyllabusEntry,
)
from src.domain.value_objects import (
    Candidate,
    GenericCountersUpdate,
    PosteriorUpdate,
    SelectionEventRecord,
)
from src.repositories.interfaces import (
    AttendanceRepository,
    ClassSessionRepository,
    CourseRepository,
    DecisionRunRepository,
    DuplicateStudentError,
    EventRepository,
    ParticipationError,
    ParticipationRepository,
    StudentRepository,
    StudentStateRepository,
    SyllabusRepository,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class _MutableStudentState:
    """Representación interna MUTABLE del estado bayesiano.

    A diferencia de `domain.value_objects.Candidate` (inmutable, lo que
    ven las estrategias), esta clase es un detalle interno de
    almacenamiento -- el equivalente in-memory de una fila de la tabla
    `student_state`. Nunca se expone fuera de este módulo.
    """

    student_id: int
    alpha: float
    beta: float
    n_present: int = 0
    n_selected: int = 0
    updated_at: datetime = field(default_factory=_utcnow)

    def to_candidate(self) -> Candidate:
        return Candidate(
            student_id=self.student_id,
            alpha=self.alpha,
            beta=self.beta,
            n_present=self.n_present,
            n_selected=self.n_selected,
        )


class InMemoryDatabase:
    """"Base de datos" en memoria compartida por todos los repositorios
    in-memory de una misma instancia. Pensada para vivir durante todo un
    proceso (una simulación completa, o la vida de un test).
    """

    def __init__(self) -> None:
        self.courses: Dict[int, Course] = {}
        self.students: Dict[int, Student] = {}
        self.student_states: Dict[int, _MutableStudentState] = {}
        self.class_sessions: Dict[int, ClassSession] = {}
        self.syllabus: Dict[int, SyllabusEntry] = {}
        self.attendance: Dict[Tuple[int, int], AttendanceRecord] = {}
        self.decision_runs: Dict[int, DecisionRun] = {}
        self.events: List[SelectionEventRecord] = []
        self.participations: Dict[int, Participation] = {}

        self._counters: Dict[str, int] = {}
        self._meta_lock = threading.Lock()  # protege solo la asignación de ids
        self.write_lock = threading.Lock()  # emula SELECT ... FOR UPDATE (ver docstring del módulo)

    def next_id(self, table: str) -> int:
        with self._meta_lock:
            self._counters[table] = self._counters.get(table, 0) + 1
            return self._counters[table]


class InMemoryCourseRepository(CourseRepository):
    def __init__(self, db: InMemoryDatabase):
        self._db = db

    def create(self, name: str) -> Course:
        course = Course(id=self._db.next_id("courses"), name=name, created_at=_utcnow())
        self._db.courses[course.id] = course
        return course

    def get(self, course_id: int) -> Optional[Course]:
        return self._db.courses.get(course_id)

    def list_all(self) -> List[Course]:
        return sorted(self._db.courses.values(), key=lambda c: c.id)


class InMemoryStudentRepository(StudentRepository):
    def __init__(self, db: InMemoryDatabase):
        self._db = db

    def get_or_create(
        self,
        course_id: int,
        external_ref: str,
        display_name: str,
        alpha_init: float,
        beta_init: float,
        phone_number: Optional[str] = None,
        email: Optional[str] = None,
    ) -> Student:
        for s in self._db.students.values():
            if s.course_id == course_id and s.external_ref == external_ref:
                return s

        student = Student(
            id=self._db.next_id("students"),
            course_id=course_id,
            external_ref=external_ref,
            display_name=display_name,
            created_at=_utcnow(),
            phone_number=phone_number,
            email=email,
        )
        self._db.students[student.id] = student
        self._db.student_states[student.id] = _MutableStudentState(
            student_id=student.id, alpha=alpha_init, beta=beta_init
        )
        return student

    def upsert_from_roster(
        self,
        course_id: int,
        external_ref: str,
        display_name: str,
        alpha_init: float,
        beta_init: float,
        phone_number: Optional[str] = None,
        email: Optional[str] = None,
    ) -> Tuple[Student, str]:
        for s in self._db.students.values():
            if s.course_id == course_id and s.external_ref == external_ref:
                if (
                    s.display_name == display_name
                    and s.active
                    and (phone_number is None or s.phone_number == phone_number)
                    and (email is None or s.email == email)
                ):
                    return s, "unchanged"
                updated = replace(
                    s,
                    display_name=display_name,
                    active=True,
                    phone_number=phone_number if phone_number is not None else s.phone_number,
                    email=email if email is not None else s.email,
                )
                self._db.students[s.id] = updated
                return updated, "updated"
        student = self.get_or_create(
            course_id, external_ref, display_name, alpha_init, beta_init, phone_number, email
        )
        return student, "created"

    def update(
        self,
        student_id: int,
        external_ref: Optional[str] = None,
        display_name: Optional[str] = None,
        active: Optional[bool] = None,
        phone_number: Optional[str] = None,
        email: Optional[str] = None,
    ) -> Optional[Student]:
        current = self._db.students.get(student_id)
        if current is None:
            return None
        if external_ref is not None and external_ref != current.external_ref:
            for other in self._db.students.values():
                if other.course_id == current.course_id and other.external_ref == external_ref:
                    raise DuplicateStudentError(
                        f"Ya existe un estudiante con el código {external_ref!r} en este curso."
                    )
        changes = {
            key: value
            for key, value in (
                ("external_ref", external_ref),
                ("display_name", display_name),
                ("active", active),
            )
            if value is not None
        }
        if phone_number is not None:
            changes["phone_number"] = phone_number or None
        if email is not None:
            changes["email"] = email or None
        updated = replace(current, **changes)
        self._db.students[student_id] = updated
        return updated

    def get(self, student_id: int) -> Optional[Student]:
        return self._db.students.get(student_id)

    def list_by_course(self, course_id: int, include_inactive: bool = False) -> List[Student]:
        return sorted(
            (
                s
                for s in self._db.students.values()
                if s.course_id == course_id and (include_inactive or s.active)
            ),
            key=lambda s: s.id,
        )


class InMemoryStudentStateRepository(StudentStateRepository):
    def __init__(self, db: InMemoryDatabase):
        self._db = db

    def get_candidates_for_update(self, student_ids: Sequence[int]) -> List[Candidate]:
        # Adquiere el candado "de escritura" de toda la base in-memory y
        # lo mantiene hasta que la Unit of Work llame a commit/rollback
        # (ver `InMemoryUnitOfWork`). Es deliberadamente grueso (bloquea
        # TODA la base, no solo las filas pedidas) -- igual que hace
        # SQLite en disco -- porque el objetivo aquí es demostrar la
        # ausencia de "lost updates", no maximizar el paralelismo de la
        # simulación.
        self._db.write_lock.acquire()
        return [
            self._db.student_states[i].to_candidate()
            for i in student_ids
            if i in self._db.student_states
        ]

    def get_candidates_readonly(self, student_ids: Sequence[int]) -> List[Candidate]:
        return [
            self._db.student_states[i].to_candidate()
            for i in student_ids
            if i in self._db.student_states
        ]

    def get_all_candidates_for_course(self, course_id: int) -> List[Candidate]:
        ids = [s.id for s in self._db.students.values() if s.course_id == course_id]
        return self.get_candidates_readonly(ids)

    def apply_updates(
        self,
        generic_updates: List[GenericCountersUpdate],
        posterior_updates: List[PosteriorUpdate],
    ) -> None:
        posterior_by_id: Dict[int, PosteriorUpdate] = {u.student_id: u for u in posterior_updates}
        for g in generic_updates:
            state = self._db.student_states[g.student_id]
            p = posterior_by_id.get(g.student_id)
            state.n_present += 1 if g.present else 0
            state.n_selected += 1 if g.selected else 0
            state.alpha += p.delta_alpha if p else 0.0
            state.beta += p.delta_beta if p else 0.0
            state.updated_at = _utcnow()


class InMemoryClassSessionRepository(ClassSessionRepository):
    def __init__(self, db: InMemoryDatabase):
        self._db = db

    def create(
        self,
        course_id: int,
        label: Optional[str] = None,
        session_date: Optional[date] = None,
        topic: Optional[str] = None,
    ) -> ClassSession:
        now = _utcnow()
        session = ClassSession(
            id=self._db.next_id("class_sessions"),
            course_id=course_id,
            created_at=now,
            label=label,
            session_date=session_date or now.date(),
            topic=topic,
        )
        self._db.class_sessions[session.id] = session
        return session

    def get(self, class_session_id: int) -> Optional[ClassSession]:
        return self._db.class_sessions.get(class_session_id)

    def list_by_course(self, course_id: int) -> List[ClassSession]:
        return sorted(
            (s for s in self._db.class_sessions.values() if s.course_id == course_id),
            key=lambda s: s.id,
            reverse=True,
        )


class InMemorySyllabusRepository(SyllabusRepository):
    def __init__(self, db: InMemoryDatabase):
        self._db = db

    def upsert(self, course_id: int, session_date: date, topic: str) -> SyllabusEntry:
        for entry in self._db.syllabus.values():
            if entry.course_id == course_id and entry.session_date == session_date:
                updated = replace(entry, topic=topic)
                self._db.syllabus[entry.id] = updated
                return updated
        entry = SyllabusEntry(
            id=self._db.next_id("syllabus"), course_id=course_id, session_date=session_date, topic=topic
        )
        self._db.syllabus[entry.id] = entry
        return entry

    def get_topic_for_date(self, course_id: int, session_date: date) -> Optional[str]:
        for entry in self._db.syllabus.values():
            if entry.course_id == course_id and entry.session_date == session_date:
                return entry.topic
        return None

    def list_by_course(self, course_id: int) -> List[SyllabusEntry]:
        return sorted(
            (e for e in self._db.syllabus.values() if e.course_id == course_id),
            key=lambda e: e.session_date,
        )


class InMemoryAttendanceRepository(AttendanceRepository):
    def __init__(self, db: InMemoryDatabase):
        self._db = db

    def set_many(self, class_session_id: int, present_by_student: Dict[int, bool]) -> None:
        for student_id, present in present_by_student.items():
            self._db.attendance[(class_session_id, student_id)] = AttendanceRecord(
                class_session_id=class_session_id, student_id=student_id, present=bool(present)
            )

    def list_for_session(self, class_session_id: int) -> List[AttendanceRecord]:
        return sorted(
            (r for (sid, _), r in self._db.attendance.items() if sid == class_session_id),
            key=lambda r: r.student_id,
        )

    def present_ids(self, class_session_id: int) -> List[int]:
        return [r.student_id for r in self.list_for_session(class_session_id) if r.present]


class InMemoryDecisionRunRepository(DecisionRunRepository):
    def __init__(self, db: InMemoryDatabase):
        self._db = db

    def create(
        self,
        class_session_id: int,
        method_name: str,
        k_requested: int,
        k_selected: int,
        request_id: Optional[str],
    ) -> DecisionRun:
        run = DecisionRun(
            id=self._db.next_id("decision_runs"),
            class_session_id=class_session_id,
            method_name=method_name,
            k_requested=k_requested,
            k_selected=k_selected,
            created_at=_utcnow(),
            request_id=request_id,
        )
        self._db.decision_runs[run.id] = run
        return run

    def get(self, decision_run_id: int) -> Optional[DecisionRun]:
        return self._db.decision_runs.get(decision_run_id)


class InMemoryEventRepository(EventRepository):
    def __init__(self, db: InMemoryDatabase):
        self._db = db

    def log_decision(
        self,
        decision_run_id: int,
        considered_before: Dict[int, Candidate],
        selected_ids: List[int],
        posterior_updates: Dict[int, PosteriorUpdate],
    ) -> None:
        selected_set = set(selected_ids)
        for student_id, before in considered_before.items():
            p = posterior_updates.get(student_id)
            delta_alpha = p.delta_alpha if p else 0.0
            delta_beta = p.delta_beta if p else 0.0
            record = SelectionEventRecord(
                id=self._db.next_id("selection_events"),
                decision_run_id=decision_run_id,
                student_id=student_id,
                present=True,
                selected=student_id in selected_set,
                alpha_before=before.alpha,
                beta_before=before.beta,
                alpha_after=before.alpha + delta_alpha,
                beta_after=before.beta + delta_beta,
                created_at=_utcnow(),
            )
            self._db.events.append(record)

    def history_for_student(self, student_id: int, limit: int = 100) -> List[SelectionEventRecord]:
        matches = [e for e in self._db.events if e.student_id == student_id]
        matches.sort(key=lambda e: e.created_at, reverse=True)
        return matches[:limit]


class InMemoryParticipationRepository(ParticipationRepository):
    """Participaciones en memoria (HU-P4), para tests y simulacion.

    Reproduce las MISMAS validaciones que la implementacion de SQLAlchemy:
    estudiante tiene que pertenecer al curso de la sesion, y el sorteo tiene
    que ser de esa sesion. Si el repositorio en memoria fuera mas permisivo,
    los tests pasarian con datos invalidos y el fallo apareceria solo en
    produccion, que es justo lo que la arquitectura en capas evita.
    """

    def __init__(self, db: InMemoryDatabase):
        self._db = db

    def create(
        self,
        class_session_id: int,
        student_id: int,
        question: str,
        answer: Optional[str],
        asked_at,
        decision_run_id: Optional[int] = None,
        created_by: Optional[str] = None,
        present: bool = True,
    ) -> Participation:
        question = (question or "").strip()
        if not question:
            raise ParticipationError("la pregunta no puede ir vacia")

        sesion = self._db.class_sessions.get(class_session_id)
        if sesion is None:
            raise ParticipationError(f"la sesion {class_session_id} no existe")

        estudiante = self._db.students.get(student_id)
        if estudiante is None:
            raise ParticipationError(f"el estudiante {student_id} no existe")
        if estudiante.course_id != sesion.course_id:
            raise ParticipationError(
                f"el estudiante {student_id} pertenece al curso "
                f"{estudiante.course_id}, no al curso {sesion.course_id} de la "
                f"sesion {class_session_id}"
            )

        if decision_run_id is not None:
            run = self._db.decision_runs.get(decision_run_id)
            if run is None:
                raise ParticipationError(f"el sorteo {decision_run_id} no existe")
            if run.class_session_id != class_session_id:
                raise ParticipationError(
                    f"el sorteo {decision_run_id} es de otra sesion"
                )

        with self._db.write_lock:
            pid = self._db.next_id("participations")
        item = Participation(
            id=pid,
            class_session_id=class_session_id,
            student_id=student_id,
            question=question,
            asked_at=asked_at,
            answer=(answer or None),
            decision_run_id=decision_run_id,
            present=present,
            created_by=created_by,
        )
        self._db.participations[pid] = item
        return item

    def get(self, participation_id: int) -> Optional[Participation]:
        return self._db.participations.get(participation_id)

    def list_for_session(self, class_session_id: int,
                         include_anuladas: bool = False) -> List[Participation]:
        out = [p for p in self._db.participations.values()
               if p.class_session_id == class_session_id]
        if not include_anuladas:
            out = [p for p in out if not p.anulada]
        out.sort(key=lambda p: (p.asked_at, p.id))
        return out

    def list_for_student(self, student_id: int,
                         include_anuladas: bool = False) -> List[Participation]:
        out = [p for p in self._db.participations.values()
               if p.student_id == student_id]
        if not include_anuladas:
            out = [p for p in out if not p.anulada]
        out.sort(key=lambda p: (p.asked_at, p.id), reverse=True)
        return out

    def count_for_session(self, class_session_id: int) -> int:
        return len([p for p in self._db.participations.values()
                    if p.class_session_id == class_session_id and not p.anulada])

    def anular(self, participation_id: int,
               motivo: Optional[str] = None) -> Optional[Participation]:
        item = self._db.participations.get(participation_id)
        if item is None:
            return None
        # `Participation` es un dataclass FROZEN (inmutable, como todas las
        # entidades de dominio). Anular no la muta: se crea una copia
        # modificada con `replace` y se guarda en su lugar. Es el mismo patrón
        # que usa `_MutableStudentState` para el estado bayesiano.
        actualizado = replace(
            item, anulada=True, motivo_anulacion=(motivo or None)
        )
        self._db.participations[participation_id] = actualizado
        return actualizado
