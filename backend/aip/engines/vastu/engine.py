"""The Vastu reasoning engine.

Design commitments, each of which addresses a specific failure of existing tools:

* **Nothing is asserted without a reason.** Every verdict carries the classical
  citation, the traditional rationale, the modern mechanism (or an explicit
  statement that there is none), and the arithmetic contribution it made to the
  score.

* **Unassessable rules are excluded, not guessed.** If the model does not record
  where the water tank is, the water rule is reported as "not assessable" and
  removed from the denominator. Scoring a rule you cannot evaluate is how these
  systems manufacture false precision.

* **Conflicts are resolved openly.** Classical placement and the position of the
  approach road genuinely contradict each other on a south-facing plot. The
  engine detects the contradiction, resolves it by effective weight, and reports
  both the winner and the loser with reasons.

* **Every violation carries a counterfactual.** "Kitchen in the north-west costs
  you 7.4 points; moving it to the south-east would take the score from 68 to
  75." That converts an opaque verdict into a design decision.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable

from pydantic import BaseModel, Field

from aip.agents.base import Evidence, EvidenceKind, Finding, Severity
from aip.core.logging import get_logger, log_event
from aip.domain.geometry import Direction, Vec2, direction_of, point_in_polygon
from aip.domain.plan import FloorPlan, OpeningKind, Room, RoomType, WallKind
from aip.engines.vastu.knowledge import (
    RULES,
    RULES_BY_ID,
    RuleCategory,
    School,
    VastuRule,
    corpus_statistics,
)

logger = get_logger("aip.vastu")


class RuleVerdict(BaseModel):
    """The engine's finding on a single rule."""

    rule_id: str
    title: str
    category: str
    school: str
    citation: str

    assessable: bool = True
    reason_not_assessable: str = ""

    subject_label: str = ""
    subject_id: str = ""
    observed_direction: str = ""
    verdict: str = "neutral"          # ideal | acceptable | neutral | prohibited
    compliance: float = Field(default=0.0, ge=0.0, le=1.0)

    classical_weight: float = 0.0
    modern_validity: float = 0.0
    effective_weight: float = 0.0
    score_contribution: float = 0.0   # points added to the 0-100 score
    points_forgone: float = 0.0       # points lost versus full compliance

    traditional_rationale: str = ""
    modern_rationale: str = ""
    remedy: str = ""
    counterfactual: str = ""
    defeated_by: str = ""
    notes: str = ""

    @property
    def is_violation(self) -> bool:
        return self.assessable and self.compliance < 0.6 and not self.defeated_by


class ConflictResolution(BaseModel):
    """A recorded contradiction between two rules and how it was settled."""

    winner_rule: str
    loser_rule: str
    subject: str
    explanation: str
    winner_weight: float
    loser_weight: float


class CategoryScore(BaseModel):
    category: str
    score: float
    rules_assessed: int
    weight: float


class ReconciliationEntry(BaseModel):
    """How the client's stance changed one rule's influence.

    This is the audit trail for the traditional/modern reconciliation. Without
    it the reweighting is invisible: two stances can produce similar aggregate
    scores while the reasoning underneath them differs completely, and the user
    has no way to see that a rule with no functional basis was quietly muted.
    """

    rule_id: str
    title: str
    school: str
    classical_weight: float
    modern_validity: float
    effective_weight: float
    weight_retained: float          # fraction of classical authority retained
    status: str                     # honoured | down-weighted | near-suppressed
    basis: str                      # why it kept or lost weight


