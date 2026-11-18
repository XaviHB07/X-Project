"""Composition root de la aplicación.

Este es el ÚNICO lugar del proyecto que decide qué implementación
concreta de `UnitOfWork` se usa (SQLAlchemy) y con qué configuración. La
API (`src/api/main.py`), los scripts (`scripts/`) y los tests importan
`build_app_context()` (o construyen su propio contexto de prueba con el
repositorio in-memory) en vez de instanciar repositorios a mano.

Centralizar el "wiring" aquí es lo que permite que `SelectionService` y
las estrategias no tengan ni un solo `import` de SQLAlchemy, FastAPI o
YAML: todas esas dependencias de infraestructura conviven en este único
archivo (y en `repositories/sqlalchemy/`), nunca en la lógica de negocio.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

# Importar el paquete de estrategias tiene el efecto secundario de
# registrarlas en SelectorRegistry (ver src/strategies/__init__.py).
import src.strategies  # noqa: F401
from src.domain.events import EventBus, logging_subscriber, DecisionRunCompleted
from src.repositories.sqlalchemy.models import (
    AcademicCycleORM,
    Base,
    ClassSessionORM,
    CourseORM,
    FacultyORM,
    RoleORM,
    SchemaMigrationORM,
    SpecialtyORM,
    StudentORM,
    UniversityORM,
    UserORM,
)
from src.repositories.sqlalchemy.unit_of_work import SqlAlchemyUnitOfWork, build_session_factory
from src.services.fairness_service import FairnessMetricsService
from src.services.auth_service import (
    AuthService, ROLE_ADMIN, ROLE_STUDENT, ROLE_TEACHER, hash_password,
)
from src.services.group_exposition_service import GroupExpositionService
from src.services.group_planning_service import GroupPlanningService
from src.services.grade_analysis_service import GradeAnalysisService
from src.services.institution_service import InstitutionService
from src.services.material_service import CourseMaterialService
from src.services.quick_activity_service import QuickActivityService
from src.services.roster_service import RosterService
from src.services.selection_service import SelectionService
from src.services.session_service import SessionService

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "default.yaml"


@dataclass
class AppConfig:
    """Configuración resuelta de la aplicación (YAML + overrides de entorno)."""

    database_url: str
    method_defaults: dict
    log_level: str = "INFO"


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    """Carga `config/default.yaml` y aplica overrides desde variables de
    entorno. La variable de entorno `DATABASE_URL` tiene prioridad sobre
    el YAML -- es el mecanismo estándar en despliegues (contenedores,
    Heroku/Render/Fly, CI) para inyectar la cadena de conexión real de
    producción sin tocar el archivo versionado en git.
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    database_url = os.environ.get("DATABASE_URL", raw["production"]["database_url"])
    return AppConfig(
        database_url=database_url,
        method_defaults=raw["methods"],
        log_level=os.environ.get("LOG_LEVEL", raw["production"].get("log_level", "INFO")),
    )


@dataclass
class AppContext:
    """Todo lo que la API/los scripts necesitan para operar el sistema."""

    config: AppConfig
    uow_factory: "callable"
    event_bus: EventBus
    selection_service: SelectionService
    fairness_service: FairnessMetricsService
    roster_service: RosterService
    session_service: SessionService
    auth_service: AuthService
    group_planning_service: GroupPlanningService
    group_exposition_service: GroupExpositionService
    grade_analysis_service: GradeAnalysisService
    material_service: CourseMaterialService
    institution_service: InstitutionService
    quick_activity_service: QuickActivityService


