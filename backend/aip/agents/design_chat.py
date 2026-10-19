"""The design chat: change the outside of the house by saying so.

"Paint the boundary wall charcoal", "make the gate teak", "a tiled hip roof",
"add jaali on the upper floor", "put the walls back to the design's own
colour". The client talks about the parts they can see labelled in the 3D
view (`exteriors.PARTS`), and the chat turns what they said into a change to
the design id, so everything else - the 3D model, the four elevations, the
uniqueness registry - follows on its own.

It asks the same model router the home-page brief chat uses (and so the same
API keys), and without one it falls back to reading the message itself:
part words, colour words and the grammar's own vocabulary.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any

from aip.core.logging import get_logger
from aip.domain.plan import FloorPlan
from aip.engines.experience.exteriors import (
    ACCENTS,
    BASES,
    COLOUR_KEYS,
    FEATURES,
    OPTION_KEYS,
    PAINTS,
    PARTS,
    ROOFS,
    SCREENS,
    UPPERS,
    WINDOWS,
    Exterior,
    _hex6,
    decode_paints,
    prefer_from_text,
    with_paints,
)

logger = get_logger("aip.agents.design_chat")

_FORM = {"roof": ROOFS, "base": BASES, "upper": UPPERS, "screen": SCREENS, "windows": WINDOWS,
         "accent": tuple(ACCENTS), "feature": FEATURES}
_OPTIONS = {f: vocab for f, vocab in OPTION_KEYS.values()}

#: Colours a client names, beyond the named paints: plain words first.
_COLOURS: dict[str, str] = {
    "white": "f4f2ec", "off white": "efe9dc", "off-white": "efe9dc", "cream": "efe3c8", "beige": "dcc9a8",
    "ivory": "f4efe4", "grey": "9a9a96", "gray": "9a9a96", "light grey": "c9c9c4", "dark grey": "55565a",
    "charcoal": "3a3a3c", "black": "1d1d1f", "brown": "6b4a32", "dark brown": "4a3222", "teak": "7a4b2a",
    "walnut": "5a3d2a", "oak": "a07a52", "red": "a63a2c", "maroon": "6e2a26", "terracotta": "c27b5c",
    "orange": "d9822f", "yellow": "e8c95a", "mustard": "d9a93f", "ochre": "d9a95b", "gold": "c9a24a",
    "green": "5f7f4f", "sage": "a9b496", "olive": "6b6b3a", "dark green": "2f4a36", "mint": "cfe3d4",
    "blue": "4a6c9a", "navy": "2b3a52", "indigo": "34406e", "sky blue": "a9c8e2", "teal": "2f6f6f",
    "pink": "e2b8a6", "rose": "c98e8e", "sand": "d2b98f", "stone": "b8ab92", "copper": "b0683c",
    "bronze": "8a6a4c", "silver": "b9bcc0", "brick red": "8e4a32", "lime": "efe9dc", "purple": "6c4f7a",
}
for _surface in PAINTS.values():
    for _name, _hex in _surface:
        _COLOURS.setdefault(_name.lower(), _hex.lstrip("#"))


def _label(key: str) -> str:
    return PARTS[key][0].lower()


def _colour_name(hex_: str) -> str:
    hex_ = hex_.lstrip("#").lower()
    for name, h in _COLOURS.items():
        if h == hex_:
            return name
    return f"#{hex_}"


def describe(ex: Exterior) -> dict[str, Any]:
    """The design as the chat sees it."""
    return {
        "form": {k: getattr(ex, k) for k in _FORM} | {"planters": ex.planters},
        "options": {k: getattr(ex, k) for k in _OPTIONS},
        "colours": {f: f"#{getattr(ex, f)}" for f in COLOUR_KEYS.values() if getattr(ex, f)},
        "painted_parts": {k: f"#{v}" for k, v in decode_paints(ex.paints).items()},
    }


SYSTEM = f"""You edit the outside of an Indian house in a 3D design studio. The client sees the house in 3D with every part labelled and asks for changes in plain words. Make exactly what they ask, nothing else, and keep it buildable.

