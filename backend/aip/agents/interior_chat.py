"""The interior chat: change a room by saying so.

"Paint this wall sage", "add a jhoola by the window", "make it cosier",
"herringbone floor", "a coffered ceiling", "remove the TV unit", "a king bed".
The client may have a piece or a wall selected in the 3D view; "this" means it.

The chat turns what was said into a short list of edits (`ops`) that the room
editor applies to the room exactly as if the client had clicked them, so every
change goes through the same checks and is saved the same way. It asks the
same model router as the exterior chat (and so the same Groq key); without one
it reads the message itself.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from aip.core.logging import get_logger

logger = get_logger("aip.agents.interior_chat")

SYSTEM = """You are an interior designer editing ONE room of an Indian home for a client.
You get JSON: the room, what is in it (uid, item id, name, colour), what is selected,
the catalogue of pieces you may add, floors, wall treatments, ceilings, looks and lights.
Reply with JSON only: {"ops": [...], "reply": "one or two plain sentences"}.
Ops (use only ids from the input; "selected" means the selected piece or wall):
 {"op":"add","item":"<catalogue id>","colour":"#rrggbb"?, "size":"<standard size name>"?}
 {"op":"remove","uid":"<uid>|selected"}  or  {"op":"remove","item":"<item id>"}
 {"op":"colour","uid":"<uid>|selected","hex":"#rrggbb"}
 {"op":"size","uid":"<uid>|selected","size":"<standard size name, e.g. King, 6-seat>"}
 {"op":"turn","uid":"<uid>|selected"}
 {"op":"move","uid":"<uid>|selected","to":"N|S|E|W|C"}
 {"op":"wall","wall":"<wall id>|selected|all|accent","value":"#rrggbb or a treatment id"}
 {"op":"floor","id":"<floor id>"}   {"op":"ceiling","id":"<ceiling id>"}
 {"op":"light","kelvin":2700|4000|5500}   {"op":"look","id":"<look id>"}
 {"op":"edge","skirting":true|false,"cornice":true|false,"dado":"#rrggbb"|false}
