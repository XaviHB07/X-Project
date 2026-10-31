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
    AcademicCycle,
    AttendanceRecord,
    ClassSession,
    Course,
    CourseGroupPlan,
    DecisionRun,
    Student,
    StudentAccount,
    StudentGroup,
    StudentParticipation,
    SyllabusEntry,
)
from src.domain.value_objects import (
    Candidate,
    GenericCountersUpdate,
    PosteriorUpdate,
    SelectionEventRecord,
)
from src.repositories.interfaces import (
    AcademicCycleRepository,
    AttendanceRepository,
    ClassSessionRepository,
    CourseRepository,
    DecisionRunRepository,
    DuplicateAcademicCycleError,
    DuplicateStudentError,
    EventRepository,
    GroupPlanRepository,
    InvalidParticipationStudentError,
    ParticipationDecisionNotFoundError,
    ParticipationRepository,
    StudentRepository,
    StudentAccountRepository,
    StudentStateRepository,
    SyllabusRepository,
)
from src.repositories.sqlalchemy.models import (
    AcademicCycleORM,
    ClassSessionORM,
    CourseORM,
    CourseGroupPlanORM,
    DecisionRunORM,
    SelectionEventORM,
    SessionAttendanceORM,
    StudentORM,
    StudentStateORM,
    StudentParticipationORM,
    RoleORM,
    UserORM,
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
        user_id=row.user_id,
        roster_number=row.roster_number,
        specialty=row.specialty,
        student_condition=row.student_condition,
        times_repeated=row.times_repeated,
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

    def create(self, name: str, cycle_id: Optional[int] = None) -> Course:
        row = CourseORM(name=name, cycle_id=cycle_id)
        self._session.add(row)
        self._session.flush()  # asigna row.id sin necesidad de commit
        return self._to_course(row)

    def get(self, course_id: int) -> Optional[Course]:
        row = self._session.get(CourseORM, course_id)
        if row is None:
            return None
        return self._to_course(row)

    def list_all(self) -> List[Course]:
        rows = self._session.execute(select(CourseORM).order_by(CourseORM.id)).scalars().all()
        return [self._to_course(row) for row in rows]

    def claim_roster_import(self, course_id: int) -> bool:
        result = self._session.execute(
            update(CourseORM)
            .where(
                CourseORM.id == course_id,
                CourseORM.cycle_id.is_not(None),
                CourseORM.roster_imported_at.is_(None),
            )
            .values(roster_imported_at=datetime.now(timezone.utc))
        )
        return result.rowcount == 1

    @staticmethod
    def _to_course(row: CourseORM) -> Course:
        return Course(
            id=row.id,
            name=row.name,
            created_at=row.created_at,
            cycle_id=row.cycle_id,
            roster_imported_at=row.roster_imported_at,
        )


class SqlAlchemyAcademicCycleRepository(AcademicCycleRepository):
    def __init__(self, session: Session):
        self._session = session

    def create(self, name: str, starts_on: Optional[date] = None) -> AcademicCycle:
        existing = self._session.execute(
            select(AcademicCycleORM.id).where(AcademicCycleORM.name == name)
        ).scalar_one_or_none()
        if existing is not None:
            raise DuplicateAcademicCycleError(f"El ciclo “{name}” ya existe.")
        row = AcademicCycleORM(name=name, starts_on=starts_on)
        self._session.add(row)
        self._session.flush()
        return AcademicCycle(
            id=row.id, name=row.name, created_at=row.created_at, starts_on=row.starts_on
        )

    def get(self, cycle_id: int) -> Optional[AcademicCycle]:
        row = self._session.get(AcademicCycleORM, cycle_id)
        if row is None:
            return None
        return AcademicCycle(
            id=row.id,
            name=row.name,
            created_at=self._utc(row.created_at),
            starts_on=row.starts_on,
        )

    def list_all(self) -> List[AcademicCycle]:
        rows = self._session.execute(
            select(AcademicCycleORM).order_by(AcademicCycleORM.id)
        ).scalars().all()
        return [
            AcademicCycle(
                id=row.id,
                name=row.name,
                created_at=self._utc(row.created_at),
                starts_on=row.starts_on,
            )
            for row in rows
        ]

    def set_starts_on(self, cycle_id: int, starts_on: date) -> Optional[AcademicCycle]:
        row = self._session.get(AcademicCycleORM, cycle_id)
        if row is None:
            return None
        row.starts_on = starts_on
        self._session.flush()
        return AcademicCycle(
            id=row.id,
            name=row.name,
            created_at=self._utc(row.created_at),
            starts_on=row.starts_on,
        )

    @staticmethod
    def _utc(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class SqlAlchemyStudentAccountRepository(StudentAccountRepository):
    def __init__(self, session: Session):
        self._session = session

    def get_by_email(self, email: str) -> Optional[StudentAccount]:
        row = self._session.execute(
            select(UserORM).where(func.lower(UserORM.email) == email.lower())
        ).scalar_one_or_none()
        if row is None:
            return None
        return StudentAccount(
            id=row.id,
            username=row.username,
            full_name=row.full_name,
            email=row.email,
            role=row.role.name,
            active=row.active,
        )

    def get_by_username(self, username: str) -> Optional[StudentAccount]:
        row = self._session.execute(
            select(UserORM).where(UserORM.username == username)
        ).scalar_one_or_none()
        if row is None:
            return None
        return StudentAccount(
            id=row.id,
            username=row.username,
            full_name=row.full_name,
            email=row.email,
            role=row.role.name,
            active=row.active,
        )

    def update_username(self, account_id: int, username: str) -> StudentAccount:
        row = self._session.get(UserORM, account_id)
        if row is None:
            raise LookupError(f"Cuenta de estudiante {account_id} no encontrada.")
        row.username = username
        self._session.flush()
        return StudentAccount(
            id=row.id,
            username=row.username,
            full_name=row.full_name,
            email=row.email,
            role=row.role.name,
            active=row.active,
        )

    def create_student(
        self, username: str, full_name: str, email: Optional[str], password_hash: str
    ) -> StudentAccount:
        role_id = self._session.execute(
            select(RoleORM.id).where(RoleORM.name == "estudiante")
        ).scalar_one()
        row = UserORM(
            username=username,
            full_name=full_name,
            email=email,
            password_hash=password_hash,
            must_change_password=True,
            role_id=role_id,
        )
        self._session.add(row)
        self._session.flush()
        if email:
            self._session.execute(
                update(StudentORM)
                .where(func.lower(StudentORM.email) == email.lower())
                .values(user_id=row.id)
            )
        return StudentAccount(
            id=row.id,
            username=row.username,
            full_name=row.full_name,
            email=row.email,
            role="estudiante",
            active=row.active,
        )


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
        user_id: Optional[int] = None,
        roster_number: Optional[str] = None,
        specialty: Optional[str] = None,
        student_condition: Optional[str] = None,
        times_repeated: Optional[str] = None,
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
            user_id=user_id,
            roster_number=roster_number,
            specialty=specialty,
            student_condition=student_condition,
            times_repeated=times_repeated,
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
        user_id: Optional[int] = None,
        roster_number: Optional[str] = None,
        specialty: Optional[str] = None,
        student_condition: Optional[str] = None,
        times_repeated: Optional[str] = None,
    ) -> Tuple[Student, str]:
        existing = self._session.execute(
            select(StudentORM).where(
                StudentORM.course_id == course_id,
                StudentORM.external_ref == external_ref,
            )
        ).scalar_one_or_none()
        if existing is None:
            return self.get_or_create(
                course_id, external_ref, display_name, alpha_init, beta_init,
                phone_number, email, user_id, roster_number, specialty,
                student_condition, times_repeated,
            ), "created"
        changed = (
            existing.display_name != display_name
            or not existing.active
            or any(
                value is not None and getattr(existing, field) != value
                for field, value in (
                    ("phone_number", phone_number), ("email", email), ("user_id", user_id),
                    ("roster_number", roster_number), ("specialty", specialty),
                    ("student_condition", student_condition), ("times_repeated", times_repeated),
                )
            )
        )
        if not changed:
            return _to_student(existing), "unchanged"
        existing.display_name = display_name
        existing.active = True
        if phone_number is not None:
            existing.phone_number = phone_number
        if email is not None:
            existing.email = email
        for field, value in (
            ("user_id", user_id), ("roster_number", roster_number), ("specialty", specialty),
            ("student_condition", student_condition), ("times_repeated", times_repeated),
        ):
            if value is not None:
                setattr(existing, field, value)
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


class SqlAlchemyParticipationRepository(ParticipationRepository):
    def __init__(self, session: Session):
        self._session = session

    @staticmethod
    def _to_participation(row: StudentParticipationORM, student: StudentORM) -> StudentParticipation:
        return StudentParticipation(
            id=row.id,
            decision_run_id=row.decision_run_id,
            student_id=row.student_id,
            score=row.score,
            present=row.present,
            created_at=row.created_at,
            external_ref=student.external_ref,
            display_name=student.display_name,
            question=row.question,
            comment=row.comment,
        )

    def record_many(
        self,
        course_id: int,
        decision_run_id: int,
        score_and_presence_by_student: Dict[int, Tuple[float, bool]],
        details_by_student: Optional[Dict[int, Tuple[Optional[str], Optional[str]]]] = None,
    ) -> List[StudentParticipation]:
        details_by_student = details_by_student or {}
        decision_exists = self._session.execute(
            select(DecisionRunORM.id)
            .join(ClassSessionORM, DecisionRunORM.class_session_id == ClassSessionORM.id)
            .where(
                DecisionRunORM.id == decision_run_id,
                ClassSessionORM.course_id == course_id,
            )
        ).scalar_one_or_none()
        if decision_exists is None:
            raise ParticipationDecisionNotFoundError(
                f"La decisión {decision_run_id} no existe en el curso {course_id}."
            )

        selected_ids = set(
            self._session.execute(
                select(SelectionEventORM.student_id).where(
                    SelectionEventORM.decision_run_id == decision_run_id,
                    SelectionEventORM.selected.is_(True),
                )
            ).scalars()
        )
        submitted_ids = set(score_and_presence_by_student)
        if submitted_ids != selected_ids:
            raise InvalidParticipationStudentError(
                "Registra exactamente a todos los estudiantes seleccionados en esta decisión."
            )

        existing_rows = {
            row.student_id: row
            for row in self._session.execute(
                select(StudentParticipationORM).where(
                    StudentParticipationORM.decision_run_id == decision_run_id,
                    StudentParticipationORM.student_id.in_(list(score_and_presence_by_student)),
                )
            ).scalars()
        }
        for student_id, (score, present) in score_and_presence_by_student.items():
            question, comment = details_by_student.get(student_id, (None, None))
            row = existing_rows.get(student_id)
            if row is None:
                row = StudentParticipationORM(
                    decision_run_id=decision_run_id,
                    student_id=student_id,
                    score=score,
                    present=present,
                    question=question,
                    comment=comment,
                )
                self._session.add(row)
            else:
                row.score = score
                row.present = present
                row.question = question
                row.comment = comment

        self._session.flush()
        return self._rows_for_decision(decision_run_id, list(score_and_presence_by_student))

    def _rows_for_decision(
        self, decision_run_id: int, student_ids: List[int]
    ) -> List[StudentParticipation]:
        rows = self._session.execute(
            select(StudentParticipationORM, StudentORM)
            .join(StudentORM, StudentORM.id == StudentParticipationORM.student_id)
            .where(
                StudentParticipationORM.decision_run_id == decision_run_id,
                StudentParticipationORM.student_id.in_(student_ids),
            )
            .order_by(StudentParticipationORM.student_id)
        ).all()
        return [self._to_participation(participation, student) for participation, student in rows]

    def list_by_course(self, course_id: int, limit: int = 200) -> List[StudentParticipation]:
        rows = self._session.execute(
            select(StudentParticipationORM, StudentORM)
            .join(StudentORM, StudentORM.id == StudentParticipationORM.student_id)
            .join(DecisionRunORM, DecisionRunORM.id == StudentParticipationORM.decision_run_id)
            .join(ClassSessionORM, ClassSessionORM.id == DecisionRunORM.class_session_id)
            .where(ClassSessionORM.course_id == course_id)
            .order_by(StudentParticipationORM.created_at.desc(), StudentParticipationORM.id.desc())
            .limit(limit)
        ).all()
        return [self._to_participation(participation, student) for participation, student in rows]

    def weekly_score_averages(
        self, course_id: int, start_on: date, end_on: date
    ) -> List[Tuple[int, date, float, int]]:
        rows = self._session.execute(
            select(
                StudentParticipationORM.student_id,
                ClassSessionORM.session_date,
                func.avg(StudentParticipationORM.score),
                func.count(StudentParticipationORM.id),
            )
            .join(DecisionRunORM, DecisionRunORM.id == StudentParticipationORM.decision_run_id)
            .join(ClassSessionORM, ClassSessionORM.id == DecisionRunORM.class_session_id)
            .where(
                ClassSessionORM.course_id == course_id,
                ClassSessionORM.session_date >= start_on,
                ClassSessionORM.session_date <= end_on,
            )
            .group_by(StudentParticipationORM.student_id, ClassSessionORM.session_date)
        ).all()
        return [
            (student_id, session_date, float(average), int(count))
            for student_id, session_date, average, count in rows
            if session_date is not None
        ]

    def weekly_details(
        self, course_id: int, student_id: int, start_on: date, end_on: date
    ) -> List[Tuple[StudentParticipation, date, datetime]]:
        rows = self._session.execute(
            select(StudentParticipationORM, StudentORM, ClassSessionORM, DecisionRunORM)
            .join(StudentORM, StudentORM.id == StudentParticipationORM.student_id)
            .join(DecisionRunORM, DecisionRunORM.id == StudentParticipationORM.decision_run_id)
            .join(ClassSessionORM, ClassSessionORM.id == DecisionRunORM.class_session_id)
            .where(
                ClassSessionORM.course_id == course_id,
                StudentParticipationORM.student_id == student_id,
                ClassSessionORM.session_date >= start_on,
                ClassSessionORM.session_date <= end_on,
            )
            .order_by(DecisionRunORM.created_at.asc(), StudentParticipationORM.id.asc())
        ).all()
        return [
            (self._to_participation(participation, student), session.session_date, run.created_at)
            for participation, student, session, run in rows
            if session.session_date is not None
        ]


class SqlAlchemyGroupPlanRepository(GroupPlanRepository):
    def __init__(self, session: Session):
        self._session = session

    @staticmethod
    def _to_plan(row: CourseGroupPlanORM) -> CourseGroupPlan:
        return CourseGroupPlan(
            id=row.id,
            course_id=row.course_id,
            name=row.name,
            max_group_size=row.max_group_size,
            groups=[
                StudentGroup(name=group["name"], student_ids=list(group["student_ids"]))
                for group in row.groups
            ],
            created_at=row.created_at,
        )

    def create(
        self,
        course_id: int,
        name: str,
        max_group_size: int,
        groups: List[StudentGroup],
    ) -> CourseGroupPlan:
        row = CourseGroupPlanORM(
            course_id=course_id,
            name=name,
            max_group_size=max_group_size,
            groups=[{"name": group.name, "student_ids": group.student_ids} for group in groups],
        )
        self._session.add(row)
        self._session.flush()
        return self._to_plan(row)

    def get(self, plan_id: int) -> Optional[CourseGroupPlan]:
        row = self._session.get(CourseGroupPlanORM, plan_id)
        return self._to_plan(row) if row is not None else None

    def list_by_course(self, course_id: int) -> List[CourseGroupPlan]:
        rows = self._session.execute(
            select(CourseGroupPlanORM)
            .where(CourseGroupPlanORM.course_id == course_id)
            .order_by(CourseGroupPlanORM.created_at.desc(), CourseGroupPlanORM.id.desc())
        ).scalars().all()
        return [self._to_plan(row) for row in rows]

    def update(
        self,
        plan_id: int,
        name: str,
        max_group_size: int,
        groups: List[StudentGroup],
    ) -> Optional[CourseGroupPlan]:
        row = self._session.get(CourseGroupPlanORM, plan_id)
        if row is None:
            return None
        row.name = name
        row.max_group_size = max_group_size
        row.groups = [{"name": group.name, "student_ids": group.student_ids} for group in groups]
        self._session.flush()
        return self._to_plan(row)

    def delete(self, plan_id: int) -> bool:
        row = self._session.get(CourseGroupPlanORM, plan_id)
        if row is None:
            return False
        self._session.delete(row)
        return True
