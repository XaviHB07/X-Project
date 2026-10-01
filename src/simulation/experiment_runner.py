"""Orquestador del experimento completo: corre varios métodos de
selección a lo largo de N trials Monte Carlo y consolida los resultados
en un `pandas.DataFrame`.

Nota sobre un bug corregido
----------------------------
La versión entregada de `src/simulation/runner.py` importaba y usaba
`pyspark.sql.SparkSession` para esto -- una dependencia pesada (requiere
una JVM instalada) que ni el `README.md` ni el `requirements.txt`
originales mencionaban, y que no aporta nada aquí: con los valores por
defecto del config (100 trials x 14 clases x 3 métodos = 4,200 filas) el
resultado cabe cómodamente en memoria con pandas puro, tal como el
propio README original explicaba en su sección de librerías usadas. Se
interpreta como un error accidental (código de otro experimento pegado
por error) y se corrige aquí usando pandas, consistente con el resto del
proyecto. Ver el README de este entregable, sección "Bugs encontrados y
corregidos", para más detalle.
"""

from __future__ import annotations

from typing import Dict, List

import pandas as pd

from src.metrics.fairness_metrics import compute_all
from src.simulation.engine import run_single_trial


def run_experiment(
    method_configs: Dict[str, dict],
    n_students: int,
    n_classes: int,
    k_per_class: int,
    n_trials: int,
    attendance_min: float,
    attendance_max: float,
    base_seed: int,
) -> pd.DataFrame:
    """Corre `n_trials` simulaciones independientes para cada método.

    Args:
        method_configs: dict {nombre_metodo: hiperparametros}, p. ej.
            `{"roulette": {}, "weighted_softmax": {"tau": 0.5},
              "bayesian_fairness": {"alpha_init": 1.0, "beta_init": 1.0}}`.
            Las claves deben existir en `SelectorRegistry` (ver
            `src/strategies/registry.py`); typos se detectan al vuelo con
            un `UnknownSelectorError` claro.
        base_seed: semilla base del experimento completo. Cada trial usa
            `base_seed + trial_idx` como su propia semilla: (a) el
            experimento entero es reproducible con un solo número, y
            (b) cada trial es independiente y distinto de los demás.

    Returns:
        DataFrame con columnas: method, trial, class_idx, gini, cv, std,
        coverage. Una fila por (método, trial, clase).
    """
    records: List[dict] = []

    for method_name, params in method_configs.items():
        for trial_idx in range(n_trials):
            trial_seed = base_seed + trial_idx
            snapshots = run_single_trial(
                method_name=method_name,
                method_params=params,
                n_students=n_students,
                n_classes=n_classes,
                k_per_class=k_per_class,
                attendance_min=attendance_min,
                attendance_max=attendance_max,
                seed=trial_seed,
            )
            for snap in snapshots:
                metrics = compute_all(snap.selection_counts)
                records.append(
                    {
                        "method": method_name,
                        "trial": trial_idx,
                        "class_idx": snap.class_idx,
                        **metrics,
                    }
                )

    return pd.DataFrame.from_records(records)


def summarize_final_class(df: pd.DataFrame, n_classes: int) -> pd.DataFrame:
    """Extrae solo la última clase de cada trial y agrega promedio ± std
    por método -- el resumen "de una línea por método" que normalmente se
    reporta en la sección de resultados de un informe.
    """
    last = df[df["class_idx"] == n_classes - 1]
    agg = last.groupby("method").agg(
        gini_mean=("gini", "mean"), gini_std=("gini", "std"),
        cv_mean=("cv", "mean"), cv_std=("cv", "std"),
        std_mean=("std", "mean"), std_std=("std", "std"),
        coverage_mean=("coverage", "mean"), coverage_std=("coverage", "std"),
    )
    return agg.reset_index()
