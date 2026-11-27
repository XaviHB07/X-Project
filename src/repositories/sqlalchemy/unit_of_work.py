"""Unit of Work respaldada por una `Session` de SQLAlchemy.

Cada `with SqlAlchemyUnitOfWork(session_factory) as uow:` abre UNA
transacción de base de datos (una sesión) que agrupa todas las
operaciones de repositorio hechas dentro del bloque. Si el bloque
termina sin llamar a `uow.commit()`, `__exit__` hace `rollback()`
automáticamente -- así una excepción a mitad de una selección nunca deja
el estado a medio actualizar (por ejemplo: alpha/beta actualizados pero
el evento de auditoría no registrado).
"""

from __future__ import annotations

import os
from typing import Callable

from sqlalchemy.orm import Session, sessionmaker

from src.repositories.interfaces import UnitOfWork
from src.repositories.sqlalchemy.repository_impl import (
    SqlAlchemyAttendanceRepository,
    SqlAlchemyAcademicCycleRepository,
    SqlAlchemyClassSessionRepository,
    SqlAlchemyCourseRepository,
    SqlAlchemyCourseMaterialRepository,
    SqlAlchemyCourseEvaluationRepository,
    SqlAlchemyExposureTimeSettingsRepository,
    SqlAlchemyDecisionRunRepository,
    SqlAlchemyEventRepository,
    SqlAlchemyGroupExpositionRepository,
    SqlAlchemyGroupPlanRepository,
    SqlAlchemyParticipationRepository,
    SqlAlchemyStudentReviewRequestRepository,
    SqlAlchemyStudentRepository,
    SqlAlchemyStudentAccountRepository,
    SqlAlchemyStudentStateRepository,
    SqlAlchemySyllabusRepository,
)

SessionFactory = Callable[[], Session]


class SqlAlchemyUnitOfWork(UnitOfWork):
    """Implementación real de `UnitOfWork` para producción."""

    def __init__(self, session_factory: SessionFactory):
        self._session_factory = session_factory
        self._session: Session | None = None

    def __enter__(self) -> "SqlAlchemyUnitOfWork":
        self._session = self._session_factory()
        # Los repositorios comparten la MISMA sesión/transacción: es lo
        # que hace que todas sus operaciones se confirmen o se deshagan
        # juntas al llamar a commit()/rollback().
        self.courses = SqlAlchemyCourseRepository(self._session)
        self.course_materials = SqlAlchemyCourseMaterialRepository(self._session)
        self.exposure_time_settings = SqlAlchemyExposureTimeSettingsRepository(self._session)
        self.cycles = SqlAlchemyAcademicCycleRepository(self._session)
        self.students = SqlAlchemyStudentRepository(self._session)
        self.student_accounts = SqlAlchemyStudentAccountRepository(self._session)
        self.student_states = SqlAlchemyStudentStateRepository(self._session)
        self.class_sessions = SqlAlchemyClassSessionRepository(self._session)
        self.syllabus = SqlAlchemySyllabusRepository(self._session)
        self.attendance = SqlAlchemyAttendanceRepository(self._session)
        self.decision_runs = SqlAlchemyDecisionRunRepository(self._session)
        self.events = SqlAlchemyEventRepository(self._session)
        self.participations = SqlAlchemyParticipationRepository(self._session)
        self.evaluations = SqlAlchemyCourseEvaluationRepository(self._session)
        self.review_requests = SqlAlchemyStudentReviewRequestRepository(self._session)
        self.group_plans = SqlAlchemyGroupPlanRepository(self._session)
        self.group_expositions = SqlAlchemyGroupExpositionRepository(self._session)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        try:
            if exc_type is not None:
                # Una excepción escapó del bloque `with`: deshacemos
                # cualquier cambio pendiente. No se re-lanza aquí porque
                # Python ya se encarga de propagarla al devolver `None`/
                # `False` implícito.
                self.rollback()
            # Si no hubo excepción pero tampoco se llamó a commit()
            # explícitamente, por seguridad no dejamos una transacción
            # a medias abierta: rollback es la opción segura por
            # defecto (falla de forma visible en vez de guardar datos
            # a medio actualizar por un olvido).
        finally:
            assert self._session is not None
            self._session.close()
            self._session = None

    def commit(self) -> None:
        assert self._session is not None, "commit() llamado fuera de un bloque 'with'"
        self._session.commit()

    def rollback(self) -> None:
        assert self._session is not None, "rollback() llamado fuera de un bloque 'with'"
        self._session.rollback()


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} debe ser un número entero (recibido: {raw!r}).") from exc


