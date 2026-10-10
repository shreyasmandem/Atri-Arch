# neatHack 2026 Build Log — AtriArch (Architect Intelligence Platform)

## Project
- **Name**: AtriArch — Architect Intelligence Platform (`aip`)
- **One-sentence purpose**: An explainable multi-agent architectural design, code-compliance, Vastu Shastra, interior planning, and Monte Carlo cost-estimation platform that turns a client brief or uploaded floor plan into buildable, consensus-verified 2D/3D schemes.
- **Problem addressed**: Single-pass LLM floor-plan generators hallucinate unbuildable layouts (narrow slot rooms, misaligned staircases across floors, missing NBC 2016 egress/ventilation requirements, and unverified budgets). AtriArch replaces one-shot generation with a 13-agent committee (10 deterministic physics/code/Vastu/cost analytical critics + 3 generative critics), Pareto + Borda consensus voting, and a stateful manager-worker repair protocol (`ConsensusProtocol`) where every mutation is re-measured before acceptance.

## Team
- **Builder**: Shreyas Mandem (`@shreyasmandem`)

## Stack & Partner Integrations
- **Backend**: Python 3.13, FastAPI, Pydantic v2, Shapely, NumPy/SciPy, Trimesh, SQLAlchemy (`aiosqlite`), Hybrid BM25 + dense RAG (`aip.rag`, `aip.knowledge.code_rag`, `aip.knowledge.vastu_graph`)
- **Frontend**: TypeScript, React, Vite, Three.js (`StudioScene.tsx` 3D Studio Rabbit atelier, `TeamScene.tsx` live drafting-table agent view, interactive 2D SVG CAD & 3D presentation viewer)
- **Neatlogs (`neatlogs>=1.4`, `neatlogs-cli@0.2.0`)**:
  - Project ID: `467f83ee-e953-4b72-aa4a-2831318be004`
  - Full OpenInference / Neatlogs span hierarchy in `backend/aip/core/telemetry.py` covering root `WORKFLOW` (`atriarch.design_pipeline`), stage `CHAIN`s (`interpret`, `generate`, `critique`), `RETRIEVER` (`rag.retrieve_for_brief`), all 13 committee `AGENT` critics (`critic.compliance`, `critic.daylight`, `critic.ventilation`, `critic.privacy`, `critic.circulation`, `critic.accessibility`, `critic.spatial`, `critic.structure`, `critic.vastu`, `critic.cost`, `critic.brief`, `critic.livability`, `critic.coherence`), and `LLM` completions (`LLMRouter.complete`).
- **Entire (`v0.11.4`, `entire-graph v0.4.0`, `entire-brain v0.1.0`)**:
  - Repository: `https://github.com/shreyasmandem/neathack-AtriArch`
  - Every milestone commit on `main` is linked to a persistent `Entire-Checkpoint` under `refs/entire/checkpoints/<shard>/<ULID>` and `refs/heads/entire/checkpoints/v1` with session transcripts, token telemetry, line attributions, and structured architectural learnings.
  - Continuous Memory indexed via `entire-graph` and `entire-brain` across 125 files, 2,862 symbols, and 12,985 relations.
- **CFO.ai**:
  - Pending unit-economics and pricing/runway model integration for the final submission package.

## Build Log

### 2026-10-10 13:07 IST — Core Multi-Agent Platform & Analytical Engines (`2afbef6`)
- **Completed**: Built core domain models (`ClientBrief`, `FloorPlan`, `Room`, `Wall`, `Opening`), evolutionary slicing-tree layout generator (`layout.py`), solar/daylight engine (`daylight.py`), natural ventilation network (`ventilation.py`), acoustic privacy, 16-zone Vastu Shastra Purusha Mandala engine (`vastu/engine.py`), CPWD DAR + Monte Carlo cost estimator (`cost/estimator.py`), 13-agent committee (`critics.py`), and Pareto + Borda consensus (`consensus.py`).
- **Evidence**: Checkpoint `01M4JBXBWR4S86CEH896EBHP01` (`2afbef6`).

### 2026-10-10 15:31 IST — Vector CAD Drawings, Interior Solver & 3D Export (`19b979c`)
- **Completed**: Added architectural SVG renderer (`floorplan_svg.py`), DXF R2010 CAD writer (`dxf.py`), constrained furniture placement solver (`interior/planner.py`), procedural 3D building massing with glTF 2.0 / Wavefront OBJ exporters (`arch3d.py`), FastAPI routers, and React frontend.
- **Failure & Fix**: Scoped CSS selectors in SVG `<style>` blocks were stripped by strict SVG viewers; inlined presentation attributes on every SVG primitive.
- **Evidence**: Checkpoint `01M4JM5ST0FAC4131EFGEQDX02` (`19b979c`).

### 2026-10-10 17:58 IST — Manager-Worker Consensus Negotiation & NBC 2016 RAG (`ef7dfb7`)
- **Completed**: Built `ConsensusProtocol` (`protocol.py`) with 5 specialist repair workers (`FenestrationWorker`, `CirculationWorker`, `EnvelopeWorker`, `VastuWorker`, `InteriorWorker`), Vastu 16-zone knowledge graph (`vastu_graph.py`), and BM25 + dense RAG over NBC 2016 / IS 456 / CPWD (`code_rag.py`).
- **Failure & Fix**: Fixed interior circulation deadlocks by carving shared doorway passages and re-measuring all hard/soft constraints before accepting any worker mutation.
- **Evidence**: Checkpoint `01M4JWHZV0EX5SX76D44A2WC03` (`ef7dfb7`).

