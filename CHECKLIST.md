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

Done
- [x] Chat: bare answers read, studio auto-starts (5 s, cancellable) once plot/road/floors/bedrooms are known; Hinglish/Hindi read and answered
- [x] Over-full briefs are relaxed (floor added, least-important rooms left out, said in advisories) instead of an error
- [x] Real server errors shown in the UI (no 'closed the connection' slop); caption slop removed
- [x] Deployed: UI https://atri-arch.vercel.app (Vercel), API https://atri-arch.onrender.com (Render free Docker). Redeploy API: Render > Manual Deploy
- [x] Edit the drawing: widen/deepen, swap, rename, use-as, ceiling, undo (drawer, 'Edit design' button), re-scored in the background
- [x] Small plots: setbacks follow plot size, compact stair, tighter minimums; garage is a car's width; passages kept short
- [x] Front door faces the road on every planner; budget optional (no invented budget, cost axis no longer 0.20)
- [x] Uploads: unreadable pictures/SVGs still give a starting plan on the plot, said plainly; garbage files are a clear 422
- [x] cfo.ai used for the business forecast: docs/cfo-ai/

Open
- [~] Plan quality: 30x40 ft with parking falls back to the GA planner (flawed adjacency); parti struggles on plates under ~70 m2
- [ ] tests/test_import.py: 4 round-trip tests fail (thin 1.1 m rooms lost on re-read) - pre-existing, fixture-related
- [ ] Vastu default score ~55-65 at the balanced stance (planner weights barely move it)
- [ ] Add GROQ_API_KEY / GOOGLE_API_KEY in Render > Environment (user), then Manual Deploy
