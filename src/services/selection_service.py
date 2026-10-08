"""`SelectionService`: el caso de uso central del sistema.

Es la traducción directa, a código, del flujo que describió el asesor:

    1. cargar el estado actual del estudiante,
    2. elegir según su distribución posterior,
    3. guardar la decisión,
    4. actualizar alpha/beta y la historia,
    5. repetir en el siguiente evento/solicitud.

Toda la operación (leer con bloqueo, decidir, actualizar contadores y
posterior, registrar el evento) ocurre dentro de UNA sola `UnitOfWork`:
o se guarda completa, o no se guarda nada.

Nota sobre un bug encontrado y corregido en el diseño original
------------------------------------------------------------------
El `README.md` original describe el algoritmo así: "en cada clase se
samplea theta_i de la distribución actual de cada estudiante presente, y
se seleccionan los k con mayor muestra" — es decir, UNA sola muestra por
estudiante, UNA sola vez por clase, y de ahí se toman los k mejores
(exactamente lo que hace `BayesianFairnessBandit.select`, que ya soporta
`k` directamente vía `argsort`).

Pero `src/simulation/classroom.py` (la versión de simulación entregada)
en realidad NO llamaba a `select(...)` así: lo hacía en un bucle,
pidiendo un estudiante a la vez (`k=1`) y llamando a `update(...)` entre
cada pick, SIN remover al estudiante recién elegido de la lista de
"presentes" que se le pasaba a la siguiente vuelta. Eso tiene dos
consecuencias no documentadas y, casi con certeza, no intencionales:

    1. Un mismo estudiante podía ser seleccionado más de una vez en la
       misma clase (sobre todo notorio en `roulette`, que no tiene
       ninguna razón interna para evitarlo).
    2. Un estudiante presente pero nunca elegido terminaba acumulando
       `alpha += 1` una vez POR CADA cupo de la clase (k veces), en vez
       de una vez por clase -- inflando su "necesidad" mucho más rápido
       de lo que el modelo matemático del README pretende.

Este servicio implementa la versión que SÍ coincide con el README y con
la propia interfaz de `BaseSelector.select(candidates, k, rng)` (que ya
acepta k > 1): se muestrea una sola vez por candidato y se aplican los
deltas posteriores una sola vez por clase. Esto elimina ambos problemas
a la vez, sin necesitar lógica adicional de "remover al ya elegido" (el
top-k de una sola pasada nunca puede repetir a nadie). El detalle se
documenta también en el README de este entregable, sección "Bugs
encontrados y corregidos".
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np

from src.domain.events import DecisionRunCompleted, EventBus
from src.domain.value_objects import Candidate, DecisionResult, GenericCountersUpdate
from src.repositories.interfaces import UnitOfWork
from src.strategies.registry import SelectorRegistry

UnitOfWorkFactory = Callable[[], UnitOfWork]


class NoEligibleStudentsError(ValueError):
    """Ninguno de los `student_id` pedidos tiene estado registrado.

    Suele significar que se pasaron ids que nunca pasaron por
    `StudentRepository.get_or_create` (no están "matriculados").
    """


class NoClassSessionError(ValueError):
    """La sesión indicada para reutilizar no existe."""


class SelectionService:
    """Caso de uso: seleccionar k estudiantes de entre los presentes,
    persistiendo la decisión de forma atómica.
    """

    def __init__(self, uow_factory: UnitOfWorkFactory, event_bus: Optional[EventBus] = None):
        self._uow_factory = uow_factory
        self._event_bus = event_bus

    def run_selection(
        self,
        course_id: int,
        present_student_ids: Optional[Sequence[int]],
        k: int,
        method_name: str,
        method_params: Optional[dict] = None,
        class_session_id: Optional[int] = None,
        session_label: Optional[str] = None,
        rng: Optional[np.random.Generator] = None,
        request_id: Optional[str] = None,
    ) -> DecisionResult:
        """Ejecuta una selección completa y la persiste atómicamente.

        Args:
            course_id: curso al que pertenece la sesión (se usa solo si
                hay que crear una `class_session` nueva).
            present_student_ids: ids de los estudiantes que asistieron a
                esta sesión y por lo tanto son elegibles. Si es `None`,
                se usa la asistencia registrada en la sesión indicada por
                `class_session_id` (HU-S2); en ese caso `class_session_id`
                es obligatorio.
            k: cupos a llenar en esta sesión.
            method_name: clave de `SelectorRegistry` (p. ej.
                "bayesian_fairness"). Debe haberse importado
                `src.strategies` antes de llamar a este método para que
                el registro esté poblado (ver `services/bootstrap.py`).
            method_params: hiperparámetros del constructor de la
                estrategia (p. ej. `{"alpha_init": 1.0, "beta_init": 1.0}`
                para `bayesian_fairness`, o `{"tau": 0.5}` para
                `weighted_softmax`).
            class_session_id: si ya existe una sesión de clase creada
                (p. ej. porque la API la creó en un paso previo), se
                reutiliza. Si es `None`, se crea una nueva DENTRO de la
                misma transacción.
            rng: generador de números aleatorios. Si no se provee, se
                crea uno nuevo con entropía del sistema operativo
                (comportamiento correcto para producción real). Los
                tests y la simulación sí pasan un `rng` con semilla fija,
                para reproducibilidad.
            request_id: identificador de correlación opcional (p. ej. el
                id de request HTTP), útil para trazar en los logs / en
                `decision_runs.request_id` qué solicitud externa originó
                esta decisión.

        Returns:
            `DecisionResult` con el id de la decisión persistida y la
            lista de estudiantes elegidos.

        Raises:
            NoEligibleStudentsError: si ninguno de los
                `present_student_ids` tiene un `StudentState` registrado,
                o si se pidió usar la asistencia de la sesión y no hay
                nadie marcado como presente.
            NoClassSessionError: si `class_session_id` no existe o es de
                otro curso.
            ValueError: si `present_student_ids` es `None` y no se indicó
                `class_session_id`.
        """
        if present_student_ids is None and class_session_id is None:
            raise ValueError(
                "Indica present_student_ids o una class_session_id con asistencia registrada."
            )

        rng = rng or np.random.default_rng()
        selector = SelectorRegistry.create(method_name, method_params or {})

        with self._uow_factory() as uow:
            if class_session_id is None:
                session = uow.class_sessions.create(course_id, label=session_label)
                class_session_id = session.id
            else:
                existing = uow.class_sessions.get(class_session_id)
                if existing is None or existing.course_id != course_id:
                    # Una sesión de OTRO curso se trata igual que una
                    # inexistente: no se revela ni se usa su asistencia.
                    raise NoClassSessionError(
                        f"La sesión de clase {class_session_id} no existe en este curso."
                    )

            if present_student_ids is None:
                present_student_ids = uow.attendance.present_ids(class_session_id)
                if not present_student_ids:
                    raise NoEligibleStudentsError(
                        "La sesión no tiene estudiantes marcados como presentes."
                    )

            # Lectura CON bloqueo (equivalente a `SELECT ... FOR UPDATE`,
            # ver `repositories/sqlalchemy/repository_impl.py`): desde
            # aquí y hasta el commit()/rollback() de este `with`, ninguna
            # otra transacción concurrente puede leer-para-actualizar ni
            # escribir estas mismas filas.
            candidates: List[Candidate] = uow.student_states.get_candidates_for_update(
                present_student_ids
            )
            if not candidates:
                raise NoEligibleStudentsError(
                    "Ninguno de los estudiantes indicados tiene estado registrado. "
                    "¿Se llamó a StudentRepository.get_or_create() para ellos?"
                )

            considered_before: Dict[int, Candidate] = {c.student_id: c for c in candidates}

            # Un único muestreo por candidato, un único top-k -- esto es
            # lo que el README original describe matemáticamente, y lo
            # que ya soportan las tres estrategias (ver docstring del
            # módulo para la discusión del bug que esto corrige).
            selected_ids = selector.select(candidates, k, rng)
            posterior_updates = {
                u.student_id: u for u in selector.compute_posterior_updates(candidates, selected_ids)
            }

            generic_updates = [
                GenericCountersUpdate(
                    student_id=student_id, present=True, selected=student_id in selected_ids
                )
                for student_id in considered_before
            ]

            decision_run = uow.decision_runs.create(
                class_session_id=class_session_id,
                method_name=method_name,
                k_requested=k,
                k_selected=len(selected_ids),
                request_id=request_id,
            )
            uow.student_states.apply_updates(generic_updates, list(posterior_updates.values()))
            uow.events.log_decision(decision_run.id, considered_before, selected_ids, posterior_updates)

            uow.commit()

        result = DecisionResult(
            decision_run_id=decision_run.id,
            class_session_id=class_session_id,
            method_name=method_name,
            considered_student_ids=list(considered_before.keys()),
            selected_student_ids=list(selected_ids),
            created_at=decision_run.created_at,
            request_id=request_id,
        )

        if self._event_bus is not None:
            self._event_bus.publish(
                DecisionRunCompleted(
                    decision_run_id=result.decision_run_id,
                    class_session_id=result.class_session_id,
                    method_name=result.method_name,
                    considered_student_ids=result.considered_student_ids,
                    selected_student_ids=result.selected_student_ids,
                    occurred_at=datetime.now(timezone.utc),
                )
            )

        return result
