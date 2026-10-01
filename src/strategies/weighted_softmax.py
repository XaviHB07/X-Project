"""Nivel 2 — Algoritmo de equidad por historial (sin incertidumbre bayesiana).

Cada estudiante recibe un "score" inversamente proporcional a cuánto ya
ha participado (`n_selected`, que ahora viene del `Candidate` persistido
en vez de un contador en memoria), y esos scores se convierten en
probabilidades vía softmax:

    U_i = 1 / (1 + n_selected_i)
    P(i) = exp(U_i / tau) / sum_j exp(U_j / tau)

tau controla cuánto se favorece a quien menos ha participado:
    - tau bajo  -> selección casi determinista hacia el más rezagado.
    - tau alto  -> se acerca a la ruleta uniforme.

Sirve como punto de comparación intermedio entre la ruleta (Nivel 1) y
el bandit bayesiano (Nivel 3): usa historial, pero no modela
incertidumbre. La diferencia de resultados entre Nivel 2 y Nivel 3 es lo
que permite argumentar si Bayes realmente aporta algo más allá de "usar
el historial".
"""

from typing import List

import numpy as np

from src.domain.value_objects import Candidate
from src.strategies.base import BaseSelector
from src.strategies.registry import SelectorRegistry


@SelectorRegistry.register("weighted_softmax")
class WeightedSoftmaxSelector(BaseSelector):
    """Selección ponderada por historial, sin componente bayesiano."""

    name = "weighted_softmax"

    def __init__(self, tau: float = 0.5):
        if tau <= 0:
            raise ValueError("tau debe ser positivo (es un divisor en el softmax).")
        self.tau = tau

    def _softmax(self, scores: np.ndarray) -> np.ndarray:
        # Restamos el máximo antes de exponenciar (truco estándar de
        # estabilidad numérica): evita overflow y no cambia el resultado
        # porque softmax es invariante a desplazamientos constantes.
        z = (scores - scores.max()) / self.tau
        exp_z = np.exp(z)
        return exp_z / exp_z.sum()

    def select(self, candidates: List[Candidate], k: int, rng: np.random.Generator) -> List[int]:
        k = min(k, len(candidates))
        if k == 0:
            return []
        scores = np.array([1.0 / (1.0 + c.n_selected) for c in candidates])
        probs = self._softmax(scores)
        ids = np.array([c.student_id for c in candidates])

        # Muestreo ponderado SIN reemplazo de tamaño k. numpy.random.choice
        # con replace=False y p=... ya implementa esto correctamente, así
        # que evitamos reinventar el algoritmo a mano.
        chosen = rng.choice(ids, size=k, replace=False, p=probs)
        return [int(x) for x in chosen]

    # No sobreescribe compute_posterior_updates: el "historial" que este
    # método usa (n_selected) ya se actualiza de forma genérica por
    # SelectionService para TODAS las estrategias; no necesita estado
    # bayesiano adicional.
