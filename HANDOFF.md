# Handoff — Atri Arch (Architect Intelligence Platform)

FastAPI backend in `backend/`, static frontend in `frontend/`. Run: preview config "aip" in `.claude/launch.json` (uvicorn on :8000, no auto-reload — restart after backend edits). API at `/api/v1`. Keys live only in gitignored `backend/.env` (GROQ_API_KEY comma-separated for rotation, GOOGLE_API_KEY) — never commit or echo them.

## Working rules (from the user)
- Chained one-line updates, minimal tokens, production quality.
- Never `git push` unless asked. No subagents unless asked. Don't fabricate commits.

## Planning pipeline (backend/aip/engines/architecture)
- `parti.py` (NEW, leads) - three bands front/core/back (or a thin cross-passage "thin" mode). Genes (`Genes`) name every choice; random starts + hill-climbing; `_arrange` solves band order exhaustively on rough widths; `_size` lays bands (per-floor depths, stair fixed), `_score` is the architect's penalty. Rooms carry `enter_from` / `suite_of` / `common` so `_place_doors` follows the drawn intent. Layout judges its top 36 and gives clean parti plans `_PARTI_LEAD`.
- Checks: scratchpad-style sweep (`scripts/plan_audit.audit` over `plan_sweep.briefs(30)`), plus `CHECKLIST.md`.
- `spine.py` — hall-spine planner (variants incl. transverse, single-loaded, L). Diagonal roads try both sides (`side=`). Shrinks rooms down to `MIN_AREA` as last resort. Upper-floor suites flip baths off kitchen/dining/puja below.
- `rowhouse.py` — narrow plots (≤8.6 m): living band front, stair+passage+service column middle, dining/kitchen back.
- `layout.py` — `_spine_candidates` (spine + row) before the GA; GA is fallback. `_prepare_requirements` moves laundry/store/study upstairs when the ground floor is over-full.
- `api/schemas.py` `_apply_extras` — chat room requests claim existing rooms or add new ones (second pinned kitchen is added, not moved). `domain/brief.py` dedupes by (type, level).
- `agents/brief_agent.py` — rules parser (typos, counts per floor, "next to", garden→courtyard) + LLM turn; `reply_language()` decides reply language deterministically.

## Checks
- Sweep: `scratchpad`-style script over `scripts/plan_sweep.briefs(30)` + `scripts/plan_audit.audit`. Last: 8/32 briefs don't fit spine/row (fall back to GA).
- Tests: `cd backend && PYTHONPATH=. .venv/Scripts/python.exe -m pytest -q tests` → 6 known pre-existing failures (test_feasibility caps, 4× test_import, test_levels kw1).

## Open items (see CHECKLIST.md)
- Parti cannot draw plots under ~8 m deep (road on the long side of a 9 m plot) - spine/GA still take those.
- Generative critics fall back to `agents/computed_review.py` (measured) when free models are slow (11 s cap).
- Deploy: `DEPLOY.md` (Docker; HF Spaces or Render).
- 8 briefs still fall to the GA (tight 9 m plots with requested garage, 9×12 G+1, road on long side of narrow plot); GA output quality is weak.
- Row house: back-band bedroom without a bath is oversized; living not adjacent to dining.
- Board sometimes empty at "Decided"; pre-existing failing tests above.
- Homepage polish if wanted.
