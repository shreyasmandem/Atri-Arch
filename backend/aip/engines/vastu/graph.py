"""Vastu Knowledge Graph (VKG) and its constraint reasoner.

Why a graph rather than a rule list
-----------------------------------

The rule table in `knowledge.py` answers only the questions it was told the
answer to. Ask it where a home gym belongs and it has nothing to say, because
nobody wrote a `VS.GYM.*` rule. That is the structural weakness of every
computational Vastu system surveyed for this project: they are lookup tables
wearing the vocabulary of a reasoning system, and their coverage is exactly the
size of their table.

This module represents the doctrine as a **typed, weighted, directed graph** and
derives verdicts by **path traversal**. Rooms connect to the activities they
host, activities to the elemental principle (tattva) they embody, tattvas to the
quarters that carry them, and quarters to compass directions. A verdict for
"gym in the north-west" is then computed rather than looked up:

    gym --HOSTS--> exertion --EMBODIES--> vayu --CARRIED_BY--> vayavya
                                                    <--LIES_IN-- NW

That is a *supporting* path of length four. The same traversal finds
*conflicting* paths through the OPPOSES edges between tattvas, which is how the
graph knows a kitchen in the north-east is wrong without anyone ever writing
that rule down: fire opposes water, and the north-east carries water.

Three properties follow, and they are why the graph earns its place:

* **Coverage beyond the table.** Any room whose activity is modelled gets a
  verdict for every direction, from an authored graph of a few hundred edges.
* **Determinism.** Traversal over a fixed graph returns the same score for the
  same layout every time. A retrieval-augmented language model does not.
* **Proof.** Every score arrives with the literal path that produced it, so the
  explanation *is* the derivation rather than prose written afterwards.

Where an explicit classical rule exists it still wins: the reasoner treats the
authored corpus as ground truth and the graph as the generaliser covering what
the texts never enumerated. Both are reported, and disagreements between them
are surfaced rather than hidden.
"""

from __future__ import annotations

import heapq
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache

from aip.domain.geometry import Direction
from aip.domain.plan import RoomType


class NodeKind(str, Enum):
    """What a node in the graph represents."""

    DIRECTION = "direction"    # a compass sector, N .. NNW, plus CENTRE
    QUARTER = "quarter"        # Ishanya, Agneya, Nairutya, Vayavya, Brahmasthan
    TATTVA = "tattva"          # the five elements: prithvi, jala, agni, vayu, akasha
    DEITY = "deity"            # the presiding devata of a quarter
    ACTIVITY = "activity"      # what people do: cooking, sleeping, ablution
    ROOM = "room"              # a RoomType
    QUALITY = "quality"        # heavy, light, wet, hot, sacred, still


class EdgeKind(str, Enum):
    """Typed relations. Direction of travel matters to the reasoner."""

    LIES_IN = "lies_in"                      # DIRECTION -> QUARTER
    CARRIES = "carries"                      # QUARTER   -> TATTVA
    PRESIDED_BY = "presided_by"              # QUARTER   -> DEITY
    HOSTS = "hosts"                          # ROOM      -> ACTIVITY
    EMBODIES = "embodies"                    # ACTIVITY  -> TATTVA
    DEMANDS = "demands"                      # ACTIVITY  -> QUALITY
    AFFORDS = "affords"                      # QUARTER   -> QUALITY
    OPPOSES = "opposes"                      # TATTVA   <-> TATTVA (symmetric)
    DEFILES = "defiles"                      # ACTIVITY  -> QUALITY, ritual pollution
    HARMONISES = "harmonises"                # TATTVA   <-> TATTVA (symmetric)
    ASSERTED_FAVOUR = "asserted_favour"      # QUARTER -> ROOM, straight from a text
    ASSERTED_PROHIBIT = "asserted_prohibit"  # QUARTER -> ROOM, straight from a text


@dataclass(frozen=True, slots=True)
class Node:
    id: str
    kind: NodeKind
    label: str
    sanskrit: str = ""
    gloss: str = ""


@dataclass(frozen=True, slots=True)
class Edge:
    source: str
    target: str
    kind: EdgeKind
    #: Strength of the relation in [0, 1]. Traversal multiplies these, so a long
    #: chain of weak links cannot outvote a short strong one.
    weight: float = 1.0
    #: Where the claim comes from. Empty means it is a modelling decision of
    #: this project rather than a textual assertion, and is labelled as such.
    source_text: str = ""
    rationale: str = ""


