"""Exterior design grammar: many distinct houses from one plan.

A facade here is a combination of independent decisions an architect makes
for the street face of a house, each a small vocabulary:

* **roof**     - flat behind a parapet, a thin cantilevered slab, a mono-pitch
                 over a clerestory, a butterfly, a hipped tile roof, a gable;
* **base**     - the ground floor: plaster, a stone plinth band, exposed brick,
                 board-marked concrete;
* **upper**    - the floors above: plaster, timber boarding, dark metal panels,
                 brick;
* **screen**   - what dresses the street face of the upper floor: nothing,
                 vertical fins, horizontal louvres, a deep box frame, a jaali,
                 a perforated metal screen;
* **windows**  - punched openings, or a continuous dark glazing band per floor;
* **planters** - planter boxes along the parapets and sills, or none;
* **accent**   - one colour for the frame, fins or screen.

A design is serialised into a compact id (`ex:roof.base.upper.screen.windows.
planters.accent`), so the model URL carries the whole design and any design
can be rebuilt from its id alone. The exterior agent composes these from the
client's words; `generate` gives a varied, style-aware set without a model.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import asdict, dataclass
from typing import Any

from aip.domain.geometry import Vec2
from aip.domain.plan import FloorPlan
from aip.engines.experience.facades import Edge, edges, pitch_roof

ROOFS = ("flat", "slab", "mono", "butterfly", "hip", "gable")
BASES = ("plaster", "stone", "brick", "concrete")
UPPERS = ("plaster", "timber", "metal", "brick")
SCREENS = ("none", "fins", "louvres", "frame", "jaali", "perforated")
WINDOWS = ("punched", "band")
#: The design's signature element: what a passer-by remembers the house by.
FEATURES = ("none", "jharokha", "colonnade", "chhatri", "cornice", "breeze", "greenwall")
ACCENTS = {"bronze": "#8a6a4c", "charcoal": "#2b2a29", "teak": "#7a4b2a", "white": "#efece6",
           "terracotta": "#a8553a", "sage": "#7d8b6a", "navy": "#2b3a52", "brass": "#b08a3e",
           "ochre": "#c08a2e", "indigo": "#34406e", "forest": "#2f4a36", "rose": "#b46a6a",
           "slate": "#59626b", "sand": "#d2b98f"}

#: What each style tends towards; a design outside it is still allowed, only less likely.
STYLE_BIAS: dict[str, dict[str, tuple[str, ...]]] = {
    "contemporary": {"roof": ("flat", "slab", "mono"), "screen": ("fins", "frame", "louvres", "perforated"),
                     "feature": ("none", "cornice", "breeze", "greenwall"), "accent": ("bronze", "charcoal", "slate", "teak")},
    "modern_minimal": {"roof": ("slab", "flat"), "screen": ("none", "frame"), "upper": ("plaster", "metal"),
                       "feature": ("none",), "accent": ("white", "charcoal", "slate")},
    "tropical_modern": {"roof": ("slab", "mono", "butterfly"), "upper": ("timber",), "screen": ("louvres", "fins"),
                        "feature": ("greenwall", "breeze", "none"), "accent": ("teak", "forest", "sage")},
    "kerala_vernacular": {"roof": ("hip", "gable"), "base": ("stone", "plaster"), "upper": ("timber", "plaster"),
                          "feature": ("colonnade",), "accent": ("teak", "terracotta", "forest")},
    "traditional_indian": {"roof": ("hip", "flat"), "screen": ("jaali",), "base": ("stone",),
                           "feature": ("jharokha", "colonnade", "cornice"), "accent": ("ochre", "terracotta", "teak", "indigo")},
    "chettinad": {"roof": ("hip", "flat"), "screen": ("jaali",), "base": ("stone", "brick"),
                  "feature": ("colonnade", "cornice"), "accent": ("ochre", "indigo", "rose", "teak")},
    "rajasthani_haveli": {"roof": ("flat",), "screen": ("jaali",), "base": ("stone",),
                          "feature": ("jharokha", "chhatri"), "accent": ("sand", "rose", "ochre", "terracotta")},
    "indo_saracenic": {"roof": ("flat",), "screen": ("jaali", "frame"), "base": ("stone", "brick"),
                       "feature": ("chhatri", "colonnade", "cornice"), "accent": ("sand", "terracotta", "white")},
    "scandinavian": {"roof": ("gable", "mono"), "upper": ("timber",), "screen": ("none",),
                     "feature": ("none",), "accent": ("charcoal", "white", "slate")},
    "japandi": {"roof": ("slab", "gable"), "upper": ("timber",), "screen": ("louvres", "none"),
                "feature": ("none", "greenwall"), "accent": ("teak", "charcoal", "sand")},
    "industrial": {"base": ("concrete", "brick"), "upper": ("metal", "brick"), "screen": ("perforated", "frame"),
                   "feature": ("none", "breeze"), "accent": ("charcoal", "slate", "terracotta")},
    "biophilic": {"roof": ("slab", "butterfly"), "upper": ("timber",), "screen": ("louvres", "fins"),
                  "feature": ("greenwall",), "accent": ("forest", "sage", "teak")},
    "mid_century_modern": {"roof": ("butterfly", "mono", "slab"), "base": ("brick", "stone"), "screen": ("frame", "fins"),
                           "feature": ("breeze", "none"), "accent": ("ochre", "teak", "sage", "navy")},
}

NAMES = {
    "fins": "Fin", "louvres": "Louvre", "frame": "Frame", "jaali": "Jaali", "perforated": "Screen", "none": "Plain",
    "flat": "Parapet", "slab": "Slab", "mono": "Skillion", "butterfly": "Butterfly", "hip": "Tiled", "gable": "Gable",
    "timber": "Timber", "metal": "Metal", "brick": "Brick", "stone": "Stone", "concrete": "Concrete", "plaster": "Lime",
    "jharokha": "Jharokha", "colonnade": "Colonnade", "chhatri": "Chhatri", "cornice": "Cornice", "breeze": "Breeze-block",
    "greenwall": "Green-wall",
}


@dataclass(frozen=True, slots=True)
class Exterior:
    roof: str = "flat"
    base: str = "plaster"
    upper: str = "plaster"
    screen: str = "none"
    windows: str = "punched"
    planters: bool = False
    accent: str = "bronze"
    feature: str = "none"

    @property
    def id(self) -> str:
        return "ex:" + ".".join([self.roof, self.base, self.upper, self.screen, self.windows,
                                 "p" if self.planters else "n", self.accent, self.feature])

    @classmethod
    def parse(cls, design_id: str | None) -> Exterior | None:
        if not design_id or not design_id.startswith("ex:"):
            return None
        parts = design_id[3:].split(".")
        if len(parts) == 7:
            parts.append("none")              # ids from before the signature element
        if len(parts) != 8:
            return None
        r, b, u, s, w, p, a, f = parts
        if r not in ROOFS or b not in BASES or u not in UPPERS or s not in SCREENS or w not in WINDOWS \
                or a not in ACCENTS or f not in FEATURES:
            return None
        return cls(r, b, u, s, w, p == "p", a, f)

    def name(self) -> str:
        bits = [NAMES[self.feature] if self.feature != "none" else
                (NAMES[self.upper] if self.upper != "plaster" else NAMES[self.base]),
                NAMES[self.screen] if self.screen != "none" else "", NAMES[self.roof]]
        return " ".join(b for b in bits if b) + " House"

    def story(self) -> str:
        roof = {"flat": "a parapet roof terrace", "slab": "a thin cantilevered roof slab", "mono": "a single-pitch roof over a clerestory",
                "butterfly": "a butterfly roof", "hip": "a hipped tile roof on deep eaves", "gable": "a pitched gable roof"}[self.roof]
        base = {"plaster": "a lime-plaster ground floor", "stone": "a stone-clad ground floor", "brick": "an exposed-brick ground floor",
                "concrete": "a board-marked concrete ground floor"}[self.base]
        upper = {"plaster": "plastered floors above", "timber": "timber-boarded floors above", "metal": "dark metal-clad floors above",
                 "brick": "brick floors above"}[self.upper]
        screen = {"none": "", "fins": ", vertical fins shading the street face", "louvres": ", horizontal louvres across the street face",
                  "frame": ", a deep frame around the upper floor", "jaali": ", a jaali screen against the hard sun",
                  "perforated": ", a perforated metal screen"}[self.screen]
        win = ", glazing in continuous bands" if self.windows == "band" else ""
        plant = ", planters along the edges" if self.planters else ""
        feat = {"none": "", "jharokha": ", jharokha bays projecting over the street",
                "colonnade": ", a colonnaded verandah along the front", "chhatri": ", chhatri pavilions on the roof",
                "cornice": ", deep cornices marking every floor", "breeze": ", a breeze-block screen wall",
                "greenwall": ", a planted green wall"}[self.feature]
        return f"{base[0].upper()}{base[1:]}, {upper}{screen}{feat}{win}{plant}, under {roof}."

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name(), "story": self.story(), **asdict(self)}


def generate(plan: FloorPlan, n: int = 10, prefer: dict[str, list[str]] | None = None) -> list[Exterior]:
    """A varied set of designs for this plan: style-biased, never two alike."""
    seed = int(hashlib.sha1((plan.id or "x").encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    style = plan.style or "contemporary"
    bias = dict(STYLE_BIAS.get(style, STYLE_BIAS["contemporary"]))
    for k, v in (prefer or {}).items():
        if v:
            bias[k] = tuple(v)
    one_floor = len(plan.levels) <= 1

    def pick(key: str, pool: tuple[str, ...]) -> str:
        # The chosen style leads: most designs stay inside its vocabulary.
        fav = [x for x in bias.get(key, ()) if x in pool]
        return rng.choice(fav) if fav and rng.random() < 0.85 else rng.choice(pool)

    out: list[Exterior] = []
    seen: set[tuple] = set()
    tries = 0
    while len(out) < n and tries < 400:
        tries += 1
        e = Exterior(
            roof=pick("roof", ROOFS),
            base=pick("base", BASES),
            upper="plaster" if one_floor else pick("upper", UPPERS),
            screen=pick("screen", SCREENS),
            windows=rng.choice(WINDOWS),
            planters=rng.random() < 0.35,
            accent=pick("accent", tuple(ACCENTS)),
            feature=pick("feature", FEATURES),
        )
        # Combinations an architect would not draw.
        if e.roof in ("hip", "gable") and e.screen in ("perforated",):
            continue
        if e.base == e.upper == "brick" and e.screen == "jaali":
            continue
        if e.feature == "chhatri" and e.roof != "flat":
            continue                         # chhatris stand on a flat roof
        if e.feature == "jharokha" and one_floor:
            continue
        sig = (e.roof, e.screen, e.upper, e.base, e.feature)
        if sig in seen:
            continue
        seen.add(sig)
        out.append(e)
    return out


# ---------------------------------------------------------------------------
# Building it
# ---------------------------------------------------------------------------

def skins(ex: Exterior, n_levels: int) -> dict[int, str]:
    """The wall material of each floor's outside face."""
    out = {}
    for i in range(n_levels):
        skin = ex.base if i == 0 else ex.upper
        if skin in SKIN:
            out[i] = SKIN[skin]
    return out


