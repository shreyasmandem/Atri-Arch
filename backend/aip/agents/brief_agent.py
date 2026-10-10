"""The brief agent: a conversation that ends in a brief the generator can build.

A client does not fill in forms. They say "a 30 by 40 north-facing plot, three
bedrooms, a pooja room, parking, and a balcony off the master bedroom upstairs,
earthy colours", and expect to be understood - and to be asked about what they
left out rather than silently given a default.

Each turn this agent:

1. reads the message with a deterministic parser (plot sizes in feet or
   metres, "3BHK", "G+1", road direction, Vastu, rooms pinned to floors,
   balconies attached to rooms, amenities, colours) - so it works with no
   model at all;
2. asks a language model for the same structure, for everything phrasing
   rules miss, and merges it over the parse (the model never overrides a
   number the rules read unambiguously);
3. works out what is still missing that would change the design (plot,
   road side, floors, bedrooms) and asks for it - two questions at most, each
   with quick answers - unless the client says to go ahead;
4. replies in a sentence or two, saying back what it understood.

The same agent revises a finished design: given the brief behind it and an
instruction ("make the kitchen bigger", "add a balcony to the master
bedroom", "move the puja to the north-east"), it returns the changed brief and
a list of what changed.
"""

from __future__ import annotations

import json
import re
from typing import Any

from aip.core.logging import get_logger

logger = get_logger("aip.agents.brief")

FT = 0.3048

ROOMS = {
    "master bedroom": "master_bedroom", "master": "master_bedroom", "guest room": "guest_bedroom",
    "guest bedroom": "guest_bedroom", "kids room": "children_bedroom", "kids bedroom": "children_bedroom",
    "children's room": "children_bedroom", "bedroom": "bedroom", "living room": "living", "living": "living",
    "hall": "living", "drawing room": "drawing", "family room": "family", "family lounge": "family",
    "dining": "dining", "kitchen": "kitchen", "pantry": "pantry", "utility": "utility", "laundry": "laundry",
    "study": "study", "office": "home_office", "home office": "home_office", "library": "library",
    "pooja": "puja", "puja": "puja", "prayer room": "puja", "mandir": "puja", "store": "store",
    "storeroom": "store", "gym": "gym", "home theatre": "home_theatre", "home theater": "home_theatre",
    "theatre": "home_theatre", "balcony": "balcony", "terrace": "terrace", "verandah": "verandah",
    "veranda": "verandah", "sit-out": "verandah", "sitout": "verandah", "porch": "verandah",
    "courtyard": "courtyard", "garage": "garage", "car parking": "garage", "parking": "garage",
    "servant room": "servant", "maid room": "servant", "bathroom": "bathroom", "toilet": "toilet",
    "powder room": "powder",
}
AMENITY = {"puja": "pooja", "garage": "parking", "study": "study", "utility": "utility", "balcony": "balcony",
           "dining": "dining", "courtyard": "courtyard", "verandah": "verandah", "gym": "gym",
           "home_theatre": "home theatre", "home_office": "study", "terrace": "terrace"}
DIRS = {"north east": "NE", "north-east": "NE", "northeast": "NE", "north west": "NW", "north-west": "NW",
        "northwest": "NW", "south east": "SE", "south-east": "SE", "southeast": "SE", "south west": "SW",
        "south-west": "SW", "southwest": "SW", "north": "N", "south": "S", "east": "E", "west": "W"}
STYLES = {"modern": "modern_minimal", "minimal": "modern_minimal", "contemporary": "contemporary",
          "kerala": "kerala_vernacular", "chettinad": "chettinad", "traditional": "traditional_indian",
          "scandinavian": "scandinavian", "japandi": "japandi", "industrial": "industrial",
          "tropical": "tropical_modern", "biophilic": "biophilic", "mid century": "mid_century_modern",
          "haveli": "rajasthani_haveli", "colonial": "indo_saracenic"}
