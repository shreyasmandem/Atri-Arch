# Checklist (quickest first)

- [x] Turn on Remote Control
- [x] Chat text a little larger (messages, input, lede, tips, brief strip and its buttons)
- [x] Loading scene: grass grows on every side and every room gets its furniture
- [x] Exteriors never block the entrance (porch, steps, gate, fins, screens)
- [x] Garage car smaller, fits the porch with room round it
- [x] Minifigures: no odd running; while waiting they survey - measure the plot, peg the corners, string lines, mark setbacks
- [x] Loading under 60 s end to end (pipeline 35-40 s on the largest brief: schemes reviewed in parallel, slow free models capped at 11 s)
- [x] Scheme scores higher for real (mean 0.71 -> 0.79 on 8 briefs: measured reviews, designed glazing with credited chajjas, wider landings)
- [x] Exteriors: distinct per chosen style, more design options and colour choices (signature features: jharokha, colonnade, chhatri, cornice, breeze-block, green wall; 14 accents; six new hero houses, larger hero)
- [x] Homepage bottom cards: typing/backspacing prompts, real mini schemes, minifigures (with faces) debating, "Explore, then change it" with a real post-design change feature (one-tap change suggestions under each result)
- [x] Bigger, better 3D renders beside the chat (six houses, closer framing)
- [~] Plans: architect-quality across every brief - TOP PRIORITY (parti planner draws 20-23 of 29 feasible test briefs with stacked stairs and intended doors; left: shallow plots under 8 m deep, living-dining links in cross-passage plans, oversized rooms on light ground floors)
- [x] Prepare for free public deployment (Dockerfile, render.yaml, DEPLOY.md, PUBLIC_DEMO mode; production config smoke-tested)

## Overnight 2026-10-12 (hackathon)
- [x] Chat: bare answers read, studio auto-starts (5 s cancellable) once plot/road/floors/bedrooms known
- [x] Over-full briefs are relaxed (floor added, least-important rooms left out, said in advisories) instead of 'engine closed the connection'
- [x] Real server errors shown in the UI; no more 'closed the connection' slop
- [x] Deployed: UI https://atri-arch.vercel.app, API https://atri-arch.onrender.com (Render free Docker, keyless until GROQ_API_KEY/GOOGLE_API_KEY are added by the user in Render > Environment)
- [x] Edit the drawing: widen/deepen, swap, rename, use-as, ceiling, undo (drawer, 'Edit design' button)
- [~] Plan quality sweep (scratchpad sweep.py): area_balance 18, underuses_plot 10, living_far_from_dining 10, bedroom_no_bath 9, unfurnishable 8
- [ ] Importer round-trip tests (4 fail in tests/test_import.py: small rooms lost) and odd image uploads
- [ ] cfo.ai: run a session and screenshot into docs/
- [ ] Remove remaining copy slop; default scores higher; edge cases (shapes, ceilings)
