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
from src.repositories.sqlalchemy.models import Base
from src.repositories.sqlalchemy.unit_of_work import SqlAlchemyUnitOfWork, build_session_factory
from src.services.fairness_service import FairnessMetricsService
from src.services.participation_service import ParticipationService
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
    participation_service: ParticipationService


# Columnas agregadas a tablas que ya existían antes del Sprint 1. `create_all`
# crea tablas nuevas pero NO agrega columnas a tablas existentes, así que una
# base de datos creada con una versión anterior fallaría ("no such column").
# Esta lista es un parche mínimo y explícito hasta que se adopte Alembic (ver
# README, "De aquí a producción real"). Sintaxis válida en SQLite >= 3.23 y
# PostgreSQL.
_ADDED_COLUMNS = [
    ("students", "active", "BOOLEAN NOT NULL DEFAULT TRUE"),
    ("students", "phone_number", "VARCHAR(32)"),
    ("students", "email", "VARCHAR(255)"),
    ("class_sessions", "session_date", "DATE"),
    ("class_sessions", "topic", "VARCHAR(255)"),
]


def _ensure_columns(engine) -> None:
    """Agrega las columnas de `_ADDED_COLUMNS` que falten (idempotente)."""
    from sqlalchemy import inspect, text

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
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


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
        participation_service=ParticipationService(uow_factory),
    )
