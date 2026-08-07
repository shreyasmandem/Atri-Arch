# Architect Intelligence Platform (AIP)

**An explainable multi-agent AI framework for architectural design, interior
planning, Vastu analysis, cost prediction and client-centric design automation.**

Give it a plot and a brief. It returns a buildable scheme — floorplans,
elevations, sections, a furnished interior, an explainable Vastu report, a
costed bill of quantities and a 3D walkthrough — reviewed by a committee of
thirteen independent critics, with every verdict traceable to its evidence.

It runs on a laptop. It needs no GPU, no Docker and no cloud account. Model
spend is **$0.00**, and the test suite asserts that as an invariant.

```bash
cd backend
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"   # Windows
.venv/Scripts/python -m uvicorn aip.api.app:app --port 8000
```

Then open **http://127.0.0.1:8000** for the architect studio, or
**http://127.0.0.1:8000/embed/demo** to see the client-facing widget embedded in
a (fictional) practice's website.

---

## Why this is not another AI design tool

A single model asked to "design a house" optimises one opaque internal
objective. Architecture is irreducibly multi-objective: daylight fights privacy,
Vastu fights structural economy, generous rooms fight the budget. AIP makes that
conflict explicit and resolvable.

**Thirteen critics review every candidate scheme. Ten of them are analytical.**

| | Critic | What it actually does |
|---|---|---|
| ▪ | Building Code Officer | NBC of India 2016 + local DCR, clause by clause. Breaches disqualify outright. |
| ▪ | Daylight Analyst | BRE average daylight factor per room, corrected by real solar geometry for the site's latitude |
| ▪ | Ventilation Analyst | Openable-area ratios, true cross-ventilation detection, air changes per hour against prevailing wind |
| ▪ | Privacy Analyst | Ray-cast sightlines from the entrance, topological depth to bedrooms, WC-onto-living detection |
| ▪ | Circulation Analyst | Reachability, walking distance between functionally-related rooms, circulation overhead |
| ▪ | Accessibility Analyst | Door clear widths, wheelchair turning circles, step-free entry (Harmonised Guidelines 2021) |
| ▪ | Spatial Quality Analyst | Proportion, compactness, largest inscribed square — catches rooms that meet their area and still cannot be furnished |
| ▪ | Structural Reviewer | Span economy, grid regularity, inter-floor load-path continuity |
| ▪ | Vastu Reasoner | 29 formally encoded rules with citations, reconciled against modern building science |
| ▪ | Quantity Surveyor | Takeoff from geometry, priced against a regional schedule, Monte Carlo risk band |
| ○ | Design Coherence Reviewer | *generative* — does it read as one deliberate piece of architecture? |
| ○ | Brief Fidelity Reviewer | *generative* — did it deliver what the client actually asked for? |
| ○ | Livability Reviewer | *generative* — how will this be to live in, day to day, for years? |

The analytical ten cost nothing, run in microseconds, and are exactly
reproducible. They are what stops a language model talking a bad design past the
committee: **the daylight critic is not persuadable, it is arithmetic.**

## Does the committee actually help?

Run the ablation yourself:

```bash
cd backend && .venv/Scripts/python -m aip.evaluation.harness
```

Eight benchmark briefs, three selection procedures, same candidate pool, same
seed — so the difference isolates the *procedure*, not the generator's luck.

| Arm | Composite quality | Compliance | Vastu | **Critical code breaches** |
|---|---|---|---|---|
| Single weighted objective | 0.8397 | 0.8080 | 0.7355 | **11** |
| Committee, no Pareto step | 0.8456 | 0.8421 | 0.7401 | **7** |
| **Full MACC consensus** | **0.8520** | **0.8750** | 0.7220 | **6** |

The headline is the last column: **the committee produces 45% fewer critical
statutory breaches than a single weighted objective.** Compliance rises 8.3%.

Note that Vastu goes *down* 1.8% in the full arm. That is the mechanism working
as designed, not a defect: the consensus trades a little Vastu compliance for a
large gain in code compliance, because a statutory breach is a hard constraint
and a Vastu preference is not. Reporting it is the point — a system that only
showed you its wins would not be one you could trust with the trade-offs.

Explainability scores 1.00 across all arms because every arm uses the same
finding generator; it measures the platform, not the difference between arms.

## The Vastu engine

Most Vastu software is a lookup table that returns a verdict with no reasoning
and no way to disagree. This is a defeasible rule system over a formally encoded
corpus. Every rule carries five things a lookup table does not:

1. **Provenance** — Manasara, Mayamata, Vishvakarma Prakasha, Samarangana
   Sutradhara, Brihat Samhita, or an honest `contemporary` label where no text
   exists. The treatises disagree with each other; naming the source lets you
   weigh a rule instead of obeying it.
2. **Traditional rationale** — what the text says the rule is *for*.
3. **Modern rationale** — the climatic or functional mechanism that does or does
   not support it.
4. **Modern validity** ∈ [0,1] — how much survives that scrutiny.
5. **Remedy** — the concrete change that resolves a violation.

A rule's effective weight is `w × (t + (1−t) × modern_validity)`, where `t` is
the client's stance. At `t=1` the classical corpus governs completely. At `t=0`
only rules with a demonstrable physical basis retain influence — and the report
tells you exactly which rules lost weight and why.

