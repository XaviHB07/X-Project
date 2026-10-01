"""Prueba de concurrencia: demuestra que `SelectionService`, respaldado
por el bloqueo de `get_candidates_for_update` (ver
`repositories/in_memory/repository_impl.py`), no pierde actualizaciones
cuando muchos "requests" (aquí, threads) compiten por actualizar el
estado de los MISMOS estudiantes al mismo tiempo.

Esta es la prueba en código de la preocupación central del asesor:
"en producción, dos requests pueden querer actualizar el mismo estudiante
casi al mismo tiempo [...] esto evita 'lost updates' donde dos decisiones
se pisan entre sí". El mismo patrón (lectura con bloqueo + actualización
atómica) que aquí se prueba con threads e in-memory es el que
`repositories/sqlalchemy/repository_impl.py` implementa con
`SELECT ... FOR UPDATE` + `UPDATE ... SET x = x + delta` sobre una base de
datos real.
"""

import threading
from typing import List

import numpy as np

import src.strategies  # noqa: F401  (registra las estrategias)
from src.repositories.in_memory.repository_impl import InMemoryDatabase
from src.repositories.in_memory.unit_of_work import InMemoryUnitOfWork
from src.services.selection_service import SelectionService


def test_concurrent_selection_runs_do_not_lose_updates():
    db = InMemoryDatabase()

    def uow_factory() -> InMemoryUnitOfWork:
        return InMemoryUnitOfWork(db)

    service = SelectionService(uow_factory)

    n_students = 10
    with uow_factory() as uow:
        course = uow.courses.create("Curso de concurrencia")
        student_ids = [
            uow.students.get_or_create(course.id, str(i), f"Estudiante {i}", 1.0, 1.0).id
            for i in range(n_students)
        ]
        uow.commit()

    n_threads = 8
    iterations_per_thread = 25
    k = 3
    errors: List[Exception] = []

    def worker(thread_idx: int) -> None:
        rng = np.random.default_rng(1000 + thread_idx)
        for _ in range(iterations_per_thread):
            try:
                service.run_selection(
                    course_id=course.id,
                    present_student_ids=student_ids,
                    k=k,
                    method_name="bayesian_fairness",
                    rng=rng,
                )
            except Exception as exc:  # pragma: no cover - solo para diagnosticar fallas del test
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert not errors, f"Errores durante la ejecución concurrente: {errors}"

    total_runs = n_threads * iterations_per_thread

    with uow_factory() as uow:
        candidates = uow.student_states.get_all_candidates_for_course(course.id)

    total_n_present = sum(c.n_present for c in candidates)
    total_n_selected = sum(c.n_selected for c in candidates)

    # Si alguna actualización se hubiera "perdido" por una carrera entre
    # threads, estas sumas serían MENORES a lo esperado (algún incremento
    # se habría pisado). Con el candado activo, deben cuadrar exactas.
    assert total_n_present == total_runs * n_students
    assert total_n_selected == total_runs * k

    # Cada decision_run debió registrar exactamente n_students eventos
    # (uno por estudiante considerado); si se perdieron eventos por la
    # misma razón, este conteo tampoco cuadraría.
    assert len(db.events) == total_runs * n_students
