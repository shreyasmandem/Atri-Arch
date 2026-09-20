"""How many practitioner comparisons do you need to buy?

Answered by simulation: plant a known weight vector, simulate a panel that
judges according to it with realistic noise, and measure how well the fit
recovers it as the number of comparisons grows -- under random pair sampling
against designed pair sampling.

Run this before recruiting anyone. It converts "we need practitioner labels"
into a number of comparisons and an hours estimate.

Synthetic throughout. It tells you about the estimator, not about Vastu.
"""

from __future__ import annotations

import numpy as np
from scipy.special import expit
from scipy.stats import spearmanr

from .design import select_pairs
from .fit import fit_pairwise
from .model import score
from .schema import CalibrationSet, PairwiseJudgement, PlanObservation, RuleCard

N_RULES = 29


def make_world(rng, n_plans: int, contrast: float = 1.0):
    """`contrast` controls how deliberately varied the panel plans are.

    1.0 is a representative sample of what the generator emits. Above 1.0 the
    set is curated toward plans that disagree with each other, which is what a
    panel set should be -- you are measuring rule weights, not sampling the
    population.
    """
    cards = tuple(
        RuleCard(f"rule_{i:02d}", "mayamata" if i % 3 else "contemporary",
                 float(rng.uniform(0.1, 1.0)), 1.0)
        for i in range(N_RULES)
    )
    cs = CalibrationSet(cards=cards)
    ids = tuple(c.rule_id for c in cards)
    a = max(0.4, 2.5 / contrast)
    b = max(0.4, 1.6 / contrast)
    for p in range(n_plans):
        sat = rng.beta(a, b, size=N_RULES)
        msk = rng.random(N_RULES) > 0.18
        msk[0] = True
        cs.add_plan(PlanObservation(f"plan_{p:03d}", ids, sat, msk))
    w = rng.gamma(2.0, 0.5, size=N_RULES)
    return cs, w / w.mean()


def judge(cs, true_w, pairs, rng, beta=9.0, stance=1.0):
    """Turn a list of (a,b) into simulated practitioner verdicts."""
    S, M, ids = cs.matrices()
    idx = {p: i for i, p in enumerate(ids)}
    truth = score(true_w, S, M, cs.modern_validity, stance)
    out = []
    for i, (a, b) in enumerate(pairs):
        sharp = beta * rng.uniform(0.6, 1.4)
        d = truth[idx[a]] - truth[idx[b]]
        winner = a if rng.random() < expit(sharp * d) else b
        out.append(PairwiseJudgement(a, b, winner, f"rater_{i % 5}", stance))
    return out


def run(n_plans=60, budgets=(250, 500, 1000, 2000, 4000), seeds=(1, 2, 3),
        contrast=1.0):
    print(f"\npanel plans = {n_plans}   contrast = {contrast}")
    print(f"{'pairs':>7}  {'random':>16}  {'designed':>16}")
    print(f"{'':>7}  {'rho':>7}{'acc':>9}  {'rho':>7}{'acc':>9}")
    rows = []
    for n in budgets:
        agg = {"random": [], "designed": []}
        for s in seeds:
            rng = np.random.default_rng(s)
            cs, tw = make_world(rng, n_plans, contrast)
            S, M, ids = cs.matrices()

            rand_pairs = [
                tuple(rng.choice(ids, 2, replace=False)) for _ in range(n)
            ]
            k = min(n, n_plans * (n_plans - 1) // 2)
            base = select_pairs(cs, k, min_separation=0.0, seed=s)
            des_pairs = [base[i % len(base)] for i in range(n)]

            for name, pairs in (("random", rand_pairs), ("designed", des_pairs)):
                fit_cs = CalibrationSet(cards=cs.cards)
                for pid in cs.plans:
                    fit_cs.add_plan(cs.plans[pid])
                fit_cs.pairs = judge(cs, tw, pairs, np.random.default_rng(s + 99))
                res = fit_pairwise(fit_cs, ridge=0.5)
                rho = float(spearmanr(tw, res.weights).statistic)
                agg[name].append((rho, res.train_accuracy))

        r = np.mean(agg["random"], axis=0)
        d = np.mean(agg["designed"], axis=0)
        rows.append((n, r[0], r[1], d[0], d[1]))
        print(f"{n:>7}  {r[0]:>7.3f}{r[1]:>9.3f}  {d[0]:>7.3f}{d[1]:>9.3f}")
    return rows


if __name__ == "__main__":
    print("SYNTHETIC POWER ANALYSIS -- estimator behaviour, not Vastu findings")
    print("=" * 66)
    print("rho = rank correlation between recovered and planted weights")
    run(n_plans=60, contrast=1.0)
    run(n_plans=60, contrast=2.5)
