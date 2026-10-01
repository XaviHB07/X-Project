"""Nivel 1 — Baseline: ruleta completamente aleatoria.

P(i) = 1 / N para cada estudiante considerado. Es la línea base
obligatoria: sin ella no se puede afirmar que un método "más
sofisticado" realmente mejora la equidad; podría estar empeorándola o no
aportar nada. Sin memoria, sin estado bayesiano: cada llamada es
independiente de las anteriores.
"""

from typing import List

import numpy as np

from src.domain.value_objects import Candidate
from src.strategies.base import BaseSelector
from src.strategies.registry import SelectorRegistry


@SelectorRegistry.register("roulette")
class RouletteSelector(BaseSelector):
    """Selección uniforme sin memoria."""

    name = "roulette"

    def select(self, candidates: List[Candidate], k: int, rng: np.random.Generator) -> List[int]:
        ids = [c.student_id for c in candidates]
        k = min(k, len(ids))
        if k == 0:
            return []
        # rng.choice con replace=False hace un muestreo uniforme sin
        # repetición; numpy lo implementa de forma eficiente, por eso lo
        # preferimos sobre un bucle manual.
        chosen = rng.choice(ids, size=k, replace=False)
        return [int(x) for x in chosen]

    # No sobreescribe compute_posterior_updates: la ruleta no tiene
    # estado bayesiano, así que hereda la implementación por defecto
    # (lista vacía) de BaseSelector.
