"""Nivel 3 — Bayesian Fairness Bandit (Camino B).

Este es el algoritmo central del proyecto. Aplica Thompson Sampling pero
redefiniendo qué representa theta_i, tal como se acordó en el diseño
original:

    theta_i = P(el estudiante i "sigue necesitando" ser seleccionado)

En vez de modelar "qué tan bien responde" (que llevaría al bandit a
converger hacia siempre elegir a los mismos estudiantes "buenos"),
modelamos "qué tan pendiente está su oportunidad". Esto se logra
invirtiendo el rol de las observaciones Bernoulli:

    - Si el estudiante NO fue seleccionado (pero SÍ estuvo presente):
      es evidencia de que su necesidad sigue latente -> "éxito" para la
      hipótesis "necesita oportunidad" -> alpha += 1

    - Si el estudiante SÍ fue seleccionado:
      su necesidad fue atendida -> "fracaso" para esa hipótesis -> beta += 1

Todos parten de Beta(alpha_init, beta_init), típicamente Beta(1,1):
incertidumbre uniforme, ningún estudiante arranca con ventaja ni
desventaja.

Diferencia respecto a la versión de simulación
------------------------------------------------
En `src/models/bayesian_fairness.py` (versión simulación), esta clase
guardaba `self.alpha` y `self.beta` como arrays de numpy que vivían en
memoria durante todo un trial, y `update(...)` los mutaba directamente.
Aquí la clase NO guarda ningún estado propio entre llamadas: recibe el
estado actual como `Candidate.alpha` / `Candidate.beta` (que viene de
donde sea que lo haya cargado el repositorio — base de datos en
producción, diccionario en memoria en simulación) y devuelve los deltas
a aplicar (`compute_posterior_updates`), sin aplicarlos ella misma. Eso
es lo que hace posible que esta misma clase sirva tanto para producción
como para simulación sin cambiar una línea (ver docstring de
`src/strategies/base.py`).
"""

from typing import List

import numpy as np

from src.domain.value_objects import Candidate, PosteriorUpdate
from src.strategies.base import BaseSelector
from src.strategies.registry import SelectorRegistry


@SelectorRegistry.register("bayesian_fairness")
class BayesianFairnessBandit(BaseSelector):
    """Thompson Sampling con theta_i = necesidad de oportunidad."""

    name = "bayesian_fairness"

    def __init__(self, alpha_init: float = 1.0, beta_init: float = 1.0):
        # alpha_init/beta_init solo se usan para inicializar el estado de
        # un estudiante NUEVO (ver `repositories`, método `get_or_create`
        # de StudentStateRepository). Una vez que el estudiante tiene una
        # fila persistida, su alpha/beta reales vienen del `Candidate`,
        # no de aquí.
        self.alpha_init = alpha_init
        self.beta_init = beta_init

    def select(self, candidates: List[Candidate], k: int, rng: np.random.Generator) -> List[int]:
        k = min(k, len(candidates))
        if k == 0:
            return []

        ids = np.array([c.student_id for c in candidates])
        alphas = np.array([c.alpha for c in candidates])
        betas = np.array([c.beta for c in candidates])

        # Paso de Thompson Sampling: para cada candidato se samplea UNA
        # muestra de su distribución Beta actual. rng.beta acepta arrays
        # completos y devuelve un array de muestras en una sola llamada
        # vectorizada -- evitamos un bucle Python por estudiante, lo cual
        # importa cuando se corren miles de simulaciones Monte Carlo o
        # cuando el curso es grande.
        theta_samples = rng.beta(alphas, betas)

        # Se seleccionan los k estudiantes con mayor muestra. argsort es
        # O(n log n); para cursos de decenas o cientos de estudiantes
        # esto es irrelevante en costo y más simple/legible que un heap.
        top_k_positions = np.argsort(theta_samples)[::-1][:k]
        return [int(x) for x in ids[top_k_positions]]

    def compute_posterior_updates(
        self, candidates: List[Candidate], selected_ids: List[int]
    ) -> List[PosteriorUpdate]:
        """Calcula, para cada candidato considerado, cuánto deberían
        moverse su alpha/beta tras esta ronda de selección.

        Nota: esto NO muta nada. Devuelve una lista de `PosteriorUpdate`
        que la capa de persistencia aplicará como incrementos atómicos
        (`alpha = alpha + delta_alpha`) directamente en la base de
        datos, evitando el problema de "lost update" bajo concurrencia
        (ver `repositories/sqlalchemy/repository_impl.py`).
        """
        selected_set = set(selected_ids)
        updates: List[PosteriorUpdate] = []
        for c in candidates:
            if c.student_id in selected_set:
                # Su necesidad fue atendida -> evidencia en contra de
                # "sigue necesitando oportunidad".
                updates.append(PosteriorUpdate(c.student_id, delta_alpha=0.0, delta_beta=1.0))
            else:
                # Sigue en deuda de participación -> evidencia a favor.
                updates.append(PosteriorUpdate(c.student_id, delta_alpha=1.0, delta_beta=0.0))
        return updates
