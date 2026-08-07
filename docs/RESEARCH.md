# Research notes

Companion to the project abstract. States what is claimed, how it is
implemented, what the evaluation shows, and — at some length — what it does not
show.

---

## 1. The gap

Existing AI architectural tools address isolated tasks: floorplan generation,
interior visualisation, or cost estimation. Three properties are consistently
missing.

**Collaborative reasoning.** A single model produces a single opaque judgement.
Architecture is multi-objective by nature, and a scalar objective cannot
represent "this scheme has better daylight but worse privacy" — it can only
average them, which destroys exactly the information a designer needs.

**Explainability.** Generative tools produce plausible images. Neither an
approving authority nor a client can interrogate a picture. "Why this scheme?"
has no answer.

**Continuous learning.** Nothing accumulates. A practice's hundredth project
benefits no more from the tool than its first.

To which this work adds a fourth, economic, gap: existing tools are priced per
seat or per generation, which puts them out of reach of the small practices that
would benefit most.

---

## 2. Contributions

### 2.1 Multi-Agent Critic Consensus (MACC)

The central methodological contribution. Given candidate designs `D` and critics
`C`, each owning one axis:

1. **Admissibility filter.** Any candidate carrying a `CRITICAL` finding — a
   statutory breach or physical impossibility — is disqualified outright. No
   aesthetic merit buys a way past a building code. If every candidate is
   inadmissible the filter relaxes and the result is flagged, because returning
   nothing helps nobody.

2. **Pareto filtering.** Candidate *i* dominates *i′* when it is at least as
   good on every axis and strictly better on one. What survives is the genuine
   trade-off frontier. This is the step a weighted sum destroys, because
   summation lets a strong axis conceal a fatally weak one.

3. **Reliability-weighted Borda count.** Each critic ranks the frontier; points
   are weighted by `reliability × confidence × client priority`. Borda is
   deliberately ordinal, making it robust to critics that are well-ordered but
   badly calibrated in absolute terms — which describes most LLM critics.

4. **Cardinal utility.** A weighted mean using the client's stated priorities.
   Ordinal and cardinal views are blended (λ = 0.42), so neither a miscalibrated
   scale nor a knife-edge ranking dominates alone.

5. **Agreement analysis.** Weighted dispersion per axis yields an agreement
   index. Low agreement is *surfaced*, not averaged away, and triggers a debate
   round in which generative critics see each other's reasoning and may revise.
   Analytical critics do not debate: a measurement does not change because
   another agent disagrees with it.

Implementation: `aip/agents/consensus.py`.

### 2.2 The analytical/generative split

Ten of thirteen critics compute their verdict from geometry, building physics or
codified rules. They are exact, instantaneous, free, and fully reproducible.
Three call a language model for judgement that resists formalisation.

This is the platform's defence against the failure mode the abstract identifies.
An LLM critic cannot talk a design past the daylight critic, because the
daylight critic is not persuadable — it is the BRE average daylight factor
formula evaluated over the actual glazing schedule. Conversely, analytical
critics cannot tell whether a scheme reads as coherent architecture.

The economic consequence is that quality does not scale with spend: the majority
of the committee costs nothing to run.

### 2.3 Explainable Vastu reasoning with traditional/modern reconciliation

To our knowledge no prior system encodes Vastu as a defeasible rule base with
per-rule provenance and an explicit modern-validity weighting.

29 rules across 11 categories, drawn from Manasara, Mayamata, Vishvakarma
Prakasha, Samarangana Sutradhara and Brihat Samhita, plus rules honestly labelled
`regional` or `contemporary` where no textual source exists (21 of 29 are
textual). Each carries a traditional rationale, a modern rationale, a
modern-validity score in [0,1], a remedy, and defeater relations.

Effective weight: `w_eff = w × (t + (1−t) × modern_validity)`.

This single expression is the reconciliation. It lets one rule base serve an
orthodox client and a sceptical one by reweighting rather than by switching
tables, and the report enumerates which rules lost weight and why.

Three design commitments distinguish it from a lookup table:

- **Unassessable rules are excluded from the denominator, not guessed.** Scoring
  a rule you cannot evaluate manufactures false precision.
- **Conflicts are detected and resolved openly**, with both winner and loser
  reported — the archetypal case being a south-facing road, where classical
  entrance placement and street access cannot both be satisfied.
- **Every violation carries a counterfactual** quantifying what fixing it is
  worth in score points, and whether it has any functional benefit.

Implementation: `aip/engines/vastu/`.

### 2.4 Constraint-guided generative synthesis

Floorplans are generated as **slicing trees** — the classical VLSI floorplanning
formulation — rather than as pixels. This guarantees by construction that rooms
tile the envelope with no gaps or overlaps, that every wall is straight, closed
and dimensioned, and that the result can be priced and built.

The tree is optimised by a **surrogate-assisted evolutionary search**: a cheap
geometric proxy (area fidelity, proportion, external-wall access, adjacency,
orientation) drives the population, and the expensive exact evaluation — full
physics and code suite — re-ranks only the elite survivors. This is the standard
remedy for expensive-evaluation search, and here it is the difference between
~25 s and ~1.5 s per scheme, which is what makes the system usable interactively
inside a website rather than only as a batch job.

Diversity is enforced by greedy fitness/similarity trade-off selection: a
committee reviewing three near-identical schemes learns nothing.

Implementation: `aip/engines/architecture/layout.py`.

### 2.5 Continual learning

Three learned components, all per-practice:

- **Critic reliability**, updated by a Brier-style EMA when human per-axis
  ratings arrive. A critic that consistently mispredicts loses influence.
