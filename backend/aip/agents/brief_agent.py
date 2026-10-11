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

import asyncio
import json
import re
from typing import Any

from aip.core.logging import get_logger

logger = get_logger("aip.agents.brief")

FT = 0.3048
#: Seconds a chat turn waits for a model before the rules reply on their own.
CHAT_DEADLINE = 12.0

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
    "powder room": "powder", "garden": "courtyard", "lawn": "courtyard", "open space": "courtyard",
    "open to sky": "courtyard", "open-to-sky": "courtyard", "wash area": "utility", "washing area": "utility",
    "dress": "store", "kitchens": "kitchen",
}
AMENITY = {"puja": "pooja", "garage": "parking", "study": "study", "utility": "utility", "balcony": "balcony",
           "dining": "dining", "courtyard": "courtyard", "verandah": "verandah", "gym": "gym",
           "home_theatre": "home theatre", "home_office": "study", "terrace": "terrace"}
#: Rooms a house type list does not name, drawn as the room they behave like
#: and called what the client called them: (behaves like, name, m2, opens off).
NAMED = {
    "gaming room": ("home_theatre", "Gaming Room", 13), "game room": ("home_theatre", "Game Room", 13),
    "games room": ("home_theatre", "Games Room", 13), "gaming zone": ("home_theatre", "Gaming Room", 13),
    "gaming": ("home_theatre", "Gaming Room", 13), "media room": ("home_theatre", "Media Room", 16),
    "tv room": ("family", "TV Lounge", 14), "tv lounge": ("family", "TV Lounge", 14),
    "play room": ("study", "Play Room", 12), "playroom": ("study", "Play Room", 12), "play area": ("study", "Play Room", 12),
    "music room": ("study", "Music Room", 12), "art studio": ("study", "Art Studio", 12), "art room": ("study", "Art Room", 11),
    "craft room": ("study", "Craft Room", 10), "hobby room": ("study", "Hobby Room", 11), "studio": ("study", "Studio", 12),
    "spare room": ("study", "Spare Room", 10), "reading room": ("library", "Reading Room", 10),
    "reading nook": ("library", "Reading Nook", 7), "yoga room": ("gym", "Yoga Room", 12), "yoga": ("gym", "Yoga Room", 12),
    "meditation room": ("gym", "Meditation Room", 9), "meditation": ("gym", "Meditation Room", 9),
    "home bar": ("family", "Bar Lounge", 14), "bar": ("family", "Bar Lounge", 14), "lounge": ("family", "Lounge", 15),
    "party hall": ("family", "Party Hall", 22), "party room": ("family", "Party Room", 18),
    "walk-in closet": ("store", "Walk-in Closet", 6, "master_bedroom"), "walk in closet": ("store", "Walk-in Closet", 6, "master_bedroom"),
    "walk-in wardrobe": ("store", "Walk-in Wardrobe", 6, "master_bedroom"), "walk in wardrobe": ("store", "Walk-in Wardrobe", 6, "master_bedroom"),
    "dressing room": ("store", "Dressing Room", 6, "master_bedroom"), "dressing area": ("store", "Dressing Room", 5, "master_bedroom"),
    "wine cellar": ("store", "Wine Cellar", 6), "cellar": ("store", "Cellar", 8),
    "workshop": ("utility", "Workshop", 9), "tool room": ("utility", "Tool Room", 6), "mud room": ("utility", "Mud Room", 5),
    "mudroom": ("utility", "Mud Room", 5), "pet room": ("utility", "Pet Room", 6), "wet kitchen": ("utility", "Wet Kitchen", 6, "kitchen"),
    "laundry room": ("laundry", "Laundry", 5), "laundry": ("laundry", "Laundry", 5),
    "sauna": ("bathroom", "Sauna", 5), "steam room": ("bathroom", "Steam Room", 5), "spa": ("bathroom", "Spa Bath", 7),
    "swimming pool": ("courtyard", "Pool", 30), "plunge pool": ("courtyard", "Plunge Pool", 14), "pool": ("courtyard", "Pool", 30),
    "kitchen garden": ("courtyard", "Kitchen Garden", 10), "herb garden": ("courtyard", "Herb Garden", 8),
    "deck": ("verandah", "Deck", 10), "patio": ("verandah", "Patio", 10),
    "nursery": ("children_bedroom", "Nursery", 10), "clinic": ("home_office", "Clinic", 14),
    "consulting room": ("home_office", "Consulting Room", 12), "conference room": ("home_office", "Conference Room", 16),
    "office cabin": ("home_office", "Office Cabin", 10), "computer room": ("home_office", "Computer Room", 10),
    "guest suite": ("guest_bedroom", "Guest Suite", 14),
}
#: Words before "room" that are not a room of their own ("more room", "bed room").
_NOT_A_ROOM = {"living", "dining", "bed", "bath", "store", "drawing", "family", "guest", "kids", "master", "prayer",
               "powder", "servant", "maid", "my", "a", "the", "one", "two", "three", "four", "extra", "big", "bigger",
               "small", "smaller", "more", "separate", "each", "every", "own", "this", "that", "any", "other",
               "another", "large", "open", "common", "wash", "utility", "puja", "pooja", "study", "enough", "some",
               "no", "little", "plenty", "ample", "head", "leg", "elbow", "box", "storage", "children", "childrens",
               "children's", "kid", "boys", "girls", "single", "double", "attached", "and", "with", "for", "new"}


