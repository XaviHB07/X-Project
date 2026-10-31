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
from src.repositories.sqlalchemy.models import Base, RoleORM, UserORM
from src.repositories.sqlalchemy.unit_of_work import SqlAlchemyUnitOfWork, build_session_factory
from src.services.fairness_service import FairnessMetricsService
from src.services.auth_service import (
    AuthService, ROLE_ADMIN, ROLE_STUDENT, ROLE_TEACHER, hash_password,
)
from src.services.group_planning_service import GroupPlanningService
from src.services.grade_analysis_service import GradeAnalysisService
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
    grade_analysis_service: GradeAnalysisService


# Columnas agregadas a tablas que ya existían antes del Sprint 1. `create_all`
# crea tablas nuevas pero NO agrega columnas a tablas existentes, así que una
# base de datos creada con una versión anterior fallaría ("no such column").
# Esta lista es un parche mínimo y explícito hasta que se adopte Alembic (ver
# README, "De aquí a producción real"). Sintaxis válida en SQLite >= 3.23 y
# PostgreSQL.
_ADDED_COLUMNS = [
    ("academic_cycles", "starts_on", "DATE"),
    ("courses", "cycle_id", "INTEGER"),
    ("courses", "roster_imported_at", "TIMESTAMP WITH TIME ZONE"),
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
    ("users", "must_change_password", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("class_sessions", "session_date", "DATE"),
    ("class_sessions", "topic", "VARCHAR(255)"),
    ("student_participations", "question", "TEXT"),
    ("student_participations", "comment", "TEXT"),
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
    if not missing:
        return
    with engine.begin() as conn:
        for table, column, ddl in missing:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            except SQLAlchemyError:
                # Una columna que no se pudo agregar deja la base en un estado
                # inconsistente, pero tumbar la app entera impide al menos usar
                # `/health` y diagnosticar. Se registra y se sigue.
                logging.exception("No se pudo agregar %s.%s", table, column)


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
        with session_factory() as session:
            existing_roles = set(session.query(RoleORM.name).all())
            existing_names = {name for (name,) in existing_roles}
            for role_name in (ROLE_ADMIN, ROLE_TEACHER, ROLE_STUDENT):
                if role_name not in existing_names:
                    session.add(RoleORM(name=role_name))
            session.commit()
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
        grade_analysis_service=GradeAnalysisService(uow_factory),
    )
