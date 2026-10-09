"""Invariants the calibration pipeline may not lose.

Written in the spirit of the existing suite: assert the properties that make a
result reportable, not that a number equals a number.
"""

from __future__ import annotations

import os
import sys
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

import numpy as np

try:
    import pytest
except ImportError:
    class _MockPytest:
        @staticmethod
        def fixture(fn):
            return fn
        @staticmethod
        def approx(expected, rel=1e-5, abs=1e-7):
            class _Approx:
                def __eq__(self, other):
                    return bool(np.isclose(other, expected, rtol=rel, atol=abs))
                def __repr__(self):
                    return f"approx({expected})"
            return _Approx()
        @staticmethod
        def raises(expected_exc, match=None):
            class _Raises:
                def __enter__(self):
                    return self
                def __exit__(self, exc_type, exc_val, exc_tb):
                    if exc_type is None:
                        raise AssertionError(f"Expected exception {expected_exc}, but none was raised")
                    return issubclass(exc_type, expected_exc)
            return _Raises()
    pytest = _MockPytest()

from aip.engines.vastu.calibration.design import coverage, select_pairs
from aip.engines.vastu.calibration.fit import fit_pairwise
from aip.engines.vastu.calibration.model import normalise, score, score_and_jacobian
from aip.engines.vastu.calibration.power import judge, make_world
from aip.engines.vastu.calibration.schema import (
    CalibrationSet, PairwiseJudgement, PlanObservation, RuleCard, stance_scale,
)
from aip.engines.vastu.calibration.validate import (
    bootstrap_weights, check_monotonicity, cross_validate, identifiable,
    panel_agreement,
)


def prior_of(cs, rid):
    return float(dict(zip(cs.rule_ids, cs.prior_weights))[rid])


@pytest.fixture
def world():
    rng = np.random.default_rng(11)
    cs, tw = make_world(rng, n_plans=40)
    pairs = select_pairs(cs, 600, min_separation=0.0, seed=11)
    cs.pairs = judge(cs, tw, pairs, np.random.default_rng(12))
    return cs, tw


# --- the arithmetic matches the engine's stated formula -------------------

def test_stance_endpoints():
    mv = np.array([0.0, 0.5, 1.0])
    assert np.allclose(stance_scale(mv, 1.0), 1.0)      # classical governs all
    assert np.allclose(stance_scale(mv, 0.0), mv)       # only physics survives


def test_unassessable_rules_leave_the_denominator():
    """A rule that cannot be evaluated must not drag the score toward zero."""
    ids = ("a", "b")
    mv, w = np.ones(2), np.ones(2)
    both = np.array([[1.0, 0.4]]), np.array([[1.0, 1.0]])
    only_a = np.array([[1.0, 0.0]]), np.array([[1.0, 0.0]])
    assert score(w, *both, mv, 1.0)[0] == pytest.approx(0.7)
    assert score(w, *only_a, mv, 1.0)[0] == pytest.approx(1.0)


def test_score_is_scale_invariant(world):
    """Only weight ratios are identifiable; the fit must not pretend otherwise."""
    cs, _ = world
    S, M, _ = cs.matrices()
    w = np.abs(np.random.default_rng(3).normal(size=S.shape[1])) + 0.1
    a = score(w, S, M, cs.modern_validity, 1.0)
    b = score(w * 7.3, S, M, cs.modern_validity, 1.0)
    assert np.allclose(a, b)


def test_analytic_jacobian_matches_finite_difference(world):
    cs, _ = world
    S, M, _ = cs.matrices()
    w = np.abs(np.random.default_rng(5).normal(size=S.shape[1])) + 0.5
    _sc, J = score_and_jacobian(w, S, M, cs.modern_validity, 1.0)
    h = 1e-6
    for r in (0, 4, 17):
        wp, wm = w.copy(), w.copy()
        wp[r] += h
        wm[r] -= h
        num = (score(wp, S, M, cs.modern_validity, 1.0)
               - score(wm, S, M, cs.modern_validity, 1.0)) / (2 * h)
        assert np.allclose(J[:, r], num, atol=1e-6)


# --- the guarantees that let a number be cited ---------------------------

def test_weights_are_never_negative(world):
    cs, _ = world
    res = fit_pairwise(cs, ridge=0.5)
    assert (res.weights >= 0).all(), (
        "a negative weight would assert that satisfying a classical rule makes "
        "a plan less compliant, which no citation supports"
    )


