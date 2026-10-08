"""Implementaciones concretas de los repositorios, respaldadas por
SQLAlchemy. Este es el archivo donde se resuelve, en SQL real, la
recomendación central del asesor: "lectura con bloqueo + actualización
atómica dentro de una transacción".

Todas las clases reciben una `Session` de SQLAlchemy ya abierta (se la
inyecta `SqlAlchemyUnitOfWork`, ver `unit_of_work.py`) — ninguna abre su
propia conexión ni hace su propio commit: la transacción es
responsabilidad exclusiva de la Unit of Work.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

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
from src.repositories.sqlalchemy.models import (
    ClassSessionORM,
    CourseORM,
    DecisionRunORM,
    ParticipationORM,
    SelectionEventORM,
    SessionAttendanceORM,
    StudentORM,
    StudentStateORM,
    SyllabusEntryORM,
)


def _to_candidate(row: StudentStateORM) -> Candidate:
    return Candidate(
        student_id=row.student_id,
        alpha=row.alpha,
        beta=row.beta,
        n_present=row.n_present,
        n_selected=row.n_selected,
    )


def _to_student(row: StudentORM) -> Student:
    return Student(
        id=row.id,
        course_id=row.course_id,
        external_ref=row.external_ref,
        display_name=row.display_name,
        created_at=row.created_at,
        phone_number=row.phone_number,
        email=row.email,
        active=row.active,
    )


def _to_class_session(row: ClassSessionORM) -> ClassSession:
    return ClassSession(
        id=row.id,
        course_id=row.course_id,
        created_at=row.created_at,
        label=row.label,
        session_date=row.session_date,
        topic=row.topic,
    )


class SqlAlchemyCourseRepository(CourseRepository):
    def __init__(self, session: Session):
        self._session = session

    def create(self, name: str) -> Course:
        row = CourseORM(name=name)
        self._session.add(row)
        self._session.flush()  # asigna row.id sin necesidad de commit
        return Course(id=row.id, name=row.name, created_at=row.created_at)

    def get(self, course_id: int) -> Optional[Course]:
        row = self._session.get(CourseORM, course_id)
        if row is None:
            return None
        return Course(id=row.id, name=row.name, created_at=row.created_at)

    def list_all(self) -> List[Course]:
        rows = self._session.execute(select(CourseORM).order_by(CourseORM.id)).scalars().all()
        return [Course(id=r.id, name=r.name, created_at=r.created_at) for r in rows]


class SqlAlchemyStudentRepository(StudentRepository):
    def __init__(self, session: Session):
        self._session = session

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
        existing = self._session.execute(
            select(StudentORM).where(
                StudentORM.course_id == course_id,
                StudentORM.external_ref == external_ref,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return _to_student(existing)

        row = StudentORM(
            course_id=course_id,
            external_ref=external_ref,
            display_name=display_name,
            phone_number=phone_number,
            email=email,
        )
        self._session.add(row)
        self._session.flush()  # necesitamos row.id antes de crear el estado

        state = StudentStateORM(student_id=row.id, alpha=alpha_init, beta=beta_init)
        self._session.add(state)
        self._session.flush()

        return _to_student(row)

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
        existing = self._session.execute(
            select(StudentORM).where(
                StudentORM.course_id == course_id,
                StudentORM.external_ref == external_ref,
            )
        ).scalar_one_or_none()
        if existing is None:
            return self.get_or_create(
                course_id, external_ref, display_name, alpha_init, beta_init, phone_number, email
            ), "created"
        if (
            existing.display_name == display_name
            and existing.active
            and (phone_number is None or existing.phone_number == phone_number)
            and (email is None or existing.email == email)
        ):
            return _to_student(existing), "unchanged"
        existing.display_name = display_name
        existing.active = True
        if phone_number is not None:
            existing.phone_number = phone_number
        if email is not None:
            existing.email = email
        self._session.flush()
        return _to_student(existing), "updated"

    def update(
        self,
        student_id: int,
        external_ref: Optional[str] = None,
        display_name: Optional[str] = None,
        active: Optional[bool] = None,
        phone_number: Optional[str] = None,
        email: Optional[str] = None,
    ) -> Optional[Student]:
        row = self._session.get(StudentORM, student_id)
        if row is None:
            return None
        if external_ref is not None and external_ref != row.external_ref:
            clash = self._session.execute(
                select(StudentORM.id).where(
                    StudentORM.course_id == row.course_id,
                    StudentORM.external_ref == external_ref,
                    StudentORM.id != row.id,
                )
            ).first()
            if clash is not None:
                raise DuplicateStudentError(
                    f"Ya existe un estudiante con el código {external_ref!r} en este curso."
                )
            row.external_ref = external_ref
        if display_name is not None:
            row.display_name = display_name
        if active is not None:
            row.active = active
        if phone_number is not None:
            row.phone_number = phone_number or None
        if email is not None:
            row.email = email or None
        self._session.flush()
        return _to_student(row)

    def get(self, student_id: int) -> Optional[Student]:
        row = self._session.get(StudentORM, student_id)
        return _to_student(row) if row is not None else None

    def list_by_course(self, course_id: int, include_inactive: bool = False) -> List[Student]:
        stmt = select(StudentORM).where(StudentORM.course_id == course_id)
        if not include_inactive:
            stmt = stmt.where(StudentORM.active.is_(True))
        rows = self._session.execute(stmt.order_by(StudentORM.id)).scalars().all()
        return [_to_student(r) for r in rows]


class SqlAlchemyStudentStateRepository(StudentStateRepository):
    def __init__(self, session: Session):
        self._session = session

    def get_candidates_for_update(self, student_ids: Sequence[int]) -> List[Candidate]:
        if not student_ids:
            return []
        # `.with_for_update()` compila a `SELECT ... FOR UPDATE`. En
        # PostgreSQL/MySQL esto toma un bloqueo de escritura sobre esas
        # filas exactas hasta el commit/rollback de la transacción
        # actual: cualquier otra transacción que intente leer estas
        # mismas filas con FOR UPDATE (o escribirlas) espera hasta que
        # esta termine. Así se evita que dos decisiones de selección
        # concurrentes sobre el mismo estudiante lean el mismo alpha/beta
        # "viejo" y una de las dos actualizaciones se pierda.
        #
        # Nota sobre SQLite (el motor por defecto de este proyecto para
        # desarrollo local): SQLite no soporta bloqueo por fila -- ya
        # serializa toda la base de datos a nivel de archivo en cuanto
        # una transacción escribe. `with_for_update()` es entonces un
        # no-op inofensivo ahí, pero la garantía de "no lost updates" se
        # mantiene igual (de forma más burda, bloqueando todo en vez de
        # solo las filas relevantes). En PostgreSQL sí se obtiene el
        # bloqueo fino por fila. Ver el README, sección "Concurrencia y
        # elección de base de datos".
        stmt = (
            select(StudentStateORM)
            .where(StudentStateORM.student_id.in_(student_ids))
            .with_for_update()
        )
        rows = self._session.execute(stmt).scalars().all()
        return [_to_candidate(r) for r in rows]

    def get_candidates_readonly(self, student_ids: Sequence[int]) -> List[Candidate]:
        if not student_ids:
            return []
        stmt = select(StudentStateORM).where(StudentStateORM.student_id.in_(student_ids))
        rows = self._session.execute(stmt).scalars().all()
        return [_to_candidate(r) for r in rows]

    def get_all_candidates_for_course(self, course_id: int) -> List[Candidate]:
        stmt = (
            select(StudentStateORM)
            .join(StudentORM, StudentORM.id == StudentStateORM.student_id)
            .where(StudentORM.course_id == course_id)
        )
        rows = self._session.execute(stmt).scalars().all()
        return [_to_candidate(r) for r in rows]

    def apply_updates(
        self,
        generic_updates: List[GenericCountersUpdate],
        posterior_updates: List[PosteriorUpdate],
    ) -> None:
        posterior_by_id: Dict[int, PosteriorUpdate] = {u.student_id: u for u in posterior_updates}

        for g in generic_updates:
            p = posterior_by_id.get(g.student_id)
            delta_alpha = p.delta_alpha if p else 0.0
            delta_beta = p.delta_beta if p else 0.0

            # ESTA es la actualización atómica: `alpha = alpha + delta`
            # se resuelve enteramente en el motor de base de datos, en
            # una sola sentencia SQL, sin pasar por un ciclo
            # "leer valor en Python -> sumar -> escribir valor". Ese
            # ciclo es exactamente lo que produce "lost updates" cuando
            # dos transacciones lo hacen al mismo tiempo sobre el mismo
            # valor leído. Combinado con el bloqueo de
            # `get_candidates_for_update`, esto hace que toda la
            # secuencia lectura -> decisión -> escritura sea segura bajo
            # concurrencia.
            stmt = (
                update(StudentStateORM)
                .where(StudentStateORM.student_id == g.student_id)
                .values(
                    n_present=StudentStateORM.n_present + (1 if g.present else 0),
                    n_selected=StudentStateORM.n_selected + (1 if g.selected else 0),
                    alpha=StudentStateORM.alpha + delta_alpha,
                    beta=StudentStateORM.beta + delta_beta,
                )
            )
            self._session.execute(stmt)


class SqlAlchemyClassSessionRepository(ClassSessionRepository):
    def __init__(self, session: Session):
        self._session = session

    def create(
        self,
        course_id: int,
        label: Optional[str] = None,
        session_date: Optional[date] = None,
        topic: Optional[str] = None,
    ) -> ClassSession:
        row = ClassSessionORM(
            course_id=course_id,
            label=label,
            session_date=session_date or datetime.now(timezone.utc).date(),
            topic=topic,
        )
        self._session.add(row)
        self._session.flush()
        return _to_class_session(row)

    def get(self, class_session_id: int) -> Optional[ClassSession]:
        row = self._session.get(ClassSessionORM, class_session_id)
        return _to_class_session(row) if row is not None else None

    def list_by_course(self, course_id: int) -> List[ClassSession]:
        rows = self._session.execute(
            select(ClassSessionORM)
            .where(ClassSessionORM.course_id == course_id)
            .order_by(ClassSessionORM.id.desc())
        ).scalars().all()
        return [_to_class_session(r) for r in rows]


class SqlAlchemySyllabusRepository(SyllabusRepository):
    def __init__(self, session: Session):
        self._session = session

    @staticmethod
    def _to_entry(row: SyllabusEntryORM) -> SyllabusEntry:
        return SyllabusEntry(
            id=row.id, course_id=row.course_id, session_date=row.session_date, topic=row.topic
        )

    def upsert(self, course_id: int, session_date: date, topic: str) -> SyllabusEntry:
        row = self._session.execute(
            select(SyllabusEntryORM).where(
                SyllabusEntryORM.course_id == course_id,
                SyllabusEntryORM.session_date == session_date,
            )
        ).scalar_one_or_none()
        if row is None:
            row = SyllabusEntryORM(course_id=course_id, session_date=session_date, topic=topic)
            self._session.add(row)
        else:
            row.topic = topic
        self._session.flush()
        return self._to_entry(row)

    def get_topic_for_date(self, course_id: int, session_date: date) -> Optional[str]:
        return self._session.execute(
            select(SyllabusEntryORM.topic).where(
                SyllabusEntryORM.course_id == course_id,
                SyllabusEntryORM.session_date == session_date,
            )
        ).scalar_one_or_none()

    def list_by_course(self, course_id: int) -> List[SyllabusEntry]:
        rows = self._session.execute(
            select(SyllabusEntryORM)
            .where(SyllabusEntryORM.course_id == course_id)
            .order_by(SyllabusEntryORM.session_date)
        ).scalars().all()
        return [self._to_entry(r) for r in rows]


class SqlAlchemyAttendanceRepository(AttendanceRepository):
    def __init__(self, session: Session):
        self._session = session

    def set_many(self, class_session_id: int, present_by_student: Dict[int, bool]) -> None:
        if not present_by_student:
            return
        existing = {
            r.student_id: r
            for r in self._session.execute(
                select(SessionAttendanceORM).where(
                    SessionAttendanceORM.class_session_id == class_session_id,
                    SessionAttendanceORM.student_id.in_(list(present_by_student)),
                )
            ).scalars()
        }
        for student_id, present in present_by_student.items():
            row = existing.get(student_id)
            if row is None:
                self._session.add(
                    SessionAttendanceORM(
                        class_session_id=class_session_id, student_id=student_id, present=bool(present)
                    )
                )
            else:
                row.present = bool(present)
        self._session.flush()

    def list_for_session(self, class_session_id: int) -> List[AttendanceRecord]:
        rows = self._session.execute(
            select(SessionAttendanceORM)
            .where(SessionAttendanceORM.class_session_id == class_session_id)
            .order_by(SessionAttendanceORM.student_id)
        ).scalars().all()
        return [
            AttendanceRecord(
                class_session_id=r.class_session_id, student_id=r.student_id, present=r.present
            )
            for r in rows
        ]

    def present_ids(self, class_session_id: int) -> List[int]:
        return [r.student_id for r in self.list_for_session(class_session_id) if r.present]


class SqlAlchemyDecisionRunRepository(DecisionRunRepository):
    def __init__(self, session: Session):
        self._session = session

    def create(
        self,
        class_session_id: int,
        method_name: str,
        k_requested: int,
        k_selected: int,
        request_id: Optional[str],
    ) -> DecisionRun:
        row = DecisionRunORM(
            class_session_id=class_session_id,
            method_name=method_name,
            k_requested=k_requested,
            k_selected=k_selected,
            request_id=request_id,
        )
        self._session.add(row)
        self._session.flush()
        return DecisionRun(
            id=row.id,
            class_session_id=row.class_session_id,
            method_name=row.method_name,
            k_requested=row.k_requested,
            k_selected=row.k_selected,
            created_at=row.created_at,
            request_id=row.request_id,
        )

    def get(self, decision_run_id: int) -> Optional[DecisionRun]:
        row = self._session.get(DecisionRunORM, decision_run_id)
        if row is None:
            return None
        return DecisionRun(
            id=row.id,
            class_session_id=row.class_session_id,
            method_name=row.method_name,
            k_requested=row.k_requested,
            k_selected=row.k_selected,
            created_at=row.created_at,
            request_id=row.request_id,
        )


class SqlAlchemyEventRepository(EventRepository):
    def __init__(self, session: Session):
        self._session = session

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
            row = SelectionEventORM(
                decision_run_id=decision_run_id,
                student_id=student_id,
                present=True,
                selected=student_id in selected_set,
                alpha_before=before.alpha,
                beta_before=before.beta,
                alpha_after=before.alpha + delta_alpha,
                beta_after=before.beta + delta_beta,
            )
            self._session.add(row)

    def history_for_student(self, student_id: int, limit: int = 100) -> List[SelectionEventRecord]:
        stmt = (
            select(SelectionEventORM)
            .where(SelectionEventORM.student_id == student_id)
            .order_by(SelectionEventORM.created_at.desc())
            .limit(limit)
        )
        rows = self._session.execute(stmt).scalars().all()
        return [
            SelectionEventRecord(
                id=r.id,
                decision_run_id=r.decision_run_id,
                student_id=r.student_id,
                present=r.present,
                selected=r.selected,
                alpha_before=r.alpha_before,
                beta_before=r.beta_before,
                alpha_after=r.alpha_after,
                beta_after=r.beta_after,
                created_at=r.created_at,
            )
            for r in rows
        ]


def _to_participation(row: ParticipationORM) -> Participation:
    return Participation(
        id=row.id,
        class_session_id=row.class_session_id,
        student_id=row.student_id,
        question=row.question,
        asked_at=row.asked_at,
        answer=row.answer,
        decision_run_id=row.decision_run_id,
        present=row.present,
        created_by=row.created_by,
        anulada=row.anulada,
        motivo_anulacion=row.motivo_anulacion,
    )


class SqlAlchemyParticipationRepository(ParticipationRepository):
    """Persistencia de participaciones con SQLAlchemy (HU-P4).

    Valida dos cosas al crear, y no por capricho:

    1. Que la sesion exista y que el estudiante pertenezca a SU curso. Sin
       esa comprobacion, se podria registrar una participacion cruzada (alumno
       del curso A participate en la sesion del curso B) y el historial de
       ambos cursos quedaria contaminado. Es un error de datos silencioso: no
       rompe nada visible hasta que las metricas de equidad salen raras.

    2. Que `asked_at` no sea nulo. En SQLite una columna DateTime sin timezone
       puede devolver `None` si la fila se inserto a mano.
    """

    def __init__(self, session: Session):
        self._session = session

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

        sesion = self._session.get(ClassSessionORM, class_session_id)
        if sesion is None:
            raise ParticipationError(
                f"la sesion {class_session_id} no existe"
            )

        estudiante = self._session.get(StudentORM, student_id)
        if estudiante is None:
            raise ParticipationError(
                f"el estudiante {student_id} no existe"
            )
        if estudiante.course_id != sesion.course_id:
            raise ParticipationError(
                f"el estudiante {student_id} pertenece al curso "
                f"{estudiante.course_id}, no al curso {sesion.course_id} de la "
                f"sesion {class_session_id}"
            )

        if decision_run_id is not None:
            run = self._session.get(DecisionRunORM, decision_run_id)
            if run is None:
                raise ParticipationError(
                    f"el sorteo {decision_run_id} no existe"
                )
            if run.class_session_id != class_session_id:
                raise ParticipationError(
                    f"el sorteo {decision_run_id} es de otra sesion"
                )

        fila = ParticipationORM(
            class_session_id=class_session_id,
            student_id=student_id,
            question=question,
            answer=(answer or None),
            asked_at=asked_at,
            decision_run_id=decision_run_id,
            created_by=created_by,
            present=present,
        )
        self._session.add(fila)
        self._session.flush()
        return _to_participation(fila)

    def get(self, participation_id: int) -> Optional[Participation]:
        fila = self._session.get(ParticipationORM, participation_id)
        return _to_participation(fila) if fila else None

    def list_for_session(
        self,
        class_session_id: int,
        include_anuladas: bool = False,
    ) -> List[Participation]:
        stmt = select(ParticipationORM).where(
            ParticipationORM.class_session_id == class_session_id
        )
        if not include_anuladas:
            stmt = stmt.where(ParticipationORM.anulada.is_(False))
        stmt = stmt.order_by(
            ParticipationORM.asked_at.asc(), ParticipationORM.id.asc()
        )
        return [_to_participation(r) for r in self._session.execute(stmt).scalars()]

    def list_for_student(
        self,
        student_id: int,
        include_anuladas: bool = False,
    ) -> List[Participation]:
        stmt = select(ParticipationORM).where(
            ParticipationORM.student_id == student_id
        )
        if not include_anuladas:
            stmt = stmt.where(ParticipationORM.anulada.is_(False))
        stmt = stmt.order_by(
            ParticipationORM.asked_at.desc(), ParticipationORM.id.desc()
        )
        return [_to_participation(r) for r in self._session.execute(stmt).scalars()]

    def count_for_session(self, class_session_id: int) -> int:
        stmt = select(func.count()).select_from(ParticipationORM).where(
            ParticipationORM.class_session_id == class_session_id,
            ParticipationORM.anulada.is_(False),
        )
        return int(self._session.execute(stmt).scalar_one())

    def anular(
        self,
        participation_id: int,
        motivo: Optional[str] = None,
    ) -> Optional[Participation]:
        fila = self._session.get(ParticipationORM, participation_id)
        if fila is None:
            return None
        fila.anulada = True
        fila.motivo_anulacion = (motivo or None)
        self._session.flush()
        return _to_participation(fila)
