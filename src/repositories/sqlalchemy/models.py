"""Modelos ORM (SQLAlchemy 2.0, estilo `Mapped`/`mapped_column`).

Estos modelos son un detalle de infraestructura: nada fuera de
`repositories/sqlalchemy/` debería importarlos directamente. La capa de
servicios y la API hablan en términos de `src/domain/entities.py` y
`src/domain/value_objects.py`; es `repository_impl.py` quien traduce
entre unos y otros.

Esquema (ver README para el diagrama y la justificación completa):

    courses (1) ---- (N) students (1) ---- (1) student_state
    courses (1) ---- (N) class_sessions (1) ---- (N) decision_runs (1) ---- (N) selection_events
    decision_runs (1) ---- (N) student_participations (N) ---- (1) students
    courses (1) ---- (N) syllabus_entries
    class_sessions (1) ---- (N) session_attendance (N) ---- (1) students
    students (1) ---- (N) selection_events
    courses (1) ---- (N) group_expositions (1) ---- (N) group_exposition_member_scores (N) ---- (1) students
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    false,
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


class UniversityORM(Base):
    """HU-A5: universidad atendida por el sistema. `enabled = False` la da de
    baja sin borrarla (conserva el histórico)."""

    __tablename__ = "universities"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    faculties: Mapped[List["FacultyORM"]] = relationship(back_populates="university")


class FacultyORM(Base):
    """HU-A6: facultad que pertenece a una universidad."""

    __tablename__ = "faculties"
    __table_args__ = (
        UniqueConstraint("university_id", "name", name="uq_faculties_university_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    university_id: Mapped[int] = mapped_column(
        ForeignKey("universities.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    university: Mapped["UniversityORM"] = relationship(back_populates="faculties")
    specialties: Mapped[List["SpecialtyORM"]] = relationship(back_populates="faculty")


class SpecialtyORM(Base):
    """HU-A7: especialidad que pertenece a una facultad."""

    __tablename__ = "specialties"
    __table_args__ = (
        UniqueConstraint("faculty_id", "name", name="uq_specialties_faculty_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    faculty_id: Mapped[int] = mapped_column(
        ForeignKey("faculties.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    faculty: Mapped["FacultyORM"] = relationship(back_populates="specialties")


class SchemaMigrationORM(Base):
    """Migraciones de datos que deben ejecutarse una sola vez (p. ej. pasar
    los cursos del MVP 1 al esquema universidad → facultad → especialidad →
    ciclo). Mientras no se adopte Alembic, este registro evita repetirlas en
    cada arranque."""

    __tablename__ = "schema_migrations"

    name: Mapped[str] = mapped_column(String(120), primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AcademicCycleORM(Base):
    __tablename__ = "academic_cycles"
    # HU-C3: el nombre es único por docente dueño (dos docentes pueden tener
    # cada uno su "2026-II"). Antes del Sprint 6 era único en todo el
    # sistema; `bootstrap._ensure_columns` retira esa restricción vieja en
    # PostgreSQL. La unicidad de los ciclos sin dueño (NULL) se valida en
    # el repositorio, porque SQL trata cada NULL como distinto.
    __table_args__ = (
        Index("uq_academic_cycles_owner_name", "owner_teacher_id", "name", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    starts_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    ends_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    owner_teacher_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    # HU-C2: contexto institucional (universidad → facultad → especialidad)
    # en el que el docente registra el ciclo. Es opcional en la base porque
    # los ciclos anteriores al Sprint 6 no lo tenían; la migración del MVP 1
    # (`bootstrap._migrate_mvp1_institutional_schema`) los completa.
    specialty_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("specialties.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    courses: Mapped[List["CourseORM"]] = relationship(back_populates="cycle")
    specialty: Mapped[Optional["SpecialtyORM"]] = relationship()


class RoleORM(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)

    users: Mapped[List["UserORM"]] = relationship(back_populates="role")


class UserORM(Base):
    __tablename__ = "users"
    __table_args__ = (Index("uq_users_dni", "dni", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # HU-A8: apellidos y nombres por separado. `full_name` se conserva como
    # nombre para mostrar ("Nombres Apellidos") y para cuentas antiguas.
    last_names: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_names: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    dni: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_number: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    role: Mapped["RoleORM"] = relationship(back_populates="users")
    course_assignments: Mapped[List["TeacherCourseORM"]] = relationship(
        back_populates="teacher", cascade="all, delete-orphan"
    )
    sessions: Mapped[List["AuthSessionORM"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class TeacherCourseORM(Base):
    __tablename__ = "teacher_courses"

    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), primary_key=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    teacher: Mapped["UserORM"] = relationship(back_populates="course_assignments")
    course: Mapped["CourseORM"] = relationship()


class AuthSessionORM(Base):
    __tablename__ = "auth_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    user: Mapped["UserORM"] = relationship(back_populates="sessions")


class CourseORM(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    # HU-C4: código del curso (p. ej. "SI807U"), único dentro de su ciclo.
    # Es opcional en la base porque los cursos del MVP 1 no lo tenían.
    code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # HU-C4: deshabilitar da de baja el curso sin borrarlo.
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    cycle_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("academic_cycles.id"), nullable=True
    )
    roster_imported_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    cycle: Mapped[Optional["AcademicCycleORM"]] = relationship(back_populates="courses")
    students: Mapped[List["StudentORM"]] = relationship(back_populates="course")
    class_sessions: Mapped[List["ClassSessionORM"]] = relationship(back_populates="course")
    syllabus_entries: Mapped[List["SyllabusEntryORM"]] = relationship(back_populates="course")


class CourseMaterialORM(Base):
    __tablename__ = "course_materials"
    __table_args__ = (
        Index("ix_course_materials_course_created", "course_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    class_session_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("class_sessions.id"), nullable=True
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    topic: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    content_type: Mapped[str] = mapped_column(String(127), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    file_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    course: Mapped["CourseORM"] = relationship()
    class_session: Mapped[Optional["ClassSessionORM"]] = relationship()


class ExposureTimeSettingsORM(Base):
    __tablename__ = "exposure_time_settings"

    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), primary_key=True)
    min_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    course: Mapped["CourseORM"] = relationship()


class CourseGroupPlanORM(Base):
    __tablename__ = "course_group_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    max_group_size: Mapped[int] = mapped_column(Integer, nullable=False)
    groups: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    course: Mapped["CourseORM"] = relationship()


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
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    roster_number: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    specialty: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    student_condition: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    times_repeated: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    # server_default: las filas que ya existían antes de esta columna
    # quedan activas (ver `_ensure_columns` en services/bootstrap.py).
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )

    course: Mapped["CourseORM"] = relationship(back_populates="students")
    user: Mapped[Optional["UserORM"]] = relationship()
    state: Mapped[Optional["StudentStateORM"]] = relationship(
        back_populates="student", uselist=False, cascade="all, delete-orphan"
    )
    events: Mapped[List["SelectionEventORM"]] = relationship(back_populates="student")
    participations: Mapped[List["StudentParticipationORM"]] = relationship(
        back_populates="student"
    )


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
    __table_args__ = (
        Index("ix_class_sessions_course_session_date", "course_id", "session_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    session_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    topic: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    course: Mapped["CourseORM"] = relationship(back_populates="class_sessions")
    decision_runs: Mapped[List["DecisionRunORM"]] = relationship(back_populates="class_session")
    attendance: Mapped[List["SessionAttendanceORM"]] = relationship(back_populates="class_session")


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
    participations: Mapped[List["StudentParticipationORM"]] = relationship(
        back_populates="decision_run"
    )


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


class StudentParticipationORM(Base):
    """Calificación y asistencia capturadas tras una selección."""

    __tablename__ = "student_participations"
    __table_args__ = (
        UniqueConstraint("decision_run_id", "student_id", name="uq_participation_run_student"),
        CheckConstraint("score >= 0 AND score <= 5", name="ck_participation_score_range"),
        CheckConstraint(
            "difficulty >= 1 AND difficulty <= 5",
            name="ck_participation_difficulty_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    decision_run_id: Mapped[int] = mapped_column(
        ForeignKey("decision_runs.id"), nullable=False
    )
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    present: Mapped[bool] = mapped_column(Boolean, nullable=False)
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    grade_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    question: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    voided: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    decision_run: Mapped["DecisionRunORM"] = relationship(back_populates="participations")
    student: Mapped["StudentORM"] = relationship(back_populates="participations")


class CourseEvaluationORM(Base):
    """Evaluación independiente de las participaciones de clase."""

    __tablename__ = "course_evaluations"
    __table_args__ = (
        Index("ix_course_evaluations_course_created", "course_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class StudentEvaluationResultORM(Base):
    """Nota y feedback opcionales por estudiante y evaluación."""

    __tablename__ = "student_evaluation_results"
    __table_args__ = (
        UniqueConstraint("evaluation_id", "student_id", name="uq_evaluation_student"),
        CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 5)",
            name="ck_student_evaluation_score_range",
        ),
        Index("ix_evaluation_results_student", "student_id", "evaluation_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    evaluation_id: Mapped[int] = mapped_column(
        ForeignKey("course_evaluations.id"), nullable=False
    )
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    grade_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )


class StudentReviewRequestORM(Base):
    """Solicitud de revisión de una nota visible para el estudiante."""

    __tablename__ = "student_review_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'in_review', 'resolved')",
            name="ck_student_review_request_status",
        ),
        CheckConstraint(
            "(participation_id IS NOT NULL AND evaluation_result_id IS NULL) OR "
            "(participation_id IS NULL AND evaluation_result_id IS NOT NULL)",
            name="ck_student_review_request_target",
        ),
        Index("ix_student_review_requests_student_created", "student_user_id", "created_at"),
        Index("ix_student_review_requests_course_status", "course_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    participation_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("student_participations.id"), nullable=True
    )
    evaluation_result_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("student_evaluation_results.id"), nullable=True
    )
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    resolution_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class GroupExpositionORM(Base):
    """Exposición calificada de un grupo: nota grupal + datos de contexto.

    `group_name` y `plan_name` son copias (snapshot): la propuesta de grupos
    vive como JSON editable en `course_group_plans`, así que la nota no puede
    depender de que ese JSON siga igual. `group_plan_id` queda solo como
    referencia y se pone en NULL si la propuesta se elimina.
    """

    __tablename__ = "group_expositions"
    __table_args__ = (
        CheckConstraint(
            "group_score >= 0 AND group_score <= 5", name="ck_group_exposition_score_range"
        ),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name="ck_group_exposition_duration",
        ),
        Index("ix_group_expositions_course_created", "course_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    class_session_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("class_sessions.id"), nullable=True, index=True
    )
    group_plan_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("course_group_plans.id", ondelete="SET NULL"), nullable=True
    )
    plan_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    group_name: Mapped[str] = mapped_column(String(255), nullable=False)
    group_score: Mapped[float] = mapped_column(Float, nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    course: Mapped["CourseORM"] = relationship()
    member_scores: Mapped[List["GroupExpositionMemberScoreORM"]] = relationship(
        back_populates="exposition",
        cascade="all, delete-orphan",
        order_by="GroupExpositionMemberScoreORM.id",
    )


class GroupExpositionMemberScoreORM(Base):
    """Nota individual de un integrante dentro de una exposición grupal.

    `score` admite NULL únicamente para integrantes ausentes (la regla
    "presente => nota obligatoria" la valida el servicio).
    """

    __tablename__ = "group_exposition_member_scores"
    __table_args__ = (
        UniqueConstraint(
            "exposition_id", "student_id", name="uq_group_exposition_member"
        ),
        CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 5)",
            name="ck_group_exposition_member_score_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exposition_id: Mapped[int] = mapped_column(
        ForeignKey("group_expositions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id"), nullable=False, index=True
    )
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    present: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Lugar en el orden de exposición (1 = primero). La columna no se llama
    # `position` porque esa es una palabra clave de SQL.
    position: Mapped[Optional[int]] = mapped_column("exposition_order", Integer, nullable=True)

    exposition: Mapped["GroupExpositionORM"] = relationship(back_populates="member_scores")
    student: Mapped["StudentORM"] = relationship()


# --------------------------------------------------------------------------
# Épica 7 — Actividades rápidas (Sprint 7)
# --------------------------------------------------------------------------


class QuickActivityORM(Base):
    """Actividad rápida de una sesión (preguntas cortas).

    Es la base compartida de la épica 7: HU-Q1 aporta las preguntas (hoy se
    escriben a mano; la generación con IA las enviará en el mismo formato),
    HU-Q2 publica la actividad con un código temporal (`join_code` +
    `expires_at`), HU-Q5 valida el ingreso del estudiante y HU-Q3 registra
    sus respuestas en `quick_activity_responses`.

    Estados: `draft` (en preparación), `published` (acepta respuestas hasta
    `expires_at`) y `closed` (cerrada por el docente).

    Modos (`mode`):

    * `self_paced` — test: cada estudiante responde todas las preguntas a su
      ritmo dentro del rango de tiempo que fija el docente.
    * `live` — quiz en vivo (tipo Kahoot/Quizizz): el docente proyecta una
      pregunta a la vez y los estudiantes responden desde su dispositivo con
      `question_seconds` por pregunta. El avance lo guardan `live_phase`
      (`lobby` → `question` → `reveal` → … → `finished`), `live_position`
      (número de la pregunta actual) y `live_started_at`.
    """

    __tablename__ = "quick_activities"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'published', 'closed')", name="ck_quick_activity_status"
        ),
        CheckConstraint("mode IN ('self_paced', 'live')", name="ck_quick_activity_mode"),
        Index("ix_quick_activities_course_created", "course_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    class_session_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("class_sessions.id"), nullable=True
    )
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    # Código que el estudiante escribe (o lee del QR). Único entre todas las
    # actividades para que el ingreso no necesite indicar el curso.
    join_code: Mapped[Optional[str]] = mapped_column(String(12), nullable=True, unique=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    results_email_claimed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # HU-Q5: "cada estudiante responde una sola vez, salvo que el docente lo
    # permita".
    allow_multiple_responses: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="self_paced", server_default="self_paced"
    )
    question_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    live_phase: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    live_position: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    live_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    questions: Mapped[List["QuickActivityQuestionORM"]] = relationship(
        back_populates="activity",
        cascade="all, delete-orphan",
        order_by="QuickActivityQuestionORM.position",
    )
    responses: Mapped[List["QuickActivityResponseORM"]] = relationship(
        back_populates="activity", cascade="all, delete-orphan"
    )


class QuickActivityQuestionORM(Base):
    """Pregunta corta. Si `options` tiene alternativas es de opción múltiple
    (con `correct_option` opcional, índice desde 0); si no, es de respuesta
    abierta."""

    __tablename__ = "quick_activity_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    activity_id: Mapped[int] = mapped_column(
        ForeignKey("quick_activities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column("question_order", Integer, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    correct_option: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    activity: Mapped["QuickActivityORM"] = relationship(back_populates="questions")


class QuickActivityResponseORM(Base):
    """HU-Q3: un envío de un estudiante, asociado a su cuenta (`user_id`) y a
    su matrícula en el curso (`student_id`). `attempt` empieza en 1; la
    restricción única impide registrar dos veces el mismo intento aunque
    lleguen dos envíos simultáneos."""

    __tablename__ = "quick_activity_responses"
    __table_args__ = (
        UniqueConstraint(
            "activity_id", "student_id", "attempt", name="uq_quick_activity_response_attempt"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    activity_id: Mapped[int] = mapped_column(
        ForeignKey("quick_activities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    activity: Mapped["QuickActivityORM"] = relationship(back_populates="responses")
    student: Mapped["StudentORM"] = relationship()
    answers: Mapped[List["QuickActivityAnswerORM"]] = relationship(
        back_populates="response", cascade="all, delete-orphan"
    )


class QuickActivityAnswerORM(Base):
    """Respuesta a una pregunta dentro de un envío. `is_correct` solo se
    calcula en preguntas de opción múltiple con alternativa correcta; queda
    lista para los resultados de HU-Q4."""

    __tablename__ = "quick_activity_answers"
    __table_args__ = (
        UniqueConstraint("response_id", "question_id", name="uq_quick_activity_answer"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    response_id: Mapped[int] = mapped_column(
        ForeignKey("quick_activity_responses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id: Mapped[int] = mapped_column(
        ForeignKey("quick_activity_questions.id", ondelete="CASCADE"), nullable=False
    )
    answer_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    selected_option: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_correct: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    # Quiz en vivo: puntaje por acierto y rapidez, y tiempo de respuesta.
    points: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    response_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    answered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    response: Mapped["QuickActivityResponseORM"] = relationship(back_populates="answers")
    question: Mapped["QuickActivityQuestionORM"] = relationship()
