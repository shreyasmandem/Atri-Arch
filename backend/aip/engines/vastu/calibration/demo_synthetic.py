"""END-TO-END RUN ON SYNTHETIC DATA.

This does NOT produce Vastu weights you may ship. There is no practitioner in
it. It invents a ground-truth weight vector, simulates a noisy panel that judges
according to it, and checks the pipeline recovers what it planted.

What it verifies: the gradients are right, the optimiser converges, grouped CV
beats the prior, monotonicity holds, and the bootstrap flags exactly the rules
the simulated panel never exercised.

What it cannot verify: anything about Vastu. Run this to trust the machinery,
then replace `simulate_panel` with real judgements.
"""

from __future__ import annotations

import numpy as np
from scipy.special import expit
from scipy.stats import spearmanr

import os
import sys

try:
    from .design import coverage, select_pairs
    from .fit import fit_pairwise
    from .model import score
    from .schema import CalibrationSet, PairwiseJudgement, PlanObservation, RuleCard
    from .validate import (
        bootstrap_weights, check_monotonicity, cross_validate, identifiable,
        panel_agreement, select_panel_plans,
    )
except ImportError:
    _HERE = os.path.dirname(os.path.abspath(__file__))
    _BACKEND_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
    if _BACKEND_ROOT not in sys.path:
        sys.path.insert(0, _BACKEND_ROOT)
    from aip.engines.vastu.calibration.design import coverage, select_pairs
    from aip.engines.vastu.calibration.fit import fit_pairwise
    from aip.engines.vastu.calibration.model import score
    from aip.engines.vastu.calibration.schema import CalibrationSet, PairwiseJudgement, PlanObservation, RuleCard
    from aip.engines.vastu.calibration.validate import (
        bootstrap_weights, check_monotonicity, cross_validate, identifiable,
        panel_agreement, select_panel_plans,
    )

N_RULES, N_PLANS, N_RATERS = 29, 60, 5
N_PAIRS = 2000  # see power.py for why this number and not 450


def synthetic_corpus(rng) -> tuple[RuleCard, ...]:
    return tuple(
        RuleCard(
            rule_id=f"rule_{i:02d}",
            provenance="mayamata" if i % 3 else "contemporary",
            modern_validity=float(rng.uniform(0.1, 1.0)),
            prior_weight=1.0,
        )
        for i in range(N_RULES)
    )


def synthetic_plans(cards, rng, dead_rules=(27, 28)) -> CalibrationSet:
    """`dead_rules` are assessable but constant -- the bootstrap must flag them."""
    cs = CalibrationSet(cards=cards)
    ids = tuple(c.rule_id for c in cards)
    for p in range(N_PLANS):
        sat = rng.beta(2.5, 1.6, size=N_RULES)
        msk = rng.random(N_RULES) > 0.18          # ~18% not assessable
        msk[0] = True                              # keep at least one
        for d in dead_rules:
            sat[d], msk[d] = 0.8, True             # no variance to learn from
        cs.add_plan(PlanObservation(f"plan_{p:02d}", ids, sat, msk))
    return cs


def simulate_panel(cs, true_w, rng, pairs, stance=1.0, beta=9.0):
    """Raters compare the given pairs under Bradley-Terry, with per-rater noise."""
    S, M, ids = cs.matrices()
    idx = {p: i for i, p in enumerate(ids)}
    truth = score(true_w, S, M, cs.modern_validity, stance)

    for i, (a, b) in enumerate(pairs):
        sharp = beta * rng.uniform(0.6, 1.4)       # some raters are noisier
        d = truth[idx[a]] - truth[idx[b]]
        winner = a if rng.random() < expit(sharp * d) else b
        cs.pairs.append(
            PairwiseJudgement(a, b, winner, f"rater_{i % N_RATERS}",
                              stance=stance, confidence=1.0)
        )
    return cs


def main() -> None:
    rng = np.random.default_rng(7)
    cards = synthetic_corpus(rng)
    true_w = rng.gamma(2.0, 0.5, size=N_RULES)
    true_w /= true_w.mean()

    cs = synthetic_plans(cards, rng)
    S, M, plan_ids = cs.matrices()

    print("SYNTHETIC RUN -- NOT A VASTU RESULT\n" + "=" * 62)
    print(f"{N_RULES} rules  {N_PLANS} plans  {N_RATERS} raters")
    chosen = select_panel_plans(S, M, plan_ids, n=24)
    print(f"panel selection: {len(chosen)} of {N_PLANS} plans span the rule space")

    base = select_pairs(cs, 900, min_separation=0.0, seed=7)
    pairs = [base[i % len(base)] for i in range(N_PAIRS)]
    simulate_panel(cs, true_w, rng, pairs)
    print(f"judgements: {len(cs.pairs)} designed comparisons")

    low = [r for r, v in coverage(cs, pairs).items() if v < 0.05]
    print(f"rules with negligible leverage from this design: {len(low)}")

    agree = panel_agreement(cs)
    print(f"panel self-agreement: {agree['agreement']:.3f} "
          f"over {int(agree['comparisons'])} repeated comparisons  <- ceiling")

    res = fit_pairwise(cs, stance=1.0, ridge=0.5)
    print(f"\nfit: converged={res.converged}  beta={res.beta:.2f}  "
          f"train acc={res.train_accuracy:.3f}")

    rho = spearmanr(true_w, res.weights).statistic
    err = float(np.mean(np.abs(res.weights - true_w)))
    print(f"weight recovery: spearman={rho:.3f}  mean abs err={err:.3f}")

    cv = cross_validate(cs, folds=5, ridge=0.5)
    print(f"\ngrouped CV ({cv.folds} folds): fitted={cv.accuracy_fitted:.3f}  "
          f"prior={cv.accuracy_prior:.3f}  gain={cv.improvement:+.3f}")

    print(f"frozen (no variance in panel set): {list(res.frozen)}")

    fails = check_monotonicity(res.weights, cs)
    print(f"monotonicity: {'clean' if not fails else str(len(fails)) + ' FAILURES'}")

    iv = bootstrap_weights(cs, draws=60, ridge=0.5)
    prior = dict(zip(cs.rule_ids, cs.prior_weights))
    ident = identifiable(iv, prior)
    n_id = sum(ident.values())
    print(f"identifiable weights: {n_id}/{N_RULES}")
    dead = [r for r in ("rule_27", "rule_28") if not ident[r]]
    print(f"constant rules correctly withheld by bootstrap: {dead}")

    print("\nlargest moves from the prior")
    for rid, p, w in res.moved(cs.prior_weights)[:6]:
        lo, _m, hi = iv[rid]
        flag = "" if ident[rid] else "   (not identified -- keep prior)"
        print(f"  {rid}  {p:.2f} -> {w:.2f}  [{lo:.2f},{hi:.2f}]{flag}")


if __name__ == "__main__":
    main()