FLOOR_WORDS = {"ground": 0, "first": 1, "second": 2, "third": 3, "top": -1, "upstairs": 1, "upper": 1, "downstairs": 0}
GO_AHEAD = re.compile(r"\b(go ahead|you decide|your call|anything|doesn'?t matter|no preference|just design|surprise me|proceed|start)\b")

ESSENTIAL = ("plot", "road_direction", "levels", "bedrooms")
QUESTIONS = {
    "plot": ("What size is the plot?", ["30 x 40 ft", "40 x 60 ft", "12 x 18 m", "60 x 80 ft"]),
    "road_direction": ("Which side does the road run along?", ["North", "East", "South", "West"]),
    "levels": ("How many floors?", ["Ground only", "G+1", "G+2", "G+3"]),
    "bedrooms": ("How many bedrooms?", ["2", "3", "4", "5"]),
}


def _num(s: str) -> float:
    return float(s.replace(",", ""))


WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8}
ALWAYS = {"living", "dining", "kitchen"}   # every house has these; only placements matter


def parse(text: str) -> dict[str, Any]:
    """What the rules can read with confidence. Keys only for what was said."""
    t = " " + text.lower().replace("×", "x") + " "
    t = re.sub(r"\b(" + "|".join(WORDNUM) + r")\b(?=[\s-]*(?:bhk|bed|bath|floor|storey|stor|level|kids|children|elder|balcon))",
               lambda m: str(WORDNUM[m.group(1)]), t)
    out: dict[str, Any] = {}
    m = re.search(r"(\d{1,3}(?:\.\d+)?)\s*(ft|feet|foot|'|m|mtr|metres?|meters?)?\s*(?:x|by|\*)\s*(\d{1,3}(?:\.\d+)?)\s*(ft|feet|foot|'|m|mtr|metres?|meters?)?", t)
    if m:
        a, b = _num(m.group(1)), _num(m.group(3))
        unit = (m.group(2) or m.group(4) or "").strip()
        if unit in {"ft", "feet", "foot", "'"} or (not unit and min(a, b) >= 25):
            out["plot_unit"] = "ft"
            a, b = a * FT, b * FT
        else:
            out["plot_unit"] = "m"
        out["plot_width"], out["plot_depth"] = round(a, 2), round(b, 2)
    if m := re.search(r"(\d+)\s*(?:bhk|bed\s?rooms?|bedrooms?|br\b)", t):
        out["bedrooms"] = int(m.group(1))
    if m := re.search(r"(\d+)\s*(?:bath\s?rooms?|baths|toilets)", t):
        out["bathrooms"] = int(m.group(1))
    if m := re.search(r"\bg\s*\+\s*(\d)", t):
        out["levels"] = int(m.group(1)) + 1
    elif m := re.search(r"(\d)\s*(?:floors?|storeys?|stories|levels?)\b", t):
        out["levels"] = int(m.group(1))
    elif re.search(r"\b(single[- ]storey|single floor|ground floor only|one floor|bungalow)\b", t):
        out["levels"] = 1
    elif re.search(r"\b(duplex|two[- ]storey|double[- ]storey)\b", t):
        out["levels"] = 2
    for word, d in DIRS.items():
        if re.search(rf"\b{word}[- ]facing\b|\broad (?:on|to|at|along) the {word}\b|\b{word} road\b|\bfacing {word}\b", t):
            out["road_direction"] = d
            break
    if re.search(r"\bno vastu\b|\bignore vastu\b|\bdon'?t care about vastu\b", t):
        out["vastu"] = "ignore"
    elif re.search(r"\bstrict(?:ly)? vastu\b|\bvastu compliant\b|\bfull vastu\b", t):
        out["vastu"] = "strict"
    elif "vastu" in t:
        out["vastu"] = "balanced"
    for word, style in STYLES.items():
        if re.search(rf"\b{word}\b", t):
            out.setdefault("styles", []).append(style)
    if m := re.search(r"(?:budget|cost)[^\d₹]{0,12}(?:₹|rs\.?|inr)?\s*(\d+(?:\.\d+)?)\s*(lakh|lakhs|lac|l\b|crore|cr)", t):
        n = _num(m.group(1))
        out["budget"] = n * (1e7 if m.group(2).startswith("cr") else 1e5)
    if m := re.search(r"(\d+)\s*(?:elders?|grandparents?|senior|parents)", t):
        out["occupant_elders"] = int(m.group(1))
    elif re.search(r"\b(elderly|grandparents|parents|senior citizens?|in-?laws)\b", t):
        out["occupant_elders"] = 2
    if m := re.search(r"(\d+)\s*(?:kids|children)", t):
        out["occupant_children"] = int(m.group(1))

    # Rooms, and where they go. "a balcony off the master bedroom on the first floor".
    rooms, amen = [], set()
    for clause in re.split(r"[.;,\n]| and | with | plus ", t):
        found = None
        host = None
        # "a balcony off the master bedroom": the balcony is the room, the bedroom its host.
        for extra in ("balcony", "terrace", "sit-out"):
            if re.search(rf"\b{extra}", clause):
                found = ROOMS[extra]
                rest = clause.replace(extra, " ")
                host = next((ROOMS[w] for w in sorted(ROOMS, key=len, reverse=True)
                             if re.search(rf"\b{re.escape(w)}s?\b", rest) and ROOMS[w] not in {"balcony", "terrace"}), None)
                break
        for word in (sorted(ROOMS, key=len, reverse=True) if found is None else []):
            if re.search(rf"\b{re.escape(word)}s?\b", clause):
                found = ROOMS[word]
                break
        if not found or re.search(r"\b(no|without|don'?t want|skip)\b", clause):
            continue
        if found in ("bedroom", "bathroom", "toilet") and not re.search(r"\b(ground|first|second|third|upstairs|downstairs|floor)\b", clause):
            continue                  # counts are read above; only pinned ones matter here
        level = None
        if m := re.search(r"\b(ground|first|second|third|top|upstairs|upper|downstairs)\b", clause):
            level = FLOOR_WORDS[m.group(1)]
        elif m := re.search(r"(?:floor|level)\s*(\d)", clause):
            level = int(m.group(1))
        req: dict[str, Any] = {"type": found}
        if level is not None:
            req["level"] = level
        if m := re.search(r"(\d+)\s*(?:balconies|balcony)", clause):
            req["count"] = int(m.group(1))
        for word, d in DIRS.items():
            if re.search(rf"\b(?:in|on|at|towards?) the {word}\b", clause):
                req["direction"] = d
                break
        if found in ("master_bedroom", "bedroom", "guest_bedroom") and re.search(r"attached|en-?suite", clause):
            req["attached_bathroom"] = True
        if host:
            req["attach_to"] = host
        if found in AMENITY:
            amen.add(AMENITY[found])
        if found in ALWAYS and level is None and "direction" not in req:
            continue
        if level is not None or "direction" in req or found not in AMENITY or found in {"balcony", "courtyard", "garage"}:
            rooms.append(req)
    if rooms:
        out["rooms"] = rooms
    if amen:
        out["amenities"] = sorted(amen)
    # Colour words are kept as the client wrote them; the palette engine reads them.
    colour = [c for c in re.split(r"[.;,\n]| and ", text) if re.search(r"colou?rs?|paint|walls?|tones?|palette|shades?|white|beige|grey|gray|wood|earthy|pastel", c, re.I)]
    if colour:
        out["colours"] = "; ".join(c.strip() for c in colour)[:600]
    if m := re.search(r"\b(?:in|at|located in)\s+([a-z][a-z .]{2,30}?)(?:[,.;]|$| city| area)", t):
        city = m.group(1).strip()
        if city not in {"the", "a", "my", "front", "back"} and not any(w in city for w in ("floor", "bedroom", "north", "south", "east", "west")):
            out["locality"] = city.title()
    return out


