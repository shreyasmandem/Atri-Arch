---
name: Atri Arch Studio
description: A studio of architects and thirteen specialists, in the Studio Rabbit world of warm black, cream and grain.
colors:
  ink: "#0b0a09"
  coal: "#141312"
  soot: "#1a1919"
  cream: "#ede6dc"
  cream-2: "rgba(237, 230, 220, 0.74)"
  cream-3: "rgba(237, 230, 220, 0.5)"
  cream-4: "rgba(237, 230, 220, 0.3)"
  rule: "rgba(237, 230, 220, 0.1)"
  rule-2: "rgba(237, 230, 220, 0.2)"
  brick: "#c4553f"
  stone: "#a39c92"
  sand: "#c9b497"
  pale-cream: "#e8dcc6"
typography:
  display:
    fontFamily: "Archivo, Helvetica, Arial, sans-serif"
    fontSize: "clamp(46px, 6.2vw, 96px)"
    fontWeight: 500
    lineHeight: 0.92
    letterSpacing: "-0.025em"
    fontVariation: "'wdth' 94"
  soft:
    fontFamily: "Archivo, Helvetica, Arial, sans-serif"
    fontSize: "clamp(26px, 2.9vw, 46px)"
    fontWeight: 300
    lineHeight: 1.05
    letterSpacing: "-0.01em"
  headline:
    fontFamily: "Archivo, Helvetica, Arial, sans-serif"
    fontSize: "30px"
    fontWeight: 500
    lineHeight: 1
    letterSpacing: "-0.01em"
  body:
    fontFamily: "Geist, Helvetica, Arial, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Geist, Helvetica, Arial, sans-serif"
    fontSize: "11px"
    fontWeight: 600
    letterSpacing: "0.14em"
rounded:
  pill: "999px"
  panel: "16px"
  frame: "14px"
  cell: "6px"
spacing:
  gutter: "clamp(16px, 3.2vw, 48px)"
  row: "16px"
  group: "clamp(40px, 6vh, 64px)"
components:
  button-primary:
    backgroundColor: "{colors.cream}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    height: "56px"
    padding: "0 30px"
  button-line:
    backgroundColor: "transparent"
    textColor: "{colors.cream}"
    rounded: "{rounded.pill}"
    height: "40px"
    padding: "0 20px"
  toggle-on:
    backgroundColor: "{colors.cream}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "8px 15px"
  input-underline:
    backgroundColor: "transparent"
    textColor: "{colors.cream}"
    padding: "2px 0 4px"
---

# Design System: Atri Arch Studio

## Overview

**Creative North Star: "The Studio After Dark"**

The studio runs in the Studio Rabbit world: a warm black room, cream type, the grain of film over everything, and nothing that glows. Content is set the way that site sets its chapters: what matters goes large, uppercase and tight in Archivo, the soft line beside it in Archivo italic, and everything you operate in quiet Geist. The brief is the project's title, so the first screen is the house being asked for, typeset and drawn to scale as you type.

Structure comes from hairline rules, not boxes. There are no cards, no glass panels and no gradients standing in for depth. Colour is almost absent: cream at four strengths does the work, a few warm neutrals tell disciplines apart, and one brick red means something is wrong.

**Key Characteristics:**
- Warm black ground, cream type, animated film grain at 6%.
- Archivo uppercase display with an italic soft line; Geist for UI and tracked uppercase labels.
- Hairline rules and pill controls; cream-filled selection.
- Brick red is the only signal colour.
- One authored moment per screen: the self-drawing brief, the 3D studio at work, the drawing that carries into the review.

## Colors

A warm monochrome: black with a little brown in it, cream with a little paper in it.

