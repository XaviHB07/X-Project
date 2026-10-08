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
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

from src.domain.entities import (
    AttendanceRecord,
    ClassSession,
    Course,
    DecisionRun,
    Participation,
    Student,
    SyllabusEntry,
)
from src.domain.value_objects import (
    Candidate,
    GenericCountersUpdate,
    PosteriorUpdate,
    SelectionEventRecord,
)


class DuplicateStudentError(ValueError):
    """Se intentó dejar a dos estudiantes del mismo curso con el mismo
    `external_ref`."""


class ParticipationError(ValueError):
    """Una participación no se pudo registrar: referencias inválidas o
    estudiante que no pertenece a la sesión."""


class CourseRepository(ABC):
    """Persistencia de cursos (el contenedor de estudiantes)."""

    @abstractmethod
    def create(self, name: str) -> Course: ...

    @abstractmethod
    def get(self, course_id: int) -> Optional[Course]: ...

    @abstractmethod
    def list_all(self) -> List[Course]:
        """Todos los cursos, del más antiguo al más reciente (HU-S1: el
        docente elige el curso sobre el que inicia la sesión)."""
        ...


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
        phone_number: Optional[str] = None,
        email: Optional[str] = None,
    ) -> Student:
        """Devuelve el estudiante si ya existe (por `external_ref` dentro
        del curso); si no, lo crea junto con su `StudentState` inicial
        en `Beta(alpha_init, beta_init)`. Es idempotente a propósito: un
        cliente puede llamarlo en cada request de "matrícula" sin
        preocuparse por duplicados.
        """
        ...

    @abstractmethod
    def upsert_from_roster(
        self,
        course_id: int,
        external_ref: str,
        display_name: str,
        alpha_init: float,
        beta_init: float,
        phone_number: Optional[str] = None,
        email: Optional[str] = None,
    ) -> Tuple[Student, str]:
        """Crea o actualiza un estudiante a partir de una fila del Excel
        (HU-C1). A diferencia de `get_or_create`, si el estudiante ya
        existe SÍ actualiza su nombre (y lo reactiva si estaba retirado).

        Devuelve `(estudiante, estado)` con estado `"created"`,
        `"updated"` o `"unchanged"`, para que quien importa pueda
        informar al docente qué pasó con cada fila.
        """
        ...

    @abstractmethod
    def update(
        self,
        student_id: int,
        external_ref: Optional[str] = None,
        display_name: Optional[str] = None,
        active: Optional[bool] = None,
        phone_number: Optional[str] = None,
        email: Optional[str] = None,
    ) -> Optional[Student]:
        """Actualiza los campos no-`None`. Devuelve `None` si el
        estudiante no existe; lanza `DuplicateStudentError` si el nuevo
        `external_ref` ya lo usa otro estudiante del mismo curso."""
        ...

    @abstractmethod
    def get(self, student_id: int) -> Optional[Student]: ...

    @abstractmethod
    def list_by_course(self, course_id: int, include_inactive: bool = False) -> List[Student]: ...


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
    def create(
        self,
        course_id: int,
        label: Optional[str] = None,
        session_date: Optional[date] = None,
        topic: Optional[str] = None,
    ) -> ClassSession:
        """Si `session_date` es `None` se usa la fecha actual (UTC)."""
        ...

    @abstractmethod
    def get(self, class_session_id: int) -> Optional[ClassSession]: ...

    @abstractmethod
    def list_by_course(self, course_id: int) -> List[ClassSession]:
        """Sesiones del curso, la más reciente primero."""
        ...


class SyllabusRepository(ABC):
    """Persistencia de la planificación (sílabo) del curso: qué tema
    corresponde a cada fecha. Alimenta la propuesta de tema de HU-S1."""

    @abstractmethod
    def upsert(self, course_id: int, session_date: date, topic: str) -> SyllabusEntry:
        """Una sola entrada por (curso, fecha): si ya existía, reemplaza el tema."""
        ...

    @abstractmethod
    def get_topic_for_date(self, course_id: int, session_date: date) -> Optional[str]: ...

    @abstractmethod
    def list_by_course(self, course_id: int) -> List[SyllabusEntry]: ...