def door_spans(level, e: Edge, margin: float = 0.45, windows: bool = False) -> list[tuple[float, float]]:
    """Where along an outside edge its doors are, as fractions of the edge,
    widened by a margin: nothing a facade adds may stand in a doorway."""
    L = e.length
    if L < 1e-6:
        return []
    out = []
    d = e.dir
    for w in getattr(level, "walls", []):
        doors = [o for o in w.openings if windows or o.kind.is_door or o.kind.value in ("french_window", "sliding_door")]
        if not doors:
            continue
        a, c = Vec2(w.start.x, w.start.y), Vec2(w.end.x, w.end.y)
        # On this edge's line: both ends within a wall's thickness of it.
        n = Vec2(-d.y, d.x)
        if abs((a - e.a).dot(n)) > 0.3 or abs((c - e.a).dot(n)) > 0.3:
            continue
        for o in doors:
            p = a + (c - a) * o.position
            t = (p - e.a).dot(d) / L
            half = (o.width / 2 + margin + (0.35 if o.kind.value == "main_door" else 0.0)) / L
            out.append((t - half, t + half))
    return out


def clear(t0: float, t1: float, spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """The parts of [t0, t1] that stay clear of every span."""
    parts = [(t0, t1)]
    for a, b in spans:
        nxt = []
        for x, y in parts:
            if b <= x or a >= y:
                nxt.append((x, y))
                continue
            if a > x:
                nxt.append((x, a))
            if b < y:
                nxt.append((b, y))
        parts = nxt
    return [(x, y) for x, y in parts if y - x > 1e-3]


def _free(t: float, half: float, spans) -> bool:
    return all(t + half <= a or t - half >= b for a, b in spans)


def _box(b, node, mat, p: Vec2, y: float, size, yaw: float) -> None:
    b.box(node, mat, (p.x, y, -p.y), size, yaw)


def _yaw(e: Edge) -> float:
    return math.atan2(e.dir.y, e.dir.x)


SKIN = {"stone": "clad", "brick": "ex_brick", "concrete": "ex_concrete", "timber": "ex_timber", "metal": "ex_metal"}


def apply(b, plan: FloorPlan, ex: Exterior, levels: list[tuple[Any, float, Any]], road: Vec2 | None,
          roof_y: float) -> dict[str, Any]:
    """Dress the house in the design; return the roof the builder should draw."""
    street = lambda e: road is None or e.out.dot(road) > 0.6  # noqa: E731
    b.p.m["ex_accent"] = b.p.m["frame"].__class__("exterior_accent", _rgb(ACCENTS[ex.accent]), 0.5, 0.3)
    n = len(levels)
    for li, (level, base, fp) in enumerate(levels):
        h = level.floor_to_floor
        node = f"level_{level.index}/facade"
        skin = ex.base if li == 0 else ex.upper
        for e in edges(fp):
            L, yaw = e.length, _yaw(e)
            spans = door_spans(level, e)
            # A slab band between floors marks each storey on the skin.
            if li > 0 and skin != "plaster":
                _box(b, node, "slab", e.at(0.5, 0.06), base - 0.08, (L + 0.12, 0.16, 0.1), yaw)
            if ex.windows == "band" and street(e) and L > 2.5:
                # The glazing band stops either side of a door; it never covers one.
                for t0, t1 in clear(0.07, 0.93, spans):
                    if (t1 - t0) * L > 0.8:
                        _box(b, node, "ex_glassband", e.at((t0 + t1) / 2, 0.06), base + 1.55, ((t1 - t0) * L, 1.2, 0.04), yaw)
            upper = li >= 1 or n == 1
            if upper and street(e):
                _screen(b, node, ex.screen, e, L, yaw, base, h, spans, ground=li == 0)
            if ex.planters and li == 0 and street(e) and L > 3:
                for t in (0.18, 0.82):
                    if not _free(t, 0.9 / L, spans):
                        continue               # never a planter in front of a door
                    p = e.at(t, 0.55)
                    _box(b, node, "ex_concrete", p, base + 0.25, (1.2, 0.5, 0.5), yaw)
                    b.blob(node, "leaf", (p.x, base + 0.62, -p.y), 0.34, 0.8)
        if li == n - 1 and ex.planters and ex.roof in ("flat", "slab"):
            for e in edges(fp):
                if street(e) and e.length > 3:
                    p = e.at(0.5, -0.35)
                    _box(b, "roof", "ex_concrete", p, roof_y + 0.22, (min(3.0, e.length * 0.5), 0.4, 0.4), _yaw(e))
                    b.blob("roof", "leaf", (p.x, roof_y + 0.55, -p.y), 0.3, 0.7)
    _feature(b, ex, levels, street, roof_y)
    return {"roof": {"flat": "flat", "slab": "slab", "mono": "pitch", "butterfly": "butterfly", "hip": "hip", "gable": "gable"}[ex.roof]}


def _feature(b, ex: Exterior, levels, street, roof_y: float) -> None:
    """The design's signature element, always clear of doors (and of windows
    where it would cover them)."""
    f = ex.feature
    if f == "none" or not levels:
        return
    n = len(levels)
    for li, (level, base, fp) in enumerate(levels):
        h = level.floor_to_floor
        node = f"level_{level.index}/facade"
        for e in edges(fp):
            L, yaw = e.length, _yaw(e)
            doors = door_spans(level, e)
            if f == "colonnade" and li == 0 and street(e) and L > 3.0:
                # Posts along the front, a beam and a shallow roof: the verandah line.
                k = max(2, int(L / 2.4))
                for i in range(k + 1):
                    t = i / k
                    if _free(t, 0.2 / L, doors):
                        p = e.at(t, 1.5)
                        b.cylinder(node, "plaster", (p.x, base, -p.y), 0.13, h - 0.25, 14)
                        _box(b, node, "slab", p, base + 0.04, (0.42, 0.08, 0.42), yaw)
                _box(b, node, "ex_accent", e.at(0.5, 1.5), base + h - 0.32, (L + 0.3, 0.26, 0.3), yaw)
                b.slab(node, "slab", [e.at(0, 0), e.at(1, 0), e.at(1, 1.75), e.at(0, 1.75)], base + h - 0.18, base + h - 0.06)
            elif f == "jharokha" and li >= 1 and street(e) and L > 3.0:
                # Projecting bay windows on brackets, each under a small canopy.
                wins = clear(0.12, 0.88, door_spans(level, e, 0.3))
                for t0, t1 in wins[:2]:
                    w = min(1.8, (t1 - t0) * L * 0.8)
                    if w < 1.0:
                        continue
                    c = e.at((t0 + t1) / 2, 0.38)
                    _box(b, node, "ex_accent", c, base + 0.55, (w, 0.14, 0.76), yaw)
                    for s_ in (-1, 1):
                        _box(b, node, "joinery", c + e.dir * (s_ * (w / 2 - 0.05)), base + 1.25, (0.1, 1.3, 0.7), yaw)
                    _box(b, node, "ex_glassband", c + e.out * 0.3, base + 1.25, (w - 0.2, 1.1, 0.04), yaw)
                    _box(b, node, "ex_accent", c, base + 1.98, (w + 0.3, 0.12, 0.95), yaw)
                    b.blob(node, "ex_accent", (c.x, base + 2.1, -c.y), w * 0.32, 0.45)
            elif f == "cornice":
                _box(b, node, "slab", e.at(0.5, 0.2), base + h - 0.12, (L + 0.5, 0.2, 0.42), yaw)
                _box(b, node, "ex_accent", e.at(0.5, 0.26), base + h - 0.3, (L + 0.42, 0.1, 0.3), yaw)
            elif f == "breeze" and li == min(1, n - 1) and street(e) and L > 3.0:
                # A breeze-block panel between the windows: shade with air through it.
                for t0, t1 in clear(0.08, 0.92, door_spans(level, e, 0.2, windows=True)):
                    w = (t1 - t0) * L
                    if w < 1.0:
                        continue
                    c = e.at((t0 + t1) / 2, 0.12)
                    cols, rows = max(2, int(w / 0.4)), max(3, int((h - 0.6) / 0.4))
                    for i in range(cols):
                        for j in range(rows):
                            if (i + j) % 2 == 0:
                                q = c + e.dir * (-w / 2 + (i + 0.5) * w / cols)
                                _box(b, node, "ex_concrete", q, base + 0.3 + (j + 0.5) * (h - 0.6) / rows,
                                     (w / cols - 0.06, (h - 0.6) / rows - 0.06, 0.12), yaw)
            elif f == "greenwall" and not street(e) and L > 3.0 and li == 0:
                # A planted wall on the garden side, clear of every opening.
                for t0, t1 in clear(0.05, 0.95, door_spans(level, e, 0.2, windows=True)):
                    w = (t1 - t0) * L
                    if w < 1.2:
                        continue
                    c = e.at((t0 + t1) / 2, 0.08)
                    _box(b, node, "ex_concrete", c, base + h / 2, (w, h - 0.3, 0.06), yaw)
                    for i in range(max(2, int(w / 0.6))):
                        for j in range(max(3, int((h - 0.4) / 0.6))):
                            q = c + e.dir * (-w / 2 + 0.3 + i * 0.6) + e.out * 0.1
                            b.blob(node, "leaf" if (i + j) % 2 else "leaf2", (q.x, base + 0.35 + j * 0.6, -q.y), 0.27, 0.8)
    if f == "chhatri" and ex.roof == "flat":
        level, base, fp = levels[-1]
        if fp is not None and not fp.is_empty:
            x0, y0, x1, y1 = fp.bounds
            for cx, cy in ((x0 + 0.9, y0 + 0.9), (x1 - 0.9, y1 - 0.9)):
                for dx in (-0.45, 0.45):
                    for dy in (-0.45, 0.45):
                        b.cylinder("roof", "plaster", (cx + dx, roof_y + 0.2, -(cy + dy)), 0.07, 1.5, 10)
                b.slab("roof", "slab", [Vec2(cx - 0.65, cy - 0.65), Vec2(cx + 0.65, cy - 0.65), Vec2(cx + 0.65, cy + 0.65),
                                        Vec2(cx - 0.65, cy + 0.65)], roof_y + 1.7, roof_y + 1.82)
                b.blob("roof", "ex_accent", (cx, roof_y + 2.05, -cy), 0.6, 0.6)


def _screen(b, node, kind, e: Edge, L: float, yaw: float, base: float, h: float,
            spans: list[tuple[float, float]] = (), ground: bool = False) -> None:
    """The street screen, kept out of every doorway: fins and slats are left
    out where a door is, louvres, jaali and frame beams run either side of it."""
    spans = list(spans)
    if kind == "fins":
        k = max(3, int(L / 0.45))
        for i in range(k):
            t = (i + 0.5) / k
            if _free(t, 0.05 / L, spans):
                _box(b, node, "ex_accent", e.at(t, 0.22), base + h / 2, (0.06, h - 0.1, 0.38), yaw)
    elif kind == "louvres":
        rows = int((h - 0.4) / 0.22)
        for t0, t1 in clear(0.04, 0.96, spans):
            for j in range(rows):
                _box(b, node, "ex_accent", e.at((t0 + t1) / 2, 0.28), base + 0.3 + j * 0.22, ((t1 - t0) * L, 0.05, 0.22), yaw)
    elif kind == "frame":
        d = 0.75
        # On the ground floor the frame has no sill beam: it would be a kerb across the door.
        for y in ((base + h - 0.1,) if ground else (base + 0.05, base + h - 0.1)):
            _box(b, node, "ex_accent", e.at(0.5, d / 2), y, (L + 0.5, 0.22, d), yaw)
        for t, s in ((0.0, 1), (1.0, -1)):
            _box(b, node, "ex_accent", e.at(t, d / 2) + e.dir * (s * 0.14), base + h / 2, (0.22, h, d), yaw)
    elif kind == "jaali" and L > 2.0:
        rows = int((h - 0.6) / 0.2)
        for t0, t1 in clear(0.2, 0.8, spans):
            w = (t1 - t0) * L
            if w < 0.8:
                continue
            s0 = e.at((t0 + t1) / 2, 0.32)
            cols = max(2, int(w / 0.2))
            for i in range(cols + 1):
                _box(b, node, "joinery", s0 + e.dir * (-w / 2 + i * w / cols), base + 0.3 + (h - 0.6) / 2, (0.04, h - 0.6, 0.05), yaw)
            for j in range(rows + 1):
                _box(b, node, "joinery", s0, base + 0.3 + j * (h - 0.6) / rows, (w, 0.04, 0.05), yaw)
    elif kind == "perforated" and L > 2.0:
        w = L * 0.55
        k = max(6, int(w / 0.12))
        for i in range(k):
            t = 0.62 - 0.275 + (i + 0.5) * 0.55 / k
            if not _free(t, 0.06 / L, spans):
                continue
            gap = 0.03 + 0.05 * abs(math.sin(i * 0.7))       # a slatted rhythm reads as perforation
            _box(b, node, "ex_metal", e.at(t, 0.3), base + h / 2, (w / k - gap, h - 0.3, 0.03), yaw)


def _rgb(hex_: str) -> tuple[float, float, float]:
    v = hex_.lstrip("#")
    return tuple(int(v[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def roof(b, kind: str, footprint, y: float, road: Vec2 | None, slab_mat: str = "slab") -> bool:
    """Roofs the builder does not already draw. True if drawn."""
    if footprint is None or footprint.is_empty:
        return False
    x0, y0, x1, y1 = footprint.bounds
    if kind == "slab":
        # A thin roof plate cantilevered well past the walls, with a fascia.
        o = 0.6
        b.slab("roof", slab_mat, [Vec2(x0 - o, y0 - o), Vec2(x1 + o, y0 - o), Vec2(x1 + o, y1 + o), Vec2(x0 - o, y1 + o)], y, y + 0.18)
        return True
    if kind == "pitch":
        pitch_roof(b, footprint, y, road)
        return True
    if kind in ("butterfly", "gable"):
        eave = 0.6
        x0, y0, x1, y1 = x0 - eave, y0 - eave, x1 + eave, y1 + eave
        along_x = (x1 - x0) >= (y1 - y0)
        mid = (y0 + y1) / 2 if along_x else (x0 + x1) / 2
        rise = (min(x1 - x0, y1 - y0)) * (0.12 if kind == "butterfly" else 0.3)
        # Ridge (gable) or valley (butterfly) along the long axis.
        r = rise if kind == "gable" else -rise * 0.6
        lo = y + 0.2 + (0 if kind == "gable" else rise)
        P = lambda px, py, h: (px, h, -py)  # noqa: E731
        mat = "roof_tile" if kind == "gable" else "ex_metal"
        if along_x:
            A, B, C, D = P(x0, y0, lo), P(x1, y0, lo), P(x1, y1, lo), P(x0, y1, lo)
            M0, M1 = P(x0, mid, lo + r), P(x1, mid, lo + r)
            b.quad_strip("roof", mat, A, B, M1, M0)
            b.quad_strip("roof", mat, M0, M1, C, D)
            b.tri("roof", "plaster", A, M0, D) if kind == "gable" else None
            b.tri("roof", "plaster", B, C, M1) if kind == "gable" else None
        else:
            A, B, C, D = P(x0, y0, lo), P(x1, y0, lo), P(x1, y1, lo), P(x0, y1, lo)
            M0, M1 = P(mid, y0, lo + r), P(mid, y1, lo + r)
            b.quad_strip("roof", mat, A, M0, M1, D)
            b.quad_strip("roof", mat, M0, B, C, M1)
            b.tri("roof", "plaster", A, B, M0) if kind == "gable" else None
            b.tri("roof", "plaster", D, C, M1) if kind == "gable" else None
        if kind == "butterfly":
            # Walls carried up to meet the raised outer edges.
            fx0, fy0, fx1, fy1 = footprint.bounds
            b.slab("roof", "plaster", [Vec2(fx0, fy0), Vec2(fx1, fy0), Vec2(fx1, fy1), Vec2(fx0, fy1)], y, y + 0.2)
        return True
    return False