Parts they can paint (key: label): {"; ".join(f"{k}: {v[0]}" for k, v in PARTS.items())}

Form (use only these values): {"; ".join(f"{k}: {', '.join(v)}" for k, v in _FORM.items())}; planters: true/false
Options: {"; ".join(f"{k}: {', '.join(v)}" for k, v in _OPTIONS.items())}

Return only JSON: {{"reply": "one or two friendly sentences saying what you changed, naming the parts as labelled", "form": {{field: value}}, "options": {{field: value}}, "paint": {{part key: "#rrggbb"}}, "reset": [part keys back to the design's own colour]}}. Leave out anything not changing. Colours are hex; pick tasteful real-world shades (teak #7a4b2a, charcoal #3a3a3c, Mangalore red #a8553a, lime white #efe9dc). If the request is unclear, change nothing and ask which part they mean in "reply"."""


#: A part a client names that this house builds another way: "the gate" is
#: its steelwork when the gate is a sliding one, "the roof" its slab when untiled.
_ALIAS = {"gate": "gate_steel", "gate_steel": "gate", "roof_tile": "ex_roof", "ex_roof": "roof_tile",
          "plaster": "clad", "ex_timber": "timber", "timber": "ex_timber"}


def _apply(ex: Exterior, form: dict, options: dict, paint: dict, reset: list,
           present: set[str] | None = None) -> tuple[Exterior, list[str]]:
    """The validated change and a line per thing that changed. With `present`
    (the parts the 3D model has), a part the house lacks is swapped for the one
    it builds instead, or reported."""
    said: list[str] = []
    changes: dict[str, Any] = {}
    for k, v in (form or {}).items():
        if k == "planters":
            if bool(v) != ex.planters:
                changes["planters"] = bool(v)
                said.append("planters added" if v else "planters removed")
        elif k in _FORM and v in _FORM[k] and v != getattr(ex, k):
            changes[k] = v
            said.append(f"{k} now {str(v).replace('_', ' ')}")
    for k, v in (options or {}).items():
        if k not in _OPTIONS or v not in _OPTIONS[k]:
            continue
        # An option's first value is what the house has when the id leaves it out.
        cur = getattr(ex, k) or _OPTIONS[k][0]
        if v != cur:
            changes[k] = "" if v == _OPTIONS[k][0] else v
            said.append(f"{k} now {v}")
    if changes:
        ex = replace(ex, **changes)
        if present is not None and changes.get("roof") in ("hip", "gable", "mono", "butterfly", "vault"):
            present = present | {"roof_tile", "ex_roof"}   # a new pitched roof brings its tiles
    pmap: dict[str, str | None] = {}
    for k, v in (paint or {}).items():
        if present and k in PARTS and k not in present:
            if _ALIAS.get(k) in present:
                k = _ALIAS[k]
            else:
                said.append(f"this design has no {_label(k)} to paint")
                continue
        if k in PARTS and _hex6(v):
            pmap[k] = _hex6(v)
            said.append(f"{_label(k)} painted {_colour_name(_hex6(v))}")
    for k in reset or []:
        if k in PARTS and k in decode_paints(ex.paints):
            pmap[k] = None
            said.append(f"{_label(k)} back to the design's own colour")
    if pmap:
        ex = with_paints(ex, pmap)
    return ex, said


def _parts_in(text: str) -> list[str]:
    """The parts a message names, longest words first so "boundary wall" beats "wall"."""
    words = sorted(((w, k) for k, (_l, _g, ws) in PARTS.items() for w in (*ws, PARTS[k][0].lower())),
                   key=lambda x: -len(x[0]))
    found, taken = [], text
    for w, k in words:
        m = re.search(rf"\b{re.escape(w)}\b", taken)
        if m:
            if k not in found:
                found.append(k)
            taken = taken[:m.start()] + " " * (m.end() - m.start()) + taken[m.end():]
    return found


def _colour_in(text: str) -> str:
    m = re.search(r"#?\b([0-9a-f]{6})\b", text)
    if m:
        return m.group(1)
    for name in sorted(_COLOURS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(name)}\b", text):
            return _COLOURS[name]
    return ""


#: Words that name a field of the grammar, so "roof hip" or "stone boundary" reads as a finish.
_FIELD_WORDS = {
    "roof": ("roof",), "base": ("base", "ground floor", "ground", "downstairs", "lower floor"),
    "upper": ("upper", "upstairs", "first floor", "upper floor", "top floor"),
    "screen": ("screen", "screening"), "windows": ("windows", "window"), "feature": ("feature", "signature"),
    "boundary": ("boundary", "compound", "fence"), "gate": ("gate",), "paving": ("paving", "drive", "driveway"),
    "railing": ("railing", "railings"), "shade": ("chajja", "chajjas", "sunshade", "sunshades", "shade"),
    "canopy": ("canopy", "porch"), "parapet": ("parapet",), "garden": ("garden",), "solar": ("solar",),
    "deck": ("terrace", "deck"), "lights": ("lights", "lighting"), "yard": ("yard",), "panel": ("panel",),
    "garage": ("garage", "car porch", "carport", "parking", "car park"),
}
#: Values too common to read without their field named ("open" the windows is not the garage).
_NEEDS_FIELD = {"open", "closed", "none", "on", "off", "plain", "standard"}
#: How a client says some values.
_VALUE_WORDS = {"hip": ("hip", "hipped"), "gable": ("gable", "pitched"), "butterfly": ("butterfly",),
                "jaali": ("jaali", "jali"), "louvres": ("louvres", "louvers"), "fins": ("fins",),
                "slats": ("slats", "battens"), "perforated": ("perforated",), "hedge": ("hedge",),
                "sliding": ("sliding",), "glass": ("glass",), "brick": ("brick",), "stone": ("stone",),
                "timber": ("timber", "wood", "wooden"), "concrete": ("concrete",), "terracotta": ("terracotta",),
                "deep": ("deep",), "pergola": ("pergola",), "on": ("solar panels", "add solar"),
                "strips": ("led strips", "strip lights"), "washers": ("wall washers", "uplights"),
                "closed": ("closed", "close", "shut", "shutter", "rolling shutter", "covered"),
                "open": ("open", "uncovered", "carport")}


def _vocab_in(clause: str) -> dict[str, str]:
    """Shapes and finishes a clause names: a value next to its field, or a
    value only one field has."""
    fields = {**_FORM, **_OPTIONS}
    hit: dict[str, str] = {}
    named = {f for f, ws in _FIELD_WORDS.items() if any(re.search(rf"\b{re.escape(w)}\b", clause) for w in ws)}
    for f, vocab in fields.items():
        for v in vocab:
            words = _VALUE_WORDS.get(v, (v.replace("_", " "),))
            if not any(re.search(rf"\b{re.escape(w)}\b", clause) for w in words):
                continue
            owners = [g for g, vs in fields.items() if v in vs]
            # "screen" names the street screen; it is a parapet only when the parapet is named.
            if f not in named and any(v in ws for g, ws in _FIELD_WORDS.items() if g != f):
                continue
            if v in _NEEDS_FIELD and f not in named:
                continue
            if f in named or (len(owners) == 1 and not named & set(owners) - {f}):
                hit.setdefault(f, v)
    return hit


def _by_rules(ex: Exterior, message: str, present: set[str] | None = None) -> tuple[Exterior, list[str], str]:
    text = message.lower()
    paint: dict[str, str] = {}
    reset: list[str] = []
    form, options = {}, {}
    # Clause by clause: "make the roof hip with Mangalore red tiles, the gate teak and a stone boundary".
    for clause in re.split(r"[,;.]| and | also | then ", text):
        parts = _parts_in(clause)
        if parts and re.search(r"\b(reset|original|back to|default|undo)\b", clause):
            reset += parts
            continue
        vocab = _vocab_in(clause)
        hx = _colour_in(clause) if parts else ""
        if parts and hx:
            # "the gate teak": a colour for the part named, not the design's accent.
            vocab.pop("accent", None)
        for f, v in vocab.items():
            (form if f in _FORM else options)[f] = v
        # A colour, unless the only colour word is the finish just named ("a stone boundary").
        if hx and vocab and _colour_in(" ".join(w for w in clause.split() if w not in set(vocab.values()))) == "":
            hx = ""
        if hx:
            # Paint the part the colour is for: a roof change paints the tiles, not the slab too.
            keep = [k for k in parts if not (vocab.get("roof") and k == "ex_roof" and "roof_tile" in parts)]
            for k in keep or parts:
                paint[k] = hx
    if not (form or options or paint or reset):
        # The grammar's own words, for what the clauses missed: "something Kerala", "lots of greenery".
        for k, v in prefer_from_text(message).items():
            if isinstance(v, tuple) and v and (k in _FORM or k in _OPTIONS):
                (form if k in _FORM else options)[k] = v[0]
    ex2, said = _apply(ex, form, options, paint, reset, present)
    if not said:
        return ex, [], ("I could not tell what to change. Name a part as it is labelled in the 3D view "
                        "and a colour or finish - for example \"paint the boundary wall charcoal\" or \"make the roof hip\".")
    return ex2, said, "Done: " + "; ".join(said) + "."


async def edit_exterior(plan: FloorPlan, design_id: str, message: str,
                        history: list[dict[str, str]] | None = None, *, use_llm: bool = True,
                        parts: list[str] | None = None) -> dict[str, Any]:
    """Apply what the client asked to the design; the new design and a reply."""
    ex = Exterior.parse(design_id)
    if ex is None:
        raise ValueError("Not an exterior design id.")
    one_floor = len(plan.levels) <= 1
    present = {k for k in (parts or []) if k in PARTS} or None
    by = "rules"
    new, said, reply = ex, [], ""
    if use_llm:
        try:
            from aip.core.llm import LLMRouter, assistant, system, user
            from aip.core.providers import Capability

            msgs = [system(SYSTEM)]
            for turn in (history or [])[-6:]:
                if turn.get("role") in ("user", "assistant") and turn.get("text"):
                    text = str(turn["text"])[:600]
                    msgs.append(user(text) if turn["role"] == "user" else assistant(text))
            msgs.append(user(json.dumps({"design": describe(ex), "floors": len(plan.levels),
                                         "parts_in_this_house": sorted(present) if present else "all",
                                         "style": plan.style, "message": message})))
            router = LLMRouter()
            try:
                resp = await router.complete(msgs, capability=Capability.STRUCTURED, temperature=0.2, max_tokens=700,
                                             json_schema={"type": "object"}, latency_sensitive=True)
            finally:
                await router.aclose()
            if getattr(resp, "provider", "") != "offline":
                raw = resp.text[resp.text.find("{"): resp.text.rfind("}") + 1]
                d = json.loads(raw)
                new, said = _apply(ex, d.get("form") or {}, d.get("options") or {}, d.get("paint") or {},
                                   d.get("reset") or [], present)
                reply = str(d.get("reply") or "")[:400]
                by = getattr(resp, "provider", "model") or "model"
        except Exception as exc:  # noqa: BLE001 - the rules still edit
            logger.info("design_chat.llm_unavailable %s", exc)
    if by == "rules":
        new, said, reply = _by_rules(ex, message, present)
    new, notes = new.fitted(one_floor)
    out = new.to_dict()
    return {"reply": reply or ("Done: " + "; ".join(said) + "." if said else "Nothing changed."),
            "design": out, "changed": said, "notes": notes, "by": by}


__all__ = ["edit_exterior", "describe"]
