"""`FairnessMetricsService`: calcula las métricas de equidad (Gini, CV,
std, cobertura) a partir del estado PERSISTIDO actual, en vez de a partir
de los `ClassSnapshot` en memoria que usaba la simulación original.

Esta es una consecuencia directa de la pregunta original del usuario: en
producción "el estado acumulado ya contiene la información histórica
relevante" (cita del asesor), así que basta con leer `n_selected` de cada
`StudentState` persistido -- no hace falta reconstruir nada a partir del
log de eventos para responder "¿qué tan equitativo ha sido el curso hasta
ahora?".
"""

from __future__ import annotations

import numpy as np

from src.metrics.fairness_metrics import compute_all
from src.repositories.interfaces import UnitOfWork
from src.services.selection_service import UnitOfWorkFactory


class FairnessMetricsService:
    """Caso de uso de solo lectura: métricas de equidad de un curso."""

    def __init__(self, uow_factory: UnitOfWorkFactory):
        self._uow_factory = uow_factory

    def compute_for_course(self, course_id: int) -> dict:
        """Devuelve `{gini, cv, std, coverage, n_students}` para un curso.

        No toma ningún bloqueo (usa `get_all_candidates_for_course`, de
        solo lectura): calcular una métrica no debería competir por los
        mismos candados que usan las transacciones de selección.
        """
        with self._uow_factory() as uow:  # type: UnitOfWork
            candidates = uow.student_states.get_all_candidates_for_course(course_id)

        counts = np.array([c.n_selected for c in candidates], dtype=float)
        metrics = compute_all(counts)
        metrics["n_students"] = len(candidates)
        return metrics
