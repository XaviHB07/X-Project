"""Contratos abstractos de persistencia (patrón Repository) y de
transacción (patrón Unit of Work).

Nada en este archivo sabe qué motor de base de datos hay detrás. Eso es
intencional: `src/services/selection_service.py` importa SOLO de aquí,
nunca de `repositories/sqlalchemy` ni de `repositories/in_memory`
directamente. Quien decide qué implementación concreta usar es la
"composition root" del programa (`src/services/bootstrap.py`), típicamente
en función de una variable de entorno o de si estamos corriendo tests.

Esto es lo que en el texto del asesor se resume como "Base de datos como
fuente de verdad" + "actualización atómica dentro de una transacción":
aquí es donde se modela ese contrato, sin comprometerse todavía a una
tecnología concreta.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Sequence

from src.domain.entities import ClassSession, Course, DecisionRun, Student
from src.domain.value_objects import (
    Candidate,
    GenericCountersUpdate,
    PosteriorUpdate,
    SelectionEventRecord,
)


class CourseRepository(ABC):
    """Persistencia de cursos (el contenedor de estudiantes)."""

    @abstractmethod
    def create(self, name: str) -> Course: ...

    @abstractmethod
    def get(self, course_id: int) -> Optional[Course]: ...


class StudentRepository(ABC):
    """Persistencia de la IDENTIDAD del estudiante (datos que casi no
    cambian). El estado bayesiano mutable vive aparte, en
    `StudentStateRepository` — ver el docstring de `domain/entities.py`
    para la justificación de esta separación.
    """

    @abstractmethod
    def get_or_create(
        self,
        course_id: int,
        external_ref: str,
        display_name: str,
        alpha_init: float,
        beta_init: float,
    ) -> Student:
        """Devuelve el estudiante si ya existe (por `external_ref` dentro
        del curso); si no, lo crea junto con su `StudentState` inicial
        en `Beta(alpha_init, beta_init)`. Es idempotente a propósito: un
        cliente puede llamarlo en cada request de "matrícula" sin
        preocuparse por duplicados.
        """
        ...

    @abstractmethod
    def get(self, student_id: int) -> Optional[Student]: ...

    @abstractmethod
    def list_by_course(self, course_id: int) -> List[Student]: ...


class StudentStateRepository(ABC):
    """Persistencia del estado bayesiano (alpha, beta, n_present, n_selected).

    Esta es la interfaz donde se juega la concurrencia. Ver la
    implementación en `repositories/sqlalchemy/repository_impl.py` para
    el detalle de cómo se evita el "lost update" quDe describía el
    asesor cuando dos requests intentan actualizar al mismo estudiante
    casi al mismo tiempo.
    """

    @abstractmethod
    def get_candidates_for_update(self, student_ids: Sequence[int]) -> List[Candidate]:
        """Lee el estado actual de los estudiantes dados, tomando un
        bloqueo de escritura sobre esas filas (equivalente a
        `SELECT ... FOR UPDATE`) que se mantiene hasta que la unidad de
        trabajo actual haga `commit()` o `rollback()`.

        Debe llamarse siempre DENTRO de una `UnitOfWork` activa: es la
        forma de garantizar que, entre el momento en que se lee alpha/beta
        y el momento en que se escribe el nuevo valor, ninguna otra
        transacción concurrente pueda leer o modificar esas mismas filas.
        """
        ...

    @abstractmethod
    def get_candidates_readonly(self, student_ids: Sequence[int]) -> List[Candidate]:
        """Igual que `get_candidates_for_update`, pero SIN bloquear filas.

        Se usa para lecturas que no van a derivar en una escritura (p.
        ej. mostrar el estado actual de un estudiante en un endpoint
        `GET`, o calcular métricas de equidad). Bloquear filas para una
        simple lectura sería innecesariamente costoso y podría generar
        contención con las transacciones de escritura reales.
        """
        ...

    @abstractmethod
    def get_all_candidates_for_course(self, course_id: int) -> List[Candidate]:
        """Estado actual de TODOS los estudiantes de un curso, sin
        bloqueo. Lo usa `FairnessMetricsService` para calcular Gini/CV/
        cobertura sobre el curso completo.
        """
        ...

    @abstractmethod
    def apply_updates(
        self,
        generic_updates: List[GenericCountersUpdate],
        posterior_updates: List[PosteriorUpdate],
    ) -> None:
        """Aplica los deltas calculados por la estrategia como
        incrementos atómicos (`columna = columna + delta`) directamente
        en el motor de persistencia, en vez de leer-modificar-escribir en
        Python. Esa diferencia es la que evita perder actualizaciones
        bajo concurrencia (ver la implementación SQLAlchemy para el
        detalle exacto del SQL generado).
        """
        ...


class ClassSessionRepository(ABC):
    """Persistencia de sesiones de clase (una ocurrencia concreta de
    "clase" o "evento de selección" dentro de un curso).
    """

    @abstractmethod
    def create(self, course_id: int, label: Optional[str] = None) -> ClassSession: ...

    @abstractmethod
    def get(self, class_session_id: int) -> Optional[ClassSession]: ...


class DecisionRunRepository(ABC):
    """Persistencia de cada invocación del servicio de selección — la
    unidad transaccional central del sistema (ver docstring de
    `domain/entities.DecisionRun`).
    """

    @abstractmethod
    def create(
        self,
        class_session_id: int,
        method_name: str,
        k_requested: int,
        k_selected: int,
        request_id: Optional[str],
    ) -> DecisionRun: ...

    @abstractmethod
    def get(self, decision_run_id: int) -> Optional[DecisionRun]: ...


class EventRepository(ABC):
    """Log de eventos de selección: la traza de auditoría detallada que
    complementa al estado resumido (`StudentState`). Ver la discusión
    del asesor sobre "estado actual" vs "historial de eventos".
    """

    @abstractmethod
    def log_decision(
        self,
        decision_run_id: int,
        considered_before: Dict[int, Candidate],
        selected_ids: List[int],
        posterior_updates: Dict[int, PosteriorUpdate],
    ) -> None:
        """Registra un evento por cada candidato considerado (presente),
        con su estado ANTES y DESPUÉS de esta decisión, para poder
        reconstruir/explicar cualquier decisión pasada sin tener que
        recalcular nada a partir del estado actual.
        """
        ...

    @abstractmethod
    def history_for_student(
        self, student_id: int, limit: int = 100
    ) -> List[SelectionEventRecord]:
        """Historial de eventos de un estudiante, más reciente primero."""
        ...


class UnitOfWork(ABC):
    """Agrupa todos los repositorios de una transacción y garantiza que
    se confirman o se descartan juntos (patrón Unit of Work).

    Uso esperado (ver `services/selection_service.py`):

        with uow_factory() as uow:
            candidates = uow.student_states.get_candidates_for_update(ids)
            ...
            uow.student_states.apply_updates(...)
            uow.events.log_decision(...)
            uow.commit()

    Si `commit()` nunca se llama (p. ej. porque una excepción interrumpe
    el bloque `with`), `__exit__` hace `rollback()` automáticamente: o se
    guarda todo el resultado de la decisión, o no se guarda nada.
    """

    courses: CourseRepository
    students: StudentRepository
    student_states: StudentStateRepository
    class_sessions: ClassSessionRepository
    decision_runs: DecisionRunRepository
    events: EventRepository

    @abstractmethod
    def __enter__(self) -> "UnitOfWork": ...

    @abstractmethod
    def __exit__(self, exc_type, exc_val, exc_tb) -> None: ...

    @abstractmethod
    def commit(self) -> None: ...

    @abstractmethod
    def rollback(self) -> None: ...
