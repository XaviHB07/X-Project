"""Entidades de dominio: representan "cosas" que existen a lo largo del
tiempo y tienen identidad (a diferencia de los value objects, que son
solo datos).

Estas clases son deliberadamente simples (dataclasses planas) y NO son
los modelos de SQLAlchemy. Esa separación importa: la capa de servicios
y la de API hablan en términos de estas entidades de dominio, nunca de
`StudentORM` o `SelectionEventORM` directamente. Así, si mañana se
cambia el motor de base de datos (o se usa el repositorio in-memory en
un test), nada fuera de `repositories/` se entera del cambio.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


@dataclass(frozen=True)
class Course:
    """Un curso/aula: el contenedor de estudiantes sobre el que se hace
    selección. Existe para poder correr varios cursos en paralelo sobre
    la misma base de datos sin que se mezclen sus estudiantes ni sus
    métricas de equidad.
    """

    id: int
    name: str
    created_at: datetime
    cycle_id: Optional[int] = None
    roster_imported_at: Optional[datetime] = None


@dataclass(frozen=True)
class CourseMaterial:
    """Material académico asociado a un curso y, opcionalmente, a una sesión."""

    id: int
    course_id: int
    file_name: str
    title: str
    content_type: str
    size_bytes: int
    created_at: datetime
    updated_at: datetime
    class_session_id: Optional[int] = None
    topic: Optional[str] = None


@dataclass(frozen=True)
class CourseMaterialContent:
    """Contenido persistido de un material, incluido el texto extraído."""

    file_name: str
    content_type: str
    file_data: bytes
    extracted_text: str


@dataclass(frozen=True)
class ExposureTimeSettings:
    """Límites de duración de una exposición dentro de un curso."""

    course_id: int
    min_minutes: int
    max_minutes: int
    updated_at: datetime


@dataclass(frozen=True)
class AcademicCycle:
    """Un periodo académico que agrupa cursos independientes.

    HU-C3: el docente registra, modifica y elimina sus propios ciclos.
    `owner_teacher_id` identifica al docente que lo creó; es `None` en los
    ciclos creados por el Administrador (o anteriores al Sprint 6).
    `enabled` permite dar de baja el ciclo sin borrarlo, conservando su
    histórico: un ciclo deshabilitado no admite cursos nuevos.
    """

    id: int
    name: str
    created_at: datetime
    starts_on: Optional[date] = None
    ends_on: Optional[date] = None
    enabled: bool = True
    owner_teacher_id: Optional[int] = None


@dataclass(frozen=True)
class StudentAccount:
    """Cuenta global que puede vincularse a matrículas en varios cursos."""

    id: int
    username: str
    full_name: str
    email: Optional[str]
    role: str
    active: bool


@dataclass(frozen=True)
class StudentGroup:
    """Grupo dentro de una propuesta de distribución de un curso."""

    name: str
    student_ids: list[int]


@dataclass(frozen=True)
class CourseGroupPlan:
    """Propuesta de grupos guardada para poder consultarla y editarla."""

    id: int
    course_id: int
    name: str
    max_group_size: int
    groups: list[StudentGroup]
    created_at: datetime


@dataclass(frozen=True)
class CourseGroupPlanDraft:
    """Propuesta de grupos todavía no confirmada ni persistida."""

    course_id: int
    name: str
    max_group_size: int
    groups: list[StudentGroup]
    created_at: datetime


@dataclass(frozen=True)
class Student:
    """Identidad de un estudiante dentro de un curso.

    Nota de diseño: igual que en la simulación original, este modelo NO
    incluye notas, rendimiento académico ni ninguna característica de
    "calidad de respuesta". Sigue siendo una decisión deliberada: el
    algoritmo de equidad (Camino B) solo debe poder ver asistencia y
    selección, nunca desempeño, para no reintroducir por la puerta de
    atrás el sesgo que el diseño original buscaba evitar.
    """

    id: int
    course_id: int
    external_ref: str
    display_name: str
    created_at: datetime
    phone_number: Optional[str] = None
    email: Optional[str] = None
    user_id: Optional[int] = None
    roster_number: Optional[str] = None
    specialty: Optional[str] = None
    student_condition: Optional[str] = None
    times_repeated: Optional[str] = None
    # HU-C1: un estudiante retirado del curso no se borra (conserva su
    # historial de selección); solo deja de aparecer en la lista activa
    # y de ser elegible. Re-importarlo desde el Excel lo reactiva.
    active: bool = True


@dataclass(frozen=True)
class StudentState:
    """Estado bayesiano acumulado de un estudiante — el "resumen" que
    reemplaza a "guardar todo el historial" (ver README, sección sobre
    la pregunta original de diseño). Vive en la tabla `student_state`.
    """

    student_id: int
    alpha: float
    beta: float
    n_present: int
    n_selected: int
    updated_at: datetime


@dataclass(frozen=True)
class ClassSession:
    """Una ocurrencia concreta de "clase" (o, más generalmente, de
    "evento de selección") dentro de un curso. En la simulación esto era
    implícito (`class_idx` dentro de un `for`); en producción es una fila
    real, porque puede haber muchas creándose de forma concurrente,
    desde distintos requests, y cada una necesita una identidad propia
    para poder auditarse.
    """

    id: int
    course_id: int
    created_at: datetime
    label: Optional[str] = None
    # HU-S1: fecha de la clase (por defecto, la fecha actual) y tema
    # confirmado por el docente (propuesto desde el sílabo si existe).
    session_date: Optional[date] = None
    topic: Optional[str] = None


@dataclass(frozen=True)
class DecisionRun:
    """Una invocación concreta del servicio de selección: "en esta sesión,
    con este método, se pidieron k estudiantes de entre los presentes".
    Es la unidad transaccional (ver `services/selection_service.py`): o
    se guarda completa (decisión + actualización de estado + eventos) o
    no se guarda nada.
    """

    id: int
    class_session_id: int
    method_name: str
    k_requested: int
    k_selected: int
    created_at: datetime
    request_id: Optional[str] = None


@dataclass(frozen=True)
class SyllabusEntry:
    """Una línea de la planificación/sílabo de un curso: "el día D se ve
    el tema T". Es lo que permite que HU-S1 proponga el tema al iniciar
    una sesión. La carga masiva del sílabo no es parte del Sprint 1; por
    ahora las entradas se registran una a una.
    """

    id: int
    course_id: int
    session_date: date
    topic: str


@dataclass(frozen=True)
class AttendanceRecord:
    """Asistencia de un estudiante a una sesión de clase concreta (HU-S2).

    Es distinta de `StudentState.n_present`: aquella es un contador
    acumulado que solo se actualiza cuando se ejecuta una selección;
    esta es la marca editable del docente para UNA sesión.
    """

    class_session_id: int
    student_id: int
    present: bool


@dataclass(frozen=True)
class StudentParticipation:
    """Calificación y asistencia registradas para un estudiante seleccionado."""

    id: int
    decision_run_id: int
    student_id: int
    score: float
    present: bool
    created_at: datetime
    external_ref: str
    display_name: str
    difficulty: int = 3
    grade_visible: bool = False
    question: Optional[str] = None
    comment: Optional[str] = None


@dataclass(frozen=True)
class GroupExpositionMemberEntry:
    """Nota individual de un integrante tal como la envía el docente.

    `score` puede quedar vacío solo si el integrante no estuvo presente;
    `position` es su lugar en el orden de exposición (1 = primero).
    """

    student_id: int
    present: bool
    score: Optional[float] = None
    position: Optional[int] = None


@dataclass(frozen=True)
class GroupExpositionMemberScore:
    """Nota individual ya registrada de un integrante del grupo expositor."""

    student_id: int
    external_ref: str
    display_name: str
    present: bool
    score: Optional[float] = None
    position: Optional[int] = None


@dataclass(frozen=True)
class GroupExposition:
    """Calificación de la exposición de un grupo elegido por ruleta/bolillero.

    Guarda una nota grupal y una nota individual por integrante. El nombre
    del grupo y el de la propuesta se copian al momento de calificar: las
    propuestas de grupos se pueden editar o eliminar después, y la nota
    registrada no debe cambiar ni perderse por eso.
    """

    id: int
    course_id: int
    group_name: str
    group_score: float
    created_at: datetime
    updated_at: datetime
    members: list[GroupExpositionMemberScore] = field(default_factory=list)
    class_session_id: Optional[int] = None
    group_plan_id: Optional[int] = None
    plan_name: Optional[str] = None
    comment: Optional[str] = None
    duration_seconds: Optional[int] = None
