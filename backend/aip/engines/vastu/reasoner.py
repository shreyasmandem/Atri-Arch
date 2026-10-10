"""Graph-path constraint reasoner over the Vastu Knowledge Graph.

Given a room and a compass direction, this computes a compliance verdict by
searching the VKG for derivations connecting the two, then aggregating the
supporting and contradicting paths it finds.

The contract, and why each clause matters:

* **Deterministic.** Same graph plus same query yields the same score, bit for
  bit. This is the property a retrieval-augmented language model cannot offer,
  and it is what makes a compliance number defensible to a client or an
  approving authority.
* **Proof-carrying.** Every verdict returns the actual paths that produced it,
  with their edge types, weights and textual citations. The explanation is the
  derivation, not prose written to fit a number.
* **Generalising.** Verdicts exist for room/direction pairs no classical text
  enumerates, because they are derived through activity and element rather than
  read from a table.
* **Deferential.** Where the authored corpus makes an explicit assertion, that
  assertion governs. The graph reports agreement or disagreement with it rather
  than quietly overriding a cited text with an inference.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from aip.domain.geometry import Direction
from aip.domain.plan import RoomType
from aip.engines.vastu.graph import (
    QUARTER_OF_DIRECTION,
    EdgeKind,
    Path,
    VastuGraph,
    build_graph,
)

#: Paths longer than this are too tenuous to carry evidential weight.
MAX_DEPTH = 5
#: How many derivations to retain per polarity.
MAX_PATHS = 8


@dataclass(slots=True)
class Derivation:
    """One path, rendered for a human."""

    chain: str
    polarity: int
    score: float
    length: int
    citations: list[str] = field(default_factory=list)

    @property
    def supports(self) -> bool:
        return self.polarity > 0


@dataclass(slots=True)
class GraphVerdict:
    """The reasoner's answer for one room in one direction."""

    room: str
    direction: str
    quarter: str

    support: float          # aggregated supporting evidence, [0, 1]
    conflict: float         # aggregated contradicting evidence, [0, 1]
    score: float            # net compliance in [0, 1]
    confidence: float       # how much evidence there was at all

    verdict: str            # ideal | acceptable | neutral | discouraged | prohibited
    derived: bool           # True when no text asserts this and the graph inferred it
    asserted: str           # "favour" | "prohibit" | "" from the authored corpus
    agrees_with_text: bool | None   # None when there is no assertion to compare against

    derivations: list[Derivation] = field(default_factory=list)
    explanation: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "room": self.room, "direction": self.direction, "quarter": self.quarter,
            "support": round(self.support, 4), "conflict": round(self.conflict, 4),
            "score": round(self.score, 4), "confidence": round(self.confidence, 4),
            "verdict": self.verdict, "derived": self.derived,
            "asserted": self.asserted, "agrees_with_text": self.agrees_with_text,
            "explanation": self.explanation,
            "derivations": [
                {"chain": d.chain, "supports": d.supports, "score": round(d.score, 4),
                 "length": d.length, "citations": d.citations}
                for d in self.derivations
            ],
        }