def named_room(text: str) -> dict[str, Any] | None:
    """Any room the client names, as the room it behaves like plus its own name:
    "a gaming room" is a media room called Gaming Room, "a pottery room" a study
    called Pottery Room. None if the text names no such room."""
    t = " " + text.lower().replace("_", " ") + " "
    for phrase in sorted(NAMED, key=len, reverse=True):
        if re.search(rf"\b{re.escape(phrase)}s?\b", t):
            kind, label, area, *host = NAMED[phrase]
            r: dict[str, Any] = {"type": kind, "label": label, "area": area}
            if host:
                r["attach_to"] = host[0]
            return r
    for m in re.finditer(r"\b([a-z']+)\s+rooms?\b", t):
        w = m.group(1)
        if w in _NOT_A_ROOM or w in ROOMS or f"{w} room" in ROOMS or len(w) < 3:
            continue
        return {"type": "study", "label": f"{w.title()} Room", "area": 11}
    return None


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

START = re.compile(r"^\s*(yes|yeah|yep|ok|okay|sure|start|begin|go|go ahead|let.?s go|let.?s do it|do it|proceed|haan|ha|chalo|shuru)(?![a-z])")
ESSENTIAL = ("plot", "road_direction", "levels", "bedrooms")
QUESTIONS = {
    "plot": ("What size is the plot?", ["30 x 40 ft", "40 x 60 ft", "12 x 18 m", "60 x 80 ft"]),
    "road_direction": ("Which side does the road run along?", ["North", "East", "South", "West"]),
    "levels": ("How many floors?", ["Ground only", "G+1", "G+2", "G+3"]),
    "bedrooms": ("How many bedrooms?", ["2", "3", "4", "5"]),
}

#: The rules' own reply, for when no model answers, in the languages clients
#: most often write in. Options stay as the rules read them, so a tap parses.
LOCAL = {
    "Hinglish": {"noted": "Theek hai - {}.", "plot": "Plot ka size kya hai?",
                 "road_direction": "Road plot ke kis taraf hai?", "levels": "Kitni manzil chahiye?",
                 "bedrooms": "Kitne bedroom chahiye?",
                 "done": "Sab kuch mil gaya. Taiyaar hon to Start designing dabaiye, ya kuch aur batana ho to bataiye."},
    "Hindi": {"noted": "ठीक है - {}।", "plot": "प्लॉट का साइज़ क्या है?",
              "road_direction": "सड़क प्लॉट के किस तरफ़ है?", "levels": "कितनी मंज़िलें चाहिए?",
              "bedrooms": "कितने बेडरूम चाहिए?",
              "done": "सब कुछ मिल गया। तैयार हों तो Start designing दबाइए, या कुछ और बताना हो तो बताइए।"},
}


def _num(s: str) -> float:
    return float(s.replace(",", ""))


WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8}
ALWAYS = {"living", "dining", "kitchen"}   # every house has these; only placements matter
FLOOR_RE = r"(ground|first|second|third|fourth|top|terrace|\d)"
NEXT_TO = r"\b(?:next to|beside|adjacent to|adjoining|near|attached to|connected to|opening (?:in)?to|off|by) (?:the |a |my )?"
VOCAB = sorted({w for k in ROOMS for w in k.split()} | set(FLOOR_WORDS) | {w.replace("-", " ") for k in DIRS for w in k.split()}
               | {"floor", "facing", "road", "plot", "bedrooms", "bathrooms", "garden", "vastu", "storey"})


#: Hindi the rules can read, in Devanagari and in Latin letters, as the English
#: they already parse ("दो मंज़िल" -> "two floor", "teen bedroom" -> "three bedroom").
HINDI = {
    "बेडरूम": "bedroom", "बेड रूम": "bedroom", "बाथरूम": "bathroom", "मंज़िलें": "floors", "मंजिलें": "floors",
    "मंज़िल": "floor", "मंजिल": "floor", "एक": "one", "दो": "two", "तीन": "three", "चार": "four", "पांच": "five",
    "पाँच": "five", "उत्तर": "north", "दक्षिण": "south", "पूर्व": "east", "पश्चिम": "west", "सड़क": "road",
    "रोड": "road", "गैरेज": "garage", "पार्किंग": "parking", "रसोई": "kitchen", "किचन": "kitchen", "पूजा": "puja",
    "बालकनी": "balcony", "फीट": "ft", "फुट": "ft", "मीटर": "m", "प्लॉट": "plot", "वास्तु": "vastu",
    "बगीचा": "garden", "आंगन": "courtyard", "स्टडी": "study", "लिविंग": "living", "डाइनिंग": "dining",
    "ड्राइंग रूम": "drawing room", "बच्चों": "children", "माता-पिता": "parents", "दादा-दादी": "grandparents",
}
HINGLISH = {"teen": "three", "char": "four", "paanch": "five", "panch": "five", "manzil": "floor",
            "manzile": "floors", "manzilein": "floors", "uttar": "north", "dakshin": "south", "purab": "east",
            "paschim": "west", "sadak": "road", "rasoi": "kitchen", "bagicha": "garden", "aangan": "courtyard"}


def _hindi(t: str) -> str:
    for w in sorted(HINDI, key=len, reverse=True):
        t = t.replace(w, f" {HINDI[w]} ")
    t = t.translate(str.maketrans("०१२३४५६७८९", "0123456789"))
    t = re.sub(r"\b(" + "|".join(HINGLISH) + r")\b", lambda m: HINGLISH[m.group(1)], t)
    # "do" is Hindi for two only before what is counted ("do manzil", "do bedroom").
    return re.sub(r"\bdo(?=\s+(?:floors?|bedrooms?|bhk|bathrooms?|balcon))", "two", t)


def _spell(t: str) -> str:
    """Mend typing slips on the words that matter ("tuility", "gardern", "groun",
    "secnd", "bathrom") - only ever to a room, floor or direction word."""
    import difflib

    def fix(m: re.Match) -> str:
        w = m.group(0)
        if len(w) < 5 or w in VOCAB or w.rstrip("s") in VOCAB or w[:-2] in VOCAB or w[:-3] + "y" in VOCAB:
            return w
        hit = difflib.get_close_matches(w, VOCAB, n=1, cutoff=0.84)
        return hit[0] if hit else w
    return re.sub(r"[a-z]+", fix, t)