class VastuReport(BaseModel):
    """Complete, explainable Vastu assessment of a plan."""

    plan_id: str = ""
    score: float = Field(default=0.0, ge=0.0, le=100.0)
    grade: str = "-"
    tradition_weight: float = 0.5
    stance_label: str = ""

    verdicts: list[RuleVerdict] = Field(default_factory=list)
    conflicts: list[ConflictResolution] = Field(default_factory=list)
    category_scores: list[CategoryScore] = Field(default_factory=list)
    reconciliation: list[ReconciliationEntry] = Field(default_factory=list)
    reconciliation_note: str = ""

    rules_total: int = 0
    rules_assessed: int = 0
    rules_not_assessable: int = 0
    violations: int = 0
    serious_violations: int = 0

    summary: str = ""
    top_remedies: list[dict[str, Any]] = Field(default_factory=list)
    corpus: dict[str, Any] = Field(default_factory=dict)

    @property
    def violated(self) -> list[RuleVerdict]:
        return [v for v in self.verdicts if v.is_violation]

    @property
    def compliant(self) -> list[RuleVerdict]:
        return [v for v in self.verdicts if v.assessable and v.compliance >= 0.6]

    def to_findings(self) -> list[Finding]:
        """Convert violations into committee findings for the critic layer."""
        out: list[Finding] = []
        for verdict in self.violated:
            if verdict.effective_weight < 0.12:
                continue     # a rule the client's stance has all but switched off
            severity = (
                Severity.MAJOR
                if verdict.verdict == "prohibited" and verdict.effective_weight > 0.5
                else Severity.MODERATE
                if verdict.effective_weight > 0.3
                else Severity.MINOR
            )
            out.append(
                Finding(
                    code=verdict.rule_id,
                    severity=severity,
                    message=(
                        f"{verdict.title}: {verdict.subject_label or 'element'} is "
                        f"{verdict.observed_direction or 'misplaced'} "
                        f"({verdict.verdict})."
                    ),
                    target_id=verdict.subject_id,
                    target_label=verdict.subject_label,
                    metric="vastu_compliance",
                    actual=verdict.observed_direction,
                    expected="ideal sector",
                    remedy=verdict.remedy,
                    evidence=[
                        Evidence(
                            kind=EvidenceKind.SHASTRA,
                            source=verdict.citation,
                            detail=verdict.traditional_rationale[:280],
                            value=round(verdict.effective_weight, 3),
                            relevance=round(verdict.effective_weight, 3),
                            locator=verdict.subject_id,
                        ),
                        Evidence(
                            kind=EvidenceKind.COMPUTED,
                            source="Modern validity assessment",
                            detail=verdict.modern_rationale[:280],
                            value=verdict.modern_validity,
                        ),
                    ],
                )
            )
        return out


@dataclass(slots=True)
class _Observation:
    """What the engine could actually measure for one rule."""

    assessable: bool
    direction: Direction | None = None
    subject_label: str = ""
    subject_id: str = ""
    compliance_override: float | None = None
    reason: str = ""
    note: str = ""


