# Atri Arch: an AI architecture studio

**Type one sentence about your plot. A team of AI agents designs the house, checks
it against building code, daylight, airflow, structure, Vastu and cost, and hands
you a full drawing set in about a minute.**

> "30x40 plot, road on the north, G+1, 3 bedrooms, car parking and a pooja room"

→ three competing schemes → a validity gate → a 13-critic committee → a Pareto +
Borda vote → repair agents → plans, elevations, sections, DXF, a 3D model,
airflow, a Vastu reading, a Monte Carlo cost estimate and furnished interiors.

| | |
|---|---|
| **Live** | https://atri-arch.vercel.app (the API is pinged every 5 minutes, so it is awake when you open it) |
| **Demo video (2:17)** | https://x.com/mandemshreyas/status/2109655589924266239 |
| **Built for** | [#neatHack](https://neatlogs.com/hackathon), Oct 10-12 2026, solo |

---

## How neatlogs, Entire and cfo.ai were used

### neatlogs: every agent run traced, and the incidents it caught

Every design run is traced through the neatlogs SDK
([`backend/aip/core/telemetry.py`](backend/aip/core/telemetry.py)) as one span tree:

```
atriarch.design_pipeline            WORKFLOW
├─ interpret                         CHAIN
├─ rag.retrieve_for_brief            RETRIEVER   (NBC 2016 + Vastu corpus)
├─ generate                          CHAIN       (3 planners)
└─ critique                          CHAIN
   ├─ critic.compliance ... critic.cost        AGENT x 10  (analytical tools)
   └─ critic.coherence / brief / livability    AGENT x 3   (LLM critics)
      └─ <provider>/<model>                     LLM         (every call, every failover)
```

1,100+ traces were recorded over the weekend. Two real incidents came out of them:

| | What neatlogs showed | Fix |
|---|---|---|
| **Incident 01** | Failed LLM spans on almost every run. Opening them: `http 404 model_not_found` for `qwen/qwen3.6-27b` and `groq/compound`. Groq had withdrawn both ids, and every critic in the parallel fan-out rediscovered the same 404, on every run. | Withdrawn ids replaced with the live `qwen/qwen3.8-27b`, and a retired model is now retired once for the whole process instead of once per critic. [commit `bfae4c0`](https://entire.io/gh/shreyasmandem/neathack-AtriArch/commit/bfae4c0edf19a5abf5393d2b60ed76c0345393ba) |
| **Incident 02** | `rate limited (retry-after 1.0s / 2.0s)` spans on `openai/gpt-oss-120b` and `gemini-2.5-pro` when 13 critics fan out at once. | A 429 now means "later, not broken": the router fails over to the next model immediately instead of sleeping, and never opens the circuit breaker for a rate limit. |

**Result, from neatlogs' own weekly digest:** the share of requests with recorded
errors fell from **85.3% to 40.0%**. Most of what remains are free-tier 429s that the
router recovers from by failing over; when every free model is busy, an LLM critic is
marked `degraded` in the API and UI rather than failing the run.

### Entire: memory for the coding agent

Atri Arch was built with Claude Code inside Entire, so every commit carries a
checkpoint with the session, the prompts and the reasoning behind the change.

- **Checkpoints, one per commit:** [entire.io/.../commits](https://entire.io/gh/shreyasmandem/neathack-AtriArch/commits) · [analytics (75+ checkpoints)](https://entire.io/gh/shreyasmandem/neathack-AtriArch/analytics)
- **Key decisions you can open and read the reasoning for:**
  - [`acbfde7`](https://entire.io/gh/shreyasmandem/neathack-AtriArch/commit/acbfde7eb7b1236551807e86ab51e03fae2c9c11): a scheme that fails the validity check can never win the vote while a clean one exists
  - [`d653f3d`](https://entire.io/gh/shreyasmandem/neathack-AtriArch/commit/d653f3d82de0979f3d511469d509c55fe156150d): the corridor planner, valid by construction for plots the searching planners could not hold
  - [`bfae4c0`](https://entire.io/gh/shreyasmandem/neathack-AtriArch/commit/bfae4c0edf19a5abf5393d2b60ed76c0345393ba): the neatlogs incident fix above
- **entire-graph:** while fixing Incident 01, `entire graph search --query "retire a withdrawn model id"` pointed straight at `DeadModels` in `core/llm.py`, its covering test and the provider probe script, out of 3,391 symbols and 8,334 relations.
- **Entire Brain:** the invariant "a scheme that fails the validity guardrail never wins the vote" is recorded as a Brain fact, so later sessions don't undo it.
- **Agent guide checked into the repo:** [`.entire/agent-guide.md`](.entire/agent-guide.md), referenced from `CLAUDE.md` and `AGENTS.md`.

### cfo.ai: the business plan, and the decision it changed

cfo.ai's AI CFO built a 12-month forecast from the pricing: **₹1,999** for a scheme,
**₹7,999** for a full design set with edits. Base case: about **₹81 lakh** in year one
at an **84% margin**, with upside and downside scenarios.

The useful part was what it caught. Only about 8% of free users pay, so every buyer
funds around 12 free designs: the real AI cost per buyer is about **₹560, not ₹40**.
That changed the product. Every design and import is now metered against a per-firm
quota ([`check_design_quota`](backend/aip/api/security.py)), and the studio falls back
to its measured, non-LLM reviews whenever a model is slow or rate-limited.
Forecast and notes: [`docs/cfo-ai/`](docs/cfo-ai/).

---

## Where the agents and the LLMs are

Atri Arch is a team of agents, not one prompt. Language models do the parts that
need judgement; physics and code checks are tools the agents use, so no model can
talk a bad plan past the committee.

| Agent | Uses an LLM for |
|---|---|
| **Brief agent** | The conversation. Reads a brief in English, Hindi or Hinglish, asks only what is missing, and starts when the client says go. |
| **3 LLM critics** | Design coherence, brief fidelity and livability: the judgements that resist a formula. |
| **Revision agent** | "Make the kitchen bigger, add a balcony off the master": reads a change in any language and applies it. |
| **Exterior designer** | Composes facades in a facade grammar for what the client said. |
| **Plan reader** | Reads a photo or scan of an existing plan with a vision model. |
| **Design rationale** | Writes the client-facing explanation of what was chosen and what it traded away. |
| **10 analytical critics** | No LLM. Code, daylight, ventilation, privacy, circulation, accessibility, space, structure, Vastu and cost are measured, because a daylight factor should be arithmetic, not an opinion. |

The models are free-tier (Groq, Gemini, OpenRouter and others) behind a
capability-addressed router with failover, rate-limit handling and a circuit breaker.
That is why the incidents above mattered: the router is the agent's nervous system.

## What was built during neatHack

The analytical core (geometry, the measured critics, the Vastu corpus and the cost
engine) started before the hackathon as a research project; the Phase 1 report is in
[`docs/`](docs/). neatHack is where it became an agent you can talk to and a product
people can use. Everything below was built Oct 10-12, and every commit is
checkpointed in Entire:

- The conversational **brief agent** (any language) and the **revision agent**
- The **exterior designer agent** with seven facade languages and palettes, day and night
- Four planners (**parti, spine, row-house, corridor**), a pre-search **feasibility gate** and the **validity guardrail**
- The live **atelier**: the committee drafting on stage while the plans are made
- Elevations and sections drawn live from the 3D model, interior walkthroughs
- **Exact editing** after design: widen, deepen, swap, rename, retype, ceiling, undo
- Plan import from **photos and SVGs**, not only DXF
- **neatlogs tracing**, the incident fixes above, and the **cfo.ai** business model
- Free deployment (Vercel + Render), a phone layout, and server-restart recovery

## Run it locally

```bash
cd backend
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"   # Windows
.venv/Scripts/python -m uvicorn aip.api.app:app --port 8000
```

Open **http://127.0.0.1:8000** for the studio, or
**http://127.0.0.1:8000/embed/demo** for the client-facing widget on a (fictional)
practice's website. It runs on a laptop with no GPU and no Docker. Add free API keys
for the LLM agents ([docs/API_SETUP.md](docs/API_SETUP.md)); without them the
analytical half still works and LLM output is labelled `degraded`. Deployment notes:
[`DEPLOY.md`](DEPLOY.md).

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

## The agents negotiate, they do not just vote

Selecting the best of three schemes cannot fix a flaw all three share. So after
the committee votes, a **manager–worker consensus protocol** takes the winner and
negotiates it against seven constraints — three hard, four soft — each owned by
the agent responsible for repairing it.

```
opening state   score 0.6632   2 constraint(s) open
   OPEN [hard] code.no_critical: 1 critical statutory breach(es)
   OPEN [hard] daylight.statutory: 1 room(s) below the statutory glazing ratio
round 1       0.6632 -> 0.8276   hard 2 -> 0
   [ACCEPT] floorplan_architect: apply 5 targeted geometric repair(s) (+0.0784)
   [ACCEPT] floorplan_architect: re-pack the envelope to give Master Bedroom
                                 its statutory width (+0.0861)
round 2       0.8276 -> 0.8700   hard 0 -> 0
   [ACCEPT] vastu_compliance: swap two room assignments (+0.0424)
outcome         satisfied   final 0.8700   hard open 0   1.2s
```

A proposal is accepted **only when re-measuring the whole design shows a net
gain**, and hard constraints are weighted three times a soft one. Those two rules
together mean the design can never end a round worse than it began, and no
accumulation of comfort gains can outrank fixing a statutory breach. Both are
asserted by tests.

When a brief genuinely cannot be built, the loop says so — and the agent that
owns the failing constraint has to explain why it cannot help:

```
   [no change] cost_estimator: already specified at the lowest finish tier, so no
   further step-down exists. The overrun is driven by the size of the programme,
   not by the specification, and cannot be closed without the client either
   raising the budget or dropping accommodation.
outcome         converged   hard open 0
   STILL OPEN [soft] cost.within_budget: 310% of budget
```

An agent that owns a failing constraint and stays silent is indistinguishable
from an agent that never ran.

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

### The knowledge graph — reasoning past the corpus

An authored corpus can only judge a placement some text troubled to write down.
Every other room falls through as "not assessable", which is honest but useless.
So alongside the rules there is a **knowledge graph**: 98 nodes and 255 edges over
12 relation types, linking compass sectors to mandala quarters, quarters to
elements and presiding deities, elements to the qualities they afford, and rooms
to the activities they host.

Compliance is computed by **best-first path search**, not retrieval. Every verdict
returns the chain that produced it:

```
Gym          -> NW  Gym -[hosts]-> Physical exertion -[demands]-> Airy -[affords]-> North-west
Home Theatre -> S   Home Theatre -[hosts]-> Screen viewing -[demands]-> Dark -[affords]-> South
Home Office  -> NE  Home Office -[hosts]-> Study -[demands]-> Light -[affords]-> North-east
```

No rule in the corpus mentions a gym, a home theatre or a home office. The graph
reaches all three by reasoning through what happens inside the room.

| | |
|---|---|
| Placements a cited text addresses | 112 |
| Placements the graph can derive | 578 |
| **Coverage gain** | **5.16×** |
| Agreement with the corpus where it does speak | **112 / 113 (99.1%)** |
| Mean query time | 0.38 ms |

Perfect agreement would be a warning sign — it would mean the graph was only
reading the assertions back. The one disagreement is *shown to the user*: the
cited text governs the score, and the conflict is printed beside it.

Two decisions worth naming, because both correct errors a purely elemental
treatment makes confidently:

- **Ritual pollution is modelled explicitly.** A WC in the north-east looks
  harmonious on elemental grounds — ablution embodies water, Ishanya carries
  water — yet every text prohibits it. The objection is *shaucha*, purity. Without
  that edge the graph reaches the opposite of the doctrine by impeccable logic.
- **No evidence is not a neutral verdict.** A placement with no supporting *or*
  contradicting path is reported `undetermined` and excluded from the score,
  rather than being called "neutral" as though it had been weighed.

## What it produces

- **Drawings** — floorplans, four elevations, two sections, roof and site plans,
  as SVG. Walls poched, doors with swing arcs, dimensions, north point, scale bar.
- **CAD** — AutoCAD R12 **DXF** per level: walls poched as closed polylines at
  true thickness, doors as leaf-and-swing symbols, glazing, the structural grid,
  dimension strings and a room schedule, on the layer names an Indian practice
  already uses. The test suite reads the file back with an independent CAD
  library and asserts every wall's length and thickness survived — validating our
  own writer with our own parser would prove nothing.
- **3D** — glTF/GLB with real window reveals (walls decomposed around openings,
  no CSG dependency), plus OBJ for CAD. WebXR walkthrough waypoints ordered as a
  visitor would experience the house.
- **Interior** — furniture placed geometrically against door swings, clearances
  and orientation rules, with a priced schedule, palette, materials and lighting
  design.
- **Cost** — a real bill of quantities taken off the geometry, a P10/P50/P90
  Monte Carlo band, an S-curve cash flow, a named risk register, and a
  calibration factor that learns *this practice's* deviation from the schedule.

## Free models, with failover, never the source of truth

The agents' LLM calls handle conversation, revision, facade design, plan reading,
critique and explanation. What can be measured (geometry, solar position, daylight
factors, airflow, sightlines, quantity takeoff, Vastu rules) is measured, and the
agents use those measurements as tools, so a model's opinion is always checked
against arithmetic.

For the LLM work, `aip/core/providers.py` is a registry of free-tier
and local models. The router is capability-addressed (`Capability.REASONING`,
not a vendor name), rate-limit aware, circuit-broken, failover-capable, and
routes on **measured latency as well as quality** - a model 4% better and 40x
slower is the wrong choice when thirteen critics are fanning out.

Provider catalogues rot, so the registry is verified rather than trusted:

```bash
cd backend && .venv/Scripts/python scripts/verify_providers.py
```

This sends one probe to every registered model and reports what actually
answers. It is worth running before any demo - when first executed against live
credentials it found that *every* OpenRouter `:free` id in the registry had been
withdrawn and five Groq ids were decommissioned.

**With no API key at all, the platform still works.** Every analytical result is
unaffected; only generated commentary degrades, and it is labelled `degraded` in
the API payload and in the UI. See [docs/API_SETUP.md](docs/API_SETUP.md) for
which free accounts to create and why.

## Bring your own plan

The studio has two ways in. State a brief and the committee designs; or upload
a plan you already have, and the same committee reviews it. `POST
/api/v1/plans/import` reads a **DXF** (rooms from closed outlines and their
labels, at the drawing's own units), an **SVG** (shapes and the text inside
them), a **photo or scan** (a free vision model lists the rooms, each with a
confidence the studio shows you), or a plan JSON this studio exported. Then
`POST /api/v1/plans/{id}/review/stream` runs every critic, the Vastu graph, the
cost takeoff, the airflow solve and the negotiation on it, streamed over the
same events the design run uses.

Nothing about an upload is silent. The response says what was read, what was
assumed about scale, which labels could not be classified, whether doors and
windows had to be placed, and - when no plot was given - what plot was assumed.
The round trip is the test: a scheme the platform drew, exported as DXF and
uploaded, comes back with every room's type and area identical.

## Embedding into a practice's website

One tag:

```html
<script src="https://your-aip-host/embed/aip-widget.js"
        data-key="aip_pk_your_public_key"
        data-practice="Kalpa Studio"
        data-accent="#7FA3D4"
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
    protocol.py    the manager-worker negotiation state machine
  engines/
    architecture/  layout synthesis, solar, metrics, NBC codes, drawings, repair
      dxf.py         AutoCAD R12 export, written by hand, no dependency
    vastu/         the encoded corpus and the reasoning engine
      graph.py       the knowledge graph
      reasoner.py    graph-path constraint reasoning
    cost/          rate schedule, quantity takeoff, Monte Carlo estimator
    interior/      furniture catalogue and the layout solver
    experience/    3D model generation, glTF/OBJ export, walkthrough
  rag/          hybrid BM25 + dense retrieval, corpus, continual learning
  api/          FastAPI app, routers, schemas, auth and tenancy
  db/           multi-tenant SQLAlchemy schema
  evaluation/   the benchmark harness and ablations
backend/scripts/  provider verification, report generation
frontend/       the architect studio (no build step)
embed/          the embeddable widget and its demo host page
docs/           architecture, research notes, API setup, sample output
```

## Testing

```bash
cd backend && .venv/Scripts/python -m pytest -q
```

240+ tests. They run with **no provider configured**, which is deliberate: it
proves the measured half of the committee never depends on a model being up. The suite asserts that isolation explicitly
rather than relying on environment variables being unset — the moment a developer
creates a `.env`, the trap would be a suite that silently starts calling live
providers and still passes.

Among what they pin: the negotiation can never leave a design worse than it found
it; no constraint may name an owner that is not a live agent; the knowledge graph
is deterministic edge-for-edge across builds; and the DXF is read back with an
independent CAD library to confirm every wall's length and thickness survived.

## Documentation

- [docs/API_SETUP.md](docs/API_SETUP.md) — the free accounts to create, in priority order
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — how the pieces fit together
- [docs/RESEARCH.md](docs/RESEARCH.md) — novelty claims, method, evaluation, limitations
- [docs/AIP_Project_Report_Phase1.docx](docs/AIP_Project_Report_Phase1.docx) — the
  Phase 1 report. Regenerate it with `python scripts/build_report.py` from
  `backend/`: every figure in it is measured from the running system at build
  time, so the document cannot drift from the code.
- `http://127.0.0.1:8000/docs` — interactive OpenAPI reference

## Status and honest limitations

This is a working research platform, not a shipped commercial product. What is
real and what is not:

**Real:** the generator, all ten analytical critics, the consensus procedure,
the manager–worker negotiation protocol, the Vastu engine with both its rule
corpus and its knowledge graph, quantity takeoff and pricing, the interior
solver, drawing, DXF and 3D generation, the plan importer, the API, tenancy,
the learning loop, and the evaluation harness. All tested.

**Indicative, needs a practice's own data:** the rate schedule is benchmarked to
CPWD conventions and market levels but is not a tendered schedule. Load your own
via `RateSchedule.from_file`.

**Not built, and not claimed:** photorealistic rendering — there is no image
provider wired in and no diffusion step anywhere in the pipeline. The
visualisation path is the vector drawing set and a dimensionally exact 3D model,
which is the more defensible artefact: a photorealistic render of a concept plan
invites a client to react to lighting and materials that no part of the system
has reasoned about. Also absent: structural sizing beyond span sanity checks,
MEP layout, IFC/BIM export (DXF is the honest target at concept stage — IFC would
imply a multi-discipline coordination this system has not performed), and iOS AR
(GLB covers WebXR and Android; iOS Quick Look needs a USDZ conversion requiring
Apple's toolchain).

**Where the knowledge graph stops:** 94 of 578 room-and-sector placements have no
derivation path and are reported `undetermined` rather than scored. That is the
correct behaviour, but it is coverage left on the table, and closing it is the
first item of next-phase work.

**Not measurable without a human study:** user satisfaction, expert-rated design
quality, and retrieval relevance. The harness reports these as
`not_measured_without_human_study` rather than inventing a proxy number.

## Licence

Apache-2.0.
