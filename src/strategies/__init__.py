"""Algoritmos de selección (patrón Strategy) + registro dinámico (patrón
Factory/Registry).

Los tres niveles del proyecto original se preservan tal cual en su
esencia matemática (ruleta uniforme, softmax por historial, Thompson
Sampling invertido). Lo que cambia es el CONTRATO: ya no reciben
`List[Student]` (el dataclass de la simulación, con `attendance_prob` y
mutación in-place), sino `List[Candidate]` (value object inmutable,
`src/domain/value_objects.py`), y en vez de mutar su propio estado
interno con `update(...)`, devuelven una lista de deltas con
`compute_posterior_updates(...)`.

Importar este paquete tiene el efecto secundario (deliberado) de
registrar las tres estrategias en `SelectorRegistry` a través del
decorador `@SelectorRegistry.register(...)` que decora cada clase. Por
eso `services/bootstrap.py` simplemente hace `import src.strategies` una
vez al arrancar la aplicación, y desde ahí `SelectorRegistry.create(...)`
ya conoce las tres. Agregar un cuarto método a futuro es: crear el
archivo, decorar la clase, importarlo aquí. Ni `SelectionService` ni la
API necesitan cambiar una sola línea.
"""

from src.strategies.roulette import RouletteSelector
from src.strategies.weighted_softmax import WeightedSoftmaxSelector
from src.strategies.bayesian_fairness import BayesianFairnessBandit
from src.strategies.base import BaseSelector
from src.strategies.registry import SelectorRegistry

__all__ = [
    "BaseSelector",
    "SelectorRegistry",
    "RouletteSelector",
    "WeightedSoftmaxSelector",
    "BayesianFairnessBandit",
]
