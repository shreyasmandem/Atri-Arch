# Architecture

How the pieces fit together, and why they are arranged this way.

## The pipeline

```
ClientBrief
    │
    ├─ interpret ──── fill gaps the client did not know to state
    ├─ retrieve ───── hybrid BM25 + dense over the corpus → Evidence[]
    ├─ generate ───── surrogate-assisted evolutionary search → FloorPlan[]
    │
    ├─ critique ───── 13 agents × N candidates, bounded fan-out → Critique[]
    │                   10 analytical (exact, free, microseconds)
    │                    3 generative (free-tier LLM, judgement)
    │
    ├─ consensus ──── admissibility → Pareto → weighted Borda → ConsensusResult
    │
    ├─ debate ─────── only if the committee genuinely disagrees
    ├─ refine ─────── apply named remedies; keep only if the score improves
    │
    ├─ negotiate ──── manager-worker consensus protocol
    │                   measure 7 constraints (3 hard, 3x weighted)
    │                   route each failure to the agent that owns it
    │                   accept a change only if re-measurement improves
    │                   repeat until satisfied, converged, or out of budget
    │
    └─ explain ────── plain-language rationale for the client
                            │
                            ▼
       drawings · DXF · 3D · Vastu report · BOQ · interior · transcript
```

The distinction between `consensus` and `negotiate` is the one that matters.
Consensus *selects* between fixed candidates; it cannot fix a flaw all of them
share. Negotiation *changes* the chosen scheme and re-measures, so it can.

Progress streams as server-sent events, so a client watching in a browser sees
the committee working rather than a spinner.

## The single source of truth

`FloorPlan` (`aip/domain/plan.py`) is the one representation every engine reads
and writes. That is what allows a Vastu violation to name the exact wall to move,
and moving that wall to immediately re-price the project.

```
FloorPlan
 ├─ Site          boundary, north angle, lat/long, setbacks, FAR, coverage
 ├─ ColumnGrid    spacings, column size, beam depth, slab thickness
 └─ Level[]
     ├─ Room[]        polygon, type, ceiling height, finishes, metadata
     ├─ Wall[]        start, end, thickness, kind, bounding rooms
     │   └─ Opening[]   kind, position along wall, width, height, sill
     └─ Staircase[]   tread, riser, width, going, headroom
```

Coordinates are metres, +Y toward the top of the sheet, and `Site.north_angle`
records where true north actually is. Every directional judgement — Vastu sector,
solar exposure, prevailing wind — derives from that one field, so a rotated site
rotates the compass rather than the plan.

## Why slicing trees, not diffusion

Pixel-space floorplan generation produces images, not buildings: walls that do
not close, rooms without doors, areas that cannot be dimensioned, and nothing a
quantity surveyor can consume. It also needs a GPU, which breaks the zero-cost
promise.

A slicing tree encodes a plan as recursive horizontal/vertical cuts with split
ratios, with rooms at the leaves. This guarantees a valid partition **by
construction**. The tree is then optimised by evolutionary search against the
analytical metric suite, which is exact and runs in microseconds — so thousands
of candidates per second on a laptop CPU, for free.

Language models enter afterwards, where they add value: interpreting an ambiguous
brief, judging aesthetic coherence, and explaining the result. Geometry is left
to geometry.

**Surrogate assistance.** Evolution runs against a cheap geometric proxy; the
expensive exact evaluation re-ranks only elite survivors. Roughly 17× faster,
and the reason the widget can respond interactively.

## The free-model router

`aip/core/providers.py` is a capability market: 42 models across 10 providers,
each a genuine free tier or local inference. Callers ask for
`Capability.REASONING`, never for a vendor.

`aip/core/llm.py` adds:

- **Local rate limiting** — sliding windows per model against documented free
  tier RPM/RPD, so we throttle ourselves rather than discovering limits via 429.
- **Circuit breaking** — a provider that is down or out of quota is parked with
  exponential cool-off instead of being retried by every critic.
- **Structured output repair** — free models are inconsistent at JSON. The router
  strips `<think>` traces and code fences, repairs trailing commas, bare keys,
  single quotes and truncation, then performs one guided repair round.
- **Provider diversity** — `diversified()` spreads ensemble members across model
  *families* before repeating one, because correlated critics carry no
  information.
- **Graceful degradation** — with nothing reachable, `OfflineBackend` returns
  deterministic schema-valid stubs marked `degraded=True`, surfaced in the API
  and the UI. The analytical engines never touch this path.

## Tenancy

Every meaningful row belongs to a `Firm`. Two key classes, because a
browser-embedded credential cannot be secret:

- **Public** (`aip_pk_…`) — ships in the embed snippet, origin-bound, limited to
  client-facing operations.
- **Secret** (`aip_sk_…`) — server-side only, full access.

Enforced at the dependency layer (`require_secret`) rather than left to each
endpoint to remember. Plan ids are not capabilities: `PlanStore.get` takes a
firm id and refuses cross-tenant reads even for a correctly-guessed id.

## Learning

Three per-practice learned components, all fed by `/feedback` and `/actuals`:

| Component | Signal | Update rule |
|---|---|---|
| Critic reliability | human per-axis ratings | Brier-style EMA, clamped [0.15, 0.99] |
| Corpus weights | accepted/rejected designs | ±0.12 / −0.09, clamped [0.15, 4.0] |
| Cost calibration | delivered vs predicted cost | EMA, ratio clamped [0.55, 1.85] |

Clamping everywhere is deliberate: a single unusual project must not be able to
distort a model a practice depends on.

## Frontend

Two surfaces, deliberately different.

**Studio** (`frontend/`) — Operate mode, for the architect. No build step: plain
HTML, CSS and ES modules served from the same origin as the API. Laid out on the
vastu-purusha-mandala, a 9×9 pada grid whose centre stays clear because that is
the rule the engine enforces. Rooms light the padas they occupy in their
quarter's pigment; an occupied Brahmasthan flares in hingula red.

**Widget** (`embed/`) — Persuade mode, for the client, on the practice's own
site. Renders inside a shadow root so a hostile host stylesheet cannot reach it
and it cannot reach the host. Themed by the practice, not by us.

## Failure modes handled explicitly

| Situation | Behaviour |
|---|---|
| No API key at all | Analytical results unaffected; generative critics labelled `degraded` |
| Every candidate breaches code | Admissibility relaxes, least-bad returned, loud warning in the explanation |
| Vastu rule not evaluable | Excluded from the denominator with a stated reason |
| Vastu rules conflict | Resolved by effective weight; both sides reported |
| Refinement makes things worse | Discarded; the original is kept |
| Free tier exhausted | Circuit breaker parks the provider, router fails over |
| Room too small for its furniture | Reported with dimensions, not silently omitted |
| Provider returns malformed JSON | Repaired, then one guided retry, then a schema-valid stub |