### Primary
- **Cream** (#ede6dc): all primary text, the primary button, selected toggles and tabs, line work in drawings and the 3D board.

### Neutral
- **Ink** (#0b0a09): the ground everywhere, and the 3D board's clear colour.
- **Coal** (#141312) and **Soot** (#1a1919): raised surfaces only: dialogs, toasts, speech bubbles, the drawing sheet.
- **Cream at 74 / 50 / 30%**: secondary text, labels, faint captions. **Rules at 10 / 20%**: every divider and control outline.
- **Stone** (#a39c92), **Sand** (#c9b497), **Pale cream** (#e8dcc6): discipline marks (analysis, structure and cost, judgement and Vastu), mandala quarters and the airflow ramp's upper end. They are tones, never fills of a region.

### Tertiary
- **Brick** (#c4553f): breaches, critical findings, low scores, a sealed room in the airflow diagram, the toast dot. Nothing decorative.

### Named Rules
**The One Signal Rule.** Brick red appears only where something fails. If a screen shows red, it is telling you about a problem.

## Typography

**Display Font:** Archivo (variable, width 94%), self-hosted.
**Body Font:** Geist (variable), self-hosted. Both are taken from the Studio Rabbit site.

### Hierarchy
- **Display** (500, clamp(46px, 6.2vw, 96px), line-height 0.92, -0.025em, uppercase): the brief headline's hard lines, the run's stage word, the review score (84px).
- **Soft** (Archivo italic 300, clamp(26px, 2.9vw, 46px)): the brief headline's soft lines, the run title, spoken narration in the 3D tab.
- **Headline** (Archivo 500, 30px, uppercase): spec groups and pane sections.
- **Body** (Geist 400, 15px / 1.5, tabular numerals): reading text, kept to 64–72ch.
- **Label** (Geist 600, 11px, 0.14–0.16em, uppercase): row keys, tabs, buttons, captions. The floor is 11px.

### Named Rules
**The Chapter Rule.** A screen's subject is said once, large and uppercase, with a tracked index line above it only when the index carries information (Stage 4 of 9).

## Layout

- The brief is two columns: a sticky title column (headline and plot drawing) and the specification sheet, a run of rows with a 9.5rem key column and hairline separators. A sticky action bar ends the sheet.
- The run is the 3D board full bleed, with the chapter caption bottom left, controls top right, a 320px scores column on the right and a 2px progress line along the bottom edge.
- The review is the drawing stage and a 360px side panel: score, a 2×2 stats grid, the committee, the brief collapsed.
- Gutter clamp(16px, 3.2vw, 48px); rows 16px; groups 40–64px apart.
- Breakpoints: 1180px (narrower side panel), 980px (brief and review stack), 760px (single-column rows, full-width primary button, segmented control as a grid).

## Elevation & Depth

Flat, in tones. Depth comes from the ink, coal and soot steps and from vignettes, not shadows. The only shadows are the soft drop under a drawing on the plate and under floating dialogs, toasts and bubbles (0 12–40px blur, black).

## Shapes

Pills (999px) for every control, 6px cells in the road picker, a 14px frame for the drop zone, 16px for dialogs. Lines are 1px; in the report, a 1px inset rule on the left marks a finding's severity instead of a coloured border.

## Components

### Buttons
- **Primary** (`.btn--cream`): cream pill, ink label text, an arrow that moves 4px on hover. 56px on the brief, 40px elsewhere.
- **Line** (`.btn--line`): transparent pill with a 1px rule outline that brightens on hover.
- **Quiet** (`.btn--quiet`): label text only, for drawing tools.

### Chips
- **Toggles** (`.amenity-chip`): outlined pills; a checked toggle fills cream with ink text.
- **Segmented** (`.seg`): a pill track; the chosen option fills cream.

### Inputs / Fields
- **Number and text**: borderless with a 1px underline that brightens on hover and turns cream on focus; numbers at 24px; units in small cream-3 text beside them; − and + steppers as outlined circles.
- **Select**: same underline, with a drawn cream chevron.

### Navigation
- The bar: wordmark left, scheme pills centre, view tabs and actions right. A tab is selected by a cream underline that draws in from the left.

### The live brief
The headline rewrites itself from the inputs, and the plot drawing redraws to scale with smooth geometry transitions: boundary, dashed setback envelope, road band, stacked floors, dimensions, north point.

### The 3D studio
Collectible-style figures on a warm black board: hard hats, blazers, rolled plans, clipboards. Speech bubbles in coal with a pigment label; the team's replies in cream. The drone camera holds the floor being drawn.

## Do's and Don'ts

### Do:
- **Do** set the subject of each screen large, uppercase and once.
- **Do** separate with hairlines and space before reaching for a container.
- **Do** keep numbers tabular and labels at 11px or larger.
- **Do** keep red for failure only.

### Don't:
- **Don't** add cards, glass, glow, gradient text or coloured borders thicker than 1px.
- **Don't** put a kicker or eyebrow label above a heading.
- **Don't** use emoji or Unicode glyphs as icons; draw them in a 1.5px stroke.
- **Don't** bring back the navy, gold-on-black or starfield looks of the earlier studio.
