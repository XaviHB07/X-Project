"""Modelos ORM (SQLAlchemy 2.0, estilo `Mapped`/`mapped_column`).

Estos modelos son un detalle de infraestructura: nada fuera de
`repositories/sqlalchemy/` debería importarlos directamente. La capa de
servicios y la API hablan en términos de `src/domain/entities.py` y
`src/domain/value_objects.py`; es `repository_impl.py` quien traduce
entre unos y otros.

Esquema (ver README para el diagrama y la justificación completa):

    courses (1) ---- (N) students (1) ---- (1) student_state
    courses (1) ---- (N) class_sessions (1) ---- (N) decision_runs (1) ---- (N) selection_events
    students (1) ---- (N) selection_events
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    """Timestamp UTC consistente para toda la aplicación.

    Se usa una función Python (en vez de `func.now()` de SQL) como
    default en varias columnas para que el comportamiento sea idéntico
    sin importar el motor de base de datos (SQLite, PostgreSQL, etc.),
    algo que `func.now()` no siempre garantiza entre dialectos.
    """
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Clase base declarativa de la que heredan todos los modelos ORM."""


class CourseORM(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    students: Mapped[List["StudentORM"]] = relationship(back_populates="course")
    class_sessions: Mapped[List["ClassSessionORM"]] = relationship(back_populates="course")


class StudentORM(Base):
    __tablename__ = "students"
    __table_args__ = (
        # Un mismo `external_ref` (p. ej. código de matrícula) no puede
        # repetirse dos veces dentro del mismo curso -- así es como
        # `get_or_create` puede ser idempotente.
        UniqueConstraint("course_id", "external_ref", name="uq_student_course_external_ref"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    external_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    course: Mapped["CourseORM"] = relationship(back_populates="students")
    state: Mapped[Optional["StudentStateORM"]] = relationship(
        back_populates="student", uselist=False, cascade="all, delete-orphan"
    )
    events: Mapped[List["SelectionEventORM"]] = relationship(back_populates="student")


class StudentStateORM(Base):
    """Estado bayesiano acumulado -- ver `domain/entities.StudentState`.

    Es la tabla que sufre escrituras concurrentes frecuentes (una fila
    por estudiante, actualizada en cada decisión de selección en la que
    participa). Separarla de `students` significa que el bloqueo de
    escritura (`SELECT ... FOR UPDATE`, ver `repository_impl.py`) afecta
    solo a esta tabla pequeña y de filas fijas, no a los datos de
    identidad del estudiante.
    """

    __tablename__ = "student_state"

    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), primary_key=True)
    alpha: Mapped[float] = mapped_column(Float, nullable=False)
    beta: Mapped[float] = mapped_column(Float, nullable=False)
    n_present: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    n_selected: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    student: Mapped["StudentORM"] = relationship(back_populates="state")


class ClassSessionORM(Base):
    __tablename__ = "class_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    course: Mapped["CourseORM"] = relationship(back_populates="class_sessions")
    decision_runs: Mapped[List["DecisionRunORM"]] = relationship(back_populates="class_session")


class DecisionRunORM(Base):
    """Una invocación del servicio de selección -- la unidad
    transaccional central (ver `domain/entities.DecisionRun`).
    """

    __tablename__ = "decision_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_session_id: Mapped[int] = mapped_column(ForeignKey("class_sessions.id"), nullable=False)
    method_name: Mapped[str] = mapped_column(String(64), nullable=False)
    k_requested: Mapped[int] = mapped_column(Integer, nullable=False)
    k_selected: Mapped[int] = mapped_column(Integer, nullable=False)
    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    class_session: Mapped["ClassSessionORM"] = relationship(back_populates="decision_runs")
    events: Mapped[List["SelectionEventORM"]] = relationship(back_populates="decision_run")


class SelectionEventORM(Base):
    """Un registro de auditoría por (decision_run, estudiante considerado).

    Guarda alpha/beta ANTES y DESPUÉS de la decisión -- más de lo mínimo
    que sugería el asesor -- precisamente para poder responder "¿por qué
    este estudiante fue/no fue elegido en este momento?" sin tener que
    reconstruir el estado a partir de eventos anteriores.
    """

    __tablename__ = "selection_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    decision_run_id: Mapped[int] = mapped_column(ForeignKey("decision_runs.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False)
    present: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False)
    alpha_before: Mapped[float] = mapped_column(Float, nullable=False)
    beta_before: Mapped[float] = mapped_column(Float, nullable=False)
    alpha_after: Mapped[float] = mapped_column(Float, nullable=False)
    beta_after: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    decision_run: Mapped["DecisionRunORM"] = relationship(back_populates="events")
    student: Mapped["StudentORM"] = relationship(back_populates="events")