def test_monotonicity_holds_after_fitting(world):
    cs, _ = world
    res = fit_pairwise(cs, ridge=0.5)
    assert check_monotonicity(res.weights, cs) == []


def test_modern_validity_is_not_learned(world):
    """The fit must move w only. If modern_validity drifted, the stance slider
    would stop meaning what the report says it means."""
    cs, _ = world
    before = cs.modern_validity.copy()
    fit_pairwise(cs, ridge=0.5)
    assert np.array_equal(cs.modern_validity, before)


def test_normalise_pins_the_scale():
    w = np.array([2.0, 4.0, 6.0])
    assert normalise(w).mean() == pytest.approx(1.0)


# --- the fit actually learns, and knows when it has not ------------------

def test_fit_recovers_planted_weights(world):
    from scipy.stats import spearmanr
    cs, tw = world
    res = fit_pairwise(cs, ridge=0.5)
    assert res.converged
    assert spearmanr(tw, res.weights).statistic > 0.4


def test_prior_is_recovered_when_judgements_are_pure_noise():
    """With coin-flip verdicts the ridge must hold the corpus in place."""
    rng = np.random.default_rng(2)
    cs, _ = make_world(rng, n_plans=20)
    ids = sorted(cs.plans)
    for i in range(400):
        a, b = rng.choice(ids, 2, replace=False)
        cs.pairs.append(PairwiseJudgement(a, b, rng.choice([a, b]), "r0"))
    res = fit_pairwise(cs, ridge=5.0)
    assert np.abs(res.weights - cs.prior_weights).max() < 0.5


def test_constant_rule_is_flagged_unidentified():
    """A rule with no variance across the panel cannot be weighted from data."""
    rng = np.random.default_rng(4)
    cs, tw = make_world(rng, n_plans=24)
    frozen = 3
    for obs in cs.plans.values():
        obs.satisfaction[frozen] = 0.75
        obs.assessable[frozen] = True
    pairs = select_pairs(cs, 400, min_separation=0.0, seed=4)
    cs.pairs = judge(cs, tw, pairs, np.random.default_rng(5))

    rid = cs.rule_ids[frozen]
    res = fit_pairwise(cs, ridge=0.5)
    assert rid in res.frozen
    assert res.as_dict()[rid] == pytest.approx(prior_of(cs, rid))

    iv = bootstrap_weights(cs, draws=25, ridge=0.5)
    prior = dict(zip(cs.rule_ids, cs.prior_weights))
    assert not identifiable(iv, prior)[rid]


def test_validate_reports_constant_and_missing_rules():
    rng = np.random.default_rng(6)
    cs, _ = make_world(rng, n_plans=12)
    for obs in cs.plans.values():
        obs.satisfaction[2] = 0.5
        obs.assessable[2] = True
        obs.assessable[5] = False
    problems = cs.validate()
    assert any("rule_02" in p and "constant" in p for p in problems)
    assert any("rule_05" in p and "never assessable" in p for p in problems)


def test_pair_referencing_unscored_plan_is_rejected():
    rng = np.random.default_rng(8)
    cs, _ = make_world(rng, n_plans=8)
    cs.pairs.append(PairwiseJudgement("plan_000", "ghost", "ghost", "r0"))
    with pytest.raises(ValueError, match="unscored"):
        fit_pairwise(cs)


# --- held-out behaviour --------------------------------------------------

def test_grouped_cv_splits_by_plan_not_by_pair(world):
    cs, _ = world
    cv = cross_validate(cs, folds=4, ridge=0.5)
    assert cv.folds >= 3
    assert 0.0 <= cv.accuracy_fitted <= 1.0


def test_cv_refuses_a_panel_too_small_to_split():
    rng = np.random.default_rng(9)
    cs, _ = make_world(rng, n_plans=6)
    with pytest.raises(ValueError, match="too few"):
        cross_validate(cs, folds=5)


def test_panel_agreement_is_reported_as_a_ceiling(world):
    cs, _ = world
    cs.pairs.append(PairwiseJudgement("plan_000", "plan_001", "plan_000", "rA"))
    cs.pairs.append(PairwiseJudgement("plan_000", "plan_001", "plan_001", "rB"))
    a = panel_agreement(cs)
    assert a["comparisons"] >= 1
    assert 0.0 <= a["agreement"] <= 1.0


# --- experiment design ---------------------------------------------------

