"""Registro dinámico de estrategias (patrón Factory, variante Registry).

Problema que resuelve
----------------------
En la versión de simulación, `scripts/run_experiment.py` tenía una
función `build_selectors(methods_cfg)` con un `if/elif` (en realidad un
dict literal) que conocía, a mano, los nombres de las tres clases. Cada
vez que se agregaba un algoritmo nuevo había que recordar tocar ese
archivo. Es un acoplamiento evitable.

Solución
--------
Cada estrategia se auto-registra con un decorador en el momento en que
su módulo se importa:

    @SelectorRegistry.register("bayesian_fairness")
    class BayesianFairnessBandit(BaseSelector):
        ...

Y cualquier capa que necesite construir una estrategia por nombre
(la API, el servicio, el runner de simulación, la config YAML) le
pregunta al registro, sin importar el módulo concreto ni conocer el
nombre de la clase:

    selector = SelectorRegistry.create("bayesian_fairness", {"alpha_init": 1.0, "beta_init": 1.0})

Agregar un cuarto método a futuro (p. ej. un bandit contextual) es:
1. crear `src/strategies/contextual.py` con la clase decorada, y
2. añadir la línea de import en `src/strategies/__init__.py`.
Ningún otro archivo del proyecto necesita cambiar.
"""

from __future__ import annotations

from inspect import signature
from typing import Callable, Dict, List, Type

from src.strategies.base import BaseSelector


class UnknownSelectorError(ValueError):
    """Se pidió un método de selección que no está registrado."""


class InvalidSelectorParametersError(ValueError):
    """Los parámetros no coinciden con el constructor de la estrategia."""


class SelectorRegistry:
    """Registro global (a nivel de proceso) de estrategias disponibles."""

    _factories: Dict[str, Type[BaseSelector]] = {}

    @classmethod
    def register(cls, name: str) -> Callable[[Type[BaseSelector]], Type[BaseSelector]]:
        """Decorador: registra una clase de estrategia bajo un nombre corto."""

        def decorator(selector_cls: Type[BaseSelector]) -> Type[BaseSelector]:
            if name in cls._factories and cls._factories[name] is not selector_cls:
                raise ValueError(
                    f"El nombre de estrategia '{name}' ya está registrado por "
                    f"{cls._factories[name].__name__}; no se puede reasignar a "
                    f"{selector_cls.__name__}."
                )
            cls._factories[name] = selector_cls
            return selector_cls

        return decorator

    @classmethod
    def create(cls, name: str, params: dict | None = None) -> BaseSelector:
        """Construye una instancia nueva de la estrategia `name`.

        Args:
            name: clave de registro (p. ej. "bayesian_fairness").
            params: kwargs para el constructor de la estrategia (p. ej.
                `{"alpha_init": 1.0, "beta_init": 1.0}`). Se pasan tal
                cual, así que deben coincidir con la firma de `__init__`
                de la estrategia concreta.

        Raises:
            UnknownSelectorError: si `name` no fue registrado (typo en
                el YAML de config, o el módulo de la estrategia nunca se
                importó).
        """
        if name not in cls._factories:
            disponibles = ", ".join(sorted(cls._factories)) or "(ninguna registrada todavía)"
            raise UnknownSelectorError(
                f"Estrategia de selección desconocida: '{name}'. "
                f"Disponibles: {disponibles}."
            )
        selector_cls = cls._factories[name]
        constructor_params = params or {}
        try:
            signature(selector_cls).bind(**constructor_params)
        except TypeError as exc:
            raise InvalidSelectorParametersError(
                f"Parámetros inválidos para la estrategia '{name}': {exc}"
            ) from exc
        return selector_cls(**constructor_params)

    @classmethod
    def available(cls) -> List[str]:
        """Nombres de todas las estrategias registradas hasta el momento."""
        return sorted(cls._factories.keys())
