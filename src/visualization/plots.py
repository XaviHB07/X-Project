"""Gráficos comparativos entre métodos de selección.

Sin cambios de fondo respecto al proyecto original: matplotlib puro (sin
seaborn), un color y una etiqueta fija por método para que todos los
gráficos de un mismo informe sean visualmente consistentes.
"""

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

METHOD_COLORS = {
    "roulette": "#9CA3AF",          # gris: baseline neutro
    "weighted_softmax": "#F59E0B",  # ámbar: intermedio
    "bayesian_fairness": "#2563EB", # azul: el método propuesto
}

METHOD_LABELS = {
    "roulette": "Nivel 1: Ruleta uniforme",
    "weighted_softmax": "Nivel 2: Softmax por historial",
    "bayesian_fairness": "Nivel 3: Bayesian Fairness Bandit",
}


def plot_metric_over_time(df: pd.DataFrame, metric: str, output_path: Path) -> None:
    """Evolución de una métrica (eje Y) a lo largo de las clases (eje X),
    promediando entre trials y mostrando ±1 desviación estándar como
    banda sombreada.
    """
    fig, ax = plt.subplots(figsize=(8, 5))

    for method, group in df.groupby("method"):
        stats = group.groupby("class_idx")[metric].agg(["mean", "std"]).reset_index()
        color = METHOD_COLORS.get(method)
        label = METHOD_LABELS.get(method, method)
        ax.plot(stats["class_idx"], stats["mean"], label=label, color=color, linewidth=2)
        ax.fill_between(
            stats["class_idx"],
            stats["mean"] - stats["std"],
            stats["mean"] + stats["std"],
            color=color,
            alpha=0.15,
        )

    ax.set_xlabel("Número de clase")
    ax.set_ylabel(metric.upper() if metric == "cv" else metric.capitalize())
    ax.set_title(f"Evolución de {metric} por método (media ± 1 std sobre los trials)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_final_boxplot(df: pd.DataFrame, metric: str, n_classes: int, output_path: Path) -> None:
    """Boxplot de la métrica final (última clase) a través de los trials:
    muestra variabilidad entre trials, no solo el promedio.
    """
    last = df[df["class_idx"] == n_classes - 1]
    methods = [m for m in METHOD_LABELS if m in last["method"].unique()]
    data = [last[last["method"] == m][metric].values for m in methods]
    labels = [METHOD_LABELS[m] for m in methods]
    colors = [METHOD_COLORS[m] for m in methods]

    fig, ax = plt.subplots(figsize=(7, 5))
    bplot = ax.boxplot(data, tick_labels=labels, patch_artist=True)
    for patch, color in zip(bplot["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.6)

    ax.set_ylabel(metric.upper() if metric == "cv" else metric.capitalize())
    ax.set_title(f"Distribución de {metric} tras la clase {n_classes} (entre trials)")
    ax.grid(axis="y", alpha=0.3)
    plt.setp(ax.get_xticklabels(), rotation=15, ha="right")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
