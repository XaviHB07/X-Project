"""Tests unitarios de las estrategias de selección (patrón Strategy) y
del registro dinámico (`SelectorRegistry`).

Se prueban en aislamiento total: ningún test de este archivo toca una
base de datos ni una `UnitOfWork` -- solo `Candidate` (un value object
plano) y `numpy.random.Generator`, tal como pide el contrato de
`BaseSelector`.
"""

import numpy as np
import pytest

from src.domain.value_objects import Candidate
from src.strategies.bayesian_fairness import BayesianFairnessBandit
from src.strategies.registry import SelectorRegistry, UnknownSelectorError
from src.strategies.roulette import RouletteSelector
from src.strategies.weighted_softmax import WeightedSoftmaxSelector


def make_candidates(n: int, alpha=1.0, beta=1.0, n_selected=0) -> list[Candidate]:
    return [
        Candidate(student_id=i, alpha=alpha, beta=beta, n_present=0, n_selected=n_selected)
        for i in range(n)
    ]


class TestRouletteSelector:
    def test_selects_k_distinct_ids(self):
        selector = RouletteSelector()
        candidates = make_candidates(10)
        rng = np.random.default_rng(42)

        selected = selector.select(candidates, k=4, rng=rng)

        assert len(selected) == 4
        assert len(set(selected)) == 4  # sin duplicados
        assert set(selected).issubset({c.student_id for c in candidates})

    def test_k_larger_than_pool_selects_everyone(self):
        selector = RouletteSelector()
        candidates = make_candidates(3)
        rng = np.random.default_rng(1)

        selected = selector.select(candidates, k=10, rng=rng)

        assert sorted(selected) == [0, 1, 2]

    def test_k_zero_selects_nothing(self):
        selector = RouletteSelector()
        candidates = make_candidates(5)
        assert selector.select(candidates, k=0, rng=np.random.default_rng(0)) == []

    def test_has_no_posterior_state(self):
        selector = RouletteSelector()
        candidates = make_candidates(3)
        updates = selector.compute_posterior_updates(candidates, selected_ids=[0])
        assert updates == []


class TestWeightedSoftmaxSelector:
    def test_rejects_non_positive_tau(self):
        with pytest.raises(ValueError):
            WeightedSoftmaxSelector(tau=0.0)
        with pytest.raises(ValueError):
            WeightedSoftmaxSelector(tau=-1.0)

    def test_favors_students_with_less_history(self):
        """Con tau pequeño, el estudiante con n_selected=0 debería ganar
        casi siempre frente a uno con historial alto.
        """
        selector = WeightedSoftmaxSelector(tau=0.05)
        rested = Candidate(student_id=1, alpha=1, beta=1, n_present=5, n_selected=0)
        overused = Candidate(student_id=2, alpha=1, beta=1, n_present=5, n_selected=50)
        candidates = [rested, overused]

        wins_rested = 0
        for seed in range(200):
            rng = np.random.default_rng(seed)
            picked = selector.select(candidates, k=1, rng=rng)
            if picked == [1]:
                wins_rested += 1

        assert wins_rested > 190  # prácticamente siempre elige al de menos historial

    def test_no_duplicates_in_batch_selection(self):
        selector = WeightedSoftmaxSelector(tau=0.5)
        candidates = make_candidates(8, n_selected=3)
        rng = np.random.default_rng(7)

        selected = selector.select(candidates, k=5, rng=rng)

        assert len(selected) == 5
        assert len(set(selected)) == 5


class TestBayesianFairnessBandit:
    def test_selects_k_distinct_ids(self):
        selector = BayesianFairnessBandit()
        candidates = make_candidates(12)
        rng = np.random.default_rng(3)

        selected = selector.select(candidates, k=5, rng=rng)

        assert len(selected) == 5
        assert len(set(selected)) == 5

    def test_prefers_higher_alpha_relative_to_beta(self):
        """Un estudiante con mucha evidencia de 'necesitar oportunidad'
        (alpha alto, beta bajo) debería ganar casi siempre frente a uno
        cuya necesidad ya fue mayormente atendida (alpha bajo, beta alto).
        """
        selector = BayesianFairnessBandit()
        needs_turn = Candidate(student_id=1, alpha=20.0, beta=1.0, n_present=20, n_selected=0)
        already_served = Candidate(student_id=2, alpha=1.0, beta=20.0, n_present=20, n_selected=19)
        candidates = [needs_turn, already_served]

        wins_needs_turn = 0
        for seed in range(200):
            rng = np.random.default_rng(seed)
            picked = selector.select(candidates, k=1, rng=rng)
            if picked == [1]:
                wins_needs_turn += 1

        assert wins_needs_turn > 190

    def test_posterior_updates_alpha_for_non_selected_beta_for_selected(self):
        selector = BayesianFairnessBandit()
        candidates = make_candidates(4, alpha=2.0, beta=3.0)

        updates = {u.student_id: u for u in selector.compute_posterior_updates(candidates, selected_ids=[0, 2])}

        assert updates[0].delta_alpha == 0.0 and updates[0].delta_beta == 1.0
        assert updates[2].delta_alpha == 0.0 and updates[2].delta_beta == 1.0
        assert updates[1].delta_alpha == 1.0 and updates[1].delta_beta == 0.0
        assert updates[3].delta_alpha == 1.0 and updates[3].delta_beta == 0.0

    def test_posterior_updates_cover_every_considered_candidate_exactly_once(self):
        """Cada candidato considerado recibe EXACTAMENTE un delta (alpha+1
        o beta+1), nunca más de uno -- esto es lo que el bug corregido en
        `SelectionService` garantiza ahora (ver su docstring).
        """
        selector = BayesianFairnessBandit()
        candidates = make_candidates(6)

        updates = selector.compute_posterior_updates(candidates, selected_ids=[1, 4])

        assert len(updates) == len(candidates)
        assert {u.student_id for u in updates} == {c.student_id for c in candidates}
        for u in updates:
            total_delta = u.delta_alpha + u.delta_beta
            assert total_delta == 1.0


class TestSelectorRegistry:
    def test_default_strategies_are_registered(self):
        # Basta con haber importado src.strategies (hecho arriba, vía los
        # imports directos de las clases) para que el registro esté
        # poblado.
        available = SelectorRegistry.available()
        assert {"roulette", "weighted_softmax", "bayesian_fairness"}.issubset(set(available))

    def test_create_known_strategy(self):
        selector = SelectorRegistry.create("weighted_softmax", {"tau": 0.3})
        assert isinstance(selector, WeightedSoftmaxSelector)
        assert selector.tau == 0.3

    def test_create_unknown_strategy_raises(self):
        with pytest.raises(UnknownSelectorError):
            SelectorRegistry.create("no_existe", {})