class VastuEngine:
    """Evaluates a floorplan against the encoded corpus."""

    def __init__(self, tradition_weight: float = 0.5) -> None:
        self.tradition_weight = max(0.0, min(1.0, tradition_weight))

    # ------------------------------------------------------------- public --

    def analyse(self, plan: FloorPlan) -> VastuReport:
        verdicts: list[RuleVerdict] = []
        weighted_sum = 0.0
        weight_total = 0.0

        observations: dict[str, _Observation] = {}
        for rule in RULES:
            observations[rule.id] = self._observe(rule, plan)

        conflicts = self._resolve_conflicts(observations, plan)
        defeated = {c.loser_rule: c for c in conflicts}

        for rule in RULES:
            observation = observations[rule.id]
            effective = rule.effective_weight(self.tradition_weight)

            verdict = RuleVerdict(
                rule_id=rule.id,
                title=rule.title,
                category=rule.category.value,
                school=rule.school.label,
                citation=rule.citation,
                classical_weight=round(rule.weight, 3),
                modern_validity=round(rule.modern_validity, 3),
                effective_weight=round(effective, 4),
                traditional_rationale=rule.traditional_rationale,
                modern_rationale=rule.modern_rationale,
                remedy=rule.remedy,
                subject_label=observation.subject_label,
                subject_id=observation.subject_id,
                notes=observation.note,
            )

            if not observation.assessable:
                verdict.assessable = False
                verdict.reason_not_assessable = observation.reason
                verdicts.append(verdict)
                continue

            if rule.id in defeated:
                conflict = defeated[rule.id]
                verdict.defeated_by = conflict.winner_rule
                verdict.notes = conflict.explanation
                verdict.assessable = False
                verdict.reason_not_assessable = (
                    f"Superseded by {conflict.winner_rule}, which carries greater "
                    f"effective weight under your stance."
                )
                verdicts.append(verdict)
                continue

            if observation.compliance_override is not None:
                compliance = observation.compliance_override
                verdict.verdict = _word_for(compliance)
            else:
                direction = observation.direction or Direction.CENTRE
                compliance = rule.compliance_for(direction)
                verdict.verdict = rule.verdict_word(direction)

            verdict.compliance = round(compliance, 4)
            verdict.observed_direction = (
                observation.direction.value if observation.direction else ""
            )
            verdict.score_contribution = round(effective * compliance, 4)
            verdict.points_forgone = round(effective * (1.0 - compliance), 4)

            weighted_sum += effective * compliance
            weight_total += effective
            verdicts.append(verdict)

        raw = (weighted_sum / weight_total) if weight_total > 0 else 0.0
        score = round(raw * 100, 1)

        # Convert the abstract weights into readable point contributions.
        if weight_total > 0:
            for verdict in verdicts:
                if verdict.assessable:
                    verdict.score_contribution = round(
                        verdict.score_contribution / weight_total * 100, 2
                    )
                    verdict.points_forgone = round(verdict.points_forgone / weight_total * 100, 2)

        report = VastuReport(
            plan_id=plan.id,
            score=score,
            grade=_grade(score),
            tradition_weight=self.tradition_weight,
            stance_label=_stance_label(self.tradition_weight),
            verdicts=verdicts,
            conflicts=conflicts,
            category_scores=self._category_scores(verdicts),
            rules_total=len(RULES),
            rules_assessed=sum(1 for v in verdicts if v.assessable),
            rules_not_assessable=sum(1 for v in verdicts if not v.assessable),
            corpus=corpus_statistics(),
        )
        report.reconciliation = self._reconciliation()
        report.reconciliation_note = self._reconciliation_note(report)
        report.violations = len(report.violated)
        report.serious_violations = sum(
            1 for v in report.violated if v.verdict == "prohibited" and v.effective_weight > 0.4
        )
        report.top_remedies = self._counterfactuals(report, weight_total)
        report.summary = self._summarise(report)

        log_event(
            logger, "vastu.analysed",
            plan=plan.id, score=score, assessed=report.rules_assessed,
            violations=report.violations, tradition_weight=self.tradition_weight,
        )
        return report

    # -------------------------------------------------------- observation --

    def _observe(self, rule: VastuRule, plan: FloorPlan) -> _Observation:
        """Measure the plan for one rule, or explain why it cannot be measured."""
        handler = {
            RuleCategory.ZONE_PLACEMENT: self._observe_zone,
            RuleCategory.FIRE: self._observe_zone,
            RuleCategory.ENTRANCE: self._observe_entrance,
            RuleCategory.BRAHMASTHAN: self._observe_brahmasthan,
            RuleCategory.WATER: self._observe_water,
            RuleCategory.MASS_DISTRIBUTION: self._observe_mass,
            RuleCategory.PROPORTION: self._observe_proportion,
            RuleCategory.OPENINGS: self._observe_openings,
            RuleCategory.SLOPE: self._observe_slope,
            RuleCategory.CIRCULATION: self._observe_circulation,
            RuleCategory.SLEEPING: self._observe_sleeping,
        }.get(rule.category)
        if handler is None:
            return _Observation(False, reason="No observer implemented for this category.")
        return handler(rule, plan)

    def _observe_zone(self, rule: VastuRule, plan: FloorPlan) -> _Observation:
        # Rules about an element *within* a room are handled first: they name a
        # subject room but are not answered by that room's compass sector.
        if rule.id == "VS.KITCHEN.COOK_FACES_EAST":
            kitchen = plan.first_room_of(RoomType.KITCHEN)
            if kitchen is None:
                return _Observation(False, reason="No kitchen in this plan.")
            facing = kitchen.metadata.get("hob_facing")
            if not facing:
                return _Observation(
                    False,
                    subject_label=kitchen.display_name(),
                    subject_id=kitchen.id,
                    reason="Hob orientation is decided during interior design, not at plan stage.",
                )
            return _Observation(
                True,
                subject_label=kitchen.display_name(),
                subject_id=kitchen.id,
                compliance_override=1.0 if str(facing).upper().startswith("E") else 0.3,
                note=f"Hob faces {facing}.",
            )

        if rule.subject is None:
            return _Observation(False, reason="Rule has no measurable subject in the model.")

        rooms = plan.rooms_of(rule.subject)
        if not rooms:
            return _Observation(
                False, reason=f"No {rule.subject.label} in this plan."
            )
        # Judge by the largest instance; secondary rooms are noted separately.
        room = max(rooms, key=lambda r: r.area)
        direction = plan.direction_of_room(room)
        note = ""
        if len(rooms) > 1:
            others = ", ".join(
                plan.direction_of_room(r).value for r in rooms if r.id != room.id
            )
            note = f"{len(rooms)} instances; others lie {others}."
        return _Observation(
            True,
            direction=direction,
            subject_label=room.display_name(),
            subject_id=room.id,
            note=note,
        )

    def _observe_entrance(self, rule: VastuRule, plan: FloorPlan) -> _Observation:
        door, wall = _main_door(plan)
        if door is None or wall is None:
            return _Observation(False, reason="No main entrance is defined in this plan.")

        if rule.id == "VS.ENTRANCE.ROAD_FACING":
            roads = plan.site.road_directions or []
            if not roads:
                return _Observation(False, reason="Approach road direction is not recorded.")
            facing = _wall_facing(plan, wall)
            aligned = min(
                abs(((facing.bearing - r.bearing) + 180) % 360 - 180) for r in roads
            )
            return _Observation(
                True,
                direction=facing,
                subject_label="Main entrance",
                subject_id=door.id,
                compliance_override=1.0 if aligned <= 45 else max(0.0, 1.0 - aligned / 180),
                note=f"Road lies {'/'.join(r.value for r in roads)}; door faces {facing.value}.",
            )

        facing = _wall_facing(plan, wall)
        return _Observation(True, direction=facing, subject_label="Main entrance", subject_id=door.id)

    def _observe_brahmasthan(self, rule: VastuRule, plan: FloorPlan) -> _Observation:
        ground = plan.level_at(0)
        if ground is None or not ground.rooms:
            return _Observation(False, reason="No ground floor to assess.")

        centre_polygon = plan.brahmasthan_polygon()
        centre = plan.centre
        occupants = [
            room for room in ground.rooms
            if point_in_polygon(centre, room.polygon) or _covers_centre(room, centre_polygon)
        ]

        if rule.id == "VS.BRAHMASTHAN.NO_TOILET":
            offenders = [r for r in occupants if r.type in {RoomType.TOILET, RoomType.BATHROOM}]
            if offenders:
                return _Observation(
                    True, compliance_override=0.0,
                    subject_label=offenders[0].display_name(), subject_id=offenders[0].id,
                    note="A sanitary room occupies the central zone.",
                )
            return _Observation(True, compliance_override=1.0, subject_label="Central zone")

        if rule.id == "VS.BRAHMASTHAN.NO_STAIR":
            offenders = [r for r in occupants if r.type is RoomType.STAIRCASE]
            if offenders:
                return _Observation(
                    True, compliance_override=0.0,
                    subject_label=offenders[0].display_name(), subject_id=offenders[0].id,
                    note="The staircase occupies the central zone.",
                )
            return _Observation(True, compliance_override=1.0, subject_label="Central zone")

        # VS.BRAHMASTHAN.OPEN - graded by what sits at the centre.
        if not occupants:
            return _Observation(True, compliance_override=1.0, subject_label="Central zone",
                                note="The centre of the plan is open.")
        heavy = {RoomType.TOILET, RoomType.BATHROOM, RoomType.STAIRCASE, RoomType.STORE, RoomType.SHAFT}
        light = {RoomType.COURTYARD, RoomType.CORRIDOR, RoomType.FOYER, RoomType.LOBBY, RoomType.LIVING}
        worst = min(
            (0.0 if r.type in heavy else 0.85 if r.type in light else 0.45) for r in occupants
        )
        occupant = occupants[0]
        return _Observation(
            True, compliance_override=worst,
            subject_label=occupant.display_name(), subject_id=occupant.id,
            note=f"Central zone is occupied by {', '.join(r.display_name() for r in occupants[:3])}.",
        )

    def _observe_water(self, rule: VastuRule, plan: FloorPlan) -> _Observation:
        marker = plan.metadata.get("water_source_direction")
        if marker:
            try:
                direction = Direction(str(marker).upper())
            except ValueError:
                return _Observation(False, reason=f"Unrecognised water source direction {marker!r}.")
            return _Observation(True, direction=direction, subject_label="Water source")

        tanks = [r for r in plan.all_rooms if "water" in r.tags or r.type is RoomType.UTILITY]
        if not tanks:
            return _Observation(
                False,
                reason=(
                    "No water source is modelled. Tag a room 'water' or set "
                    "metadata.water_source_direction to assess this rule."
                ),
            )
        room = tanks[0]
        return _Observation(
            True,
            direction=plan.direction_of_room(room),
            subject_label=room.display_name(),
            subject_id=room.id,
            note="Inferred from the utility/water-tagged room.",
        )

    def _observe_mass(self, rule: VastuRule, plan: FloorPlan) -> _Observation:
        if rule.id == "VS.OPEN.NORTHEAST":
            site = plan.site
            if not site.boundary:
                return _Observation(False, reason="No plot boundary recorded, so setbacks cannot be compared.")
            north_east_open = site.setback_front + site.setback_left
            south_west_open = site.setback_rear + site.setback_right
            if north_east_open <= 0 and south_west_open <= 0:
                return _Observation(False, reason="Setbacks are not specified.")
            ratio = north_east_open / (north_east_open + south_west_open)
            return _Observation(
                True, compliance_override=max(0.0, min(1.0, ratio * 1.6)),
                subject_label="Open space distribution",
                note=f"North/east open {north_east_open:.1f} m versus south/west {south_west_open:.1f} m.",
            )

        # VS.MASS.SOUTHWEST_HEAVY - compare built mass across the diagonal.
        rooms = [r for r in plan.all_rooms if not r.type.is_outdoor]
        if not rooms:
            return _Observation(False, reason="No enclosed rooms to weigh.")

        centre = plan.centre
        north_angle = plan.site.north_angle
        sw_mass = 0.0
        ne_mass = 0.0
        for room in rooms:
            direction = direction_of(room.centre, centre, north_angle)
            mass = room.area * room.ceiling_height * (1 + 0.35 * room.level)
            if direction in {Direction.SW, Direction.S, Direction.W, Direction.SSW, Direction.WSW}:
                sw_mass += mass
            elif direction in {Direction.NE, Direction.N, Direction.E, Direction.NNE, Direction.ENE}:
                ne_mass += mass
        total = sw_mass + ne_mass
        if total <= 0:
            return _Observation(False, reason="Mass is evenly distributed on the diagonal axes.")
        ratio = sw_mass / total
        return _Observation(
            True,
            compliance_override=max(0.0, min(1.0, (ratio - 0.35) / 0.30)),
            subject_label="Building mass",
            note=f"South-west mass share {ratio:.0%} (target above 50%).",
        )

    def _observe_proportion(self, rule: VastuRule, plan: FloorPlan) -> _Observation:
        env = plan.envelope()
        if env.width <= 0 or env.height <= 0:
            return _Observation(False, reason="Plan envelope is degenerate.")

        if rule.id == "VS.CORNER.NORTHEAST_EXTENSION":
            ground = plan.level_at(0)
            if ground is None:
                return _Observation(False, reason="No ground floor.")
            # Is the north-east corner of the bounding box actually built on?
            corner = _rotate_corner(env, plan.site.north_angle, Direction.NE)
            probe = Vec2(
                corner.x + (env.centre.x - corner.x) * 0.12,
                corner.y + (env.centre.y - corner.y) * 0.12,
            )
            filled = any(point_in_polygon(probe, r.polygon) for r in ground.rooms)
            return _Observation(
                True, compliance_override=1.0 if filled else 0.25,
                subject_label="North-east corner",
                note="Corner is built out." if filled else "Corner is cut or recessed.",
            )

        aspect = env.aspect_ratio
        # 1:1 scores 1.0, decaying to 0 at about 1:2.6.
        compliance = max(0.0, min(1.0, 1.0 - (aspect - 1.0) / 1.6))
        return _Observation(
            True, compliance_override=compliance,
            subject_label="Plan proportion",
            note=f"Envelope proportion {aspect:.2f}:1.",
        )

    def _observe_openings(self, rule: VastuRule, plan: FloorPlan) -> _Observation:
        by_direction: dict[Direction, float] = {}
        for level in plan.levels:
            for wall in level.walls:
                if wall.kind is not WallKind.EXTERIOR:
                    continue
                facing = _wall_facing(plan, wall)
                for opening in wall.openings:
                    if opening.kind.is_glazed:
                        by_direction[facing] = by_direction.get(facing, 0.0) + opening.area
        total = sum(by_direction.values())
        if total <= 0:
            return _Observation(False, reason="No glazing is modelled yet.")

        favourable = sum(
            area for d, area in by_direction.items()
            if d.cardinal in {Direction.N, Direction.NE, Direction.E}
        )
        share = favourable / total
        return _Observation(
            True,
            compliance_override=max(0.0, min(1.0, share / 0.55)),
            subject_label="Glazing distribution",
            note=f"{share:.0%} of glazing faces north, north-east or east.",
        )

    def _observe_slope(self, rule: VastuRule, plan: FloorPlan) -> _Observation:
        slope = plan.site.slope_percent
        direction_raw = plan.metadata.get("slope_direction") or plan.site.__dict__.get("slope_direction")
        if abs(slope) < 0.5:
            return _Observation(
                True, compliance_override=0.7,
                subject_label="Site gradient",
                note="Site is effectively level, so the rule is close to vacuous; scored neutral-positive.",
            )
        if not direction_raw:
            return _Observation(
                False,
                reason="Site slopes but the fall direction is not recorded (set metadata.slope_direction).",
            )
        try:
            direction = Direction(str(direction_raw).upper())
        except ValueError:
            return _Observation(False, reason=f"Unrecognised slope direction {direction_raw!r}.")
        return _Observation(True, direction=direction, subject_label="Site gradient")

    def _observe_circulation(self, rule: VastuRule, plan: FloorPlan) -> _Observation:
        stairs = [s for level in plan.levels for s in level.staircases]
        if not stairs:
            return _Observation(False, reason="Single-storey plan; there is no staircase.")
        stair = stairs[0]

        if rule.id == "VS.STAIR.CLOCKWISE":
            return _Observation(
                True,
                compliance_override=1.0 if stair.direction == "clockwise" else 0.0,
                subject_label="Staircase",
                subject_id=stair.id,
                note=f"Ascent is {stair.direction}.",
            )

        room = plan.first_room_of(RoomType.STAIRCASE)
        if room is None:
            from aip.domain.geometry import centroid

            direction = direction_of(centroid(stair.polygon), plan.centre, plan.site.north_angle)
        else:
            direction = plan.direction_of_room(room)
        return _Observation(
            True, direction=direction, subject_label="Staircase", subject_id=stair.id
        )

    def _observe_sleeping(self, rule: VastuRule, plan: FloorPlan) -> _Observation:
        bedrooms = plan.rooms_of(
            RoomType.MASTER_BEDROOM, RoomType.BEDROOM, RoomType.GUEST_BEDROOM, RoomType.CHILDREN_BEDROOM
        )
        if not bedrooms:
            return _Observation(False, reason="No bedrooms in this plan.")
        oriented = [r for r in bedrooms if r.metadata.get("bed_head_direction")]
        if not oriented:
            return _Observation(
                False,
                reason=(
                    "Bed positions are decided during interior layout. This rule "
                    "will be assessed once furniture is placed."
                ),
            )
        good = sum(
            1 for r in oriented
            if str(r.metadata["bed_head_direction"]).upper().startswith(("S", "E"))
        )
        return _Observation(
            True,
            compliance_override=good / len(oriented),
            subject_label="Bed orientation",
            note=f"{good} of {len(oriented)} beds have the head to the south or east.",
        )

    # ---------------------------------------------------------- conflicts --

    def _resolve_conflicts(
        self, observations: dict[str, _Observation], plan: FloorPlan
    ) -> list[ConflictResolution]:
        """Detect and settle contradictions between rules.

        The archetypal case is a plot whose only road frontage is south or west.
        The classical entrance rule and the requirement that a house be enterable
        from its street cannot both be honoured. Rather than silently scoring the
        plan down for something the site made unavoidable, the engine names the
        conflict, resolves it by effective weight, and shows its working.
        """
        resolved: list[ConflictResolution] = []

        for rule in RULES:
            if not rule.defeats:
                continue
            observation = observations.get(rule.id)
            if observation is None or not observation.assessable:
                continue

            for target_id in rule.defeats:
                target = RULES_BY_ID.get(target_id)
                target_observation = observations.get(target_id)
                if target is None or target_observation is None or not target_observation.assessable:
                    continue

                # Only a genuine contradiction counts: both rules bear on the same
                # subject and cannot both be satisfied.
                if not self._contradicts(rule, target, observations, plan):
                    continue

                rule_weight = rule.effective_weight(self.tradition_weight)
                target_weight = target.effective_weight(self.tradition_weight)
                winner, loser = (
                    (rule, target) if rule_weight >= target_weight else (target, rule)
                )
                win_w, lose_w = (
                    (rule_weight, target_weight)
                    if rule_weight >= target_weight
                    else (target_weight, rule_weight)
                )
                resolved.append(
                    ConflictResolution(
                        winner_rule=winner.id,
                        loser_rule=loser.id,
                        subject=observation.subject_label or "entrance",
                        winner_weight=round(win_w, 4),
                        loser_weight=round(lose_w, 4),
                        explanation=(
                            f"'{winner.title}' and '{loser.title}' cannot both be "
                            f"satisfied on this site. At your stance "
                            f"({_stance_label(self.tradition_weight)}), the first "
                            f"carries effective weight {win_w:.2f} against "
                            f"{lose_w:.2f}, so it governs. {loser.remedy}"
                        ),
                    )
                )
        return resolved

    def _contradicts(
        self,
        rule: VastuRule,
        target: VastuRule,
        observations: dict[str, _Observation],
        plan: FloorPlan,
    ) -> bool:
        if rule.category is RuleCategory.ENTRANCE and target.category is RuleCategory.ENTRANCE:
            roads = plan.site.road_directions or []
            if not roads:
                return False
            # A contradiction exists only when no road lies in an auspicious sector.
            auspicious = rule.ideal | rule.acceptable if rule.ideal else target.ideal
            return not any(r in auspicious or r.cardinal in auspicious for r in roads)
        return False

    # ------------------------------------------------------ presentation --

    def _category_scores(self, verdicts: list[RuleVerdict]) -> list[CategoryScore]:
        buckets: dict[str, list[RuleVerdict]] = {}
        for verdict in verdicts:
            if verdict.assessable:
                buckets.setdefault(verdict.category, []).append(verdict)

        out: list[CategoryScore] = []
        for category, items in sorted(buckets.items()):
            weight = sum(v.effective_weight for v in items)
            if weight <= 0:
                continue
            score = sum(v.effective_weight * v.compliance for v in items) / weight
            out.append(
                CategoryScore(
                    category=category,
                    score=round(score * 100, 1),
                    rules_assessed=len(items),
                    weight=round(weight, 3),
                )
            )
        return sorted(out, key=lambda c: c.score)

    def _reconciliation(self) -> list[ReconciliationEntry]:
        """Show what the stance did to every rule's authority.

        At an orthodox stance nothing is down-weighted and the list is uniform.
        As the stance moves toward modern, rules lose influence in exact
        proportion to how little functional basis they have - and the client can
        see precisely which ones, and read the reason.
        """
        entries: list[ReconciliationEntry] = []
        for rule in RULES:
            effective = rule.effective_weight(self.tradition_weight)
            retained = effective / rule.weight if rule.weight > 0 else 0.0
            if retained >= 0.92:
                status = "honoured"
            elif retained >= 0.55:
                status = "down-weighted"
            else:
                status = "near-suppressed"

            if rule.modern_validity >= 0.7:
                basis = "Retains full weight: has a demonstrable climatic or functional basis."
            elif rule.modern_validity >= 0.4:
                basis = "Partially supported by modern practice; weight reduced in proportion."
            else:
                basis = (
                    "No established functional mechanism; retained only to the "
                    "extent your stance defers to classical authority."
                )

            entries.append(
                ReconciliationEntry(
                    rule_id=rule.id,
                    title=rule.title,
                    school=rule.school.label,
                    classical_weight=round(rule.weight, 3),
                    modern_validity=round(rule.modern_validity, 3),
                    effective_weight=round(effective, 4),
                    weight_retained=round(retained, 4),
                    status=status,
                    basis=basis,
                )
            )
        return sorted(entries, key=lambda e: e.weight_retained)

    def _reconciliation_note(self, report: VastuReport) -> str:
        suppressed = [e for e in report.reconciliation if e.status == "near-suppressed"]
        reduced = [e for e in report.reconciliation if e.status == "down-weighted"]
        stance = _stance_label(self.tradition_weight)

        if self.tradition_weight >= 0.9:
            return (
                f"At an orthodox stance every rule in the corpus retains its full "
                f"classical authority; no rule was down-weighted. The score is a "
                f"faithful reading of the texts."
            )
        if not suppressed and not reduced:
            return "No rules were re-weighted at this stance."

        names = ", ".join(f"'{e.title}'" for e in suppressed[:3])
        return (
            f"At a '{stance}' stance, {len(reduced)} rule(s) were down-weighted and "
            f"{len(suppressed)} reduced to near-zero influence because they have no "
            f"established functional mechanism"
            + (f" - notably {names}" if names else "")
            + f". The {sum(1 for e in report.reconciliation if e.modern_validity >= 0.7)} "
            f"rules with a demonstrable climatic basis kept their full weight, which "
            f"is why this score still reflects real building performance rather than "
            f"doctrine alone."
        )

    def _counterfactuals(self, report: VastuReport, weight_total: float) -> list[dict[str, Any]]:
        """Rank remedies by the score they would recover.

        This is what turns a Vastu report from a verdict into a design tool: the
        architect sees not just what is wrong but what fixing it is worth, and
        can therefore decide what is worth the plan disruption.
        """
        if weight_total <= 0:
            return []
        out: list[dict[str, Any]] = []
        for verdict in sorted(report.violated, key=lambda v: -v.points_forgone):
            if verdict.points_forgone < 0.15:
                continue
            projected = round(min(100.0, report.score + verdict.points_forgone), 1)

            # Directional rules describe a sector; the rest describe a condition.
            # Using one template for both produced sentences like "Building mass
            # lies off-sector", which reads as a bug even when the score is right.
            if verdict.observed_direction:
                observed = (
                    f"{verdict.subject_label or 'This element'} lies "
                    f"{verdict.observed_direction}, which the corpus treats as "
                    f"{verdict.verdict}"
                )
            elif verdict.notes:
                observed = f"{verdict.notes.rstrip('.')} ({verdict.verdict})"
            else:
                observed = (
                    f"{verdict.subject_label or 'This element'} does not satisfy "
                    f"the rule ({verdict.verdict})"
                )

            out.append(
                {
                    "rule_id": verdict.rule_id,
                    "title": verdict.title,
                    "subject": verdict.subject_label,
                    "current_direction": verdict.observed_direction,
                    "verdict": verdict.verdict,
                    "remedy": verdict.remedy,
                    "points_recoverable": verdict.points_forgone,
                    "score_if_fixed": projected,
                    "modern_validity": verdict.modern_validity,
                    "worth_doing": (
                        "high" if verdict.modern_validity >= 0.65
                        else "moderate" if verdict.modern_validity >= 0.4
                        else "cultural only - no functional benefit"
                    ),
                    "explanation": (
                        f"{observed}. That costs {verdict.points_forgone:.1f} points; "
                        f"correcting it would raise the score to {projected:.1f}."
                    ),
                }
            )
        return out[:8]

    def _summarise(self, report: VastuReport) -> str:
        parts = [
            f"Vastu score {report.score:.0f}/100 ({report.grade}), assessed at a "
            f"'{report.stance_label}' stance.",
            f"{report.rules_assessed} of {report.rules_total} rules could be evaluated "
            f"against this model; {report.rules_not_assessable} were excluded rather "
            f"than guessed.",
        ]
        if report.violations:
            worst = report.violated[0] if report.violated else None
            parts.append(
                f"{report.violations} rule(s) are not satisfied"
                + (f", the most costly being '{worst.title}'." if worst else ".")
            )
        else:
            parts.append("No rule violations were found at this stance.")

        if report.conflicts:
            parts.append(
                f"{len(report.conflicts)} genuine conflict(s) between rules were "
                f"detected and resolved explicitly rather than ignored."
            )
        climatic = [
            v for v in report.compliant
            if v.modern_validity >= 0.7
        ]
        if climatic:
            parts.append(
                f"{len(climatic)} of the satisfied rules also have a demonstrable "
                f"climatic or functional basis, so they improve the building "
                f"regardless of belief."
            )
        return " ".join(parts)


