"""Tests de `SelectionService` sobre el repositorio in-memory.

Estos tests son el corazón de la validación de este rediseño: prueban
exactamente el flujo que describía el asesor (cargar estado -> elegir ->
guardar decisión -> actualizar alpha/beta -> registrar evento) de punta a
punta, sin necesitar una base de datos real.
"""

from typing import List, Tuple

import numpy as np
import pytest

import src.strategies  # noqa: F401  (registra las estrategias)
from src.domain.events import DecisionRunCompleted, EventBus
from src.repositories.in_memory.repository_impl import InMemoryDatabase
from src.repositories.in_memory.unit_of_work import InMemoryUnitOfWork
from src.services.selection_service import NoEligibleStudentsError, SelectionService
from src.strategies.registry import UnknownSelectorError


def make_service() -> Tuple[callable, SelectionService]:
    db = InMemoryDatabase()

    def uow_factory() -> InMemoryUnitOfWork:
        return InMemoryUnitOfWork(db)

    return uow_factory, SelectionService(uow_factory)


def enroll_students(
    uow_factory, n: int, alpha_init: float = 1.0, beta_init: float = 1.0
) -> Tuple[int, List[int]]:
    with uow_factory() as uow:
        course = uow.courses.create("Curso de prueba")
        ids = [
            uow.students.get_or_create(course.id, str(i), f"Estudiante {i}", alpha_init, beta_init).id
            for i in range(n)
        ]
        uow.commit()
    return course.id, ids


class TestRunSelection:
    def test_selects_k_students_and_updates_counters(self):
        uow_factory, service = make_service()
        course_id, ids = enroll_students(uow_factory, 10)

        result = service.run_selection(
            course_id=course_id,
            present_student_ids=ids,
            k=3,
            method_name="bayesian_fairness",
            rng=np.random.default_rng(0),
        )

        assert len(result.selected_student_ids) == 3
        assert len(set(result.selected_student_ids)) == 3
        assert set(result.considered_student_ids) == set(ids)

        with uow_factory() as uow:
            candidates = {
                c.student_id: c for c in uow.student_states.get_all_candidates_for_course(course_id)
            }

        for sid in ids:
            c = candidates[sid]
            assert c.n_present == 1
            if sid in result.selected_student_ids:
                assert c.n_selected == 1
                assert c.beta == 2.0  # 1.0 inicial + 1 delta por ser elegido
                assert c.alpha == 1.0
            else:
                assert c.n_selected == 0
                assert c.alpha == 2.0  # 1.0 inicial + 1 delta por seguir en deuda
                assert c.beta == 1.0

    def test_raises_when_no_students_registered(self):
        _, service = make_service()
        with pytest.raises(NoEligibleStudentsError):
            service.run_selection(
                course_id=1, present_student_ids=[999], k=1, method_name="roulette"
            )

    def test_unknown_method_raises(self):
        uow_factory, service = make_service()
        course_id, ids = enroll_students(uow_factory, 5)
        with pytest.raises(UnknownSelectorError):
            service.run_selection(
                course_id=course_id, present_student_ids=ids, k=1, method_name="no_existe"
            )

    def test_event_log_records_before_and_after_state(self):
        uow_factory, service = make_service()
        course_id, ids = enroll_students(uow_factory, 4)

        result = service.run_selection(
            course_id=course_id,
            present_student_ids=ids,
            k=2,
            method_name="bayesian_fairness",
            rng=np.random.default_rng(5),
        )

        with uow_factory() as uow:
            for sid in ids:
                history = uow.events.history_for_student(sid)
                assert len(history) == 1
                event = history[0]
                assert event.decision_run_id == result.decision_run_id
                assert event.alpha_before == 1.0 and event.beta_before == 1.0
                if sid in result.selected_student_ids:
                    assert event.selected is True
                    assert event.beta_after == 2.0
                else:
                    assert event.selected is False
                    assert event.alpha_after == 2.0

    def test_two_sequential_sessions_accumulate_state(self):
        """Cada sesión debe sumar EXACTAMENTE 1 al total alpha+beta de
        cada estudiante considerado -- esto es justo lo que el bug
        corregido en SelectionService garantiza (ver su docstring): antes
        de la corrección, con k>1 un estudiante podía acumular varios
        deltas por una sola clase.
        """
        uow_factory, service = make_service()
        course_id, ids = enroll_students(uow_factory, 6)

        service.run_selection(
            course_id=course_id, present_student_ids=ids, k=2,
            method_name="bayesian_fairness", rng=np.random.default_rng(1),
        )
        service.run_selection(
            course_id=course_id, present_student_ids=ids, k=2,
            method_name="bayesian_fairness", rng=np.random.default_rng(2),
        )

        with uow_factory() as uow:
            candidates = uow.student_states.get_all_candidates_for_course(course_id)

        for c in candidates:
            assert c.n_present == 2
            assert c.alpha + c.beta == pytest.approx(4.0)  # 2.0 inicial + 1 delta x 2 sesiones

    def test_no_student_selected_twice_within_one_session(self):
        """Con k igual al número de presentes, todos deben ser elegidos
        exactamente una vez -- nunca dos veces (el bug que corregimos).
        """
        uow_factory, service = make_service()
        course_id, ids = enroll_students(uow_factory, 5)

        result = service.run_selection(
            course_id=course_id, present_student_ids=ids, k=5,
            method_name="roulette", rng=np.random.default_rng(3),
        )

        assert sorted(result.selected_student_ids) == sorted(ids)

    def test_event_bus_publishes_decision_run_completed(self):
        db = InMemoryDatabase()

        def uow_factory() -> InMemoryUnitOfWork:
            return InMemoryUnitOfWork(db)

        bus = EventBus()
        received: List[DecisionRunCompleted] = []
        bus.subscribe(DecisionRunCompleted, received.append)
        service = SelectionService(uow_factory, event_bus=bus)

        course_id, ids = enroll_students(uow_factory, 5)
        service.run_selection(
            course_id=course_id, present_student_ids=ids, k=2,
            method_name="roulette", rng=np.random.default_rng(9),
        )

        assert len(received) == 1
        assert received[0].method_name == "roulette"
        assert len(received[0].selected_student_ids) == 2