@dataclass(slots=True)
class Path:
    """A derivation: the chain of edges that produced a verdict."""

    nodes: list[str]
    edges: list[Edge]
    polarity: int          # +1 supports the placement, -1 contradicts it
    score: float           # product of edge weights, in [0, 1]

    @property
    def length(self) -> int:
        return len(self.edges)

    def render(self, graph: VastuGraph) -> str:
        """The derivation as a readable chain."""
        parts: list[str] = []
        for i, edge in enumerate(self.edges):
            parts.append(graph.node(self.nodes[i]).label)
            parts.append(f"-[{edge.kind.value}]->")
        parts.append(graph.node(self.nodes[-1]).label)
        return " ".join(parts)

    def citations(self) -> list[str]:
        return sorted({e.source_text for e in self.edges if e.source_text})


class VastuGraph:
    """A typed multigraph with path-based inference."""

    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._out: dict[str, list[Edge]] = defaultdict(list)
        self._in: dict[str, list[Edge]] = defaultdict(list)

    # -- construction ------------------------------------------------------

    def add_node(self, node: Node) -> None:
        self._nodes[node.id] = node

    def add_edge(self, edge: Edge, symmetric: bool = False) -> None:
        if edge.source not in self._nodes or edge.target not in self._nodes:
            raise KeyError(f"edge references an unknown node: {edge.source} -> {edge.target}")
        self._out[edge.source].append(edge)
        self._in[edge.target].append(edge)
        if symmetric:
            mirror = Edge(edge.target, edge.source, edge.kind, edge.weight,
                          edge.source_text, edge.rationale)
            self._out[mirror.source].append(mirror)
            self._in[mirror.target].append(mirror)

    # -- access ------------------------------------------------------------

    def node(self, node_id: str) -> Node:
        return self._nodes[node_id]

    def has(self, node_id: str) -> bool:
        return node_id in self._nodes

    def out_edges(self, node_id: str) -> list[Edge]:
        return self._out.get(node_id, [])

    def in_edges(self, node_id: str) -> list[Edge]:
        return self._in.get(node_id, [])

    def nodes_of(self, kind: NodeKind) -> list[Node]:
        return [n for n in self._nodes.values() if n.kind is kind]

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        return sum(len(v) for v in self._out.values())

    def statistics(self) -> dict[str, object]:
        by_node: dict[str, int] = defaultdict(int)
        for n in self._nodes.values():
            by_node[n.kind.value] += 1
        by_edge: dict[str, int] = defaultdict(int)
        cited = 0
        for edges in self._out.values():
            for e in edges:
                by_edge[e.kind.value] += 1
                if e.source_text:
                    cited += 1
        rooms = len(self.nodes_of(NodeKind.ROOM))
        directions = len(self.nodes_of(NodeKind.DIRECTION))
        return {
            "nodes": self.node_count,
            "edges": self.edge_count,
            "nodes_by_kind": dict(sorted(by_node.items())),
            "edges_by_kind": dict(sorted(by_edge.items())),
            "textually_cited_edges": cited,
            "rooms": rooms,
            "directions": directions,
            "derivable_placements": rooms * directions,
        }

    # -- inference ---------------------------------------------------------

    def paths(
        self,
        start: str,
        goal: str,
        *,
        max_depth: int = 6,
        max_paths: int = 6,
        min_score: float = 0.04,
    ) -> list[Path]:
        """Best-first search for derivations from `start` to `goal`.

        Each traversal of an ``OPPOSES`` edge flips the polarity of the path, so
        one search finds supporting and contradicting derivations at the same
        time: an even number of oppositions supports the placement, an odd
        number contradicts it. The frontier is ordered by accumulated score, so
        the strongest derivations surface first and the search stops early
        rather than enumerating a combinatorial space.
        """
        found: list[Path] = []
        frontier: list[tuple[float, int, str, tuple[str, ...], tuple[Edge, ...], int]] = [
            (-1.0, 0, start, (start,), (), 1)
        ]
        tie = 0
        best_seen: dict[tuple[str, int], float] = {}

        while frontier and len(found) < max_paths:
            neg, _, current, nodes, edges, polarity = heapq.heappop(frontier)
            score = -neg

            if current == goal and edges:
                found.append(Path(list(nodes), list(edges), polarity, round(score, 6)))
                continue
            if len(edges) >= max_depth:
                continue

            # Reaching the same node with the same polarity at a worse score
            # cannot lead to a better derivation.
            key = (current, polarity)
            if best_seen.get(key, 0.0) > score + 1e-9:
                continue
            best_seen[key] = max(best_seen.get(key, 0.0), score)

            for edge in self._out.get(current, []):
                if edge.target in nodes:          # no cycles
                    continue
                nxt = score * edge.weight
                if nxt < min_score:
                    continue
                flip = -1 if edge.kind in (EdgeKind.OPPOSES, EdgeKind.DEFILES) else 1
                tie += 1
                heapq.heappush(frontier, (
                    -nxt, tie, edge.target, (*nodes, edge.target),
                    (*edges, edge), polarity * flip,
                ))

        return found