SCHEMA_HINT = """Return JSON with only the keys the client actually stated or clearly implied:
plot_width, plot_depth (metres; convert feet x 0.3048), road_direction (N/NE/E/SE/S/SW/W/NW),
levels (1-6), bedrooms, bathrooms, locality, styles (list of: contemporary, modern_minimal,
tropical_modern, kerala_vernacular, traditional_indian, chettinad, scandinavian, japandi,
industrial, biophilic, mid_century_modern, rajasthani_haveli, indo_saracenic), vastu
(ignore/advisory/balanced/strict), budget (INR), occupant_elders, occupant_children,
amenities (list from: pooja, parking, study, utility, balcony, courtyard, verandah, gym,
home theatre, terrace), rooms (list of {type, count, level (0=ground), direction, area,
attached_bathroom}) for any room the client placed on a floor or in a direction or sized,
colours (the client's colour wishes in their words), notes (anything else they asked for)."""


async def llm_parse(text: str, current: dict[str, Any]) -> dict[str, Any]:
    """A model's reading of the same message, or {} if none is reachable."""
    try:
        from aip.core.llm import LLMRouter, system, user

        router = LLMRouter()
        try:
            resp = await router.complete(
                [system("You turn a client's description of the house they want into a structured brief. "
                        "Be literal: never invent a number they did not give. " + SCHEMA_HINT),
                 user(f"Brief so far: {json.dumps(current)}\nClient says: {text}\nJSON:")],
                temperature=0.1, max_tokens=700, json_schema={"type": "object"})
        finally:
            await router.aclose()
        raw = resp.text.strip()
        raw = raw[raw.find("{"): raw.rfind("}") + 1]
        data = json.loads(raw) if raw else {}
        return data if isinstance(data, dict) and not getattr(resp, "degraded", False) else {}
    except Exception as exc:  # noqa: BLE001 - the rules still answer
        logger.info("brief.llm_unavailable %s", exc)
        return {}