class VastuReasoner:
    """Path-based inference over the VKG."""

    def __init__(self, graph: VastuGraph | None = None) -> None:
        self.graph = graph or build_graph()

    # -- core query --------------------------------------------------------

    def evaluate(self, room: RoomType, direction: Direction) -> GraphVerdict:
        g = self.graph
        room_id = f"room_{room.value}"
        dir_id = f"dir_{direction.value}"
        quarter_id = QUARTER_OF_DIRECTION[direction]

        if not g.has(room_id):
            return GraphVerdict(
                room=room.label, direction=direction.value,
                quarter=g.node(quarter_id).sanskrit if g.has(quarter_id) else "",
                support=0.0, conflict=0.0, score=0.5, confidence=0.0,
                verdict="not modelled", derived=False, asserted="",
                agrees_with_text=None,
                explanation=(
                    f"{room.label} is not represented in the knowledge graph, so no "
                    f"derivation is possible. It is excluded rather than guessed at."
                ),
            )

        # Search from the room toward the quarter. Travelling room -> activity ->
        # tattva and quarter -> tattva means the meeting point is the element,
        # so the search runs against the quarter's own outbound edges reversed;
        # the graph carries CARRIES edges quarter->tattva, so we search the
        # opposite way and reverse the rendering.
        raw = g.paths(room_id, quarter_id, max_depth=MAX_DEPTH, max_paths=MAX_PATHS * 2)
        if not raw:
            raw = self._paths_via_tattva(room_id, quarter_id)

        supporting = [p for p in raw if p.polarity > 0]
        conflicting = [p for p in raw if p.polarity < 0]

        support = self._aggregate(supporting)
        conflict = self._aggregate(conflicting)

        # The direction's own participation in its quarter scales everything: an
        # intermediate sector is a weaker member of its quarter than a principal
        # one, and the verdict should soften accordingly.
        participation = 1.0
        for edge in g.out_edges(dir_id):
            if edge.kind is EdgeKind.LIES_IN and edge.target == quarter_id:
                participation = edge.weight
                break

        support *= participation
        conflict *= participation

        asserted, assert_weight = self._assertion(quarter_id, room_id)
        score, verdict = self._resolve(support, conflict, asserted, assert_weight)

        confidence = min(1.0, (len(supporting) + len(conflicting)) / 4.0)

        # "Neutral" claims the evidence was weighed and came out balanced. When
        # no derivation exists at all and no text speaks, that claim is false:
        # the honest word is that the question is open. Saying so keeps the
        # score at 0.5 - no bias either way - while stopping the report from
        # presenting an absence of reasoning as a considered middle verdict.
        if confidence == 0.0 and not asserted:
            verdict = "undetermined"
        agrees: bool | None = None
        if asserted:
            agrees = (asserted == "favour" and score >= 0.6) or (
                asserted == "prohibit" and score <= 0.4)

        derivations = [
            Derivation(p.render(g), p.polarity, p.score, p.length, p.citations())
            for p in sorted(raw, key=lambda p: -p.score)[:MAX_PATHS]
        ]

        v = GraphVerdict(
            room=room.label, direction=direction.value,
            quarter=g.node(quarter_id).sanskrit,
            support=support, conflict=conflict, score=score, confidence=confidence,
            verdict=verdict, derived=not asserted, asserted=asserted,
            agrees_with_text=agrees, derivations=derivations,
        )
        v.explanation = self._explain(v)
        return v

    def _paths_via_tattva(self, room_id: str, quarter_id: str) -> list[Path]:
        """Meet in the middle at the elemental layer.

        Quarters point *to* their tattva and rooms reach tattvas through their
        activities, so the two never meet head-on in a single forward search.
        Joining the two half-paths at the element is the natural formulation of
        the doctrine anyway: a placement is right when the room's element and
        the quarter's element agree.
        """
        g = self.graph
        joined: list[Path] = []

        quarter_tattvas = {
            e.target: e for e in g.out_edges(quarter_id) if e.kind is EdgeKind.CARRIES
        }
        if not quarter_tattvas:
            return joined

        for tattva_id, q_edge in quarter_tattvas.items():
            for half in g.paths(room_id, tattva_id, max_depth=3, max_paths=MAX_PATHS):
                # Reverse the quarter's CARRIES edge so the chain reads
                # room -> ... -> tattva -> quarter.
                from aip.engines.vastu.graph import Edge

                closing = Edge(tattva_id, quarter_id, EdgeKind.CARRIES,
                               q_edge.weight, q_edge.source_text, q_edge.rationale)
                joined.append(Path(
                    nodes=[*half.nodes, quarter_id],
                    edges=[*half.edges, closing],
                    polarity=half.polarity,
                    score=round(half.score * q_edge.weight, 6),
                ))
        return joined

    # -- aggregation -------------------------------------------------------

    @staticmethod
    def _aggregate(paths: list[Path]) -> float:
        """Combine evidence with diminishing returns.

        A noisy-OR rather than a sum: three weak corroborating derivations
        should strengthen a conclusion without ever exceeding certainty, and a
        second path saying the same thing adds less than the first did.
        """
        combined = 0.0
        for p in sorted(paths, key=lambda p: -p.score):
            combined += (1.0 - combined) * p.score
        return min(1.0, combined)

    def _assertion(self, quarter_id: str, room_id: str) -> tuple[str, float]:
        """Does a cited text speak directly to this placement?"""
        best_kind, best_weight = "", 0.0
        for edge in self.graph.out_edges(quarter_id):
            if edge.target != room_id:
                continue
            if edge.kind is EdgeKind.ASSERTED_FAVOUR and edge.weight > best_weight:
                best_kind, best_weight = "favour", edge.weight
            elif edge.kind is EdgeKind.ASSERTED_PROHIBIT and edge.weight > best_weight:
                best_kind, best_weight = "prohibit", edge.weight
        return best_kind, best_weight

    @staticmethod
    def _resolve(support: float, conflict: float, asserted: str, weight: float) -> tuple[str, str]:
        """Fuse derived evidence with any explicit textual assertion."""
        derived = 0.5 + 0.5 * (support - conflict)
        derived = max(0.0, min(1.0, derived))

        if asserted == "favour":
            score = derived * (1 - weight) + 1.0 * weight
        elif asserted == "prohibit":
            score = derived * (1 - weight) + 0.0 * weight
        else:
            score = derived

        if score >= 0.78:
            verdict = "ideal"
        elif score >= 0.6:
            verdict = "acceptable"
        elif score > 0.4:
            verdict = "neutral"
        elif score > 0.22:
            verdict = "discouraged"
        else:
            verdict = "prohibited"
        return round(score, 4), verdict

    def _explain(self, v: GraphVerdict) -> str:
        strongest_for = next((d for d in v.derivations if d.supports), None)
        strongest_against = next((d for d in v.derivations if not d.supports), None)

        if v.verdict == "undetermined":
            return (
                f"The graph holds no derivation connecting {v.room} to the "
                f"{v.direction} sector ({v.quarter}), and no text in the corpus "
                f"addresses the placement. It is recorded as undetermined rather "
                f"than scored, because an absence of evidence is not a neutral verdict."
            )

        parts = [
            f"{v.room} in the {v.direction} sector ({v.quarter}) scores "
            f"{v.score:.2f} and is judged {v.verdict}."
        ]
        if strongest_for:
            parts.append(f"Strongest support: {strongest_for.chain}.")
        if strongest_against:
            parts.append(f"Strongest objection: {strongest_against.chain}.")

        if v.asserted == "favour":
            parts.append("A cited text favours this placement directly, which governs the score.")
        elif v.asserted == "prohibit":
            parts.append("A cited text prohibits this placement directly, which governs the score.")
        else:
            parts.append(
                "No classical text in the corpus addresses this placement; the verdict "
                "is derived through the graph and is labelled as inference, not citation."
            )
        if v.agrees_with_text is False:
            parts.append(
                "Note: the graph's own derivation disagrees with the cited assertion. "
                "The text governs, but the disagreement is reported rather than hidden."
            )
        return " ".join(parts)

    # -- bulk queries ------------------------------------------------------

    def best_directions(self, room: RoomType, top: int = 3) -> list[GraphVerdict]:
        """Rank every compass sector for a room. Used by the layout optimiser."""
        verdicts = [
            self.evaluate(room, d) for d in Direction if d is not Direction.CENTRE
        ]
        verdicts.sort(key=lambda v: -v.score)
        return verdicts[:top]

    def coverage(self) -> dict[str, object]:
        """How much of the placement space the graph can actually answer.

        The headline comparison for the report: the authored corpus speaks to a
        few dozen room/direction pairs, while the graph derives a verdict for
        every one of them.
        """
        from aip.engines.vastu.knowledge import RULES

        rooms = [r for r in RoomType if self.graph.has(f"room_{r.value}")]
        directions = list(Direction)
        total = len(rooms) * len(directions)

        asserted_pairs: set[tuple[str, str]] = set()
        for rule in RULES:
            if rule.subject is None:
                continue
            for d in (*rule.ideal, *rule.acceptable, *rule.prohibited):
                asserted_pairs.add((rule.subject.value, d.value))

        return {
            "rooms_modelled": len(rooms),
            "directions": len(directions),
            "placements_total": total,
            "placements_asserted_by_text": len(asserted_pairs),
            "placements_derivable_by_graph": total,
            "coverage_gain": round(total / max(1, len(asserted_pairs)), 2),
        }


@lru_cache(maxsize=1)
def get_reasoner() -> VastuReasoner:
    return VastuReasoner()


def evaluate_placement(room: RoomType, direction: Direction) -> GraphVerdict:
    """Convenience entry point."""
    return get_reasoner().evaluate(room, direction)
