"""The exterior designer: a specialist agent for the outside of the house.

The plan decides the rooms; this agent decides how the house meets the
street. It works in the exterior grammar (`engines/experience/exteriors.py`)
- roof, ground-floor skin, upper-floor skin, street screen, window treatment,
planters and accent - so whatever it proposes can be built, and it composes
from what the client actually said ("super-modern and unique", "traditional
with a tiled roof", "lots of wood", "earthy colours") together with the
plan's style, the climate and the plot.

It proposes a set of distinct designs, each with a name and a one-line idea,
best first. Without a model it falls back to the grammar's own style-aware
generator, so the 3D view always has designs to cycle through.
"""

from __future__ import annotations

import json
from typing import Any

from aip.core.logging import get_logger
from aip.domain.plan import FloorPlan
from aip.engines.experience.exteriors import (
    ACCENTS,
    BASES,
    FEATURES,
    ROOFS,
    SCREENS,
    UPPERS,
    WINDOWS,
    Exterior,
    generate,
    prefer_from_text,
    with_style_details,
)

logger = get_logger("aip.agents.exterior")

_CACHE: dict[tuple[str, str], list[dict[str, Any]]] = {}

SYSTEM = f"""You are the exterior designer in an Indian residential architecture studio. You design how a house meets the street: distinctive, buildable, never generic.

You compose each design from this grammar - use only these values:
- roof: {", ".join(ROOFS)}  (flat = parapet roof terrace; slab = thin cantilevered roof plate; mono = single pitch over a clerestory; butterfly; hip = tiled hipped roof on deep eaves; gable)
- base (ground-floor skin): {", ".join(BASES)}
- upper (upper-floor skin): {", ".join(UPPERS)}
- screen (street face of the upper floor): {", ".join(SCREENS)}
- windows: {", ".join(WINDOWS)}  (band = continuous dark glazing band per floor)
- planters: true/false
- accent (colour of frame, fins or screen): {", ".join(ACCENTS)}
- feature (the signature element): {", ".join(FEATURES)}  (jharokha = projecting bay windows on brackets; colonnade = posts and a verandah roof along the front; chhatri = roof pavilions, flat roofs only; cornice = deep floor cornices; breeze = breeze-block screen; greenwall = planted wall; balcony = cantilevered balcony; arcade = arches along the front; portico = double-height columns at the door; bay = projecting box window; floatbox = deep framed box floating off the upper floor; featurewall = full-height monolith wall; thinnai = raised south-Indian verandah platforms by the door; bangla = curved-roof pavilion on a flat roof; pergolaframe = double-height timber pergola; cornerglass = glazed upper corner. Columns, arches and canopies are drawn in the design's own character, so pick materials and roof that suit the element)

Design for the client's words first, then the house style - stay in the style's own vocabulary (a haveli has jharokhas, jaali and sandstone; Kerala has tiled hip roofs on a colonnade; Scandinavian is a timber gable with nothing applied), the climate (hot Indian cities want shade on the west and south: fins, louvres, jaali, deep frames, overhangs) and good taste: one strong idea per design, materials that belong together, no two designs alike.

Return only JSON: {{"designs": [{{"name": "a short evocative name (2-4 words)", "idea": "one sentence on the concept", "roof": ..., "base": ..., "upper": ..., "screen": ..., "windows": ..., "planters": ..., "accent": ..., "feature": ...}}]}} with 8 designs, best first."""


async def design_exteriors(plan: FloorPlan, preferences: str = "", *, use_llm: bool = True) -> list[dict[str, Any]]:
    key = (plan.id, preferences.strip().lower())
    if key in _CACHE:
        return _CACHE[key]
    one_floor = len(plan.levels) <= 1
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    if use_llm:
        try:
            from aip.core.llm import LLMRouter, system, user
            from aip.core.providers import Capability

            context = {
                "style": plan.style, "floors": len(plan.levels), "city": plan.site.locality,
                "road": [d.value for d in plan.site.road_directions],
                "client": preferences or "no stated preference - surprise them, tastefully",
            }
            router = LLMRouter()
            try:
                resp = await router.complete(
                    [system(SYSTEM), user(json.dumps(context))], capability=Capability.STRUCTURED,
                    temperature=0.8, max_tokens=1600, json_schema={"type": "object"}, latency_sensitive=True)
            finally:
                await router.aclose()
            if getattr(resp, "provider", "") != "offline":
                raw = resp.text[resp.text.find("{"): resp.text.rfind("}") + 1]
                for d in (json.loads(raw).get("designs") or [])[:10]:
                    try:
                        ex = Exterior(
                            roof=d["roof"] if d.get("roof") in ROOFS else "flat",
                            base=d["base"] if d.get("base") in BASES else "plaster",
                            upper="plaster" if one_floor else (d["upper"] if d.get("upper") in UPPERS else "plaster"),
                            screen=d["screen"] if d.get("screen") in SCREENS else "none",
                            windows=d["windows"] if d.get("windows") in WINDOWS else "punched",
                            planters=bool(d.get("planters")),
                            accent=d["accent"] if d.get("accent") in ACCENTS else "bronze",
                            feature=d["feature"] if d.get("feature") in FEATURES else "none",
                        )
                    except (KeyError, TypeError):
                        continue
                    ex = with_style_details(ex, plan.style)
                    if ex.id in seen:
                        continue
                    seen.add(ex.id)
                    item = ex.to_dict()
                    item["name"] = str(d.get("name") or item["name"])[:40]
                    item["story"] = str(d.get("idea") or item["story"])[:220]
                    item["by"] = "exterior designer"
                    out.append(item)
        except Exception as exc:  # noqa: BLE001 - the grammar still designs
            logger.info("exterior.llm_unavailable %s", exc)
    for ex in generate(plan, 10, prefer=prefer_from_text(preferences)):
        if len(out) >= 10:
            break
        if ex.id not in seen:
            seen.add(ex.id)
            out.append(ex.to_dict())
    _CACHE[key] = out
    return out
