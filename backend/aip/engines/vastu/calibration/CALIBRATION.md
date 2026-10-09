# Vastu weight calibration

## What is actually trainable

The Vastu engine is a defeasible rule system, and it should stay one. A learned
model that outputs a compliance score cannot cite Mayamata 9.12, and the whole
claim in README.md — that every number traces to a critic, a model and a
citation — dies the moment the score comes out of a network.

Of everything in the engine, exactly one object is fit from data:

| Quantity | Source | Trainable |
|---|---|---|
| rule satisfaction | geometry, computed | no — it is arithmetic |
| `modern_validity` | editorial, from the corpus | **no, deliberately** |
| provenance, rationale, remedy | the treatises | no |
| stance `t` | the client's slider | no |
| **rule weight `w_r`** | currently hand-set | **yes** |

`modern_validity` is frozen by the fit and asserted frozen by a test. If the
optimiser were allowed to move it, the stance slider would stop meaning what the
report says it means, and the traditional/modern reconciliation would become
unciteable.

## The finding, before the protocol

Measured on synthetic panels with the engine's own arithmetic:

* Averaging 29 rules compresses plans into a narrow band. On a representative
  set the **median score gap between two plans is about 0.05** on a 0–1 scale.
* **Uniform weights already reproduce a correctly-weighted ranking on ~80% of
  plan pairs.** The entire ceiling for weight calibration is the remaining 20%.
* Simulated practitioners comparing plans that close together agree with each
  other **~55% of the time**. They cannot reliably resolve the pairs where the
  weights would matter.

Both numbers reproduce with `python -m calibration.power`.

Taken together: calibrating `w` is a real but small effect, bounded above by a
fifth of the ordering and bounded below by what a panel can actually see. It is
worth building the pipeline — you need it to *know* that, and you need it again
whenever the corpus grows — but it should not be the next quarter's work.

Higher-return uses of the same practitioner hours, in order:

1. **Close the 94 of 578 undetermined knowledge-graph placements** named in
   README.md. Coverage beats weighting: an undetermined placement contributes
   nothing, whereas a mis-weighted rule still contributes most of its signal.
2. **Validate satisfaction functions, not weights.** Ask practitioners whether
   the engine is reading a plan correctly on a given rule, not which of two
   plans is better overall. That is a question they answer reliably, and a wrong
   satisfaction function is a much larger error than a wrong weight.
3. **Report Vastu as a profile, not a scalar.** The compression above is the
   reason Vastu moved only −1.8% across arms in the ablation table: a 29-rule
   mean has little dynamic range, so the axis carries little weight in the
   Borda count regardless of `w`. A per-quarter or per-severity breakdown
   discriminates where the mean cannot.

## If you run the panel anyway

**Instrument.** Pairwise, never absolute. "Which of these two is more
Vastu-compliant" is stable; a 0–100 rating carries a large drifting per-rater
offset. `fit_absolute` exists and fits per-rater affine calibration, but it is
the weaker instrument.

**Stance.** Ask every rater at `t = 1.0`, strict classical. The modern head does
not need human labels at all — it is supervised by the analytical critics you
already run, since "kitchen in SE" has a modern validity that is a solar-gain
and cross-ventilation calculation. Never mix stances in one fit.

**Plan set.** Curate for contrast, do not sample representatively. In the sweep,
a contrasted set with 1000 comparisons recovered weights better (ρ≈0.78) than a
representative set with 2000 (ρ≈0.55). You are measuring rule weights, not
estimating a population. `select_panel_plans` picks the spanning subset.

**Comparison set.** `select_pairs` runs greedy D-optimality over the
Bradley-Terry design vectors and drops near-ties. Pair design helps meaningfully
once plans are contrasted, and barely at all before that — plan diversity
dominates. Check `coverage()` before sending anything out: a rule with
negligible leverage will not be identified no matter how many raters you hire.
Fix it by adding plans that vary on that rule, not by buying more judgements.

**Budget.** About 2000 designed comparisons for ρ≈0.8 recovery. Five raters at
400 each, roughly two hours a head at 15–20 seconds per comparison. Overlap at
least 10% of comparisons across raters — `panel_agreement` needs them, and that
agreement figure is your ceiling, not your baseline.

## The ship gate

A fitted weight vector may replace the hand-set corpus only if all five hold:

1. `cross_validate` grouped **by plan** beats the prior on held-out pairs.
   Splitting by pair leaks — the same plan appears on both sides.
2. `check_monotonicity` returns clean.
3. Held-out accuracy is **below** `panel_agreement`. Above it means overfitting,
   not insight; there is no signal up there to have learned.
4. `bootstrap_weights` resamples **plans**, not pairs, and every weight you ship
   as changed has an interval excluding the prior.
5. `adapter.write_back` is used, so unidentified rules keep the editor's value.

Gate 1 is the one that will fail, and failing it is a legitimate result: report
that the panel did not improve on the corpus and keep the hand-set weights.

## Structural guarantees

Two properties hold by construction rather than by trusting the data, and both
are tested:

* **`w ≥ 0` is bounded, so the score is monotone in every rule.** Improving any
  assessable rule can never lower the score, because
  `∂score_i/∂S_ir = a_ir / Σ_r a_ir ≥ 0`. A negative weight would assert that
  satisfying a classical rule makes a plan less compliant, which no citation
  supports.
* **Unassessable rules leave the denominator**, never enter as zero. Same rule
  the corpus already follows.

One pathology is handled explicitly: a rule with no variance across the panel
still has a non-zero gradient — it pulls every plan toward its own fixed
satisfaction, compressing the spread, an effect `beta` absorbs almost exactly.
Its weight is confounded with `beta`, so the fit freezes it at the prior and
reports it in `FitResult.frozen`. Leaving it to the bootstrap does not work; that
was found by a test that failed.

## Wiring it in

`adapter.py` names what it needs from the reasoner rather than calling it, since
`backend/` was not to hand. The contract is two vectors per plan: per-rule
satisfaction, and per-rule assessability, **separately**. If the reasoner
currently returns one number that collapses "scored 0" into "not assessable",
that is the first thing to fix — it is the same false-precision failure the
corpus refuses everywhere else.

```
calibration/
  schema.py    RuleCard, PlanObservation, PairwiseJudgement, CalibrationSet
  model.py     the engine's arithmetic + analytic Jacobian
  fit.py       sign-constrained Bradley-Terry, ridge toward the corpus
  design.py    which plans and which comparisons to buy
  validate.py  grouped CV, monotonicity, bootstrap, panel agreement
  adapter.py   the seam to aip.engines.vastu.reasoner
  power.py     how many comparisons you need
  demo_synthetic.py
  tests/       22 tests
```

Everything in `power.py` and `demo_synthetic.py` is synthetic. It tells you
about the estimator, not about Vastu.