### 2026-10-10 20:19 IST — Studio Rabbit 3D Atelier & Local Floor-Plan Importer (`1e33a8d`)
- **Completed**: Rebuilt frontend studio with `StudioScene.tsx` (3D rabbit atelier) and `TeamScene.tsx` (13 specialist rabbits around a live drafting table reacting to SSE stage events), plus local deterministic floor-plan importer (`importer.py`) for JSON, SVG, DXF, and raster PNG/JPG plans (`opencv` + `rapidocr`).
- **Failure & Fix**: Morphological closing on raster plans bridged doorway gaps when kernel exceeded 15 px; capped closing kernel at `max(3, min(11, wall_px))`.
- **Evidence**: Checkpoint `01M4K4NDK81N2C162HRF0AAJ04` (`1e33a8d`), 23 importer tests passing (`tests/test_import.py`).

### 2026-10-10 22:47 IST — 3D Presentation Architecture & Environmental Ribbons (`2bbc288`)
- **Completed**: Upgraded 3D massing (`arch3d.py`, `viewer3d.js`) with room-category tint palettes, glazed window casements, hip/parapet roofs, interactive floor peeling, sun-path arc, and live natural ventilation ribbons.
- **Evidence**: Checkpoint `01M4KD31H041T5GR93K73SJH05` (`2bbc288`).

### 2026-10-11 01:12 IST — Pre-Search Programme Feasibility Gate & Locked Stair Carve (`6f57cf2`)
- **Completed**: Audited generated plans (`scripts/plan_audit.py`) and built pre-search `feasibility.py` gate (add floor -> drop optional rooms -> shrink to furnishable minimums -> raise HTTP 422 `InfeasibleBriefError`), locked dog-leg staircase (`2.4 x 4.5 m`) across floors, room aspect-ratio caps, and plot-filling luxury growth for generous sites.
- **Verification**: 19 new tests in `tests/test_feasibility.py` and 45 engine tests in `tests/test_engines.py` passing.
- **Evidence**: Checkpoint `01M4KNDCZ09NSDZPN218ZZDE06` (`6f57cf2`).

### 2026-10-11 01:55–02:57 IST — Entire Continuous Memory & Neatlogs Agent Tracing (`aa52ca3` & current)
- **Completed**:
  - Enabled **Entire CLI (`v0.11.4`)**, **Entire Graph (`v0.4.0`)**, and **Entire Brain (`v0.1.0`)** (`AGENTS.md`, `CLAUDE.md`, `.entire/agent-guide.md`, `.entire/graph-agent.md`).
  - Integrated **Neatlogs (`neatlogs>=1.4`, `neatlogs-cli@0.2.0`)** in `backend/aip/core/telemetry.py`, instrumenting `DesignPipeline.run` (`WORKFLOW`), pipeline stages (`CHAIN`), RAG retrieval (`RETRIEVER`), all 13 committee critics (`AGENT`), and `LLMRouter.complete` (`LLM`).
  - Verified live trace ingestion (`POST https://ingest.neatlogs.com/v1/traces` HTTP 200, trace `bb02dc4d2a6a4265`) and hermetic span-hierarchy test (`tests/test_telemetry.py` passing).

## Demo
- **Local run instructions**:
  1. Ensure `.env` at repo root has `NEATLOGS_API_KEY` and `NEATLOGS_PROJECT_ID` (gitignored).
  2. Start the backend + studio server:
     ```bash
     cd backend
     .venv/Scripts/python -m uvicorn aip.api.app:app --host 127.0.0.1 --port 8000
     ```
  3. Open `http://127.0.0.1:8000` to launch the 3D Studio Rabbit atelier, submit a brief or upload a DXF/SVG/PNG plan, watch the 13-agent committee negotiate in real time, and inspect the resulting traces in Neatlogs and checkpoints in Entire.

## Known Limitations & Next Steps
- Free-tier cloud LLM providers (Groq/OpenRouter) can hit per-minute rate limits during parallel 13-critic fan-out; `LLMRouter` automatically circuit-breaks rate-limited providers and falls back to deterministic analytical scoring while recording degraded status on the Neatlogs `LLM` span.
- Complete CFO.ai pricing, unit-economics, cost, and runway model and attach to the final submission.

## Submission Checklist
- [x] **Neatlogs**: `neatlogs-cli@0.2.0` installed, Python SDK (`neatlogs>=1.4`) integrated across `WORKFLOW`, `AGENT`, `RETRIEVER`, `CHAIN`, and `LLM` spans, live traces verified on project `467f83ee-e953-4b72-aa4a-2831318be004`.
- [x] **Entire**: Checkpoints (`refs/entire/checkpoints/*`), `entire-graph`, and `entire-brain` active and synced to `https://github.com/shreyasmandem/neathack-AtriArch`.
- [ ] **CFO.ai**: Pricing, cost per design run, revenue, and runway model to be added before final demo submission.