# Columnas agregadas a tablas que ya existían antes del Sprint 1. `create_all`
# crea tablas nuevas pero NO agrega columnas a tablas existentes, así que una
# base de datos creada con una versión anterior fallaría ("no such column").
# Esta lista es un parche mínimo y explícito hasta que se adopte Alembic (ver
# README, "De aquí a producción real"). Sintaxis válida en SQLite >= 3.23 y
# PostgreSQL.
_ADDED_COLUMNS = [
    ("academic_cycles", "starts_on", "DATE"),
    # HU-C3 (Sprint 6): el docente gestiona sus propios ciclos. Sin
    # `REFERENCES` por la misma razón que `students.user_id` (ver abajo).
    ("academic_cycles", "ends_on", "DATE"),
    ("academic_cycles", "enabled", "BOOLEAN NOT NULL DEFAULT TRUE"),
    ("academic_cycles", "owner_teacher_id", "INTEGER"),
    # HU-C2 (Sprint 6): contexto universidad → facultad → especialidad.
    ("academic_cycles", "specialty_id", "INTEGER"),
    ("courses", "cycle_id", "INTEGER"),
    ("courses", "roster_imported_at", "TIMESTAMP WITH TIME ZONE"),
    # HU-C4 (Sprint 6): código y estado del curso.
    ("courses", "code", "VARCHAR(32)"),
    ("courses", "enabled", "BOOLEAN NOT NULL DEFAULT TRUE"),
    ("students", "active", "BOOLEAN NOT NULL DEFAULT TRUE"),
    ("students", "phone_number", "VARCHAR(32)"),
    ("students", "email", "VARCHAR(255)"),
    # Sin `REFERENCES`: esta función corre ANTES de `create_all`, así que la
    # tabla `users` puede todavia no existir y PostgreSQL aborta el ALTER con
    # `relation "users" does not exist`. El vinculo se crea como clave forense
    # logica en el modelo ORM, no como restriccion en la base.
    ("students", "user_id", "INTEGER"),
    ("students", "roster_number", "VARCHAR(255)"),
    ("students", "specialty", "VARCHAR(255)"),
    ("students", "student_condition", "VARCHAR(255)"),
    ("students", "times_repeated", "VARCHAR(255)"),
    ("users", "phone_number", "VARCHAR(32)"),
    ("users", "email", "VARCHAR(255)"),
    ("users", "dni", "VARCHAR(32)"),
    # Quiz en vivo (Sprint 7): por si una base ya tenía las tablas de
    # actividades rápidas de la primera versión (solo modo test).
    ("quick_activities", "mode", "VARCHAR(16) NOT NULL DEFAULT 'self_paced'"),
    ("quick_activities", "question_seconds", "INTEGER"),
    ("quick_activities", "live_phase", "VARCHAR(16)"),
    ("quick_activities", "live_position", "INTEGER"),
    ("quick_activities", "live_started_at", "TIMESTAMP WITH TIME ZONE"),
    ("quick_activity_answers", "points", "INTEGER"),
    ("quick_activity_answers", "response_ms", "INTEGER"),
    ("quick_activity_answers", "answered_at", "TIMESTAMP WITH TIME ZONE"),
    # HU-A8 (Sprint 5): apellidos y nombres del docente por separado.
    ("users", "last_names", "VARCHAR(255)"),
    ("users", "first_names", "VARCHAR(255)"),
    ("users", "must_change_password", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("class_sessions", "session_date", "DATE"),
    ("class_sessions", "topic", "VARCHAR(255)"),
    ("student_participations", "question", "TEXT"),
    ("student_participations", "comment", "TEXT"),
    ("student_participations", "difficulty", "INTEGER NOT NULL DEFAULT 3"),
    ("student_participations", "grade_visible", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("student_participations", "voided", "BOOLEAN NOT NULL DEFAULT FALSE"),
]


def _ensure_columns(engine) -> None:
    """Agrega las columnas de `_ADDED_COLUMNS` que falten (idempotente)."""
    from sqlalchemy import inspect, text
    from sqlalchemy.exc import SQLAlchemyError

    # Primero se lee el esquema completo y recién después se ejecutan los
    # ALTER: así no se mezcla reflexión con una transacción de escritura
    # abierta (SQLite lo tolera mal con varios accesos simultáneos).
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    missing = []
    for table, column, ddl in _ADDED_COLUMNS:
        if table not in existing_tables:
            continue  # tabla nueva: create_all la creará completa
        present = {c["name"] for c in inspector.get_columns(table)}
        if column not in present:
            missing.append((table, column, ddl))
    if missing:
        with engine.begin() as conn:
            for table, column, ddl in missing:
                try:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
                except SQLAlchemyError:
                    logging.exception("No se pudo agregar %s.%s", table, column)
    if "users" in existing_tables:
        with engine.begin() as conn:
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_dni ON users (dni)"))
    if "academic_cycles" in existing_tables:
        _migrate_cycle_name_uniqueness(engine)


def _migrate_cycle_name_uniqueness(engine) -> None:
    """HU-C3: el nombre del ciclo pasa de ser único en todo el sistema a ser
    único por docente dueño (idempotente).

    En PostgreSQL se retira la restricción `UNIQUE (name)` que creaba la
    versión anterior. En SQLite esa restricción va dentro de la definición
    de la tabla y no puede quitarse sin reconstruirla; como SQLite solo se
    usa en desarrollo local, basta con borrar el archivo `.db` para tenerla
    con el esquema nuevo (los ciclos seguirán funcionando, pero dos docentes
    no podrán repetir un nombre hasta hacerlo).
    """
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError

    with engine.begin() as conn:
        try:
            if engine.dialect.name == "postgresql":
                conn.execute(text(
                    "ALTER TABLE academic_cycles DROP CONSTRAINT IF EXISTS academic_cycles_name_key"
                ))
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_academic_cycles_owner_name "
                "ON academic_cycles (owner_teacher_id, name)"
            ))
        except SQLAlchemyError:
            logging.exception("No se pudo migrar la unicidad de academic_cycles.name")