# ---------------------------------------------------------------------------
# Helpers and shortcuts
# ---------------------------------------------------------------------------


def _word_for(compliance: float) -> str:
    if compliance >= 0.9:
        return "ideal"
    if compliance >= 0.6:
        return "acceptable"
    if compliance <= 0.1:
        return "prohibited"
    return "neutral"


def _grade(score: float) -> str:
    if score >= 85:
        return "Excellent"
    if score >= 72:
        return "Good"
    if score >= 58:
        return "Acceptable"
    if score >= 42:
        return "Needs improvement"
    return "Poor"


def _stance_label(tradition_weight: float) -> str:
    if tradition_weight >= 0.9:
        return "orthodox"
    if tradition_weight >= 0.7:
        return "strict"
    if tradition_weight >= 0.4:
        return "balanced"
    if tradition_weight >= 0.15:
        return "advisory"
    return "modern"


def _main_door(plan: FloorPlan):
    for level in plan.levels:
        for wall in level.walls:
            for opening in wall.openings:
                if opening.kind is OpeningKind.MAIN_DOOR:
                    return opening, wall
    return None, None


def _wall_facing(plan: FloorPlan, wall) -> Direction:
    from aip.domain.geometry import bearing_to_direction

    normal = wall.outward_normal(plan.centre)
    bearing = math.degrees(math.atan2(normal.x, normal.y)) + plan.site.north_angle
    return bearing_to_direction(bearing)