- **Corpus weights**, raised for passages that informed accepted designs.
- **Cost calibration**, an EMA over predicted/actual ratios from completed
  projects, clamped to [0.55, 1.85] so one unusual project cannot distort it.

This is the compounding asset: a practice's own delivered work becomes the corpus
that grounds its next proposal, which no general-purpose model can replicate
because it never sees that data.

---

## 3. Evaluation

### 3.1 Design

Eight benchmark briefs spanning the cases an Indian practice actually receives,
chosen for coverage of failure modes rather than flattering results: a narrow
6.5 m urban plot, a south-facing road creating a genuine Vastu/access conflict,
a deliberately under-funded budget, a two-storey villa, and a multi-generational
programme with a wheelchair accessibility requirement.

Three arms share the same candidate pool and the same random seed, so
differences isolate the **selection procedure**, not the generator's luck:

- `single_critic` — one weighted-sum objective (the conventional design)
- `no_pareto` — full committee, ranked by weighted sum only
- `full` — admissibility + Pareto + reliability-weighted Borda

Generative critics are excluded so results are reproducible and independent of
which free tier happened to be reachable.

Reproduce: `python -m aip.evaluation.harness`

### 3.2 Results

| Arm | Composite | Compliance | Vastu | Explainability | **Critical breaches** | s/brief |
|---|---|---|---|---|---|---|
| `single_critic` | 0.8397 | 0.8080 | 0.7355 | 1.000 | **11** | 1.62 |
| `no_pareto` | 0.8456 | 0.8421 | 0.7401 | 1.000 | **7** | 1.64 |
| `full` | **0.8520** | **0.8750** | 0.7220 | 1.000 | **6** | 1.64 |

Total model spend: **$0.00**.

### 3.3 Reading the results honestly

**The finding that matters is the last column.** Critical statutory breaches fall
from 11 to 6 — a 45% reduction — with compliance up 8.3%. The admissibility
filter and Pareto step are doing real work: they systematically reject schemes
that a scalar objective accepts because a high daylight score offsets a setback
violation. In practice that is the difference between a scheme that can be
submitted for sanction and one that cannot.

**Composite quality gains only 1.5%,** and that is the honest picture. Most of
the value is concentrated in eliminating catastrophic outcomes rather than in
raising the average. A multi-objective procedure is insurance, not uplift.

**Vastu drops 1.8% in the full arm.** This is the mechanism working as designed,
not a regression: the consensus trades a small amount of Vastu compliance for a
large gain in code compliance, because a statutory breach is a hard constraint
and a Vastu preference is not. A system that reported only its wins would not be
one you could trust with the trade-offs it exists to make.

**Explainability is 1.000 across all arms and is therefore not evidence for
MACC.** Every arm uses the same finding generator, so it measures the platform's
explainability, not a difference between procedures. It is reported because the
abstract commits to the metric, with the operational definition: *a finding is
explained when it names what is wrong, cites the authority for that judgement,
and states the fix.*

**Latency is effectively identical across arms** (1.62 vs 1.64 s), so the
consensus machinery is not the cost centre — generation is. The committee is
close to free.

### 3.4 What this evaluation cannot tell you

Reported as `not_measured_without_human_study` in the harness output rather than
proxied:

- **User satisfaction.** Requires a study with practising architects and their
  clients. Any synthetic stand-in would be indistinguishable from an invented
  result.
- **Expert-rated design quality.** Requires blind rating by qualified architects
  against schemes produced by human designers for the same briefs. This is the
  single most important missing experiment: the analytical critics measure
  whether a building performs, not whether it is *good*.
- **Recommendation relevance.** Requires ground-truth relevance judgements. The
  30-passage shipped corpus is far too small for a meaningful retrieval
  benchmark.
- **Cost accuracy against delivered cost.** Measured here against the client's
  *budget*, which is a constraint, not ground truth. Real accuracy requires
  completed projects, which is exactly what the `/actuals` endpoint accumulates.

Further threats to validity worth stating plainly:

- **n = 8 briefs.** Enough to demonstrate the mechanism, not enough for
  statistical significance. No confidence intervals are reported because they
  would not be meaningful at this sample size.
- **The benchmark is self-authored.** The briefs were written by the same author
  as the system. An independent benchmark would be stronger evidence.
- **Compliance is measured by the same code engine that the generator optimises
  against.** This is not circular for the *ablation* — all arms share that
  engine, so it cannot explain the difference between them — but the absolute
  compliance numbers should not be read as third-party validation.
- **The Vastu modern-validity scores are the author's judgement.** They are
  argued in prose in `aip/engines/vastu/knowledge.py` and are open to
  disagreement; the architecture is designed so that disagreeing means editing a
  number, not rewriting the engine.

---

## 4. Reproducibility

```bash
cd backend
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"
.venv/Scripts/python -m pytest -q                       # 123 tests
.venv/Scripts/python -m aip.evaluation.harness          # writes docs/evaluation.json
```

All results are seeded. The suite runs with no provider configured, which is
itself the evidence for the zero-cost claim: if the analytical half depended on
an API, these tests could not pass.

---

## 5. Where this goes next

In rough order of research value:

1. **Blind expert evaluation** against human-designed schemes for the same
   briefs. Everything else is secondary to this.
2. **Cost accuracy against delivered projects**, which the calibration loop is
   already built to collect.
3. **A larger, independently-authored benchmark**, ideally drawn from real
   practice enquiries rather than authored cases.
4. **Learned critic weighting evaluated longitudinally** — does reliability
   calibration measurably improve selection over a practice's project history?
5. **Diffusion-based facade and interior synthesis** conditioned on the solved
   geometry, keeping the constraint solver as the source of truth.
6. **Extension to real-estate intelligence**, per the abstract's future work.
