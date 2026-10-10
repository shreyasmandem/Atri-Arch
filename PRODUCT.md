# PRODUCT.md — Architect Intelligence Platform (AIP)

> Derived from the founder's written brief and the project abstract. The founder
> instructed the build to proceed without blocking on an interview, so items
> marked **[assumed]** are inferences from that brief, not confirmed answers.

## What it is

An explainable multi-agent AI platform that takes an architectural brief and
returns a buildable scheme: floorplans, elevations, sections, an interior layout,
a Vastu report, a costed bill of quantities, and a 3D/AR walkthrough.

It is sold to **architecture practices**, and it embeds into the practice's own
website so their **clients** can use it directly under the practice's brand.

## The unique mechanism

**A committee, not an oracle.** Thirteen independent critics review every
candidate scheme. Ten are *analytical* — they compute daylight factors, air-change rates,
sightlines, walking distances, statutory compliance, structural spans, Vastu rule
satisfaction and quantity takeoff exactly, from geometry, in microseconds, for
free. Three are *generative* and supply judgement that resists formalisation.

A Pareto filter removes dominated schemes, a reliability-weighted Borda count
ranks the survivors, and disagreement is surfaced rather than averaged away.
Every number traces to a critic, a model and a citation.

The second mechanism: **it costs the practice nothing.** All model access runs on
free tiers or local inference. `total_model_cost_usd` is asserted to be exactly
zero by the test suite.

## Audience and scene

**Primary — the architect.** In studio, on a large monitor, often with a client
sitting beside them or on a call. They are being asked "why this scheme?" and
need to answer with authority in front of someone paying them. They already own
Revit and AutoCAD; this is not a replacement, it is the thing that gets them to a
defensible first scheme in minutes instead of a fortnight.

**Secondary — the client.** On a phone, on the practice's website, at night,
before they have committed to anyone. They cannot read a floorplan. They want to
know: what will my house look like, is it Vastu-compliant, and what will it cost.

## Modes by surface

- **Studio SPA** — Operate. The architect completes a task and defends a result.
- **Embedded widget** — Persuade, on the practice's site: it must convert a
  curious visitor into a booked conversation. [assumed]

## What must be true

- Nothing is asserted without a reason. Every score carries its evidence.
- Uncertainty is shown, never smoothed. P10/P90 bands, committee disagreement,
  and "not assessable" verdicts are features.
- Vastu is treated with intellectual honesty: classical citation *and* modern
  validity, reconciled by a stance the client controls.
- Degraded mode is labelled, never disguised.

## Constraints

- Zero marginal cost. No paid API may become load-bearing.
- Runs on a laptop. No GPU, no Docker, no cloud account required to try it.
- Indian residential practice is the first market: NBC 2016, CPWD rate
  conventions, INR, Vastu, tropical climate.

## Brand commitments

None inherited — greenfield. The practice's own branding overrides the widget's
theme via the `theme` field on the firm record.

## Not claims we may invent

Prices beyond the indicative rate schedule (which is labelled indicative),
customer names, benchmarks against named competitors, or capabilities the code
does not have.