That is the traditional/modern reconciliation, and it is arithmetic you can
audit rather than a claim.

Three further commitments:

- **Unassessable rules are excluded, not guessed.** If the model does not record
  where the water tank is, the water rule is reported as "not assessable" and
  removed from the denominator. Scoring what you cannot evaluate is how these
  systems manufacture false precision.
- **Conflicts are resolved openly.** On a south-facing plot, classical entrance
  placement and basic street access genuinely contradict. The engine detects it,
  resolves it by effective weight, and shows its working.
- **Every violation carries a counterfactual.** *"Kitchen in the north-west
  costs 4.0 points; moving it south-east takes the score from 71 to 75."*

## What it produces

- **Drawings** — floorplans, four elevations, two sections, roof and site plans,
  as SVG. Walls poched, doors with swing arcs, dimensions, north point, scale bar.
- **3D** — glTF/GLB with real window reveals (walls decomposed around openings,
  no CSG dependency), plus OBJ for CAD. WebXR walkthrough waypoints ordered as a
  visitor would experience the house.
- **Interior** — furniture placed geometrically against door swings, clearances
  and orientation rules, with a priced schedule, palette, materials and lighting
  design.
- **Cost** — a real bill of quantities taken off the geometry, a P10/P50/P90
  Monte Carlo band, an S-curve cash flow, a named risk register, and a
  calibration factor that learns *this practice's* deviation from the schedule.

## Zero cost, and why that is structural

Everything that can be solved analytically — geometry, solar position, daylight
factors, airflow, sightlines, quantity takeoff, Vastu rule evaluation — is
solved analytically, not by burning model credits. Language models are used only
where judgement resists formalisation.

When a model *is* needed, `aip/core/providers.py` is a registry of **42 models
across 10 providers**, every one a genuine free tier or local inference. The
router is capability-addressed (`Capability.REASONING`, not a vendor name),
rate-limit aware, circuit-broken and failover-capable.

**With no API key at all, the platform still works.** Every analytical result is
unaffected; only generated commentary degrades, and it is labelled `degraded` in
the API payload and in the UI. See [docs/API_SETUP.md](docs/API_SETUP.md) for
which free accounts to create and why.

## Embedding into a practice's website

One tag:

```html
<script src="https://your-aip-host/embed/aip-widget.js"
        data-key="aip_pk_your_public_key"
        data-practice="Kalpa Studio"
        data-accent="#8a5a2b"
        defer></script>
```

The widget renders inside a shadow root, so a WordPress theme's global CSS
cannot break it and it cannot break the site. Public keys are origin-bound and
cannot read the practice's project list; secret keys never leave the server.

## Repository layout

```
backend/aip/
  core/         config, structured logging, the free-model router, provider registry
  domain/       geometry, the building schema, the client brief
  agents/       critic base classes, the committee, MACC consensus, orchestrator
  engines/
    architecture/  layout synthesis, solar, metrics, NBC codes, drawings, repair
    vastu/         the encoded corpus and the reasoning engine
    cost/          rate schedule, quantity takeoff, Monte Carlo estimator
    interior/      furniture catalogue and the layout solver
    experience/    3D model generation, glTF/OBJ export, walkthrough
  rag/          hybrid BM25 + dense retrieval, corpus, continual learning
  api/          FastAPI app, routers, schemas, auth and tenancy
  db/           multi-tenant SQLAlchemy schema
  evaluation/   the benchmark harness and ablations
frontend/       the architect studio (no build step)
embed/          the embeddable widget and its demo host page
docs/           architecture, research notes, API setup, sample output
```

## Testing

```bash
cd backend && .venv/Scripts/python -m pytest -q
```

123 tests. They run with **no provider configured**, which is deliberate: it
proves the analytical half is genuinely independent of any API, and that is the
whole basis of the zero-cost claim.

## Documentation

- [docs/API_SETUP.md](docs/API_SETUP.md) — the free accounts to create, in priority order
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — how the pieces fit together
- [docs/RESEARCH.md](docs/RESEARCH.md) — novelty claims, method, evaluation, limitations
- `http://127.0.0.1:8000/docs` — interactive OpenAPI reference

## Status and honest limitations

This is a working research platform, not a shipped commercial product. What is
real and what is not:

**Real:** the generator, all ten analytical critics, the consensus procedure,
the Vastu engine and its corpus, quantity takeoff and pricing, the interior
solver, drawing and 3D generation, the API, tenancy, the learning loop, and the
evaluation harness. All tested.

**Indicative, needs a practice's own data:** the rate schedule is benchmarked to
CPWD conventions and market levels but is not a tendered schedule. Load your own
via `RateSchedule.from_file`.

**Not yet built:** photorealistic rendering (prompts are generated; no image
provider is wired in by default), structural sizing beyond span sanity checks,
MEP layout, and iOS AR (GLB covers WebXR and Android; iOS Quick Look needs a
USDZ conversion requiring Apple's toolchain).

**Not measurable without a human study:** user satisfaction, expert-rated design
quality, and retrieval relevance. The harness reports these as
`not_measured_without_human_study` rather than inventing a proxy number.

## Licence

Apache-2.0.
