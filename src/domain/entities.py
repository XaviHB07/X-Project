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

from dataclasses import dataclass
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
class Participation:
    """Una participación efectiva de un estudiante en una sesión (HU-P4).

    Es la entidad que cierra MVP 1. Sin ella, el sistema sortea estudiantes
    pero no queda rastro de qué se preguntó ni de qué respondió: la selección
    (`selection_events`) es un registro del ALGORITMO, no de lo que pasó en
    clase. Son cosas distintas y las dos hacen falta.

    Lo que guarda, y por qué cada campo:

      `question` / `answer`  el contenido de la participación. Es el dato que
                             el docente va a necesitar después para calificar
                             (MVP 2) y para revisar qué Preguntas funcionaron.
      `asked_at`             cuándo se preguntó. Con `id` da un orden
                             inequívoco aunque dos participaciones caigan en
                             el mismo segundo, cosa habitual en clase.
      `decision_run_id`      de qué sorteo salió este estudiante. Es lo que
                             permite auditar "lo elegí por Bayesian fairness
                             en el sorteo #7", y reconstruir la sesión completa
                             más adelante. Opcional porque HU-P4 no lo exige:
                             el docente puede registrar a mano una
                             participación que no venía de un sorteo.
      `present`              si el estudiante estaba presente. Se copia en el
                             momento del registro y NO se lee en vivo de la
                             asistencia: si el docente corrige la asistencia
                             despues, el historial no debe cambiar bajo sus
                             pies. El registro es una foto de ese instante.
      `anulada` / `motivo`   anulacion logica. Anular nunca borra: un
                             registro mal hecho se corrige, y el rastro de que
                             estuvo mal tambien importa.
    """

    id: int
    class_session_id: int
    student_id: int
    question: str
    asked_at: datetime
    answer: Optional[str] = None
    decision_run_id: Optional[int] = None
    present: bool = True
    created_by: Optional[str] = None
    anulada: bool = False
    motivo_anulacion: Optional[str] = None