def _counted(t: str) -> tuple[list[dict[str, Any]], str]:
    """Rooms asked for by number - "2 kitchens, one on the ground and one on the
    second", "three balconies" - each placed where the client said. Returns the
    rooms and the text with those phrases blanked, so they are not read twice."""
    out: list[dict[str, Any]] = []
    names = {w: w for w in ROOMS if ROOMS[w] not in {"bedroom", "bathroom", "toilet", "master_bedroom"}}
    names |= {w[:-1] + "ies": w for w in list(names) if w.endswith("y")}       # balconies, studies
    words = "|".join(re.escape(w) for w in sorted(names, key=len, reverse=True))
    pat = re.compile(rf"\b(\d+|{'|'.join(WORDNUM)})\s+(?:separate |more |extra |different )?({words})(?:e?s)?\b")
    for m in list(pat.finditer(t)):
        n = int(m.group(1)) if m.group(1).isdigit() else WORDNUM[m.group(1)]
        if not 1 <= n <= 8:
            continue
        kind = ROOMS[names[m.group(2)]]
        tail = t[m.end(): m.end() + 140]
        stop = re.search(r"[.;\n]|\b\d+\s*(?:bed|bath)", tail)
        tail = tail[: stop.start()] if stop else tail
        found_at = list(re.finditer(rf"\b(one|two|three|four|\d|another|the other|other|second one|the second one)\s+(?:is |are )?(?:on|in|at|for)?\s*(?:the\s+)?{FLOOR_RE}", tail))
        levels = []
        for x in found_at:
            q = int(x.group(1)) if x.group(1).isdigit() else WORDNUM.get(x.group(1), 1)
            lv = int(x.group(2)) if x.group(2).isdigit() else FLOOR_WORDS.get(x.group(2))
            levels += [lv] * q
        levels = [(-1 if x == "terrace" else x) for x in levels if x is not None]
        if found_at:
            span = found_at[-1].end()       # blank only the placing phrases, not what follows
            t = t[: m.end()] + " " * span + t[m.end() + span:]
        for k in range(n):
            r: dict[str, Any] = {"type": kind}
            if k < len(levels) and levels[k] is not None and levels[k] >= 0:
                r["level"] = levels[k]
            out.append(r)
        t = t[: m.start()] + " " * (m.end() - m.start()) + t[m.end():]
    # "one more kitchen", collapsed: same type and floor become one entry with a count.
    merged: list[dict[str, Any]] = []
    for r in out:
        same = next((x for x in merged if x["type"] == r["type"] and x.get("level") == r.get("level")), None)
        if same:
            same["count"] = same.get("count", 1) + 1
        else:
            merged.append(r)
    return merged, t