def _covers_centre(room: Room, centre_polygon: list[Vec2]) -> bool:
    return any(point_in_polygon(p, room.polygon) for p in centre_polygon)


def _rotate_corner(env, north_angle: float, direction: Direction) -> Vec2:
    """Corner of the envelope lying in `direction` once north rotation is applied."""
    corners = {
        Direction.NE: Vec2(env.max_x, env.max_y),
        Direction.NW: Vec2(env.min_x, env.max_y),
        Direction.SE: Vec2(env.max_x, env.min_y),
        Direction.SW: Vec2(env.min_x, env.min_y),
    }
    centre = env.centre
    best = None
    best_delta = 1e9
    for corner in corners.values():
        actual = direction_of(corner, centre, north_angle)
        delta = abs(((actual.bearing - direction.bearing) + 180) % 360 - 180)
        if delta < best_delta:
            best_delta = delta
            best = corner
    return best or corners[Direction.NE]


def analyse_vastu(plan: FloorPlan, tradition_weight: float = 0.5) -> VastuReport:
    """Convenience entry point."""
    return VastuEngine(tradition_weight).analyse(plan)


def quick_vastu_score(plan: FloorPlan, tradition_weight: float = 0.5) -> float:
    """Fast score in [0, 1] for use inside the layout optimiser's fitness loop.

    Evaluates only the zone-placement and fire rules, which are the ones the
    layout can actually influence, and skips report construction entirely.
    """
    engine = VastuEngine(tradition_weight)
    total = 0.0
    weight = 0.0
    for rule in RULES:
        if rule.category not in {RuleCategory.ZONE_PLACEMENT, RuleCategory.FIRE}:
            continue
        if rule.subject is None:
            continue
        rooms = plan.rooms_of(rule.subject)
        if not rooms:
            continue
        room = max(rooms, key=lambda r: r.area)
        direction = plan.direction_of_room(room)
        effective = rule.effective_weight(engine.tradition_weight)
        total += effective * rule.compliance_for(direction)
        weight += effective
    return round(total / weight, 4) if weight > 0 else 0.5
