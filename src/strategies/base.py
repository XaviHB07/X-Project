"""Interfaz común para cualquier algoritmo de selección (patrón Strategy).

Diferencia clave respecto al proyecto original (`src/models/basePadre.py`
en la versión de simulación): la interfaz ya no conoce `Student` (el
dataclass con estado mutable de la simulación) ni persiste nada por sí
misma. Opera exclusivamente sobre `Candidate`, un snapshot inmutable
(ver `src/domain/value_objects.py`), y comunica sus efectos secundarios
como datos (`PosteriorUpdate`) en vez de mutaciones. Esto es lo que
permite que el mismo algoritmo funcione igual de bien:

    - dentro de una simulación Monte Carlo en memoria (`src/simulation/`), y
    - dentro de una transacción de base de datos real (`src/services/`),

sin que el algoritmo necesite saber en cuál de los dos mundos está.
"""

from abc import ABC, abstractmethod
from typing import List

import numpy as np

from src.domain.value_objects import Candidate, PosteriorUpdate


class BaseSelector(ABC):
    """Contrato que debe cumplir cualquier algoritmo de selección."""

    #: Nombre corto y estable del método (se usa como clave en el
    #: registro, en la base de datos -- `decision_runs.method_name` -- y
    #: en la configuración YAML). No debe cambiar una vez usado en
    #: producción: romper esta convención invalidaría el historial.
    name: str = "base"

    @abstractmethod
    def select(self, candidates: List[Candidate], k: int, rng: np.random.Generator) -> List[int]:
        """Elige hasta k `student_id` de entre los candidatos.

        Args:
            candidates: estudiantes considerados (normalmente, los
                presentes en la sesión actual). Es responsabilidad de
                quien llama (ver `SelectionService`) pasar solo a los
                elegibles; la estrategia no filtra asistencia.
            k: cuántos seleccionar. Si `len(candidates) < k`, se
                seleccionan todos los candidatos disponibles.
            rng: generador de números aleatorios ya inicializado. Se
                inyecta desde afuera (en vez de crearlo internamente)
                para que tanto la simulación (semillas deterministas,
                reproducibilidad) como producción (aleatoriedad real)
                puedan controlar su procedencia sin tocar la estrategia.

        Returns:
            Lista de `student_id` seleccionados, sin repetidos, de
            longitud `min(k, len(candidates))`.
        """
        raise NotImplementedError

    def compute_posterior_updates(
        self, candidates: List[Candidate], selected_ids: List[int]
    ) -> List[PosteriorUpdate]:
        """Calcula (sin aplicar) los deltas de alpha/beta tras una selección.

        Implementación por defecto: ninguna. Las estrategias sin estado
        bayesiano (`RouletteSelector`, `WeightedSoftmaxSelector`) no
        necesitan sobreescribir este método. Solo `BayesianFairnessBandit`
        lo hace, porque es la única que mantiene una distribución
        posterior Beta por estudiante.

        Nota: los contadores genéricos (`n_present`, `n_selected`) NO se
        calculan aquí -- son responsabilidad de `SelectionService`,
        porque son iguales para cualquier estrategia (ver
        `GenericCountersUpdate` en `domain/value_objects.py`).
        """
        return []
