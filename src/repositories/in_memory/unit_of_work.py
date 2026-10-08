"""Unit of Work respaldada por `InMemoryDatabase`.

A diferencia de la versión SQLAlchemy, aquí no hay una transacción real
que hacer rollback (los cambios se aplican directamente sobre los dicts
en `apply_updates`/`log_decision`), así que `commit()`/`rollback()`
existen principalmente para cumplir la misma interfaz y, sobre todo,
para soltar el `write_lock` que `get_candidates_for_update` adquirió —
eso es lo que de verdad importa para la garantía de concurrencia (ver
`repository_impl.InMemoryStudentStateRepository.get_candidates_for_update`).
"""

from __future__ import annotations

from src.repositories.in_memory.repository_impl import (
    InMemoryAttendanceRepository,
    InMemoryClassSessionRepository,
    InMemoryCourseRepository,
    InMemoryDatabase,
    InMemoryDecisionRunRepository,
    InMemoryEventRepository,
    InMemoryParticipationRepository,
    InMemoryStudentRepository,
    InMemoryStudentStateRepository,
    InMemorySyllabusRepository,
)
from src.repositories.interfaces import UnitOfWork


class InMemoryUnitOfWork(UnitOfWork):
    """Implementación en memoria de `UnitOfWork`, para simulación y tests."""

    def __init__(self, db: InMemoryDatabase):
        self._db = db
        self._lock_held = False

    def __enter__(self) -> "InMemoryUnitOfWork":
        self.courses = InMemoryCourseRepository(self._db)
        self.students = InMemoryStudentRepository(self._db)
        self.student_states = InMemoryStudentStateRepository(self._db)
        self.class_sessions = InMemoryClassSessionRepository(self._db)
        self.syllabus = InMemorySyllabusRepository(self._db)
        self.attendance = InMemoryAttendanceRepository(self._db)
        self.decision_runs = InMemoryDecisionRunRepository(self._db)
        self.events = InMemoryEventRepository(self._db)
        self.participations = InMemoryParticipationRepository(self._db)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        # Si `get_candidates_for_update` se llegó a invocar, adquirió
        # `self._db.write_lock`. Lo soltamos siempre al salir del
        # bloque `with`, se haya hecho commit, rollback, o haya
        # escapado una excepción -- igual que una base de datos real
        # libera sus bloqueos al terminar la transacción pase lo que
        # pase.
        if self._db.write_lock.locked():
            try:
                self._db.write_lock.release()
            except RuntimeError:
                # Ya estaba liberado (p. ej. porque el caller nunca
                # llegó a pedir un `for_update`); no hay nada que hacer.
                pass

    def commit(self) -> None:
        # No-op: los cambios ya se aplicaron directamente sobre los
        # dicts de InMemoryDatabase. Se mantiene el método por
        # compatibilidad de interfaz con SqlAlchemyUnitOfWork.
        pass

    def rollback(self) -> None:
        # Limitación conocida y documentada: esta implementación NO
        # deshace cambios ya aplicados a los dicts (no hay "estado
        # anterior" guardado). Es aceptable para simulación y para los
        # tests actuales, que no ejercitan rollback tras una escritura
        # parcial. Si se necesitara rollback real in-memory, la forma
        # correcta sería que `apply_updates`/`log_decision` escriban a
        # un buffer y `commit()` lo vuelque recién ahí -- se deja como
        # extensión futura, señalada aquí para que no se asuma
        # semántica transaccional completa por error.
        pass