Use real paint colours an Indian home would have. Never invent ids. Keep the room usable."""


def _words(s: str) -> set[str]:
    return set(re.findall(r"[a-z]+", s.lower()))


def _best(items: list[dict[str, Any]], text: str) -> dict[str, Any] | None:
    """The catalogue piece whose name the message names best."""
    said = _words(text)
    best, score = None, 0.0
    for it in items:
        name = _words(it["name"]) - {"with", "and", "a", "the", "of", "on"}
        hit = len(name & said)
        if not hit:
            continue
        s = hit / len(name) + (0.5 if it["name"].lower() in text.lower() else 0)
        if s > score:
            best, score = it, s
    return best if score >= 0.5 else None


def _by_rules(ctx: dict[str, Any], message: str) -> tuple[list[dict[str, Any]], str]:
    from aip.agents.design_chat import _colour_in

    text = message.lower()
    ops: list[dict[str, Any]] = []
    said: list[str] = []
    sel = ctx.get("selected") or {}
    hexv = _colour_in(text)
    hexv = f"#{hexv}" if hexv else ""
    catalogue = [it for g in ctx["catalogue"] for it in g["items"]]
    named = lambda pool: next((x for x in pool if x["name"].lower() in text or x["id"] in text), None)  # noqa: E731

    floor = named(ctx["floors"]) if "floor" in text or any(f["name"].lower() in text for f in ctx["floors"]) else None
    if floor:
        ops.append({"op": "floor", "id": floor["id"]}); said.append(f"a {floor['name'].lower()} floor")
    ceiling = named(ctx["ceilings"]) if "ceiling" in text else None
    if ceiling is None and "ceiling" in text:
        for c in ctx["ceilings"]:
            if _words(c["name"]) & _words(text) - {"ceiling", "with"}:
                ceiling = c
                break
    if ceiling:
        ops.append({"op": "ceiling", "id": ceiling["id"]}); said.append(f"a {ceiling['name'].lower()} ceiling")
    look = named(ctx["looks"])
    if look:
        ops.append({"op": "look", "id": look["id"]}); said.append(f"the {look['name']} look")
    if any(w in text for w in ("cosy", "cozy", "warm light", "warmer")):
        ops.append({"op": "light", "kelvin": 2700}); said.append("warm 2700K light")
    elif any(w in text for w in ("bright", "task light", "white light")):
        ops.append({"op": "light", "kelvin": 5500}); said.append("bright 5500K light")
    for key, words in (("skirting", ("skirting",)), ("cornice", ("cornice", "crown moulding", "moulding"))):
        if any(w in text for w in words):
            ops.append({"op": "edge", key: not any(n in text for n in ("no ", "remove"))}); said.append(key)
    if any(w in text for w in ("panelling", "paneling", "wainscot", "dado")):
        ops.append({"op": "edge", "dado": hexv or "#7a4b2a"}); said.append("wainscot panelling")

    treat = named(ctx["treatments"])
    if treat is None:
        for t in ctx["treatments"]:
            if t["id"] in text or (t["id"] == "brick" and "brick" in text) or (t["id"] == "fluted" and "flut" in text):
                treat = t
                break
    adding = re.search(r"\b(add|put|place|want|need|include)\b", text)
    removing = re.search(r"\b(remove|delete|take away|get rid of|no more)\b", text)
    wall_word = "wall" in text or (sel.get("kind") == "wall" and (hexv or treat) and not adding)
    if wall_word and (hexv or treat):
        target = "all" if re.search(r"\b(all|every|walls)\b", text) and "this" not in text else \
            "accent" if "accent" in text else ("selected" if sel.get("kind") == "wall" else "all")
        ops.append({"op": "wall", "wall": target, "value": treat["id"] if treat else hexv})
        said.append(f"{'the selected wall' if target == 'selected' else 'the ' + target + ' wall' if target == 'accent' else 'the walls'} "
                    f"in {treat['name'].lower() if treat else hexv.upper()}")
    elif removing:
        item = _best(catalogue, text)
        if item and not re.search(r"\b(this|that|it|selected)\b", text):
            ops.append({"op": "remove", "item": item["id"]}); said.append(f"removed the {item['name'].lower()}")
        elif sel.get("kind") == "piece":
            ops.append({"op": "remove", "uid": "selected"}); said.append("removed the selected piece")
    elif adding or (not ops and _best(catalogue, text)):
        item = _best(catalogue, text)
        if item:
            op = {"op": "add", "item": item["id"]}
            if hexv:
                op["colour"] = hexv
            ops.append(op); said.append(f"added a {item['name'].lower()}")
    elif hexv and sel.get("kind") == "piece":
        ops.append({"op": "colour", "uid": "selected", "hex": hexv}); said.append(f"the selected piece in {hexv.upper()}")
    if sel.get("kind") == "piece" and any(w in text for w in ("turn", "rotate")):
        ops.append({"op": "turn", "uid": "selected"}); said.append("turned it")
    for word, to in (("north wall", "N"), ("south wall", "S"), ("east wall", "E"), ("west wall", "W"), ("centre", "C"), ("center", "C")):
        if sel.get("kind") == "piece" and word in text and "move" in text:
            ops.append({"op": "move", "uid": "selected", "to": to}); said.append(f"moved to the {word}")
            break
    reply = ("Done: " + "; ".join(said) + ".") if said else \
        "I could not tell what to change. Try “paint this wall sage”, “add a jhoola”, or “herringbone floor”."
    return ops, reply


async def edit_interior(ctx: dict[str, Any], message: str, history: list[dict[str, str]] | None = None,
                        *, use_llm: bool = True) -> dict[str, Any]:
    """What to change in the room for what the client asked, and a reply."""
    if use_llm:
        try:
            from aip.core.config import get_settings
            from aip.core.llm import LLMRouter, assistant, system, user
            from aip.core.providers import Capability, available_providers

            # A hosted model with a key (Groq first). A local Ollama without its
            # models answers nothing useful, and waiting on it makes a room edit slow.
            if not [p for p in available_providers(get_settings()) if p.name != "ollama"]:
                raise RuntimeError("no hosted model is configured (add GROQ_API_KEY to backend/.env)")

            msgs = [system(SYSTEM)]
            for turn in (history or [])[-6:]:
                if turn.get("role") in ("user", "assistant") and turn.get("text"):
                    t = str(turn["text"])[:500]
                    msgs.append(user(t) if turn["role"] == "user" else assistant(t))
            slim = dict(ctx)
            slim["catalogue"] = [{"group": g["name"], "items": [{"id": i["id"], "name": i["name"],
                                                                 "sizes": [z["name"] for z in i.get("sizes", [])]}
                                                                for i in g["items"]]} for g in ctx["catalogue"]]
            msgs.append(user(json.dumps({**slim, "message": message})[:14000]))
            router = LLMRouter()
            try:
                # A room edit should feel immediate: past 8 s the rules answer instead.
                resp = await asyncio.wait_for(
                    router.complete(msgs, capability=Capability.STRUCTURED, temperature=0.2, max_tokens=700,
                                    json_schema={"type": "object"}, latency_sensitive=True), timeout=8.0)
            finally:
                await router.aclose()
            if getattr(resp, "provider", "") != "offline":
                raw = resp.text[resp.text.find("{"): resp.text.rfind("}") + 1]
                d = json.loads(raw)
                ops = [o for o in d.get("ops") or [] if isinstance(o, dict) and o.get("op")]
                if ops:
                    return {"ops": ops[:12], "reply": str(d.get("reply") or "Done.")[:400],
                            "by": getattr(resp, "provider", "model") or "model"}
        except Exception as exc:  # noqa: BLE001 - the rules still edit
            logger.info("interior_chat.llm_unavailable %s", exc)
    ops, reply = _by_rules(ctx, message)
    return {"ops": ops, "reply": reply, "by": "rules"}


__all__ = ["edit_interior"]
