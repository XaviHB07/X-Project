#!/usr/bin/env python3
"""Punto de entrada del experimento Monte Carlo (modo investigación): carga
la configuración, corre las simulaciones para los métodos configurados,
guarda el CSV de resultados y genera los gráficos comparativos.

Este script es el sucesor directo del `scripts/run_experiment.py`
original. Sigue sirviendo para lo mismo (comparar los tres niveles de
sofisticación bajo las mismas condiciones), pero ahora corre sobre el
mismo `SelectionService` y las mismas estrategias que la API de
producción (ver `src/simulation/engine.py`), y sin la dependencia
accidental de PySpark que tenía la versión entregada originalmente (ver
el README de este entregable, sección "Bugs encontrados y corregidos").

Uso:
    python scripts/run_experiment.py
    python scripts/run_experiment.py --config config/default.yaml
    python scripts/run_experiment.py --n-trials 500 --n-classes 30
"""

import argparse
import sys
from pathlib import Path

import yaml

# Permite ejecutar el script directamente sin instalar el paquete ni
# setear PYTHONPATH manualmente.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.strategies  # noqa: E402  (efecto secundario: registra las estrategias)
from src.simulation.experiment_runner import run_experiment, summarize_final_class  # noqa: E402
from src.strategies.registry import SelectorRegistry  # noqa: E402
from src.visualization.plots import plot_final_boxplot, plot_metric_over_time  # noqa: E402


def load_config(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_method_configs(cfg: dict) -> dict:
    """Traduce la sección `methods` + `experiment.method_to_compare` del
    YAML en el dict `{nombre: hiperparametros}` que espera
    `run_experiment`. A diferencia de la versión original
    (`build_selectors`, que instanciaba las clases a mano), aquí solo se
    validan los nombres contra `SelectorRegistry` -- ni este script ni
    `run_experiment` necesitan importar las clases concretas de cada
    estrategia.
    """
    methods_cfg = cfg["methods"]
    names = cfg["experiment"].get("method_to_compare", list(methods_cfg.keys()))

    unknown = [n for n in names if n not in SelectorRegistry.available()]
    if unknown:
        raise SystemExit(
            f"Métodos desconocidos en config: {unknown}. "
            f"Disponibles: {SelectorRegistry.available()}"
        )
    return {name: methods_cfg.get(name, {}) for name in names}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=Path("config/default.yaml"),
        help="Ruta al archivo de configuración YAML.",
    )
    parser.add_argument("--n-trials", type=int, default=None)
    parser.add_argument("--n-classes", type=int, default=None)
    parser.add_argument("--n-students", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_config(args.config)

    exp_cfg = cfg["experiment"]
    if args.n_trials is not None:
        exp_cfg["n_trials"] = args.n_trials
    if args.n_classes is not None:
        exp_cfg["n_classes"] = args.n_classes
    if args.n_students is not None:
        exp_cfg["n_students"] = args.n_students
    if args.seed is not None:
        exp_cfg["seed"] = args.seed

    output_dir = Path(cfg["output"]["dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[1/4] Configuración cargada desde {args.config}")
    print(
        f"      n_students={exp_cfg['n_students']}  n_classes={exp_cfg['n_classes']}  "
        f"k_per_class={exp_cfg['k_per_class']}  n_trials={exp_cfg['n_trials']}"
    )

    method_configs = build_method_configs(cfg)
    print(f"      Métodos a comparar: {list(method_configs.keys())}")

    print("[2/4] Ejecutando simulaciones Monte Carlo...")
    df = run_experiment(
        method_configs=method_configs,
        n_students=exp_cfg["n_students"],
        n_classes=exp_cfg["n_classes"],
        k_per_class=exp_cfg["k_per_class"],
        n_trials=exp_cfg["n_trials"],
        attendance_min=cfg["attendance"]["min_prob"],
        attendance_max=cfg["attendance"]["max_prob"],
        base_seed=exp_cfg["seed"],
    )

    if cfg["output"]["save_csv"]:
        csv_path = output_dir / "resultados_completos.csv"
        df.to_csv(csv_path, index=False)
        print(f"[3/4] CSV con resultados detallados guardado en {csv_path}")

        summary = summarize_final_class(df, exp_cfg["n_classes"])
        summary_path = output_dir / "resumen_metricas_finales.csv"
        summary.to_csv(summary_path, index=False)
        print(f"      Resumen de métricas finales guardado en {summary_path}")
        print("\nResumen (media ± std tras la última clase):\n")
        print(summary.to_string(index=False))

    if cfg["output"]["save_plots"]:
        print("\n[4/4] Generando gráficos comparativos...")
        for metric in ["gini", "cv", "coverage", "std"]:
            plot_metric_over_time(df, metric, output_dir / f"evolucion_{metric}.png")
            plot_final_boxplot(df, metric, exp_cfg["n_classes"], output_dir / f"boxplot_final_{metric}.png")
        print(f"      Gráficos guardados en {output_dir}/")

    print("\nExperimento completo. ✅")


if __name__ == "__main__":
    main()