def _migrate_review_request_targets(engine) -> None:
    """Permite asociar una revisión a una participación o a una evaluación."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "student_review_requests" not in inspector.get_table_names():
        return
    columns = {column["name"]: column for column in inspector.get_columns("student_review_requests")}
    if (
        columns.get("evaluation_result_id", {}).get("nullable", False)
        and "resolution_comment" in columns
        and columns["participation_id"]["nullable"]
    ):
        return

    if engine.dialect.name == "sqlite":
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS student_review_requests_new"))
            conn.execute(text(
                "CREATE TABLE student_review_requests_new ("
                "id INTEGER NOT NULL PRIMARY KEY, "
                "participation_id INTEGER NULL REFERENCES student_participations(id), "
                "evaluation_result_id INTEGER NULL REFERENCES student_evaluation_results(id), "
                "student_user_id INTEGER NOT NULL REFERENCES users(id), "
                "course_id INTEGER NOT NULL REFERENCES courses(id), "
                "reason TEXT NOT NULL, status VARCHAR(20) NOT NULL DEFAULT 'pending', "
                "resolution_comment TEXT NULL, created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL, "
                "CONSTRAINT ck_student_review_request_status "
                "CHECK (status IN ('pending', 'in_review', 'resolved')), "
                "CONSTRAINT ck_student_review_request_target CHECK ("
                "(participation_id IS NOT NULL AND evaluation_result_id IS NULL) OR "
                "(participation_id IS NULL AND evaluation_result_id IS NOT NULL))"
                ")"
            ))
            resolution_column = (
                "resolution_comment" if "resolution_comment" in columns else "NULL"
            )
            conn.execute(text(
                "INSERT INTO student_review_requests_new "
                "(id, participation_id, evaluation_result_id, student_user_id, course_id, "
                "reason, status, resolution_comment, created_at, updated_at) "
                "SELECT id, participation_id, NULL, student_user_id, course_id, reason, "
                f"status, {resolution_column}, created_at, updated_at "
                "FROM student_review_requests"
            ))
            conn.execute(text("DROP TABLE student_review_requests"))
            conn.execute(text(
                "ALTER TABLE student_review_requests_new RENAME TO student_review_requests"
            ))
            conn.execute(text(
                "CREATE INDEX ix_student_review_requests_student_created "
                "ON student_review_requests (student_user_id, created_at)"
            ))
            conn.execute(text(
                "CREATE INDEX ix_student_review_requests_course_status "
                "ON student_review_requests (course_id, status)"
            ))
        return

    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE student_review_requests "
            "ALTER COLUMN participation_id DROP NOT NULL"
        ))
        conn.execute(text(
            "ALTER TABLE student_review_requests "
            "ADD COLUMN IF NOT EXISTS evaluation_result_id INTEGER NULL "
            "REFERENCES student_evaluation_results(id)"
        ))
        conn.execute(text(
            "ALTER TABLE student_review_requests "
            "ADD COLUMN IF NOT EXISTS resolution_comment TEXT NULL"
        ))
        conn.execute(text(
            "ALTER TABLE student_review_requests "
            "ADD CONSTRAINT ck_student_review_request_target CHECK ("
            "(participation_id IS NOT NULL AND evaluation_result_id IS NULL) OR "
            "(participation_id IS NULL AND evaluation_result_id IS NOT NULL))"
        ))


# Nombres de la estructura que recibe los datos del MVP 1. Son genéricos a
# propósito: el Administrador los renombra desde "Estructura institucional"
# (HU-A5 a HU-A7) con los datos reales de su institución.
MVP1_MIGRATION = "2026-11-mvp1-institutional-schema"
MVP1_UNIVERSITY = "Universidad (migrada del MVP 1)"
MVP1_FACULTY = "Facultad (migrada del MVP 1)"
MVP1_SPECIALTY = "Especialidad (migrada del MVP 1)"
MVP1_CYCLE = "Histórico MVP 1"


def _migrate_mvp1_institutional_schema(session_factory) -> None:
    """Tarea técnica del Sprint 6: pasa cursos y ciclos anteriores al nuevo
    esquema universidad → facultad → especialidad → ciclo → curso.

    * Los ciclos sin especialidad quedan en la especialidad de migración.
    * Los cursos sin ciclo pasan al ciclo "Histórico MVP 1", cuya fecha de
      inicio es la de la sesión más antigua de esos cursos (así el portal del
      estudiante sigue ordenando sus sesiones por semana). Si un curso ya
      tenía estudiantes, esa lista cuenta como su carga inicial por Excel
      (regla de HU-C1 para cursos con ciclo).
    * No borra ni modifica sesiones, participaciones ni notas.

    Se ejecuta una sola vez (queda registrada en `schema_migrations`); en una
    base nueva solo deja el registro.
    """
    from datetime import datetime, timezone

    from sqlalchemy import func, select

    with session_factory() as session:
        if session.get(SchemaMigrationORM, MVP1_MIGRATION) is not None:
            return
        legacy_cycles = session.execute(
            select(AcademicCycleORM).where(AcademicCycleORM.specialty_id.is_(None))
        ).scalars().all()
        legacy_courses = session.execute(
            select(CourseORM).where(CourseORM.cycle_id.is_(None)).order_by(CourseORM.id)
        ).scalars().all()
        if legacy_cycles or legacy_courses:
            university = session.execute(
                select(UniversityORM).where(UniversityORM.name == MVP1_UNIVERSITY)
            ).scalar_one_or_none() or UniversityORM(name=MVP1_UNIVERSITY, enabled=True)
            session.add(university)
            session.flush()
            faculty = session.execute(
                select(FacultyORM).where(
                    FacultyORM.university_id == university.id, FacultyORM.name == MVP1_FACULTY
                )
            ).scalar_one_or_none() or FacultyORM(
                university_id=university.id, name=MVP1_FACULTY, enabled=True
            )
            session.add(faculty)
            session.flush()
            specialty = session.execute(
                select(SpecialtyORM).where(
                    SpecialtyORM.faculty_id == faculty.id, SpecialtyORM.name == MVP1_SPECIALTY
                )
            ).scalar_one_or_none() or SpecialtyORM(
                faculty_id=faculty.id, name=MVP1_SPECIALTY, enabled=True
            )
            session.add(specialty)
            session.flush()
            for cycle in legacy_cycles:
                cycle.specialty_id = specialty.id
            if legacy_courses:
                course_ids = [course.id for course in legacy_courses]
                first_session = session.execute(
                    select(func.min(ClassSessionORM.session_date)).where(
                        ClassSessionORM.course_id.in_(course_ids)
                    )
                ).scalar_one_or_none()
                starts_on = first_session or min(
                    (course.created_at.date() for course in legacy_courses if course.created_at),
                    default=None,
                )
                historic = session.execute(
                    select(AcademicCycleORM).where(
                        AcademicCycleORM.name == MVP1_CYCLE,
                        AcademicCycleORM.owner_teacher_id.is_(None),
                    )
                ).scalar_one_or_none()
                if historic is None:
                    historic = AcademicCycleORM(
                        name=MVP1_CYCLE,
                        starts_on=starts_on,
                        enabled=True,
                        specialty_id=specialty.id,
                    )
                    session.add(historic)
                    session.flush()
                now = datetime.now(timezone.utc)
                for course in legacy_courses:
                    course.cycle_id = historic.id
                    has_students = session.execute(
                        select(StudentORM.id).where(StudentORM.course_id == course.id).limit(1)
                    ).scalar_one_or_none() is not None
                    if has_students and course.roster_imported_at is None:
                        course.roster_imported_at = now
            logging.info(
                "Migración MVP 1: %s ciclos y %s cursos pasaron al esquema institucional.",
                len(legacy_cycles), len(legacy_courses),
            )
        session.add(SchemaMigrationORM(name=MVP1_MIGRATION))
        session.commit()


def _provision_initial_admin(session_factory) -> None:
    username = os.environ.get("ADMIN_USERNAME")
    password = os.environ.get("ADMIN_PASSWORD")
    if username is None and password is None:
        return

    with session_factory() as session:
        admin_role = session.query(RoleORM).filter_by(name=ROLE_ADMIN).one()
        existing_admin = session.query(UserORM).filter_by(role_id=admin_role.id).first()
        if existing_admin:
            return

        if username is None or password is None:
            raise RuntimeError("ADMIN_USERNAME y ADMIN_PASSWORD deben configurarse juntos.")

        username = username.strip()
        if not username:
            raise RuntimeError("ADMIN_USERNAME no puede estar vacío.")

        if session.query(UserORM).filter_by(username=username).first():
            raise RuntimeError(
                "ADMIN_USERNAME ya pertenece a una cuenta que no es Administrador."
            )

        session.add(
            UserORM(
                username=username,
                full_name="Administrador",
                password_hash=hash_password(password),
                role_id=admin_role.id,
            )
        )
        session.commit()
        logging.info("Se creó la cuenta inicial de Administrador desde variables de entorno.")


def build_app_context(config_path: Path = DEFAULT_CONFIG_PATH, create_tables: bool = True) -> AppContext:
    """Construye el contexto completo de la aplicación para producción
    (respaldado por SQLAlchemy).

    Args:
        config_path: ruta al YAML de configuración.
        create_tables: si es `True` (default), crea las tablas que falten
            según `Base.metadata` -- suficiente para desarrollo/demo. En
            un despliegue real se recomienda gestionar el esquema con una
            herramienta de migraciones (p. ej. Alembic) en vez de confiar
            en `create_all` (ver README, sección "De aquí a producción
            real").
    """
    config = load_config(config_path)
    logging.basicConfig(level=config.log_level)

    session_factory = build_session_factory(config.database_url)
    if create_tables:
        # Primero se ajustan las tablas viejas (si las hay) y luego create_all
        # crea lo que falte: así una base anterior al Sprint 1 sigue
        # funcionando sin perder datos.
        _ensure_columns(session_factory.engine)
        Base.metadata.create_all(session_factory.engine)
        _migrate_review_request_targets(session_factory.engine)
        _migrate_mvp1_institutional_schema(session_factory)
        with session_factory() as session:
            existing_roles = set(session.query(RoleORM.name).all())
            existing_names = {name for (name,) in existing_roles}
            for role_name in (ROLE_ADMIN, ROLE_TEACHER, ROLE_STUDENT):
                if role_name not in existing_names:
                    session.add(RoleORM(name=role_name))
            session.commit()
        provisioned_students = AuthService(
            session_factory
        ).provision_existing_student_accounts()
        if provisioned_students:
            logging.info(
                "Se crearon %s cuentas para estudiantes existentes.",
                provisioned_students,
            )
        _provision_initial_admin(session_factory)

    event_bus = EventBus()
    event_bus.subscribe(DecisionRunCompleted, logging_subscriber)

    def uow_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    return AppContext(
        config=config,
        uow_factory=uow_factory,
        event_bus=event_bus,
        selection_service=SelectionService(uow_factory, event_bus=event_bus),
        fairness_service=FairnessMetricsService(uow_factory),
        roster_service=RosterService(uow_factory),
        session_service=SessionService(uow_factory),
        auth_service=AuthService(session_factory),
        group_planning_service=GroupPlanningService(uow_factory),
        group_exposition_service=GroupExpositionService(uow_factory),
        grade_analysis_service=GradeAnalysisService(uow_factory),
        material_service=CourseMaterialService(uow_factory),
        institution_service=InstitutionService(session_factory),
        quick_activity_service=QuickActivityService(session_factory),
    )
