"""Tests unitarios de `src/metrics/fairness_metrics.py`."""

import numpy as np

from src.metrics.fairness_metrics import coefficient_of_variation, compute_all, coverage, gini, std_dev


class TestGini:
    def test_perfect_equality_is_zero(self):
        counts = np.array([5, 5, 5, 5, 5])
        assert gini(counts) == 0.0

    def test_more_concentration_gives_higher_gini(self):
        equal = np.array([4, 4, 4, 4])
        unequal = np.array([16, 0, 0, 0])
        assert gini(unequal) > gini(equal)

    def test_all_zero_counts_is_zero_by_convention(self):
        assert gini(np.zeros(5)) == 0.0

    def test_empty_array_is_zero(self):
        assert gini(np.array([])) == 0.0


class TestCoefficientOfVariation:
    def test_zero_when_all_equal(self):
        assert coefficient_of_variation(np.array([3, 3, 3])) == 0.0

    def test_positive_when_unequal(self):
        assert coefficient_of_variation(np.array([1, 5, 9])) > 0.0

    def test_zero_mean_is_handled_without_division_error(self):
        assert coefficient_of_variation(np.array([0, 0, 0])) == 0.0


class TestStdDev:
    def test_matches_numpy_std(self):
        counts = np.array([1, 2, 3, 4, 5])
        assert std_dev(counts) == float(np.std(counts))

    def test_empty_array_is_zero(self):
        assert std_dev(np.array([])) == 0.0


class TestCoverage:
    def test_all_selected_at_least_once(self):
        assert coverage(np.array([1, 2, 3])) == 1.0

    def test_none_selected(self):
        assert coverage(np.array([0, 0, 0])) == 0.0

    def test_partial_coverage(self):
        assert coverage(np.array([0, 1, 0, 1])) == 0.5

    def test_empty_array_is_zero(self):
        assert coverage(np.array([])) == 0.0


class TestComputeAll:
    def test_returns_all_four_keys(self):
        result = compute_all(np.array([1, 2, 3, 0]))
        assert set(result.keys()) == {"gini", "cv", "std", "coverage"}
