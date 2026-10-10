# DESIGN.md — Architect Intelligence Platform

Recorded from the built surfaces, not from intention. Ground truth is
`frontend/studio.css`, `frontend/index.html` and `embed/aip-widget.js`.

> **Provenance note.** This was documented in-thread rather than by the shipped
> documenter, and the screenshot-based finish review could not run: the Browser
> pane in this environment does not composite frames, so no screenshot could be
> captured. Verification was functional (DOM, computed styles, live pipeline
> runs) plus the mechanical detector, which passes clean. A visual review by a
> human is still owed.

---

## The world

**The vastu-purusha-mandala as an operating grid.**

The mandala is struck out in rice flour on a swept earth floor before
construction begins, and painted in the pigments of Indic manuscript. That is
the material world the studio is built from — deliberately not blueprint cyan,
and not the near-black-plus-neon that every AI tool ships.

The centre of the mandala, the Brahmasthan, must stay unbuilt. The engine
enforces that rule on every plan it scores, so the interface obeys its own
doctrine: the centre of the workspace holds the drawing, never chrome.

**Refused by construction:** glass cards, gradient text, a chat rail, a
hero-metric template, kickers above headings, sparklines standing in for content.

---

## Colour

Strategy: **full palette, four named roles.** The pigments are semantic, not
decorative — each names a quarter of the mandala and carries that quarter's
meaning through the entire product, from the pada grid to the critic list to the
verdict band.

| Token | Value | Quarter | Meaning |
|---|---|---|---|
| `--indigo` | `#7FA3D4` | Ishanya · NE · water | computed analysis |
| `--hingula` | `#E4694C` | Agneya · SE · fire | violation, breach, warning |
| `--ochre` | `#DFA85C` | Nairutya · SW · earth | mass, quantity, cost |
| `--orpiment` | `#F0D165` | Vayavya · NW · air | judgement, generated opinion |
| `--ok` | `#86B87A` | — | zero-cost confirmation only |

Ground and line work:

| Token | Value | Use |
|---|---|---|
| `--earth` | `#14100B` | swept earth ground |
| `--earth-2` | `#1A150E` | rails, lifted surfaces |
| `--earth-3` | `#221B12` | active rows, toasts |
| `--sunk` | `#0E0B07` | crown, inset fields, verdict cells |
| `--rule` | `#2E2517` | hairline divisions |
| `--rule-2` | `#453724` | field borders, emphasised rules |
| `--chalk` | `#F6F1E4` | rice flour — primary text and line work |
| `--chalk-2` | `#CFC5AE` | secondary text |
| `--chalk-3` | `#9C9078` | tertiary text, labels |

**Dark, chosen from the scene, not by category:** an architect at a large monitor
in a studio, often in the evening, often with a client beside them. Drawings
must read as drawings, and white line work on a dark ground is exactly how a
mandala is struck on a floor.

Contrast: `--chalk` on `--earth` ≈ 15:1. `--chalk-3` on `--earth` ≈ 7:1. Both
clear AA for body text.

---

## Type

Operate mode, so workhorse stacks are correct and no display face is imported.

- `--face` — `ui-sans-serif, "Segoe UI", system-ui, …` for UI and prose
- `--num` — `ui-monospace, "SF Mono", "Cascadia Mono", …` for every number

**Numbers are always monospaced with `font-variant-numeric: tabular-nums`.** In a
tool whose output is scores, areas, rates and confidence bands, digits that shift
width as they update are a legibility defect, not a stylistic choice.

The display voice is not a font. Headings are the workhorse face at
`letter-spacing: 0.2em`, uppercase, 600–700 weight — geometric, constructed,
consistent with the grid the whole surface is built on. The identity mark is
authored SVG built on the same 9-grid.

Fluid scale, three steps only: `--step` (labels), `--ui` (body), `--lede`
(prose). A tool needs fewer type sizes than a magazine.

---

## Layout

Three phases on one URL, switched by `body[data-phase]`:

**compose** — the mandala at full scale on the left, the brief on the right. The
diagram is the first viewport and the product's thesis: nine by nine padas with
the centre kept open.

