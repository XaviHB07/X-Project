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

from typing import Callable

from sqlalchemy.orm import Session, sessionmaker

from src.repositories.interfaces import UnitOfWork
from src.repositories.sqlalchemy.repository_impl import (
    SqlAlchemyAttendanceRepository,
    SqlAlchemyClassSessionRepository,
    SqlAlchemyCourseRepository,
    SqlAlchemyDecisionRunRepository,
    SqlAlchemyEventRepository,
    SqlAlchemyStudentRepository,
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
        self.students = SqlAlchemyStudentRepository(self._session)
        self.student_states = SqlAlchemyStudentStateRepository(self._session)
        self.class_sessions = SqlAlchemyClassSessionRepository(self._session)
        self.syllabus = SqlAlchemySyllabusRepository(self._session)
        self.attendance = SqlAlchemyAttendanceRepository(self._session)
        self.decision_runs = SqlAlchemyDecisionRunRepository(self._session)
        self.events = SqlAlchemyEventRepository(self._session)
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


def build_session_factory(database_url: str) -> SessionFactory:
    """Crea una fábrica de sesiones SQLAlchemy para una cadena de conexión dada.

    Se usa un `sessionmaker` (en vez de crear la `Session` a mano cada
    vez) porque encapsula la configuración recomendada por SQLAlchemy
    (p. ej. `expire_on_commit=False`, para poder seguir leyendo atributos
    de los objetos devueltos después de hacer commit, algo necesario
    porque `SqlAlchemyUnitOfWork.__exit__` cierra la sesión enseguida).
    """
    from sqlalchemy import create_engine

    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args, future=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    # Se expone el engine como atributo propio (en vez de obligar a leer
    # `factory.kw["bind"]`, un detalle interno de `sessionmaker`) para
    # que quien necesite crear las tablas (`Base.metadata.create_all`,
    # ver `services/bootstrap.py`) tenga una forma explícita de llegar
    # a él.
    factory.engine = engine
    return factory