class AttendanceRepository(ABC):
    """Asistencia por sesión (HU-S2)."""

    @abstractmethod
    def set_many(self, class_session_id: int, present_by_student: Dict[int, bool]) -> None:
        """Crea o actualiza la marca de asistencia de cada estudiante dado."""
        ...

    @abstractmethod
    def list_for_session(self, class_session_id: int) -> List[AttendanceRecord]: ...

    @abstractmethod
    def present_ids(self, class_session_id: int) -> List[int]:
        """Ids de los estudiantes marcados como presentes. Un estudiante
        sin registro de asistencia NO cuenta como presente."""
        ...


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


class ParticipationRepository(ABC):
    """Persistencia de participaciones (HU-P4).

    Es lo que cierra MVP 1. `EventRepository` guarda la traza del ALGORITMO
    (que estudiantes se consideraron, con que alpha/beta, y quien quedo
    elegido); esta guarda lo que PASO EN CLASE: que se pregunto, que
    respondio y cuando.

    Son cosas distintas. Sin esta, el sistema sortea estudiantes y no queda
    constancia de nada de lo que se dijo, y el criterio de exito del Roadmap
    ("queda un historial trazable") no se cumple.
    """

    @abstractmethod
    def create(
        self,
        class_session_id: int,
        student_id: int,
        question: str,
        answer: Optional[str],
        asked_at,
        decision_run_id: Optional[int] = None,
        created_by: Optional[str] = None,
        present: bool = True,
    ) -> Participation:
        """Registra una participacion y devuelve la entidad creada.

        `present` se congela en el momento del registro (ver el docstring de
        `domain.Participation`): si el docente corrige la asistencia despues,
        el historial no debe cambiar bajo sus pies.

        Lanza `ParticipationError` si la sesion o el estudiante no existen, o
        si el estudiante no pertenece al curso de esa sesion.
        """
        ...

    @abstractmethod
    def get(self, participation_id: int) -> Optional[Participation]: ...

    @abstractmethod
    def list_for_session(
        self,
        class_session_id: int,
        include_anuladas: bool = False,
    ) -> List[Participation]:
        """Participaciones de una sesion, en orden cronologico.

        Por defecto excluye las anuladas: el historial que ve el docente es el
        real. Para auditar, se pasa `include_anuladas=True`.
        """
        ...

    @abstractmethod
    def list_for_student(
        self,
        student_id: int,
        include_anuladas: bool = False,
    ) -> List[Participation]:
        """Historial completo de un estudiante, mas reciente primero."""
        ...

    @abstractmethod
    def count_for_session(self, class_session_id: int) -> int:
        """Cuantas participaciones validas lleva la sesion. Alimenta el
        contador que ve el docente durante la clase."""
        ...

    @abstractmethod
    def anular(
        self,
        participation_id: int,
        motivo: Optional[str] = None,
    ) -> Optional[Participation]:
        """Anulacion LOGICA: marca la participacion como anulada y devuelve la
        entidad actualizada, o `None` si no existe.

        Nunca borra. Una participacion mal registrada se corrige; el rastro de
        que estuvo mal tambien forma parte del historial.
        """
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
    syllabus: SyllabusRepository
    attendance: AttendanceRepository
    decision_runs: DecisionRunRepository
    events: EventRepository
    participations: ParticipationRepository

    @abstractmethod
    def __enter__(self) -> "UnitOfWork": ...

    @abstractmethod
    def __exit__(self, exc_type, exc_val, exc_tb) -> None: ...

    @abstractmethod
    def commit(self) -> None: ...

    @abstractmethod
    def rollback(self) -> None: ...