**running** — a single centred column: progress track, current stage, thirteen
critic chips that fill as verdicts land, and a streaming log.

**review** — `280px | 1fr | 300px` plus a full-width verdict band.
West rail carries the selected scheme, its axis scores and a brief recap. The
stage holds one pane at a time. East rail is the committee. Eight views:
drawings, mandala, vastu, cost, interior, 3D, findings, audit.

The mandala was originally a permanent frame around everything. That was wrong:
it left results no room, and the architect came for the drawing. It now opens
the app and returns as one diagnostic view among eight.

Breakpoints: 1400px tightens the rails; 1180px drops the west rail; 800px stacks
everything and lets the body scroll.

### The rule that broke the first build

`.brahmasthan__empty` and `.sheet` set `display:flex` in a class rule. A class
selector outranks the user-agent `[hidden]` rule, so `hidden` did nothing and
every pane stacked on top of the drawing — the result screen rendered as
overlapping text. The stylesheet now opens with:

```css
[hidden] { display: none !important; }
```

Any new pane must rely on that, never on its own display toggle.

---

## The signature moment

**Rooms light the padas they occupy, in their quarter's pigment.** The generated
plan is projected onto the 9×9 field, so the mandala becomes a diagram of the
building drawn on the diagram the building is judged against. It lives in the
Mandala view, paired with a room-by-sector table.

The Brahmasthan is scored separately: clear padas are struck open in chalk,
occupied ones flare in hingula with a stated count. That is the one rule the
whole world is built around, and washing it out in a uniform tint — which is what
the first build did — destroyed the thesis.

Motion is one authored idea, not scattered effects: critic glyphs fill and their
bars extend as verdicts land. Bars animate `transform: scaleX()` from a
left origin, never `width`, because thirteen of them animate at once.
`prefers-reduced-motion` collapses all of it.

---

## Components

- `.tab` — square, hairline, uppercase tracked. Active inverts to chalk-on-earth.
- `.fld` — inset field on `--earth-sunk`, focus ring in orpiment, unit glyph
  right-aligned inside the control.
- `.stance` — the Vastu reconciliation slider. Track gradient runs indigo →
  ochre (modern → traditional); the thumb is a rotated square, echoing a pada.
- `.critic` — 8px rotated-square glyph in its pigment, name, computed/judged
  label, tabular score, and a bar. Unseated critics sit at 0.34 opacity.
- `.finding` — severity lozenge, message, monospace citation, remedy in indigo.
- `.ledger-table` — sticky header, tabular numerals, right-aligned quantities.
- `.verdict__cell` — 2px pigment top border naming what it measures.

Icons are authored SVG on a consistent stroke. No emoji, no icon font.

---

## The widget is a different surface

`embed/aip-widget.js` is **Persuade** mode on a practice's own website, and it
inherits the palette but not the layout language. It renders inside a shadow
root with `all: initial`, so a hostile host stylesheet cannot reach it and it
cannot reach the host — verified against a demo page that forces
`border-radius: 14px !important` and Georgia on every button.

Its accent is the *practice's*, supplied via `data-accent`. Four steps, a
progress track, three stat blocks. Focus is trapped; Escape closes; focus
returns to the launcher.

---

## Rules for extending this

1. **The centre stays clear.** Nothing chrome-like may occupy the Brahmasthan.
2. **Pigments are semantic.** Never use hingula for emphasis, only for breach.
   Never use indigo for decoration, only for computed analysis.
3. **Numbers are monospaced and tabular.** Always.
4. **Uncertainty is shown.** Bands, disagreement and "not assessable" are
   first-class states, never smoothed into a single confident figure.
5. **Degraded is labelled.** If a result came from the offline fallback, the
   interface says so.
6. **Animate transform and opacity.** Not width, height, or position.
7. **No new type sizes** without removing one.
8. **One pane visible at a time.** Panes hide with `hidden`; never add a
   competing `display` rule to a pane or its children.
9. **A missing value is an em-dash**, not a blank and not a zero.
