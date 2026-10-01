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

from typing import Dict, List, Optional, Sequence

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.domain.entities import ClassSession, Course, DecisionRun, Student
from src.domain.value_objects import (
    Candidate,
    GenericCountersUpdate,
    PosteriorUpdate,
    SelectionEventRecord,
)
from src.repositories.interfaces import (
    ClassSessionRepository,
    CourseRepository,
    DecisionRunRepository,
    EventRepository,
    StudentRepository,
    StudentStateRepository,
)
from src.repositories.sqlalchemy.models import (
    ClassSessionORM,
    CourseORM,
    DecisionRunORM,
    SelectionEventORM,
    StudentORM,
    StudentStateORM,
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
    ) -> Student:
        existing = self._session.execute(
            select(StudentORM).where(
                StudentORM.course_id == course_id,
                StudentORM.external_ref == external_ref,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return _to_student(existing)

        row = StudentORM(course_id=course_id, external_ref=external_ref, display_name=display_name)
        self._session.add(row)
        self._session.flush()  # necesitamos row.id antes de crear el estado

        state = StudentStateORM(student_id=row.id, alpha=alpha_init, beta=beta_init)
        self._session.add(state)
        self._session.flush()

        return _to_student(row)

    def get(self, student_id: int) -> Optional[Student]:
        row = self._session.get(StudentORM, student_id)
        return _to_student(row) if row is not None else None

    def list_by_course(self, course_id: int) -> List[Student]:
        rows = self._session.execute(
            select(StudentORM).where(StudentORM.course_id == course_id)
        ).scalars().all()
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

    def create(self, course_id: int, label: Optional[str] = None) -> ClassSession:
        row = ClassSessionORM(course_id=course_id, label=label)
        self._session.add(row)
        self._session.flush()
        return ClassSession(id=row.id, course_id=row.course_id, created_at=row.created_at, label=row.label)

    def get(self, class_session_id: int) -> Optional[ClassSession]:
        row = self._session.get(ClassSessionORM, class_session_id)
        if row is None:
            return None
        return ClassSession(id=row.id, course_id=row.course_id, created_at=row.created_at, label=row.label)


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