def parse(text: str) -> dict[str, Any]:
    """What the rules can read with confidence. Keys only for what was said."""
    t = " " + _hindi(text.lower().replace("×", "x")) + " "
    t = re.sub(r"\b(" + "|".join(WORDNUM) + r")\b(?=[\s-]*(?:bhk|bed|bath|floor|storey|stor|level|kids|children|elder|balcon))",
               lambda m: str(WORDNUM[m.group(1)]), t)
    t = _spell(t)
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
        if re.search(rf"\b{word}[- ]facing\b|\broad (?:on|to|at|along) the {word}\b|\b{word} road\b|\bfacing {word}\b"
                     rf"|\b{word}\s+(?:mein|me|में|par|pe|ki taraf|side)\s+road\b|\broad\s+{word}\b", t):
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
    counted, t = _counted(t)
    for r in counted:
        rooms.append(r)
        if r["type"] in AMENITY:
            amen.add(AMENITY[r["type"]])
    for clause in re.split(r"[.;,\n&+]| and | aur | evam | tatha | with | plus | also | along with | saath mein | ke saath ", t):
        found = None
        host = None
        named = named_room(clause)
        if named:
            found, host = named["type"], named.get("attach_to")
        # "a balcony off the master bedroom": the balcony is the room, the bedroom its host.
        for extra in (() if named else ("balcony", "terrace", "sit-out")):
            if re.search(rf"\b{extra}", clause):
                found = ROOMS[extra]
                rest = clause.replace(extra, " ")
                host = next((ROOMS[w] for w in sorted(ROOMS, key=len, reverse=True)
                             if re.search(rf"\b{re.escape(w)}s?\b", rest) and ROOMS[w] not in {"balcony", "terrace"}), None)
                break
        if found is None and not named:
            # The room the clause is about is the first one it names
            # ("a utility next to the kitchen" is about the utility).
            hits = [(m.start(), -len(w), w) for w in ROOMS for m in [re.search(rf"\b{re.escape(w)}s?\b", clause)] if m]
            if hits:
                found = ROOMS[min(hits)[2]]
        if not found or re.search(r"\b(no|without|don'?t want|skip)\b", clause):
            continue
        if found in ("bedroom", "bathroom", "toilet") and not named and not re.search(r"\b(ground|first|second|third|upstairs|downstairs|floor)\b", clause):
            continue                  # counts are read above; only pinned ones matter here
        level = None
        if m := re.search(r"\b(ground|first|second|third|top|upstairs|upper|downstairs)\b", clause):
            level = FLOOR_WORDS[m.group(1)]
        elif m := re.search(r"(?:floor|level)\s*(\d)", clause):
            level = int(m.group(1))
        req: dict[str, Any] = {"type": found}
        if named:
            req["label"], req["area"] = named["label"], named["area"]
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
        elif m := re.search(NEXT_TO + r"(" + "|".join(re.escape(w) for w in sorted(ROOMS, key=len, reverse=True)) + r")s?\b", clause):
            if ROOMS[m.group(1)] != found:
                req["attach_to"] = ROOMS[m.group(1)]
        if named:
            if not any(r.get("label") == req["label"] and r.get("level") == req.get("level") for r in rooms):
                rooms.append(req)
            continue            # its own room, not the amenity it behaves like
        if found in AMENITY:
            amen.add(AMENITY[found])
        if found in ALWAYS and level is None and "direction" not in req and "attach_to" not in req:
            continue
        if req in rooms or (found == "courtyard" and len(req) == 1 and any(r.get("type") == "courtyard" for r in rooms)):
            continue            # said twice ("a garden, an open space") is asked once
        if (level is not None or "direction" in req or "attach_to" in req or found not in AMENITY
                or found in {"balcony", "courtyard", "garage"}):
            rooms.append(req)
    if rooms:
        out["rooms"] = rooms
    if amen:
        out["amenities"] = sorted(amen)
    # Colour words are kept as the client wrote them; the palette engine reads them.
    colour = [c for c in re.split(r"[.;,\n]| and ", text) if re.search(r"colou?rs?|paint|walls?|tones?|palette|shades?|white|beige|grey|gray|wood|earthy|pastel", c, re.I)]
    if colour:
        out["colours"] = "; ".join(c.strip() for c in colour)[:600]
    if m := re.search(r"\b(?:in|at|located in)\s+([a-z][a-z .]{2,30}?)(?:[,.;]|$| city| area| with| and| for| having)", t):
        city = m.group(1).strip()
        if city not in {"the", "a", "my", "front", "back", "home", "house", "my home", "the house", "total", "all"} \
                and city.split()[0] not in VOCAB and not any(w in city for w in ("floor", "bedroom", "north", "south", "east", "west")):
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
                key = lambda r: (r.get("type"), r.get("level"), r.get("label"))  # noqa: E731
                seen = {key(r) for r in out.get("rooms", [])}
                out["rooms"] = list(out.get("rooms", [])) + [r for r in v if key(r) not in seen]
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
        if r.get("label") and r.get("level") is None and not r.get("direction"):
            bits.append(r["label"].lower())
        elif r.get("level") is not None or r.get("direction"):
            where = (["ground floor", "first floor", "second floor", "third floor"][r["level"]] if isinstance(r.get("level"), int) and 0 <= r["level"] < 4 else "")
            bits.append(f"{(r.get('label') or r['type'].replace('_', ' ')).lower()}{' on the ' + where if where else ''}{' in the ' + r['direction'] if r.get('direction') else ''}")
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
2. Reply in the language named at the end of these instructions, in one to three short sentences: acknowledge the specific things they asked for (not a recap of everything), offer one useful architectural observation when you have a real one (for example how a courtyard helps a deep plot, or why a north road suits the living room), and ask about at most two things that are still missing and would change the design.

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
              "level": 0 for ground, 1 for first..., "direction": compass quarter, "area": m2, "attach_to": room type it opens off, "scale": 1.3 for bigger / 0.8 for smaller}] - only rooms the client placed, sized or attached, and EVERY room the client names that is not in that list (gaming room, laundry, sauna, music room, pool, workshop, anything): give it "type" = the listed type it behaves most like and "label" = its name, e.g. {"type": "home_theatre", "label": "Gaming Room"}, {"type": "laundry", "label": "Laundry"}, {"type": "study", "label": "Music Room"}. Never turn one room into another the client did not ask for. A balcony off the master bedroom upstairs is {"type": "balcony", "level": 1, "attach_to": "master_bedroom"},
   "remove": [room types the client does not want],
   "colours": "the client's colour wishes in their words",
   "notes": "anything else they want that fits nowhere above"},
 "questions": [{"key": "plot"|"road_direction"|"levels"|"bedrooms"|"other", "text": "the question, in their language", "options": ["2-5 short one-tap answers, in their language"]}],
 "go_ahead": true if they told you to proceed or decide yourself,
 "start": true if they are confirming that the design should begin now ("yes", "start", "go ahead", "haan, shuru karo", "let's do it")
}
When the essentials are known and the client confirms, set "start": true and say in a few words that the studio is starting."""


SCRIPTS = [((0x0900, 0x097F), "Hindi (or Marathi, if the message is Marathi), in Devanagari"),
           ((0x0980, 0x09FF), "Bengali, in Bengali script"), ((0x0A00, 0x0A7F), "Punjabi, in Gurmukhi"),
           ((0x0A80, 0x0AFF), "Gujarati, in Gujarati script"), ((0x0B80, 0x0BFF), "Tamil, in Tamil script"),
           ((0x0C00, 0x0C7F), "Telugu, in Telugu script"), ((0x0C80, 0x0CFF), "Kannada, in Kannada script"),
           ((0x0D00, 0x0D7F), "Malayalam, in Malayalam script"), ((0x0600, 0x06FF), "Urdu, in Urdu script")]
# Words that only appear when someone is writing an Indian language in Latin letters.
ROMAN = {
    "Hinglish (Hindi in Latin letters, mixed with English as the client does)": {
        "hai", "hain", "mujhe", "mujhko", "chahiye", "chahte", "chahta", "chahti", "karo", "karna", "kar", "kya",
        "nahi", "nahin", "mera", "meri", "mere", "hamara", "hamare", "ghar", "kamra", "kamre", "wala", "wali",
        "bhi", "aur", "ek", "do", "teen", "banao", "banana", "saath", "sath", "accha", "acha", "theek", "thik",
        "haan", "ji", "hoga", "hogi", "chalo", "shuru", "lekin", "par", "mein", "ke", "ki", "ka", "ko", "se",
        "yeh", "ye", "woh", "wo", "kitne", "kitna", "matlab", "bas", "zyada", "jyada", "thoda"},
    "romanised Kannada, in Latin letters": {"beku", "beda", "illa", "maadi", "madi", "mane", "nanage", "ide", "swalpa"},
    "romanised Tamil, in Latin letters": {"venum", "vendum", "illai", "veedu", "enaku", "romba", "konjam", "seri"},
    "romanised Telugu, in Latin letters": {"kavali", "kaavali", "ledu", "illu", "naaku", "chala", "konchem", "cheyyandi"},
}


def reply_language(text: str) -> str:
    """The language to answer in, read from the message itself - not from a place
    name in it ("Bengaluru" is English), not from earlier turns."""
    counts: dict[str, int] = {}
    for ch in text:
        o = ord(ch)
        for (lo, hi), name in SCRIPTS:
            if lo <= o <= hi:
                counts[name] = counts.get(name, 0) + 1
    if counts:
        return max(counts, key=counts.get)
    words = re.findall(r"[a-z]+", text.lower())
    for name, vocab in ROMAN.items():
        hits = {w for w in words if w in vocab}
        # Short words ("do", "par", "se", "ke") are English too: it takes two
        # distinct ones, or one that is never English, to call it.
        strong = {w for w in hits if len(w) >= 4 and w not in {"wali", "mere", "bhi"}}
        if len(hits) >= 3 or (len(hits) >= 2 and strong) or (strong and len(words) <= 4):
            return name
    return "English"


async def llm_turn(message: str, brief: dict[str, Any], history: list[dict[str, str]]) -> dict[str, Any] | None:
    """The conversation turn, by a language model; None if none is reachable."""
    try:
        from aip.core.llm import LLMRouter, assistant, system, user
        from aip.core.providers import Capability

        msgs = [system(CHAT_SYSTEM + f"\n\nThe brief so far: {json.dumps(brief, ensure_ascii=False)}")]
        for h in history[-12:]:
            text = str(h.get("text", ""))[:2000]
            msgs.append(user(text) if h.get("role") == "user" else assistant(text))
        lang = reply_language(message)
        msgs[0] = system(msgs[0].content + f"\n\nWrite the reply, questions and options in {lang}. "
                         "Decide this from the client's latest message only: a place name (Bengaluru, Chennai) "
                         "or an Indian word for a room (puja, verandah) in an English message is still English.")
        msgs.append(user(message))
        router = LLMRouter()
        try:
            # A conversation cannot wait on a queue: past the deadline the rules answer.
            resp = await asyncio.wait_for(
                router.complete(msgs, capability=Capability.STRUCTURED, temperature=0.3, max_tokens=900,
                                json_schema={"type": "object"}, latency_sensitive=True, interactive=True),
                CHAT_DEADLINE)
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


def _resolve(r: dict[str, Any]) -> dict[str, Any]:
    """A model's room as one the planner can draw: a type it does not know
    ("gaming_room", "sauna") becomes the room it behaves like, keeping its name."""
    from aip.domain.plan import RoomType

    r = dict(r)
    kind = str(r["type"]).lower().strip().replace(" ", "_")
    label = str(r.get("label") or "").strip()[:40]
    label = label.title() if label.islower() else label
    if kind in {t.value for t in RoomType} and kind != "other":
        r["type"] = kind
        if label:
            r["label"] = label
        else:
            r.pop("label", None)
        return r
    named = (named_room(label or kind) or named_room((label or kind.replace("_", " ")) + " room")
             or {"type": "study", "label": (label or kind.replace("_", " ")).title(), "area": 11})
    r["type"], r["label"] = named["type"], label or named["label"]
    r.setdefault("area", named["area"])
    if named.get("attach_to"):
        r.setdefault("attach_to", named["attach_to"])
    return r


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
                v = [_resolve(r) for r in v if isinstance(r, dict) and r.get("type")]
            out[k] = v
        except (TypeError, ValueError):
            continue
    return out


_BARE = re.compile(rf"^\s*(\d|{'|'.join(WORDNUM)})\s*(?:please|pls|plz)?\s*[.!]?\s*$")
_BARE_DIR = {**DIRS, **{v.lower(): v for v in DIRS.values()}}
_BARE_GROUND = re.compile(r"^\s*(?:just |only )?(?:ground|g)(?: floor)?(?: only)?\s*[.!]?\s*$")


def _bare_answer(message: str, brief: dict[str, Any]) -> dict[str, Any]:
    """A bare reply to a question still open - "South", "Ground only", "4" or a
    tapped chip - read as the answer to that question, since the parser only
    reads these inside a phrase ("south facing", "4 bedrooms")."""
    t = _hindi(message.lower()).strip()
    need = missing(brief)
    word = re.sub(r"\s*(?:side|road|facing)?\s*[.!]?$", "", re.sub(r"^(?:the |road |facing )", "", t)).strip()
    if "road_direction" in need and word in _BARE_DIR:
        return {"road_direction": _BARE_DIR[word]}
    if "levels" in need and _BARE_GROUND.match(t):
        return {"levels": 1}
    m = _BARE.match(t)
    if not m:
        return {}
    n = int(m.group(1)) if m.group(1).isdigit() else WORDNUM[m.group(1)]
    asked = need[:2] if any(k in need[:2] for k in ("bedrooms", "levels")) else need
    if "bedrooms" in asked and 1 <= n <= 8:
        return {"bedrooms": n}
    if "levels" in asked and 1 <= n <= 6:
        return {"levels": n}
    return {}


async def converse(message: str, brief: dict[str, Any] | None = None, *, use_llm: bool = True,
                   history: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """One turn: the updated brief, what is still missing, what to ask, and the reply."""
    brief = dict(brief or {})
    rules = parse(message)
    bare = {k: v for k, v in _bare_answer(message, brief).items() if k not in rules}
    rules.update(bare)
    turn = await llm_turn(message, brief, history or []) if use_llm else None
    if turn is not None:
        model = _clean(turn.get("updates") or {})
        # The rules win where they read a number unambiguously (a model can
        # slip a unit); the model carries everything else, in any language.
        for k in ("plot_width", "plot_depth", "plot_unit", "bedrooms", "levels", *bare):
            if k in rules:
                model[k] = rules[k]
        # Rooms the rules read (counted, placed on floors, next to another
        # room) are kept as read; the model adds the rooms the rules missed.
        if rules.get("rooms"):
            ruled = {r["type"] for r in rules["rooms"]}
            labels = {r["label"] for r in rules["rooms"] if r.get("label")}
            model["rooms"] = [r for r in model.get("rooms", [])
                              if (r["label"] not in labels if r.get("label") else r.get("type") not in ruled)]
        merged = merge(brief, {"rooms": rules.get("rooms", []), "amenities": rules.get("amenities", [])}, model)
        if model.get("remove"):
            merged["remove"] = sorted(set(brief.get("remove", [])) | set(model["remove"]))
        need = missing(merged)
        if (turn.get("go_ahead") or GO_AHEAD.search(message.lower())) and need:
            merged = apply_defaults(merged)
            need = []
        questions = [q for q in (turn.get("questions") or []) if isinstance(q, dict) and q.get("text")
                     and not (q.get("key") in ESSENTIAL and q.get("key") not in need)][:2]
        if need and not questions:
            questions = [{"key": k, "text": QUESTIONS[k][0], "options": QUESTIONS[k][1]} for k in need[:2]]
        if not need:
            questions = [q for q in questions if q.get("key") == "other"][:1]
        start = bool(turn.get("start") or START.search(message.lower())) and not need
        return {"brief": merged, "missing": need, "questions": questions, "ready": not need, "start": start,
                "reply": str(turn["reply"]).strip(), "by": "model"}
    # No model reachable: the rules, with a plain reply.
    merged = merge(brief, rules)
    need = missing(merged)
    if GO_AHEAD.search(message.lower()) and need:
        merged = apply_defaults(merged)
        need = []
    lang = reply_language(message)
    say = next((v for k, v in LOCAL.items() if lang.startswith(k)), None)
    questions = [{"key": k, "text": say[k] if say else QUESTIONS[k][0], "options": QUESTIONS[k][1]} for k in need[:2]]
    heard = _summary(rules) if rules else ""
    if questions:
        noted = (say["noted"] if say else "Noted - {}.").format(heard) + " " if heard else ""
        reply = noted + " ".join(q["text"] for q in questions)
    else:
        reply = say["done"] if say else \
            "That's everything I need. Press Start designing when you're ready, or tell me anything else you'd like."
    return {"brief": merged, "missing": need, "questions": questions, "ready": not need,
            "start": bool(START.search(message.lower())) and not need and bool(brief), "reply": reply, "by": "rules"}


async def revise(instruction: str, brief: dict[str, Any], *, use_llm: bool = True) -> dict[str, Any]:
    """Change a finished design's brief from a sentence; say what changed.

    A model reads the instruction first - in any language, however phrased
    ("the kitchen feels cramped", "puja room hatao", "move the master upstairs")
    - and returns the brief fields it changes; the rules below are the
    fallback when no model answers.
    """
    if use_llm:
        turn = await llm_turn(
            "The design already exists. The client now asks for this change - record only what changes "
            "(use rooms[].scale for bigger/smaller, remove for rooms they no longer want, rooms[].level to move "
            "a room to another floor): " + instruction, dict(brief), [])
        if turn is not None:
            upd = _clean(turn.get("updates") or {})
            if upd:
                after = merge(dict(brief), upd)
                if upd.get("remove"):
                    after["remove"] = sorted(set(brief.get("remove", [])) | set(upd["remove"]))
                return {"brief": after, "changes": [str(turn.get("reply", "")).strip() or "Updated."],
                        "understood": True}
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
        for k in ("count", "level", "direction", "area", "attached_bathroom", "scale", "attach_to", "label"):
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