def merge(base: dict[str, Any], *layers: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for layer in layers:
        for k, v in layer.items():
            if v in (None, "", [], {}):
                continue
            if k == "rooms":
                seen = {(r.get("type"), r.get("level")) for r in out.get("rooms", [])}
                out["rooms"] = list(out.get("rooms", [])) + [r for r in v if (r.get("type"), r.get("level")) not in seen]
            elif k in ("amenities", "styles"):
                out[k] = sorted(set(out.get(k, [])) | set(v))
            elif k == "colours" and out.get("colours"):
                out[k] = f"{out['colours']}; {v}"[:600]
            else:
                out[k] = v
    return out


def missing(brief: dict[str, Any]) -> list[str]:
    need = []
    if not brief.get("plot_width"):
        need.append("plot")
    for k in ESSENTIAL[1:]:
        if not brief.get(k):
            need.append(k)
    return need


def _summary(b: dict[str, Any]) -> str:
    bits = []
    if b.get("plot_width"):
        w, d = b["plot_width"], b["plot_depth"]
        if b.get("plot_unit") == "ft":
            bits.append(f"a {round(w / FT)} × {round(d / FT)} ft plot ({w:.1f} × {d:.1f} m)")
        else:
            bits.append(f"a {w:g} × {d:g} m plot")
    if b.get("road_direction"):
        bits.append(f"road on the {b['road_direction']}")
    if b.get("levels"):
        bits.append({1: "ground floor only", 2: "G+1", 3: "G+2", 4: "G+3"}.get(b["levels"], f"{b['levels']} floors"))
    if b.get("bedrooms"):
        bits.append(f"{b['bedrooms']} bedrooms")
    for r in b.get("rooms", []):
        if r.get("level") is not None or r.get("direction"):
            where = (["ground floor", "first floor", "second floor", "third floor"][r["level"]] if isinstance(r.get("level"), int) and 0 <= r["level"] < 4 else "")
            bits.append(f"{r['type'].replace('_', ' ')}{' on the ' + where if where else ''}{' in the ' + r['direction'] if r.get('direction') else ''}")
    if b.get("amenities"):
        bits.append(", ".join(a for a in b["amenities"]))
    return "; ".join(bits)


def apply_defaults(b: dict[str, Any]) -> dict[str, Any]:
    out = dict(b)
    out.setdefault("plot_width", 12.0)
    out.setdefault("plot_depth", 18.0)
    out.setdefault("road_direction", "N")
    out.setdefault("levels", 2 if out.get("bedrooms", 3) >= 3 else 1)
    out.setdefault("bedrooms", 3)
    out.setdefault("bathrooms", out["bedrooms"])
    return out


CHAT_SYSTEM = """You are Atri, the lead architect of a residential design studio in India, talking with a client who wants a house designed. You are warm, sharp and brief - like a good architect on a first call, never like a form or a chatbot.

Each turn you do two things:
1. Understand what the client said, in whatever language or mix of languages they use (English, Hindi, Hinglish, Tamil, Telugu, Kannada, Malayalam, Marathi, Bengali, Gujarati, anything) and however they phrase it, and record every concrete requirement in the brief.
2. Reply in the language and script of the client's latest message (romanised Kannada or Hindi gets romanised Kannada or Hindi back), in one to three short sentences: acknowledge the specific things they asked for (not a recap of everything), offer one useful architectural observation when you have a real one (for example how a courtyard helps a deep plot, or why a north road suits the living room), and ask about at most two things that are still missing and would change the design.

Essentials that must be known before designing: plot size, which side the road is on, number of floors, number of bedrooms. Ask for those first, one or two at a time, never all at once. Everything else (bathrooms, Vastu, style, budget, colours) has sensible defaults - do not interrogate. If the client says to go ahead or that you can decide, assume only the defaults (bathrooms equal to bedrooms, balanced Vastu, contemporary style) and say so in a few words. Never add a room or amenity the client did not ask for - parking, a lounge, a gym are theirs to request.

Plot sizes in India are usually given in feet ("30x40", "40 by 60") - convert to metres (x 0.3048). Small numbers like "12x18" are usually metres. "G+1" means 2 floors. "3BHK" means 3 bedrooms. "East facing" means the road is on the east.

Never invent a number the client did not give. Never claim to have started designing - the studio starts when they press the button.

Return only JSON:
{
 "reply": "your message to the client, in their language",
 "updates": {only the brief fields this message set or changed:
   "plot_width": metres, "plot_depth": metres, "plot_unit": "ft" or "m" (as the client gave it),
   "road_direction": "N"|"NE"|"E"|"SE"|"S"|"SW"|"W"|"NW", "levels": 1-6, "bedrooms": int, "bathrooms": int,
   "locality": "city, state", "vastu": "ignore"|"advisory"|"balanced"|"strict",
   "styles": [from contemporary, modern_minimal, tropical_modern, kerala_vernacular, traditional_indian, chettinad, scandinavian, japandi, industrial, biophilic, mid_century_modern, rajasthani_haveli, indo_saracenic],
   "budget": rupees, "occupant_elders": int, "occupant_children": int,
   "amenities": [from pooja, parking, study, utility, balcony, courtyard, verandah, gym, home theatre, terrace, store, family lounge, library, servant room],
   "rooms": [{"type": a room type such as master_bedroom, bedroom, guest_bedroom, children_bedroom, kitchen, living, dining, puja, study, balcony, terrace, courtyard, verandah, garage, gym, home_theatre, store, utility, bathroom,
              "level": 0 for ground, 1 for first..., "direction": compass quarter, "area": m2, "attach_to": room type it opens off, "scale": 1.3 for bigger / 0.8 for smaller}] - only rooms the client placed, sized or attached. A balcony off the master bedroom upstairs is {"type": "balcony", "level": 1, "attach_to": "master_bedroom"},
   "remove": [room types the client does not want],
   "colours": "the client's colour wishes in their words",
   "notes": "anything else they want that fits nowhere above"},
 "questions": [{"key": "plot"|"road_direction"|"levels"|"bedrooms"|"other", "text": "the question, in their language", "options": ["2-5 short one-tap answers, in their language"]}],
 "go_ahead": true if they told you to proceed or decide yourself
}"""


async def llm_turn(message: str, brief: dict[str, Any], history: list[dict[str, str]]) -> dict[str, Any] | None:
    """The conversation turn, by a language model; None if none is reachable."""
    try:
        from aip.core.llm import LLMRouter, assistant, system, user
        from aip.core.providers import Capability

        msgs = [system(CHAT_SYSTEM + f"\n\nThe brief so far: {json.dumps(brief, ensure_ascii=False)}")]
        for h in history[-12:]:
            text = str(h.get("text", ""))[:2000]
            msgs.append(user(text) if h.get("role") == "user" else assistant(text))
        msgs.append(user(message))
        router = LLMRouter()
        try:
            resp = await router.complete(msgs, capability=Capability.STRUCTURED, temperature=0.3, max_tokens=900,
                                         json_schema={"type": "object"}, latency_sensitive=True)
        finally:
            await router.aclose()
        if getattr(resp, "provider", "") == "offline":
            return None
        raw = resp.text.strip()
        raw = raw[raw.find("{"): raw.rfind("}") + 1]
        data = json.loads(raw) if raw else None
        return data if isinstance(data, dict) and data.get("reply") else None
    except Exception as exc:  # noqa: BLE001 - the rules still answer
        logger.info("brief.chat_llm_unavailable %s", exc)
        return None


_TYPES = {"plot_width": float, "plot_depth": float, "levels": int, "bedrooms": int, "bathrooms": int,
          "budget": float, "occupant_elders": int, "occupant_children": int}


def _clean(updates: dict[str, Any]) -> dict[str, Any]:
    """Keep what a model returned only if it is the right shape."""
    out: dict[str, Any] = {}
    for k, v in (updates or {}).items():
        if v in (None, "", [], {}):
            continue
        try:
            if k in _TYPES:
                v = _TYPES[k](v)
                if k in ("plot_width", "plot_depth") and not 2 < v < 300:
                    continue
                if k == "levels":
                    v = max(1, min(6, v))
            elif k == "road_direction":
                v = str(v).upper().replace("-", "")[:2]
                if v not in {"N", "NE", "E", "SE", "S", "SW", "W", "NW"}:
                    continue
            elif k in ("amenities", "styles", "remove"):
                v = [str(x).lower().replace("_", " ") if k == "amenities" else str(x).lower() for x in v]
            elif k == "rooms":
                v = [r for r in v if isinstance(r, dict) and r.get("type")]
            out[k] = v
        except (TypeError, ValueError):
            continue
    return out


async def converse(message: str, brief: dict[str, Any] | None = None, *, use_llm: bool = True,
                   history: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """One turn: the updated brief, what is still missing, what to ask, and the reply."""
    brief = dict(brief or {})
    rules = parse(message)
    turn = await llm_turn(message, brief, history or []) if use_llm else None
    if turn is not None:
        model = _clean(turn.get("updates") or {})
        # The rules win where they read a number unambiguously (a model can
        # slip a unit); the model carries everything else, in any language.
        for k in ("plot_width", "plot_depth", "plot_unit", "bedrooms", "levels"):
            if k in rules:
                model[k] = rules[k]
        merged = merge(brief, model)
        if model.get("remove"):
            merged["remove"] = sorted(set(brief.get("remove", [])) | set(model["remove"]))
        need = missing(merged)
        if (turn.get("go_ahead") or GO_AHEAD.search(message.lower())) and need:
            merged = apply_defaults(merged)
            need = []
        questions = [q for q in (turn.get("questions") or []) if isinstance(q, dict) and q.get("text")][:2]
        if need and not questions:
            questions = [{"key": k, "text": QUESTIONS[k][0], "options": QUESTIONS[k][1]} for k in need[:2]]
        if not need:
            questions = [q for q in questions if q.get("key") == "other"][:1]
        return {"brief": merged, "missing": need, "questions": questions, "ready": not need,
                "reply": str(turn["reply"]).strip(), "by": "model"}
    # No model reachable: the rules, with a plain reply.
    merged = merge(brief, rules)
    need = missing(merged)
    if GO_AHEAD.search(message.lower()) and need:
        merged = apply_defaults(merged)
        need = []
    questions = [{"key": k, "text": QUESTIONS[k][0], "options": QUESTIONS[k][1]} for k in need[:2]]
    heard = _summary(rules) if rules else ""
    if questions:
        reply = (f"Noted - {heard}. " if heard else "") + " ".join(q["text"] for q in questions)
    else:
        reply = "That's everything I need. Press Start designing when you're ready, or tell me anything else you'd like."
    return {"brief": merged, "missing": need, "questions": questions, "ready": not need, "reply": reply, "by": "rules"}


async def revise(instruction: str, brief: dict[str, Any], *, use_llm: bool = True) -> dict[str, Any]:
    """Change a finished design's brief from a sentence; say what changed."""
    before = dict(brief)
    rules = parse(instruction)
    t = instruction.lower()
    after = merge(before, rules)
    changes: list[str] = []
    # Relative edits the parser cannot express as values.
    for word in sorted(ROOMS, key=len, reverse=True):
        if word in t:
            kind = ROOMS[word]
            if re.search(r"\b(bigger|larger|more space|spacious|increase)\b", t):
                after.setdefault("rooms", []).append({"type": kind, "scale": 1.3})
                changes.append(f"{kind.replace('_', ' ')} enlarged")
            elif re.search(r"\b(smaller|reduce|compact)\b", t):
                after.setdefault("rooms", []).append({"type": kind, "scale": 0.8})
                changes.append(f"{kind.replace('_', ' ')} reduced")
            if re.search(r"\b(remove|no|drop|delete|without)\b", t):
                after["rooms"] = [r for r in after.get("rooms", []) if r.get("type") != kind]
                after["amenities"] = [a for a in after.get("amenities", []) if a != AMENITY.get(kind)]
                after.setdefault("remove", []).append(kind)
                changes.append(f"{kind.replace('_', ' ')} removed")
            break
    if use_llm and not changes and not rules:
        model = await llm_parse(instruction, before)
        after = merge(after, model)
    for k in ("plot_width", "plot_depth", "road_direction", "levels", "bedrooms", "bathrooms", "vastu", "styles", "colours"):
        if after.get(k) != before.get(k) and after.get(k) not in (None, []):
            changes.append(f"{k.replace('_', ' ')}: {before.get(k, '-')} → {after[k]}")
    added = [r for r in after.get("rooms", []) if r not in before.get("rooms", []) and "scale" not in r]
    changes += [f"{r['type'].replace('_', ' ')} added" + (f" on level {r['level']}" if r.get("level") is not None else "") for r in added]
    return {"brief": after, "changes": changes or ["no change understood - try naming a room and what to do with it"],
            "understood": bool(changes)}


def to_request(brief: dict[str, Any]) -> dict[str, Any]:
    """The conversation's brief as the fields of `SimpleBriefRequest`."""
    keep = ("plot_width", "plot_depth", "road_direction", "levels", "bedrooms", "bathrooms", "locality", "styles",
            "vastu", "budget", "occupant_elders", "occupant_children", "amenities", "notes", "setback_front",
            "setback_rear", "setback_left", "setback_right", "latitude", "longitude")
    out = {k: brief[k] for k in keep if brief.get(k) not in (None, "", [])}
    out.setdefault("bathrooms", brief.get("bedrooms", 3))
    extra = []
    for r in brief.get("rooms", []):
        x = {"type": r["type"]}
        for k in ("count", "level", "direction", "area", "attached_bathroom", "scale", "attach_to"):
            if r.get(k) not in (None, ""):
                x[k] = r[k]
        extra.append(x)
    if extra:
        out["extra_rooms"] = extra
    if brief.get("remove"):
        out["remove_rooms"] = sorted(set(brief["remove"]))
    if brief.get("colours"):
        out["notes"] = (out.get("notes", "") + f" Colours: {brief['colours']}").strip()[:4000]
    return out