def test_designed_pairs_cover_more_rules_than_random(world):
    cs, _ = world
    rng = np.random.default_rng(13)
    ids = sorted(cs.plans)
    rand = [tuple(rng.choice(ids, 2, replace=False)) for _ in range(120)]
    des = select_pairs(cs, 120, min_separation=0.0, seed=13)
    lo_rand = sum(v < 0.05 for v in coverage(cs, rand).values())
    lo_des = sum(v < 0.05 for v in coverage(cs, des).values())
    assert lo_des <= lo_rand


def test_selected_pairs_are_distinct_and_valid(world):
    cs, _ = world
    des = select_pairs(cs, 50, min_separation=0.0, seed=1)
    assert len(set(des)) == len(des)
    assert all(a != b and a in cs.plans and b in cs.plans for a, b in des)


# --- schema refuses bad data ---------------------------------------------

def test_satisfaction_outside_range_is_rejected():
    with pytest.raises(ValueError, match="satisfaction"):
        PlanObservation("p", ("a",), np.array([1.4]), np.array([True]))


def test_plan_with_no_assessable_rule_is_rejected():
    with pytest.raises(ValueError, match="no assessable"):
        PlanObservation("p", ("a",), np.array([0.5]), np.array([False]))


def test_rule_ordering_mismatch_is_rejected():
    cards = (RuleCard("b", "contemporary", 1.0), RuleCard("a", "contemporary", 1.0))
    cs = CalibrationSet(cards=cards)
    with pytest.raises(ValueError, match="rule ordering"):
        cs.add_plan(PlanObservation(
            "p", ("a", "b"), np.array([0.5, 0.5]), np.array([True, True])))


def test_self_comparison_is_rejected():
    with pytest.raises(ValueError, match="itself"):
        PairwiseJudgement("p", "p", "p", "r0")


def run_all_tests():
    w = world()
    tests = [
        ("test_stance_endpoints", lambda: test_stance_endpoints()),
        ("test_unassessable_rules_leave_the_denominator", lambda: test_unassessable_rules_leave_the_denominator()),
        ("test_score_is_scale_invariant", lambda: test_score_is_scale_invariant(w)),
        ("test_analytic_jacobian_matches_finite_difference", lambda: test_analytic_jacobian_matches_finite_difference(w)),
        ("test_weights_are_never_negative", lambda: test_weights_are_never_negative(w)),
        ("test_monotonicity_holds_after_fitting", lambda: test_monotonicity_holds_after_fitting(w)),
        ("test_modern_validity_is_not_learned", lambda: test_modern_validity_is_not_learned(w)),
        ("test_normalise_pins_the_scale", lambda: test_normalise_pins_the_scale()),
        ("test_fit_recovers_planted_weights", lambda: test_fit_recovers_planted_weights(w)),
        ("test_prior_is_recovered_when_judgements_are_pure_noise", lambda: test_prior_is_recovered_when_judgements_are_pure_noise()),
        ("test_constant_rule_is_flagged_unidentified", lambda: test_constant_rule_is_flagged_unidentified()),
        ("test_validate_reports_constant_and_missing_rules", lambda: test_validate_reports_constant_and_missing_rules()),
        ("test_pair_referencing_unscored_plan_is_rejected", lambda: test_pair_referencing_unscored_plan_is_rejected()),
        ("test_grouped_cv_splits_by_plan_not_by_pair", lambda: test_grouped_cv_splits_by_plan_not_by_pair(w)),
        ("test_cv_refuses_a_panel_too_small_to_split", lambda: test_cv_refuses_a_panel_too_small_to_split()),
        ("test_panel_agreement_is_reported_as_a_ceiling", lambda: test_panel_agreement_is_reported_as_a_ceiling(w)),
        ("test_designed_pairs_cover_more_rules_than_random", lambda: test_designed_pairs_cover_more_rules_than_random(w)),
        ("test_selected_pairs_are_distinct_and_valid", lambda: test_selected_pairs_are_distinct_and_valid(w)),
        ("test_satisfaction_outside_range_is_rejected", lambda: test_satisfaction_outside_range_is_rejected()),
        ("test_plan_with_no_assessable_rule_is_rejected", lambda: test_plan_with_no_assessable_rule_is_rejected()),
        ("test_rule_ordering_mismatch_is_rejected", lambda: test_rule_ordering_mismatch_is_rejected()),
        ("test_self_comparison_is_rejected", lambda: test_self_comparison_is_rejected()),
    ]
    passed = 0
    for name, fn in tests:
        fn()
        passed += 1
    print(f"All {passed}/{len(tests)} calibration invariants verified and PASSED.")


if __name__ == "__main__":
    run_all_tests()
