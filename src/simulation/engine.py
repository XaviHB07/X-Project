"""Motor de UN trial de simulación: `n_classes` clases sobre `n_students`
estudiantes, para UN método de selección.

Es el reemplazo directo de `src/simulation/classroom.py` en la versión
original. La diferencia de fondo (y el punto central de este rediseño)
es que aquí NO hay un objeto `Student` mutable ni arrays `alpha`/`beta`
en memoria propios de este módulo: todo el estado vive en una
`InMemoryDatabase` (`src/repositories/in_memory/`), y cada "clase" es una
llamada real a `SelectionService.run_selection(...)`, la misma función
que atiende requests HTTP en producción.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

from src.domain.value_objects import Candidate
from src.repositories.in_memory.repository_impl import InMemoryDatabase, InMemoryStudentStateRepository
from src.repositories.in_memory.unit_of_work import InMemoryUnitOfWork
from src.services.selection_service import NoEligibleStudentsError, SelectionService


@dataclass
class ClassSnapshot:
    """Estado de los contadores de selección justo después de una clase.

    Se guarda el vector `selection_counts` completo (no un resumen) por
    la misma razón que en la versión original: las métricas de equidad
    se calculan después, en `src/metrics/fairness_metrics.py`, y así la
    simulación queda desacoplada del cálculo de métricas.
    """

    class_idx: int
    selection_counts: np.ndarray  # shape (n_students,)


def sample_attendance_probs(
    n_students: int, rng: np.random.Generator, min_prob: float, max_prob: float
) -> np.ndarray:
    """Sortea, una vez por trial, la probabilidad de asistencia de cada
    estudiante -- modela que en un curso real no todos asisten con la
    misma regularidad.
    """
    return rng.uniform(min_prob, max_prob, size=n_students)


def run_single_trial(
    method_name: str,
    method_params: Optional[dict],
    n_students: int,
    n_classes: int,
    k_per_class: int,
    attendance_min: float,
    attendance_max: float,
    seed: int,
) -> List[ClassSnapshot]:
    """Ejecuta una simulación completa (n_classes clases) para un método.

    Args:
        method_name: clave de `SelectorRegistry` (debe haberse importado
            `src.strategies` antes de llamar a esto; `scripts/run_experiment.py`
            lo hace indirectamente al importar `src.services.bootstrap`
            o directamente `src.strategies`).
        method_params: hiperparámetros de la estrategia.
        n_students, n_classes, k_per_class: tamaño del experimento.
        attendance_min, attendance_max: rango de probabilidad de
            asistencia individual (ver `sample_attendance_probs`).
        seed: semilla determinista de ESTE trial. El llamador
            (`experiment_runner.run_experiment`) deriva semillas
            distintas por trial a partir de una semilla base, para que
            todo el experimento sea reproducible de punta a punta.

    Returns:
        Lista de `ClassSnapshot`, una por clase.
    """
    rng = np.random.default_rng(seed)

    db = InMemoryDatabase()

    def uow_factory() -> InMemoryUnitOfWork:
        return InMemoryUnitOfWork(db)

    service = SelectionService(uow_factory, event_bus=None)

    # Matricular a los n_students con external_ref = índice, para poder
    # recuperar luego el mismo orden 0..n_students-1 que usaba la
    # simulación original en su vector de conteos.
    student_ids: List[int] = []
    with uow_factory() as uow:
        course = uow.courses.create(name="simulacion")
        course_id = course.id
        for i in range(n_students):
            student = uow.students.get_or_create(
                course_id=course_id,
                external_ref=str(i),
                display_name=f"Estudiante {i}",
                alpha_init=(method_params or {}).get("alpha_init", 1.0),
                beta_init=(method_params or {}).get("beta_init", 1.0),
            )
            student_ids.append(student.id)
        uow.commit()

    index_by_student_id: Dict[int, int] = {sid: i for i, sid in enumerate(student_ids)}
    attendance_probs = sample_attendance_probs(n_students, rng, attendance_min, attendance_max)

    snapshots: List[ClassSnapshot] = []
    for class_idx in range(n_classes):
        present_mask = rng.random(n_students) < attendance_probs
        present_ids = [sid for sid, present in zip(student_ids, present_mask) if present]

        if present_ids:
            try:
                service.run_selection(
                    course_id=course_id,
                    present_student_ids=present_ids,
                    k=k_per_class,
                    method_name=method_name,
                    method_params=method_params,
                    rng=rng,
                )
            except NoEligibleStudentsError:
                # No debería ocurrir (present_ids siempre corresponde a
                # estudiantes matriculados), pero se maneja igual para
                # que un día sin nadie presente nunca tumbe el trial.
                pass

        counts = _current_counts(db, course_id, index_by_student_id, n_students)
        snapshots.append(ClassSnapshot(class_idx, counts))

    return snapshots


def _current_counts(
    db: InMemoryDatabase, course_id: int, index_by_student_id: Dict[int, int], n_students: int
) -> np.ndarray:
    """Lee `n_selected` de todos los estudiantes del curso y los ordena
    según su índice original 0..n_students-1, para producir un vector
    comparable clase a clase (igual forma que la simulación original).
    """
    counts = np.zeros(n_students, dtype=int)
    # Lectura directa del repositorio (sin abrir una Unit of Work): es
    # una consulta de solo lectura fuera de cualquier transacción de
    # escritura, igual que haría un endpoint de métricas en producción.
    candidates: List[Candidate] = InMemoryStudentStateRepository(db).get_all_candidates_for_course(course_id)
    for c in candidates:
        counts[index_by_student_id[c.student_id]] = c.n_selected
    return counts
