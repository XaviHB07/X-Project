"""Métricas de equidad sobre un vector de conteos de selección.

Todas las funciones reciben `counts`: un array donde `counts[i]` es
cuántas veces el estudiante i ha sido seleccionado hasta el momento. Se
implementan a mano (no se usa una librería externa como `scikit-bio` o
similares) porque cada fórmula son pocas líneas de numpy y así el
proyecto no arrastra una dependencia pesada por una fórmula trivial.
"""

import numpy as np


def gini(counts: np.ndarray) -> float:
    """Índice de Gini de la distribución de selecciones.

    0 = perfectamente equitativo (todos seleccionados el mismo número de
    veces). Cercano a 1 = muy concentrado (pocos estudiantes acaparan casi
    toda la participación).

    Se usa la fórmula basada en la diferencia media absoluta normalizada,
    equivalente al área entre la curva de Lorenz y la diagonal de
    igualdad perfecta:

        Gini = sum_i sum_j |x_i - x_j| / (2 * n * sum(x))
    """
    x = np.asarray(counts, dtype=float)
    n = len(x)
    if n == 0 or x.sum() == 0:
        # Sin selecciones todavía (p. ej. un curso recién creado) no hay
        # desigualdad que medir; se define como 0 por convención.
        return 0.0

    x_sorted = np.sort(x)
    # Fórmula equivalente y O(n log n) (por el sort), en vez de la doble
    # suma O(n^2): index (1-based) ponderando cada valor ordenado.
    index = np.arange(1, n + 1)
    return float((2 * np.sum(index * x_sorted) - (n + 1) * np.sum(x_sorted)) / (n * np.sum(x_sorted)))


def coefficient_of_variation(counts: np.ndarray) -> float:
    """CV = desviación estándar / media. Menor = más equilibrado.

    A diferencia de Gini, el CV no está acotado en [0,1], pero es fácil
    de interpretar en términos relativos (p. ej. "la desviación equivale
    al 40% de la media").
    """
    x = np.asarray(counts, dtype=float)
    mean = x.mean() if len(x) else 0.0
    if mean == 0:
        return 0.0
    return float(x.std() / mean)


def std_dev(counts: np.ndarray) -> float:
    """Desviación estándar simple de las selecciones. Menor = más equilibrado."""
    return float(np.asarray(counts, dtype=float).std()) if len(counts) else 0.0


def coverage(counts: np.ndarray) -> float:
    """Fracción de estudiantes que han sido seleccionados al menos una vez.

    Es la métrica más intuitiva para explicarle a un profesor: "¿qué
    porcentaje del curso ya tuvo su oportunidad?".
    """
    x = np.asarray(counts)
    if len(x) == 0:
        return 0.0
    return float(np.mean(x > 0))


def compute_all(counts: np.ndarray) -> dict:
    """Calcula las cuatro métricas de una sola vez, para no repetir código
    cada vez que se necesita un resumen completo.
    """
    return {
        "gini": gini(counts),
        "cv": coefficient_of_variation(counts),
        "std": std_dev(counts),
        "coverage": coverage(counts),
    }