# ---------------------------------------------------------------------------
# Authoring the graph
# ---------------------------------------------------------------------------

QUARTER_OF_DIRECTION: dict[Direction, str] = {
    Direction.N: "q_uttara", Direction.NNE: "q_ishanya", Direction.NE: "q_ishanya",
    Direction.ENE: "q_ishanya", Direction.E: "q_purva", Direction.ESE: "q_agneya",
    Direction.SE: "q_agneya", Direction.SSE: "q_agneya", Direction.S: "q_dakshina",
    Direction.SSW: "q_nairutya", Direction.SW: "q_nairutya", Direction.WSW: "q_nairutya",
    Direction.W: "q_paschima", Direction.WNW: "q_vayavya", Direction.NW: "q_vayavya",
    Direction.NNW: "q_vayavya", Direction.CENTRE: "q_brahmasthan",
}

#: What each room is actually *for*. This join is what lets the graph reason
#: about rooms the classical texts never enumerated: a home gym is unknown to
#: the Mayamata, but exertion is not unknown to the doctrine of vayu.
ROOM_ACTIVITIES: dict[RoomType, list[tuple[str, float]]] = {
    RoomType.KITCHEN: [("a_cooking", 1.0), ("a_storage", 0.3)],
    RoomType.PANTRY: [("a_storage", 0.9), ("a_cooking", 0.3)],
    RoomType.DINING: [("a_gathering", 0.9), ("a_cooking", 0.2)],
    RoomType.LIVING: [("a_gathering", 1.0), ("a_receiving", 0.9)],
    RoomType.DRAWING: [("a_receiving", 1.0), ("a_gathering", 0.7)],
    RoomType.FAMILY: [("a_gathering", 1.0), ("a_rest", 0.4)],
    RoomType.MASTER_BEDROOM: [("a_sleeping", 1.0), ("a_rest", 0.9)],
    RoomType.BEDROOM: [("a_sleeping", 1.0), ("a_rest", 0.8)],
    RoomType.GUEST_BEDROOM: [("a_sleeping", 0.9), ("a_receiving", 0.4)],
    RoomType.CHILDREN_BEDROOM: [("a_sleeping", 0.9), ("a_study", 0.6)],
    RoomType.STUDY: [("a_study", 1.0)],
    RoomType.HOME_OFFICE: [("a_study", 1.0), ("a_receiving", 0.3)],
    RoomType.LIBRARY: [("a_study", 1.0), ("a_storage", 0.5)],
    RoomType.BATHROOM: [("a_ablution", 1.0)],
    RoomType.TOILET: [("a_ablution", 0.7), ("a_waste", 1.0)],
    RoomType.POWDER: [("a_ablution", 0.6), ("a_waste", 0.8)],
    RoomType.PUJA: [("a_worship", 1.0)],
    RoomType.STORE: [("a_storage", 1.0)],
    RoomType.WARDROBE: [("a_storage", 0.9)],
    RoomType.UTILITY: [("a_washing", 1.0), ("a_waste", 0.4)],
    # Washing carries grey water out of the house, so laundry is sanitation as
    # much as it is washing. Without the waste component the graph reads it as
    # pure water-work and drifts it into the sacred quarter.
    RoomType.LAUNDRY: [("a_washing", 1.0), ("a_waste", 0.5)],
    RoomType.STAIRCASE: [("a_circulation", 1.0), ("a_bearing", 0.7)],
    RoomType.CORRIDOR: [("a_circulation", 1.0)],
    RoomType.FOYER: [("a_circulation", 0.8), ("a_receiving", 0.9)],
    RoomType.LOBBY: [("a_circulation", 0.8), ("a_receiving", 0.8)],
    RoomType.BALCONY: [("a_rest", 0.6), ("a_gathering", 0.4)],
    RoomType.VERANDAH: [("a_rest", 0.7), ("a_receiving", 0.6)],
    RoomType.TERRACE: [("a_rest", 0.6)],
    RoomType.COURTYARD: [("a_void", 1.0)],
    RoomType.GARAGE: [("a_bearing", 0.8), ("a_storage", 0.6)],
    RoomType.SERVANT: [("a_sleeping", 0.7), ("a_rest", 0.5)],
    RoomType.GYM: [("a_exertion", 1.0)],
    RoomType.HOME_THEATRE: [("a_screening", 1.0), ("a_gathering", 0.5)],
    RoomType.SHAFT: [("a_void", 0.7)],
}