def engine_options(database_url: str) -> dict:
    """Parámetros de `create_engine` según el motor de base de datos.

    Plan de optimización, tarea 3.7: los valores del pool se documentan y
    se dejan configurables por variable de entorno en vez de subirlos a
    ciegas. Los valores por defecto de tamaño (5 + 10) son los MISMOS que
    ya aplicaba SQLAlchemy, así que no cambian la cantidad de conexiones
    abiertas contra PostgreSQL. Lo que sí cambia por defecto:

    * `pool_pre_ping=True`: antes de entregar una conexión del pool se
      comprueba que siga viva. En hostings como Render, PostgreSQL o la
      red cortan conexiones inactivas; sin esto la primera petición tras
      un rato de inactividad fallaba con error 500.
    * `pool_recycle=1800`: se renuevan conexiones con más de 30 minutos
      por la misma razón.
    * `pool_timeout=10`: si el pool está agotado, la petición espera como
      máximo 10 s (antes 30 s) y la API responde 503 con un mensaje claro
      (ver `src/api/main.py`) en vez de dejar la pantalla cargando.

    Variables disponibles: DB_POOL_SIZE, DB_MAX_OVERFLOW, DB_POOL_TIMEOUT,
    DB_POOL_RECYCLE y DB_STATEMENT_TIMEOUT_MS (opcional; corta en
    PostgreSQL cualquier consulta que exceda ese tiempo). Regla para
    ajustarlas: (DB_POOL_SIZE + DB_MAX_OVERFLOW) x número de procesos debe
    quedar por debajo de `max_connections` de PostgreSQL, dejando margen
    para conexiones administrativas.
    """
    if database_url.startswith("sqlite"):
        # SQLite en memoria/archivo: se conserva el comportamiento de
        # siempre (pool propio de SQLAlchemy para SQLite).
        return {"connect_args": {"check_same_thread": False}}
    options: dict = {
        "pool_size": _env_int("DB_POOL_SIZE", 5),
        "max_overflow": _env_int("DB_MAX_OVERFLOW", 10),
        "pool_timeout": _env_int("DB_POOL_TIMEOUT", 10),
        "pool_recycle": _env_int("DB_POOL_RECYCLE", 1800),
        "pool_pre_ping": True,
    }
    statement_timeout_ms = _env_int("DB_STATEMENT_TIMEOUT_MS", 0)
    if statement_timeout_ms > 0 and database_url.startswith("postgresql"):
        options["connect_args"] = {"options": f"-c statement_timeout={statement_timeout_ms}"}
    return options


def build_session_factory(database_url: str) -> SessionFactory:
    """Crea una fábrica de sesiones SQLAlchemy para una cadena de conexión dada.

    Se usa un `sessionmaker` (en vez de crear la `Session` a mano cada
    vez) porque encapsula la configuración recomendada por SQLAlchemy
    (p. ej. `expire_on_commit=False`, para poder seguir leyendo atributos
    de los objetos devueltos después de hacer commit, algo necesario
    porque `SqlAlchemyUnitOfWork.__exit__` cierra la sesión enseguida).
    """
    from sqlalchemy import create_engine

    engine = create_engine(database_url, future=True, **engine_options(database_url))
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    # Se expone el engine como atributo propio (en vez de obligar a leer
    # `factory.kw["bind"]`, un detalle interno de `sessionmaker`) para
    # que quien necesite crear las tablas (`Base.metadata.create_all`,
    # ver `services/bootstrap.py`) tenga una forma explícita de llegar
    # a él.
    factory.engine = engine
    return factory
