# DESIGN.md — Atri Arch (Architect Intelligence Studio)

Documenting the modern **Pitch-Black Cosmic Space & Architectural CAD** design system.  
Ground truth is `frontend/index.html`, `frontend/studio.css`, `frontend/studio.js`, and `frontend/classic.html`.

---

## 1. Design Vision & Philosophy

**Pitch-Black Cosmic Space meets Precision Architectural CAD.**

Atri Arch presents an autonomous multi-agent architectural studio as a fusion of cosmic infinity and mathematical drafting precision. The experience opens with an animated architectural blueprint drafting sequence before expanding into a pitch-black workspace illuminated by starlight, glassmorphism cards, and laser-precise typography.

### Refused by Construction:
- Artificial Intelligence "slop" emojis (📐, 🏡, ✨, 🤖)
- Generic dark blue / navy gradients — the ground is **pure `#000000` pitch black**
- Cluttered chrome or low-contrast text
- Sluggish heavy CSS filter blurs that stutter frame rates

---

## 2. Color System & Design Tokens

### The Pure Pitch-Black Universe Palette
The base is solid `#000000`, accented with frosted glass surfaces and crisp starlight:

| Token | Value | Role |
|---|---|---|
| `--bg-base` | `#000000` | Pure pitch-black canvas and page background |
| `--bg-card` | `rgba(8, 10, 15, 0.76)` | Frosted glassmorphic card fill |
| `--bg-card-hover` | `rgba(14, 18, 26, 0.88)` | Card hover lift fill |
| `--bg-input` | `rgba(5, 6, 9, 0.85)` | Inset input field surface |
| `--bg-glass` | `rgba(255, 255, 255, 0.03)` | Subtle glass translucent highlights |
| `--rule` | `rgba(255, 255, 255, 0.08)` | Micro hairline dividers |
| `--rule-2` | `rgba(255, 255, 255, 0.14)` | Card and interactive border lines |
| `--rule-focus` | `#7FA3D4` | Focused input border glow |

### Typography & Starlight Tones
| Token | Value | Usage |
|---|---|---|
| `--chalk` | `#FFFFFF` | Primary headlines, active icons, drawn laser strokes |
| `--chalk-2` | `#E4E7EC` | Body text, titles, labels |
| `--chalk-3` | `#8D94A5` | Dimension text, secondary copy, input placeholders |
| `--chalk-4` | `#474D5A` | CAD HUD metadata, tertiary indicators |

### Semantic Architectural Pigments
| Token | Value | Role & Meaning |
|---|---|---|
| `--indigo` | `#7FA3D4` | Computed analysis, active selections, focus highlights |
| `--ochre` | `#E5A958` | Golden ratio guides, solar angle rays, mass & cost |
| `--hingula` | `#F06548` | Compliance breach, structural warning, Agneya (SE) fire |
| `--orpiment` | `#F3D063` | Vastu judgement, Vayavya (NW) air |
| `--ok` | `#3DD68C` | Live status beacon, confirmed pass |

---

## 3. Typography Stack

Apple-inspired geometric precision typography:
- **Prose & UI**: `Inter`, `-apple-system`, `BlinkMacSystemFont`, `"SF Pro Display"`, `"SF Pro Text"`, `sans-serif`
- **Telemetry & Dimensions**: `JetBrains Mono`, `ui-monospace`, `"SF Mono"`, `"Cascadia Code"`, `monospace`

**Rule**: All architectural numbers, coordinates, areas, and currency figures use monospaced digits with `font-variant-numeric: tabular-nums` to prevent layout shift during updates.

---

## 4. Key Architectural Sequences

### A. The Architectural Blueprint CAD Intro
When the studio loads, an SVG blueprint drafting sequence renders on a pitch-black screen:
1. **CAD HUD Telemetry**: `CAD // SYS.REV-04`, `SCALE 1:100`, `AZIMUTH 042° NE`, `13 CRITICS ONLINE` with a pulsing status beacon.
2. **Drafting Compass & Golden Ratio**: Fibonacci spiral arcs and solar rays (`SOLAR 45°`) sketch out.
3. **3D Isometric Pavilion**: Cantilevered slab, structural pilotis, floating roof pergola, and a 9×9 sacred Vastu module floor grid.
4. **Dimension Annotations**: Precision leader lines with extension ticks (`18.00 m`, `12.00 m`, `EL +6.80`).
5. **Brand Stroke Etch**: Laser-stroke drawing of **`ATRI · ARCH`** with subtext and live status ticker.
6. **Auto-Dismiss & Skip**: Seamlessly transitions after 2.8s or immediately upon clicking **Enter Studio →**.

### B. The Cosmic Star-Field Engine (`space-stars`)
A high-performance Canvas 2D starfield runs across 3 phases:
1. **Forming (Intro Phase)**: 240 stars materialize in a rotating galaxy cluster around the architectural CAD center.
2. **Spreading (Transition Phase)**: As the intro dismisses, stars expand outward with smooth exponential easing `(s.x += (targetX - s.x) * 0.055)` across the entire home page.
3. **Ambient (Home Page Phase)**: Stars drift with gentle sine-wave twinkling and interactive mouse repulsion.

---

## 5. UI Architecture & Comparison Tool

### Three Phase Flow:
- `body[data-phase="compose"]`: Modern glassmorphic brief composition cards with live plot dimension & area stats.
- `body[data-phase="running"]`: Autonomous multi-critic synthesis tracker with live stage indicators.
- `body[data-phase="review"]`: 8 diagnostic views (Drawings, Mandala, Vastu, Cost, Interior, 3D, Findings, Audit).

### Classic UI Comparison System:
- A dedicated **`Compare UI`** button in the header opens a side-by-side modal displaying the original classic layout (`classic.html`) next to the new modern design for real-time evaluation.