"""Value objects que cruzan las fronteras entre capas.

Un "value object" es un objeto inmutable identificado por sus datos (no
por una identidad persistente como una fila de base de datos). Se usan
aquí como el "idioma común" entre `strategies` (los algoritmos) y
`repositories` (la persistencia), de forma que ninguna de las dos capas
necesite conocer detalles internos de la otra.

Por qué esto importa para el problema original del usuario
------------------------------------------------------------
En la simulación original, `BayesianFairnessBandit` mutaba directamente
arrays de numpy (`self.alpha`, `self.beta`) que vivían en memoria durante
una corrida. Eso es exactamente lo que deja de funcionar en producción:
no hay "un" array compartido, sino filas de una base de datos que muchos
requests concurrentes pueden leer/escribir.

La solución de este rediseño es que los algoritmos de selección (Strategy)
ya NO mutan nada directamente. En su lugar:

    1. Reciben una lista de `Candidate` (snapshot inmutable del estado
       actual de cada estudiante presente, venga de donde venga: una
       base de datos real o un diccionario en memoria).
    2. Devuelven qué estudiantes eligieron (`select`).
    3. Devuelven qué *cambios* habría que aplicar a alpha/beta
       (`compute_posterior_updates`), como una lista de deltas, SIN
       aplicarlos ellos mismos.

Quien aplica esos deltas es la capa de `repositories`, de la única forma
segura de hacerlo cuando hay concurrencia: con una actualización atómica
tipo `UPDATE student_state SET alpha = alpha + :delta WHERE student_id = :id`
dentro de una transacción (ver `repositories/sqlalchemy/repository_impl.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


@dataclass(frozen=True)
class Candidate:
    """Snapshot inmutable del estado de un estudiante en el momento en que
    se lo considera para una selección.

    Es deliberadamente un "value object" (frozen, sin métodos que muten
    estado) y no una entidad de base de datos: las estrategias no deben
    poder alterar la fila real de la base de datos por accidente, solo
    razonar sobre un snapshot y proponer cambios.

    Attributes:
        student_id: identificador estable del estudiante.
        alpha: parámetro alpha actual de la Beta(alpha, beta) — evidencia
            acumulada de que el estudiante "sigue necesitando" ser
            seleccionado (ver docstring de bayesian_fairness.py).
        beta: parámetro beta actual — evidencia acumulada de que su
            necesidad ya fue atendida.
        n_present: número de clases/sesiones en las que ha estado
            presente hasta ahora (histórico persistido).
        n_selected: número de veces que ha sido seleccionado hasta ahora
            (histórico persistido). Lo usa `weighted_softmax`, que no
            tiene noción de alpha/beta.
    """

    student_id: int
    alpha: float
    beta: float
    n_present: int
    n_selected: int


@dataclass(frozen=True)
class PosteriorUpdate:
    """Delta a aplicar sobre alpha/beta de un estudiante.

    Solo las estrategias con estado bayesiano (hoy, `BayesianFairnessBandit`)
    producen updates con deltas distintos de cero; `RouletteSelector` y
    `WeightedSoftmaxSelector` no tienen parámetros bayesianos y
    simplemente no emiten ninguno (ver `BaseSelector.compute_posterior_updates`).
    """

    student_id: int
    delta_alpha: float = 0.0
    delta_beta: float = 0.0


@dataclass(frozen=True)
class GenericCountersUpdate:
    """Delta a aplicar sobre los contadores genéricos (n_present, n_selected).

    A diferencia de alpha/beta (específico del algoritmo bayesiano),
    n_present y n_selected son contadores que TODAS las estrategias
    comparten y que se actualizan siempre de la misma manera, sin
    importar qué algoritmo se use. Por eso el servicio de aplicación
    (`SelectionService`) los calcula una sola vez, en lugar de pedirle a
    cada estrategia que los reproduzca.
    """

    student_id: int
    present: bool
    selected: bool


@dataclass(frozen=True)
class SelectionEventRecord:
    """Vista de un evento de selección ya persistido, para lectura/auditoría.

    Es lo que devuelve `EventRepository.history_for_student(...)`: un
    registro de "esto pasó" con el estado antes/después, para poder
    explicar por qué un estudiante fue o no elegido en un momento dado
    sin tener que recalcular nada.
    """

    id: int
    decision_run_id: int
    student_id: int
    present: bool
    selected: bool
    alpha_before: float
    beta_before: float
    alpha_after: float
    beta_after: float
    created_at: datetime


@dataclass(frozen=True)
class DecisionResult:
    """Resultado devuelto por `SelectionService.run_selection(...)`.

    Es el objeto que cruza hacia la capa de API (o hacia quien haya
    invocado el caso de uso): contiene lo mínimo necesario para responder
    al cliente sin que este necesite conocer el esquema de base de datos.
    """

    decision_run_id: int
    class_session_id: int
    method_name: str
    considered_student_ids: List[int]
    selected_student_ids: List[int]
    created_at: datetime
    request_id: Optional[str] = None
