"""Modelos ORM (SQLAlchemy 2.0, estilo `Mapped`/`mapped_column`).

Estos modelos son un detalle de infraestructura: nada fuera de
`repositories/sqlalchemy/` debería importarlos directamente. La capa de
servicios y la API hablan en términos de `src/domain/entities.py` y
`src/domain/value_objects.py`; es `repository_impl.py` quien traduce
entre unos y otros.

Esquema (ver README para el diagrama y la justificación completa):

    courses (1) ---- (N) students (1) ---- (1) student_state
    courses (1) ---- (N) class_sessions (1) ---- (N) decision_runs (1) ---- (N) selection_events
    courses (1) ---- (N) syllabus_entries
    class_sessions (1) ---- (N) session_attendance (N) ---- (1) students
    students (1) ---- (N) selection_events
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    Index,
    Text,
    text,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    true,
)
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
    syllabus_entries: Mapped[List["SyllabusEntryORM"]] = relationship(back_populates="course")


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
    phone_number: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    # server_default: las filas que ya existían antes de esta columna
    # quedan activas (ver `_ensure_columns` en services/bootstrap.py).
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )

    course: Mapped["CourseORM"] = relationship(back_populates="students")
    state: Mapped[Optional["StudentStateORM"]] = relationship(
        back_populates="student", uselist=False, cascade="all, delete-orphan"
    )
    events: Mapped[List["SelectionEventORM"]] = relationship(back_populates="student")
    participations: Mapped[List["ParticipationORM"]] = relationship(back_populates="student")


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
    session_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    topic: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    course: Mapped["CourseORM"] = relationship(back_populates="class_sessions")
    decision_runs: Mapped[List["DecisionRunORM"]] = relationship(back_populates="class_session")
    attendance: Mapped[List["SessionAttendanceORM"]] = relationship(back_populates="class_session")
    participations: Mapped[List["ParticipationORM"]] = relationship(back_populates="class_session")


class SyllabusEntryORM(Base):
    """Planificación del curso: tema previsto para una fecha (HU-S1)."""

    __tablename__ = "syllabus_entries"
    __table_args__ = (
        UniqueConstraint("course_id", "session_date", name="uq_syllabus_course_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    topic: Mapped[str] = mapped_column(String(255), nullable=False)

    course: Mapped["CourseORM"] = relationship(back_populates="syllabus_entries")


class SessionAttendanceORM(Base):
    """Asistencia de un estudiante a una sesión concreta (HU-S2)."""

    __tablename__ = "session_attendance"

    class_session_id: Mapped[int] = mapped_column(ForeignKey("class_sessions.id"), primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), primary_key=True)
    present: Mapped[bool] = mapped_column(Boolean, nullable=False)

    class_session: Mapped["ClassSessionORM"] = relationship(back_populates="attendance")


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
    participations: Mapped[List["ParticipationORM"]] = relationship(back_populates="decision_run")


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


class ParticipationORM(Base):
    """Una participacion efectiva de un estudiante en una sesion (HU-P4).

    Es lo que cierra MVP 1: sin esta tabla el sistema sortea estudiantes pero
    no queda registro de que se pregunto ni de que respondio. `selection_events`
    es la traza del ALGORITMO; esta es la traza de lo que PASO EN CLASE. Son
    cosas distintas y hacen falta las dos.

    Decisiones de esquema:

    - No hay unicidad sobre (class_session_id, student_id). El backlog de
      HU-P1 pide explícitamente "dar menor probabilidad a quienes ya
      participaron" y HU-X3 "volver a sortear antes de iniciar la actividad",
      asi que un estudiante puede participar varias veces en una sesion. Un
      UNIQUE aqui impediria un caso de uso legitimo.

    - `present` se congela al registrar. No se lee de `session_attendance`
      en vivo: si el docente corrige la asistencia despues, el historial no
      debe cambiarle bajo los pies.

    - `anulada` con indice parcial: las participaciones anuladas no deben
      aparecer en el historial normal, pero se conservan para auditar.
    """

    __tablename__ = "participations"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_session_id: Mapped[int] = mapped_column(
        ForeignKey("class_sessions.id"), nullable=False
    )
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False)
    # Opcional a proposito: HU-P4 no lo pide. Permite registrar a mano una
    # participacion que no salio de un sorteo (el profe pregunta por su cuenta).
    decision_run_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("decision_runs.id"), nullable=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    asked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    created_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    present: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    anulada: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    motivo_anulacion: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    class_session: Mapped["ClassSessionORM"] = relationship(
        back_populates="participations"
    )
    student: Mapped["StudentORM"] = relationship(back_populates="participations")
    decision_run: Mapped["DecisionRunORM"] = relationship(back_populates="participations")

    __table_args__ = (
        # Indices explicitos: son las columnas por las que se consulta el
        # historial todo el tiempo, y dejar el indice en manos del motor
        # hace que el esquema cambie de comportamiento entre SQLite y
        # PostgreSQL (que es el caso de un despliegue real).
        #
        # El parcial es el que importa de verdad: el historial que ve el
        # docente filtra por `anulada = false`, y asi el indice solo cubre
        # las filas que se muestran.
        Index(
            "ix_participations_sesion",
            "class_session_id",
            postgresql_where=text("anulada = false"),
            sqlite_where=text("anulada = 0"),
        ),
        Index(
            "ix_participations_estudiante",
            "student_id",
            postgresql_where=text("anulada = false"),
            sqlite_where=text("anulada = 0"),
        ),
    )