@lru_cache(maxsize=1)
def build_graph() -> VastuGraph:
    """Author the VKG once and cache it. Construction is pure data."""
    g = VastuGraph()

    # -- tattvas ----------------------------------------------------------
    for nid, label, sans, gloss in [
        ("t_prithvi", "Earth", "Prithvi", "Mass, stability, permanence."),
        ("t_jala", "Water", "Jala", "Flow, purity, coolness."),
        ("t_agni", "Fire", "Agni", "Heat, transformation, digestion."),
        ("t_vayu", "Air", "Vayu", "Movement, circulation, dispersal."),
        ("t_akasha", "Space", "Akasha", "Void, openness, the unbuilt centre."),
    ]:
        g.add_node(Node(nid, NodeKind.TATTVA, label, sans, gloss))

    # The elemental oppositions are the engine of the reasoner: they are what
    # lets a path *contradict* a placement rather than merely fail to support it.
    for a, b, w, why in [
        ("t_agni", "t_jala", 1.0,
         "Fire and water annihilate one another; the texts keep their quarters diagonally opposed."),
        ("t_prithvi", "t_akasha", 0.8,
         "Mass negates void; building over the Brahmasthan is the archetypal fault."),
        ("t_agni", "t_vayu", 0.35,
         "Air feeds fire, so proximity is a hazard rather than a harmony."),
    ]:
        g.add_edge(Edge(a, b, EdgeKind.OPPOSES, w, rationale=why), symmetric=True)

    for a, b, w, why in [
        ("t_jala", "t_akasha", 0.7,
         "Water and void share the auspicious north-east; both are treated as light."),
        ("t_prithvi", "t_agni", 0.5, "Mass contains and safely holds heat."),
        ("t_vayu", "t_akasha", 0.7, "Air needs void to move through."),
    ]:
        g.add_edge(Edge(a, b, EdgeKind.HARMONISES, w, rationale=why), symmetric=True)

    # -- deities ----------------------------------------------------------
    for nid, label, gloss in [
        ("d_ishana", "Ishana", "Lord of the north-east; the most auspicious quarter."),
        ("d_agni", "Agni", "Lord of fire, presiding over the south-east."),
        ("d_nirriti", "Nirriti", "Lord of the south-west; gravity and dissolution."),
        ("d_vayu", "Vayu", "Lord of wind, presiding over the north-west."),
        ("d_kubera", "Kubera", "Lord of wealth, presiding over the north."),
        ("d_yama", "Yama", "Lord of the south; restraint and rest."),
        ("d_indra", "Indra", "Lord of the east; the rising sun."),
        ("d_varuna", "Varuna", "Lord of the west; the setting sun and the waters."),
        ("d_brahma", "Brahma", "Seated at the centre; the Brahmasthan is his."),
    ]:
        g.add_node(Node(nid, NodeKind.DEITY, label, label, gloss))

    # -- qualities --------------------------------------------------------
    for nid, label, gloss in [
        ("k_heavy", "Heavy", "Wants mass, thick walls, structural weight."),
        ("k_light", "Light", "Wants openness, glazing, low mass."),
        ("k_wet", "Wet", "Involves standing or running water."),
        ("k_hot", "Hot", "Generates heat that must exhaust away from living space."),
        ("k_sacred", "Sacred", "Ritually charged; wants quiet and morning light."),
        ("k_still", "Still", "Wants acoustic calm and low traffic."),
        ("k_airy", "Airy", "Wants through-draught and dispersal."),
        ("k_dark", "Dark", "Wants daylight excluded and the enclosure visually sealed."),
    ]:
        g.add_node(Node(nid, NodeKind.QUALITY, label, gloss=gloss))

    # -- quarters ---------------------------------------------------------
    for nid, label, sans, deity, tattva, qualities in [
        ("q_ishanya", "North-east", "Ishanya", "d_ishana", "t_jala",
         [("k_light", 1.0), ("k_sacred", 0.9), ("k_wet", 0.8)]),
        ("q_agneya", "South-east", "Agneya", "d_agni", "t_agni", [("k_hot", 1.0)]),
        ("q_nairutya", "South-west", "Nairutya", "d_nirriti", "t_prithvi",
         [("k_heavy", 1.0), ("k_still", 0.9), ("k_dark", 0.9)]),
        ("q_vayavya", "North-west", "Vayavya", "d_vayu", "t_vayu", [("k_airy", 1.0)]),
        ("q_uttara", "North", "Uttara", "d_kubera", "t_jala", [("k_light", 0.9)]),
        ("q_purva", "East", "Purva", "d_indra", "t_akasha",
         [("k_light", 0.8), ("k_sacred", 0.6)]),
        ("q_dakshina", "South", "Dakshina", "d_yama", "t_prithvi",
         [("k_heavy", 0.8), ("k_still", 0.8), ("k_dark", 0.8)]),
        ("q_paschima", "West", "Paschima", "d_varuna", "t_prithvi",
         [("k_heavy", 0.6), ("k_dark", 0.7)]),
        ("q_brahmasthan", "Centre", "Brahmasthan", "d_brahma", "t_akasha", [("k_light", 0.7)]),
    ]:
        g.add_node(Node(nid, NodeKind.QUARTER, label, sans))
        g.add_edge(Edge(nid, deity, EdgeKind.PRESIDED_BY, 1.0,
                        source_text="Vastu-purusha-mandala, standard devata assignment"))
        g.add_edge(Edge(nid, tattva, EdgeKind.CARRIES, 1.0,
                        source_text="Pancha-bhuta assignment of the mandala quarters"))
        for q, w in qualities:
            # Symmetric: rooms reach qualities through DEMANDS and quarters
            # through AFFORDS, so making this traversable both ways opens a
            # second inference channel - functional fit - running parallel to
            # the elemental one. A study demanding light and a north quarter
            # affording it is a supporting derivation in its own right.
            g.add_edge(Edge(nid, q, EdgeKind.AFFORDS, w), symmetric=True)

    # -- directions -------------------------------------------------------
    principal = {"NE", "SE", "SW", "NW", "N", "E", "S", "W", "CENTRE"}
    for direction in Direction:
        nid = f"dir_{direction.value}"
        g.add_node(Node(nid, NodeKind.DIRECTION, direction.value, direction.sanskrit))
        # An intercardinal sits squarely in its quarter; an intermediate sector
        # adjacent to one participates in it more weakly.
        weight = 1.0 if direction.value in principal else 0.85
        g.add_edge(Edge(nid, QUARTER_OF_DIRECTION[direction], EdgeKind.LIES_IN, weight))

    # -- activities -------------------------------------------------------
    for nid, label, tattvas, qualities in [
        ("a_cooking", "Cooking", [("t_agni", 1.0)], [("k_hot", 1.0)]),
        ("a_ablution", "Bathing", [("t_jala", 1.0)], [("k_wet", 1.0)]),
        ("a_waste", "Sanitation", [("t_jala", 0.6)], [("k_wet", 1.0)]),
        ("a_washing", "Washing", [("t_jala", 0.9), ("t_vayu", 0.5)],
         [("k_wet", 0.9), ("k_airy", 0.7)]),
        ("a_sleeping", "Sleeping", [("t_prithvi", 0.9)], [("k_still", 1.0), ("k_heavy", 0.6)]),
        ("a_rest", "Resting", [("t_prithvi", 0.6)], [("k_still", 0.8)]),
        ("a_worship", "Worship", [("t_akasha", 0.8), ("t_jala", 0.5)],
         [("k_sacred", 1.0), ("k_light", 0.7)]),
        ("a_study", "Study", [("t_akasha", 0.7)], [("k_light", 1.0), ("k_still", 0.8)]),
        ("a_storage", "Storage", [("t_prithvi", 1.0)], [("k_heavy", 1.0)]),
        ("a_bearing", "Bearing load", [("t_prithvi", 1.0)], [("k_heavy", 1.0)]),
        ("a_gathering", "Gathering", [("t_akasha", 0.6)], [("k_light", 0.8)]),
        ("a_receiving", "Receiving guests", [("t_akasha", 0.6)], [("k_light", 0.8)]),
        ("a_circulation", "Circulation", [("t_vayu", 0.7)], [("k_airy", 0.8)]),
        ("a_exertion", "Physical exertion", [("t_vayu", 0.9)], [("k_airy", 1.0)]),
        ("a_void", "Remaining unbuilt", [("t_akasha", 1.0)], [("k_light", 1.0)]),
        ("a_screening", "Screen viewing", [("t_prithvi", 0.7)],
         [("k_dark", 1.0), ("k_still", 0.9)]),
    ]:
        g.add_node(Node(nid, NodeKind.ACTIVITY, label))
        for t, w in tattvas:
            g.add_edge(Edge(nid, t, EdgeKind.EMBODIES, w))
        for q, w in qualities:
            g.add_edge(Edge(nid, q, EdgeKind.DEMANDS, w))

    # Ritual pollution. Elementally a WC in the north-east looks harmonious -
    # ablution embodies water and Ishanya carries water - yet every text
    # prohibits it. The objection is shaucha, purity: sanitation defiles a
    # sacred quarter. Without this edge the graph reaches the opposite of the
    # doctrine by impeccable elemental logic, which is exactly the kind of
    # confident-and-wrong result a knowledge graph exists to prevent.
    g.add_edge(Edge("a_waste", "k_sacred", EdgeKind.DEFILES, 1.0,
                    source_text="Shaucha (ritual purity) doctrine",
                    rationale="Sanitation defiles a sacred quarter regardless of elemental fit."))
    # Darkness and daylight are the same axis read in opposite directions. The
    # edge is what stops a media room being derived into the brightest quarter
    # in the mandala on the strength of it also being a gathering space.
    g.add_edge(Edge("k_dark", "k_light", EdgeKind.OPPOSES, 1.0,
                    source_text="Functional reading of the mandala's light gradient",
                    rationale="A room that must exclude daylight cannot want the quarter that supplies it."),
               symmetric=True)

    g.add_edge(Edge("a_cooking", "k_sacred", EdgeKind.DEFILES, 0.35,
                    source_text="Shaucha (ritual purity) doctrine",
                    rationale="Cooking smoke and animal fat are mildly polluting to a shrine."))

    # -- rooms ------------------------------------------------------------
    for room_type, hosted in ROOM_ACTIVITIES.items():
        nid = f"room_{room_type.value}"
        g.add_node(Node(nid, NodeKind.ROOM, room_type.label))
        for activity, w in hosted:
            g.add_edge(Edge(nid, activity, EdgeKind.HOSTS, w))

    _attach_asserted_rules(g)
    return g


def _attach_asserted_rules(g: VastuGraph) -> None:
    """Lift the authored corpus into the graph as first-class edges.

    Textual assertion and derived inference then live in one structure, which is
    what lets the reasoner report where the two disagree instead of silently
    preferring one of them.
    """
    from aip.engines.vastu.knowledge import RULES

    for rule in RULES:
        if rule.subject is None:
            continue
        room = f"room_{rule.subject.value}"
        if not g.has(room):
            continue
        for direction in rule.ideal:
            quarter = QUARTER_OF_DIRECTION.get(direction)
            if quarter and g.has(quarter):
                g.add_edge(Edge(quarter, room, EdgeKind.ASSERTED_FAVOUR, rule.weight,
                                source_text=rule.citation, rationale=rule.title))
        for direction in rule.prohibited:
            quarter = QUARTER_OF_DIRECTION.get(direction)
            if quarter and g.has(quarter):
                g.add_edge(Edge(quarter, room, EdgeKind.ASSERTED_PROHIBIT, rule.weight,
                                source_text=rule.citation, rationale=rule.title))
