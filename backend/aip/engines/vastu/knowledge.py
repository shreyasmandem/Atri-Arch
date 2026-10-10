"""The Vastu knowledge base.

Every rule is encoded with five things that a lookup table does not carry:

1. **Provenance** - which classical treatise states it, and where. Vastu is not
   one doctrine; the Manasara, Mayamata, Vishvakarma Prakasha and Samarangana
   Sutradhara disagree with each other, and regional practice diverges further.
   Naming the source lets a user weigh a rule instead of just obeying it.

2. **Traditional rationale** - what the text says the rule is *for*, in its own
   terms.

3. **Modern rationale** - the climatic, functional or ergonomic mechanism that
   does or does not support it. South-east kitchens genuinely work in the Indian
   climate: morning sun, and afternoon cooking heat exhausting away from the
   living zone. A clockwise staircase has no such mechanism.

4. **Modern validity** - a number in [0, 1] recording how much of the rule
   survives that scrutiny. This is the mechanism that reconciles traditional and
   contemporary practice, and it is stated openly rather than hidden.

5. **Remedy** - the concrete change that would resolve a violation.

The effective weight of a rule is then

    w_eff = w_classical x (t + (1 - t) x modern_validity)

where ``t`` is the client's tradition weight. At ``t = 1`` the classical corpus
governs completely. At ``t = 0`` only the rules with a demonstrable physical
basis retain influence. Every intermediate stance is a continuous blend, and the
engine reports which rules lost weight and why.

Sources are cited to the treatise and chapter. Where a rule is regional or
modern-consensus rather than textual, `School.CONTEMPORARY` records that
honestly instead of inventing a citation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from aip.domain.geometry import Direction
from aip.domain.plan import RoomType


class School(str, Enum):
    """Source tradition for a rule."""

    MANASARA = "manasara"                    # Manasara Shilpa Shastra
    MAYAMATA = "mayamata"                    # Mayamata Vastu Shastra
    VISHVAKARMA = "vishvakarma"              # Vishvakarma Prakasha
    SAMARANGANA = "samarangana"              # Samarangana Sutradhara
    BRIHAT_SAMHITA = "brihat_samhita"        # Varahamihira, Brihat Samhita
    REGIONAL_SOUTH = "regional_south"        # Dravidian / Tamil practice
    REGIONAL_NORTH = "regional_north"        # North Indian practice
    CONTEMPORARY = "contemporary"            # modern practitioner consensus

    @property
    def label(self) -> str:
        return {
            School.MANASARA: "Manasara Shilpa Shastra",
            School.MAYAMATA: "Mayamata",
            School.VISHVAKARMA: "Vishvakarma Prakasha",
            School.SAMARANGANA: "Samarangana Sutradhara",
            School.BRIHAT_SAMHITA: "Brihat Samhita (Varahamihira)",
            School.REGIONAL_SOUTH: "South Indian regional practice",
            School.REGIONAL_NORTH: "North Indian regional practice",
            School.CONTEMPORARY: "Contemporary practitioner consensus",
        }[self]

    @property
    def is_textual(self) -> bool:
        """True when the rule descends from a named classical treatise."""
        return self not in {School.CONTEMPORARY, School.REGIONAL_SOUTH, School.REGIONAL_NORTH}


class RuleCategory(str, Enum):
    ZONE_PLACEMENT = "zone_placement"        # which room belongs in which sector
    ENTRANCE = "entrance"
    BRAHMASTHAN = "brahmasthan"              # the sacred open centre
    WATER = "water"
    FIRE = "fire"
    MASS_DISTRIBUTION = "mass_distribution"  # weight to the south-west
    PROPORTION = "proportion"                # ayadi and shape ratios
    OPENINGS = "openings"
    SLOPE = "slope"
    CIRCULATION = "circulation"
    SLEEPING = "sleeping"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()


@dataclass(frozen=True, slots=True)
class VastuRule:
    """One checkable Vastu proposition."""

    id: str
    title: str
    category: RuleCategory
    school: School
    citation: str

    #: Room type the rule governs, when it is a zone-placement rule.
    subject: RoomType | None = None
    ideal: frozenset[Direction] = frozenset()
    acceptable: frozenset[Direction] = frozenset()
    prohibited: frozenset[Direction] = frozenset()

    #: Classical importance in [0, 1].
    weight: float = 0.5
    #: How much of the rule survives modern functional scrutiny, in [0, 1].
    modern_validity: float = 0.5

    traditional_rationale: str = ""
    modern_rationale: str = ""
    remedy: str = ""

    #: Rules this one outranks when they contradict each other.
    defeats: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    def effective_weight(self, tradition_weight: float) -> float:
        """Blend classical authority with demonstrable modern basis."""
        t = max(0.0, min(1.0, tradition_weight))
        return self.weight * (t + (1.0 - t) * self.modern_validity)

    def compliance_for(self, direction: Direction) -> float:
        """Score in [0, 1] for a subject found in `direction`."""
        if direction in self.ideal:
            return 1.0
        if direction in self.acceptable:
            return 0.65
        if direction in self.prohibited:
            return 0.0
        return 0.4        # unlisted: neither blessed nor forbidden

    def verdict_word(self, direction: Direction) -> str:
        if direction in self.ideal:
            return "ideal"
        if direction in self.acceptable:
            return "acceptable"
        if direction in self.prohibited:
            return "prohibited"
        return "neutral"


def _d(*names: str) -> frozenset[Direction]:
    return frozenset(Direction[n] for n in names)


# ---------------------------------------------------------------------------
# The corpus
# ---------------------------------------------------------------------------

RULES: tuple[VastuRule, ...] = (
    # ------------------------------------------------------------- kitchen --
    VastuRule(
        id="VS.KITCHEN.AGNEYA",
        title="Kitchen in the south-east (Agneya)",
        category=RuleCategory.FIRE,
        school=School.MAYAMATA,
        citation="Mayamata, ch. 8 (placement of the fire sector)",
        subject=RoomType.KITCHEN,
        ideal=_d("SE", "ESE", "SSE"),
        acceptable=_d("E", "NW", "S"),
        prohibited=_d("NE", "N", "SW"),
        weight=0.95,
        modern_validity=0.85,
        traditional_rationale=(
            "Agneya is the quarter of Agni, the fire deity. The hearth belongs "
            "in the sector governed by the element it embodies."
        ),
        modern_rationale=(
            "Strongly supported on climatic grounds. A south-east kitchen "
            "receives direct morning sun, which dries and disinfects a space "
            "that is damp and food-soiled overnight. Cooking heat peaks in the "
            "late morning and is carried away from the living and sleeping zones "
            "by the prevailing south-westerly summer wind, rather than through "
            "them. This is one of the rules that survives modern scrutiny almost "
            "intact."
        ),
        remedy="Relocate the kitchen to the south-east sector, or if fixed, place the cooking platform on the south-east wall of the room so the cook faces east.",
        tags=("high-confidence", "climatic"),
    ),
    VastuRule(
        id="VS.KITCHEN.COOK_FACES_EAST",
        title="Cook faces east while cooking",
        category=RuleCategory.FIRE,
        school=School.VISHVAKARMA,
        citation="Vishvakarma Prakasha, ch. 4",
        subject=RoomType.KITCHEN,
        weight=0.4,
        modern_validity=0.3,
        traditional_rationale="Facing the rising sun during the preparation of food is held to be auspicious.",
        modern_rationale=(
            "Weak. The orientation of the cook has no thermal or hygienic "
            "consequence. It carries a marginal daylight benefit if the platform "
            "sits under an east window, and no cost, so it is easy to honour."
        ),
        remedy="Position the hob on the east side of the kitchen platform.",
        tags=("low-cost",),
    ),
    # ------------------------------------------------------------ bedrooms --
    VastuRule(
        id="VS.MASTER.NAIRUTYA",
        title="Master bedroom in the south-west (Nairutya)",
        category=RuleCategory.ZONE_PLACEMENT,
        school=School.MANASARA,
        citation="Manasara Shilpa Shastra, ch. 9",
        subject=RoomType.MASTER_BEDROOM,
        ideal=_d("SW", "WSW", "SSW"),
        acceptable=_d("S", "W"),
        prohibited=_d("NE", "SE"),
        weight=0.9,
        modern_validity=0.7,
        traditional_rationale=(
            "Nairutya is the heaviest and most stable quarter, governed by "
            "Nirriti. The head of the household is placed in the sector of "
            "greatest gravity and permanence."
        ),
        modern_rationale=(
            "Reasonably supported. The south-west corner is the last part of an "
            "Indian house to cool at night, which is a genuine drawback, but it "
            "is also the quietest and most private corner, furthest from the "
            "entrance and the street. For a room occupied mainly after dark, "
            "acoustic privacy and separation outweigh the thermal penalty - "
            "provided the west glazing is shaded."
        ),
        remedy="Move the master bedroom to the south-west quadrant and keep west-facing glazing small and well shaded.",
        tags=("privacy",),
    ),
    VastuRule(
        id="VS.BEDROOM.SOUTH_WEST_WEST",
        title="Bedrooms in the south, west or north-west",
        category=RuleCategory.ZONE_PLACEMENT,
        school=School.MAYAMATA,
        citation="Mayamata, ch. 8",
        subject=RoomType.BEDROOM,
        ideal=_d("S", "W", "SW", "NW"),
        acceptable=_d("SSW", "WSW", "WNW", "SSE"),
        prohibited=_d("NE",),
        weight=0.6,
        modern_validity=0.5,
        traditional_rationale="The southern and western sectors are held to be restful and grounding.",
        modern_rationale=(
            "Partly supported. Keeping the north-east free for daytime and "
            "shared use is sound zoning, and bedrooms benefit from being away "
            "from the entrance. But a north or east bedroom is thermally "
            "superior in the tropics, so the rule should not override daylight "
            "and heat considerations."
        ),
        remedy="Shift the bedroom toward the southern or western half of the plan.",
    ),
    VastuRule(
        id="VS.CHILDREN.WEST_NORTH",
        title="Children's bedroom in the west or north-west",
        category=RuleCategory.ZONE_PLACEMENT,
        school=School.REGIONAL_NORTH,
        citation="North Indian practitioner consensus",
        subject=RoomType.CHILDREN_BEDROOM,
        ideal=_d("W", "NW", "WNW"),
        acceptable=_d("N", "E", "SW"),
        weight=0.4,
        modern_validity=0.35,
        traditional_rationale="Vayavya, the quarter of air and movement, is considered suited to growth and activity.",
        modern_rationale=(
            "Weak as stated. What does hold is the underlying zoning intent: "
            "children's rooms benefit from being near, but not inside, the "
            "parents' zone and away from the formal entrance."
        ),
        remedy="Locate the children's room in the west or north-west sector.",
    ),
    VastuRule(
        id="VS.SLEEP.HEAD_SOUTH",
        title="Sleep with the head toward the south",
        category=RuleCategory.SLEEPING,
        school=School.BRIHAT_SAMHITA,
        citation="Brihat Samhita, ch. 53",
        weight=0.5,
        modern_validity=0.2,
        traditional_rationale=(
            "The head toward the south, feet toward the north, aligns the body "
            "with the earth's polarity and is said to bring restful sleep."
        ),
        modern_rationale=(
            "Largely unsupported. The proposed geomagnetic mechanism is not "
            "established by controlled evidence, and the few studies cited are "
            "small and contested. The rule costs nothing to follow, so it is "
            "reported as a preference rather than a defect."
        ),
        remedy="Orient the bed so the headboard is against the southern wall.",
        tags=("advisory", "no-cost"),
    ),
    # ------------------------------------------------------------ sacred ----
    VastuRule(
        id="VS.PUJA.ISHANYA",
        title="Prayer room in the north-east (Ishanya)",
        category=RuleCategory.ZONE_PLACEMENT,
        school=School.MANASARA,
        citation="Manasara Shilpa Shastra, ch. 9",
        subject=RoomType.PUJA,
        ideal=_d("NE", "NNE", "ENE"),
        acceptable=_d("N", "E"),
        prohibited=_d("S", "SW", "SSW"),
        weight=0.95,
        modern_validity=0.55,
        traditional_rationale=(
            "Ishanya is the quarter of Ishana, the most auspicious sector, and "
            "the natural seat of the household shrine."
        ),
        modern_rationale=(
            "Moderately supported, for a reason the texts do not state. The "
            "north-east receives soft, indirect, glare-free morning light and "
            "stays the coolest part of an Indian house through the day, which "
            "genuinely suits a small room used at dawn. The cultural weight of "
            "this rule is in any case high enough that ignoring it carries real "
            "client cost."
        ),
        remedy="Relocate the prayer room to the north-east corner, ideally at ground level with an east or north window.",
        tags=("cultural-weight",),
    ),
    # ------------------------------------------------------------- water ----
    VastuRule(
        id="VS.WATER.NORTHEAST",
        title="Water sources in the north-east",
        category=RuleCategory.WATER,
        school=School.MAYAMATA,
        citation="Mayamata, ch. 6 (water and wells)",
        ideal=_d("NE", "NNE", "ENE", "N"),
        acceptable=_d("E",),
        prohibited=_d("SW", "SSW", "WSW", "SE"),
        weight=0.75,
        modern_validity=0.45,
        traditional_rationale="Water, the element of Ishanya, belongs in the north-east; its opposition to the fire sector must be preserved.",
        modern_rationale=(
            "Partly supported, historically. On a site sloping to the north-east "
            "- which the same texts prescribe - a north-east well collects clean "
            "run-off and sits furthest from the south-west latrine, which is a "
            "sound sanitary separation. For a modern plumbed building with a "
            "sealed supply, the hygienic mechanism no longer applies."
        ),
        remedy="Place the overhead tank, sump or bore-well in the north-east sector.",
    ),
    VastuRule(
        id="VS.TOILET.NORTHWEST_SOUTH",
        title="Toilets in the north-west or west, never the north-east",
        category=RuleCategory.ZONE_PLACEMENT,
        school=School.VISHVAKARMA,
        citation="Vishvakarma Prakasha, ch. 5",
        subject=RoomType.TOILET,
        ideal=_d("NW", "WNW", "W"),
        acceptable=_d("S", "SSW", "WSW"),
        prohibited=_d("NE", "NNE", "ENE", "E"),
        weight=0.8,
        modern_validity=0.5,
        traditional_rationale="Waste must be kept out of the auspicious north-east and away from the shrine and water sectors.",
        modern_rationale=(
            "Supported in intent. Separating sanitation from the water source "
            "and from the coolest, most-used daytime corner is good planning "
            "irrespective of doctrine. The north-west also carries odour away on "
            "the prevailing wind rather than through the house."
        ),
        remedy="Move the toilet to the north-west or west sector, and keep it out of the north-east quadrant entirely.",
        tags=("sanitation",),
    ),
    VastuRule(
        id="VS.BATHROOM.EAST_NORTH",
        title="Bathrooms in the east or north",
        category=RuleCategory.ZONE_PLACEMENT,
        school=School.CONTEMPORARY,
        citation="Contemporary practitioner consensus",
        subject=RoomType.BATHROOM,
        ideal=_d("E", "N", "ENE", "NNW"),
        acceptable=_d("NW", "W", "S"),
        prohibited=_d("NE", "SE"),
        weight=0.5,
        modern_validity=0.45,
        traditional_rationale="Bathing is treated separately from sanitation; the eastern sector is preferred for morning use.",
        modern_rationale=(
            "Mildly supported. East light dries a wet room quickly, which "
            "matters in a humid climate. The prohibition on the south-east is "
            "about keeping the fire and water sectors apart and has no physical "
            "basis in a modern plumbed house."
        ),
        remedy="Shift the bathroom toward the east or north side of the plan.",
    ),
    # ---------------------------------------------------------- entrance ----
    VastuRule(
        id="VS.ENTRANCE.NORTH_EAST",
        title="Main entrance in the north, east or north-east",
        category=RuleCategory.ENTRANCE,
        school=School.MANASARA,
        citation="Manasara Shilpa Shastra, ch. 9 (padavinyasa of the entrance)",
        ideal=_d("N", "NE", "E", "NNE", "ENE"),
        acceptable=_d("NNW", "ESE"),
        prohibited=_d("SW", "SSW", "WSW"),
        weight=0.85,
        modern_validity=0.6,
        traditional_rationale=(
            "The entrance admits the household's fortune. The northern and "
            "eastern padas are auspicious; the south-west admits Nirriti."
        ),
        modern_rationale=(
            "Moderately supported. A north or east entrance means arrival "
            "sequence, foyer and the most-used daytime rooms all get soft "
            "morning light and avoid the harsh western afternoon sun on the "
            "door. The prohibition matters less than the preference: the real "
            "constraint on entrance position is usually where the road is."
        ),
        remedy="Relocate the main door to the northern or eastern facade, subject to the approach road.",
        defeats=("VS.ENTRANCE.ROAD_FACING",),
    ),
    VastuRule(
        id="VS.ENTRANCE.ROAD_FACING",
        title="Entrance addresses the approach road",
        category=RuleCategory.ENTRANCE,
        school=School.CONTEMPORARY,
        citation="Practical planning requirement",
        weight=0.7,
        modern_validity=1.0,
        traditional_rationale="Not a classical rule; recorded here so the engine can reason about the conflict it creates.",
        modern_rationale=(
            "A house must be enterable from the street it fronts. Where the road "
            "lies to the south or west, the classical entrance preference and "
            "basic access are in direct conflict, and this engine resolves that "
            "explicitly rather than silently discarding one of them."
        ),
        remedy="Keep the entrance on the road side and mitigate with an entrance court, a screen wall or a rotated porch.",
        tags=("functional",),
    ),
    # ------------------------------------------------------- brahmasthan ----
    VastuRule(
        id="VS.BRAHMASTHAN.OPEN",
        title="The centre of the plan (Brahmasthan) is kept free",
        category=RuleCategory.BRAHMASTHAN,
        school=School.SAMARANGANA,
        citation="Samarangana Sutradhara, ch. 12 (vastu-purusha-mandala)",
        weight=0.9,
        modern_validity=0.75,
        traditional_rationale=(
            "The centre of the mandala is the seat of Brahma and must not be "
            "burdened by heavy construction, a staircase, a toilet or a column."
        ),
        modern_rationale=(
            "Well supported, and arguably the most useful rule in the corpus. An "
            "open centre is a courtyard, and a courtyard drives stack "
            "ventilation, brings daylight to the deep plan, and gives every "
            "surrounding room a second orientation. Traditional Indian "
            "courtyard houses are measurably more comfortable without mechanical "
            "cooling than sealed modern equivalents."
        ),
        remedy="Clear the central ninth of the plan - move any staircase, WC or structural core out of it, and consider opening it as a courtyard or double-height void.",
        tags=("high-confidence", "climatic", "passive-cooling"),
    ),
    VastuRule(
        id="VS.BRAHMASTHAN.NO_TOILET",
        title="No toilet in the Brahmasthan",
        category=RuleCategory.BRAHMASTHAN,
        school=School.SAMARANGANA,
        citation="Samarangana Sutradhara, ch. 12",
        weight=0.85,
        modern_validity=0.65,
        traditional_rationale="Placing waste at the centre of the mandala is the gravest of the placement faults.",
        modern_rationale=(
            "Supported on planning grounds. A central WC is landlocked, so it "
            "cannot be naturally ventilated or daylit, and its drainage has to "
            "cross the plan. Both are real defects."
        ),
        remedy="Move the WC to an external wall in the north-west or west.",
    ),
    VastuRule(
        id="VS.BRAHMASTHAN.NO_STAIR",
        title="No staircase in the Brahmasthan",
        category=RuleCategory.BRAHMASTHAN,
        school=School.MAYAMATA,
        citation="Mayamata, ch. 25",
        subject=RoomType.STAIRCASE,
        prohibited=_d("CENTRE",),
        weight=0.7,
        modern_validity=0.4,
        traditional_rationale="A stair at the centre pierces the seat of Brahma.",
        modern_rationale=(
            "Partly supported. A central stair blocks the courtyard effect and "
            "eats the most flexible part of the plan. Against that, a central "
            "stair gives the shortest circulation to every room, which is a real "
            "efficiency gain, so this is a genuine trade-off rather than a "
            "defect."
        ),
        remedy="Move the staircase to the south or west of the plan.",
    ),
    # ----------------------------------------------------- mass and slope ---
    VastuRule(
        id="VS.MASS.SOUTHWEST_HEAVY",
        title="Greater mass and height to the south and west",
        category=RuleCategory.MASS_DISTRIBUTION,
        school=School.MAYAMATA,
        citation="Mayamata, ch. 7",
        weight=0.7,
        modern_validity=0.7,
        traditional_rationale="The south-west must be the heaviest and highest quarter; the north-east the lightest and lowest.",
        modern_rationale=(
            "Well supported climatically in the northern hemisphere. Mass on the "
            "south and west intercepts the harshest solar gain, while keeping the "
            "north-east low and open admits the best daylight and the coolest "
            "air. This is passive solar design expressed in ritual language."
        ),
        remedy="Push taller volumes, thicker walls and service cores toward the south-west; keep the north-east single-storey and open.",
        tags=("high-confidence", "climatic"),
    ),
    VastuRule(
        id="VS.SLOPE.NORTHEAST_LOW",
        title="Ground slopes down toward the north-east",
        category=RuleCategory.SLOPE,
        school=School.BRIHAT_SAMHITA,
        citation="Brihat Samhita, ch. 53",
        weight=0.6,
        modern_validity=0.5,
        traditional_rationale="The site should fall toward Ishanya so that water and prosperity flow in the auspicious direction.",
        modern_rationale=(
            "Supported where it matters. Falling toward the north-east drains "
            "surface water away from the south-west corner where the building "
            "mass and foundations sit, and toward the traditional well position. "
            "On a flat urban plot the rule is close to vacuous."
        ),
        remedy="Grade the site so surface levels fall to the north-east, and place the soak pit or rainwater recharge there.",
    ),
    VastuRule(
        id="VS.OPEN.NORTHEAST",
        title="Greatest open space in the north and east",
        category=RuleCategory.MASS_DISTRIBUTION,
        school=School.MANASARA,
        citation="Manasara Shilpa Shastra, ch. 9",
        weight=0.65,
        modern_validity=0.75,
        traditional_rationale="Open ground in the auspicious quarters admits beneficial influence.",
        modern_rationale=(
            "Well supported. Larger north and east setbacks give the house its "
            "best daylight without heat gain, and shade the coolest facades. It "
            "is the same principle as the mass-distribution rule seen from the "
            "outside."
        ),
        remedy="Increase the north and east setbacks relative to the south and west.",
        tags=("climatic",),
    ),
    # ---------------------------------------------------------- living ------
    VastuRule(
        id="VS.LIVING.NORTH_EAST",
        title="Living room in the north, east or north-east",
        category=RuleCategory.ZONE_PLACEMENT,
        school=School.MAYAMATA,
        citation="Mayamata, ch. 8",
        subject=RoomType.LIVING,
        ideal=_d("N", "NE", "E", "NNE"),
        acceptable=_d("NW", "ENE", "ESE"),
        prohibited=_d("SW",),
        weight=0.65,
        modern_validity=0.7,
        traditional_rationale="Guests are received in the auspicious quarters.",
        modern_rationale=(
            "Supported. The living room is the most-occupied daytime space, and "
            "the north-east is the coolest, most evenly daylit part of an Indian "
            "house. Putting it in the south-west would place the largest room in "
            "the hottest corner."
        ),
        remedy="Shift the living room toward the north-east half of the plan.",
        tags=("climatic",),
    ),
    VastuRule(
        id="VS.DINING.WEST",
        title="Dining in the west or east",
        category=RuleCategory.ZONE_PLACEMENT,
        school=School.REGIONAL_SOUTH,
        citation="South Indian regional practice",
        subject=RoomType.DINING,
        ideal=_d("W", "E", "WNW"),
        acceptable=_d("N", "S", "NW", "SE"),
        weight=0.4,
        modern_validity=0.4,
        traditional_rationale="The dining space is placed adjacent to the kitchen and away from the shrine.",
        modern_rationale=(
            "Weak as a directional rule. The functional requirement underneath "
            "it - dining directly adjacent to the kitchen - is real and is "
            "checked separately by the circulation analysis."
        ),
        remedy="Place dining adjacent to the kitchen, preferring the western side.",
    ),
    VastuRule(
        id="VS.STORE.SOUTHWEST",
        title="Storage in the south-west or south",
        category=RuleCategory.ZONE_PLACEMENT,
        school=School.MAYAMATA,
        citation="Mayamata, ch. 8",
        subject=RoomType.STORE,
        ideal=_d("SW", "S", "SSW", "WSW"),
        acceptable=_d("W", "NW"),
        prohibited=_d("NE",),
        weight=0.5,
        modern_validity=0.6,
        traditional_rationale="Heavy goods belong in the heavy quarter.",
        modern_rationale=(
            "Supported as zoning. Stores need no daylight, so spending the "
            "premium north-east frontage on them would be wasteful. Putting them "
            "on the hot south-west face is an efficient use of otherwise "
            "difficult space, and the mass buffers the rooms behind."
        ),
        remedy="Move storage to the south-west, where it also acts as a thermal buffer.",
        tags=("climatic",),
    ),
    VastuRule(
        id="VS.UTILITY.NORTHWEST",
        title="Utility and washing in the north-west",
        category=RuleCategory.ZONE_PLACEMENT,
        school=School.CONTEMPORARY,
        citation="Contemporary practitioner consensus",
        subject=RoomType.UTILITY,
        ideal=_d("NW", "WNW", "W"),
        acceptable=_d("N", "SE", "S"),
        prohibited=_d("NE",),
        weight=0.4,
        modern_validity=0.55,
        traditional_rationale="Vayavya, the sector of air, suits drying and washing.",
        modern_rationale=(
            "Reasonably supported. The north-west catches the prevailing wind "
            "for drying and carries damp air and detergent odour away from the "
            "living zone rather than through it."
        ),
        remedy="Relocate the utility area to the north-west.",
    ),
    VastuRule(
        id="VS.STUDY.NORTHEAST_EAST",
        title="Study in the north-east, east or north",
        category=RuleCategory.ZONE_PLACEMENT,
        school=School.CONTEMPORARY,
        citation="Contemporary practitioner consensus",
        subject=RoomType.STUDY,
        ideal=_d("NE", "E", "N", "NNE"),
        acceptable=_d("W", "NW"),
        prohibited=_d("SW",),
        weight=0.45,
        modern_validity=0.7,
        traditional_rationale="The sector of clarity and learning is the north-east.",
        modern_rationale=(
            "Supported for a plain reason: north light is diffuse, steady and "
            "glare-free, which is exactly what sustained reading and screen work "
            "need. This is the same logic that puts artists' studios on north "
            "elevations worldwide."
        ),
        remedy="Move the study to the north or north-east and take daylight from a north window.",
        tags=("climatic",),
    ),
    VastuRule(
        id="VS.STAIR.CLOCKWISE",
        title="Staircase ascends clockwise",
        category=RuleCategory.CIRCULATION,
        school=School.REGIONAL_NORTH,
        citation="North Indian practitioner consensus",
        weight=0.35,
        modern_validity=0.05,
        traditional_rationale="Ascending clockwise follows the auspicious pradakshina direction.",
        modern_rationale=(
            "No support. Handedness of a stair has no ergonomic, structural or "
            "climatic consequence. It is retained in the corpus because clients "
            "ask about it, and it is reported at near-zero weight for any client "
            "who is not strictly orthodox - which is precisely what the "
            "traditional/modern reconciliation is for."
        ),
        remedy="Reverse the flight direction so ascent is clockwise.",
        tags=("advisory", "no-modern-basis"),
    ),
    VastuRule(
        id="VS.STAIR.SOUTHWEST",
        title="Staircase in the south or west",
        category=RuleCategory.CIRCULATION,
        school=School.MAYAMATA,
        citation="Mayamata, ch. 25",
        subject=RoomType.STAIRCASE,
        ideal=_d("S", "SW", "W", "SSW", "WSW"),
        acceptable=_d("SE", "NW"),
        prohibited=_d("NE", "CENTRE"),
        weight=0.55,
        modern_validity=0.45,
        traditional_rationale="The stair is a heavy element and belongs in the heavy quarters.",
        modern_rationale=(
            "Partly supported. A stair on the south or west wall shades the "
            "rooms behind it and does not consume premium north-east daylight. "
            "Against that, a peripheral stair lengthens circulation."
        ),
        remedy="Relocate the staircase to the southern or western edge of the plan.",
    ),
    VastuRule(
        id="VS.PROPORTION.SQUARE",
        title="Plan proportion approaches a square",
        category=RuleCategory.PROPORTION,
        school=School.MANASARA,
        citation="Manasara Shilpa Shastra, ch. 7 (ayadi proportions)",
        weight=0.5,
        modern_validity=0.45,
        traditional_rationale=(
            "The vastu-purusha-mandala is square. Plans should approach that "
            "figure; extreme elongation and missing corners are faults."
        ),
        modern_rationale=(
            "Partly supported. A compact plan has a lower surface-to-volume "
            "ratio, so it gains and loses less heat and costs less envelope per "
            "square metre. Beyond about 1:2 elongation, though, a plan gains "
            "cross-ventilation and daylight on both long faces, which is "
            "advantageous in the tropics. Compactness is therefore a real but "
            "bounded good."
        ),
        remedy="Rationalise the outline toward a square or a gentle rectangle and fill in missing corners.",
        tags=("proportion",),
    ),
    VastuRule(
        id="VS.CORNER.NORTHEAST_EXTENSION",
        title="North-east corner is not cut",
        category=RuleCategory.PROPORTION,
        school=School.VISHVAKARMA,
        citation="Vishvakarma Prakasha, ch. 3",
        weight=0.6,
        modern_validity=0.25,
        traditional_rationale=(
            "A truncated north-east corner is among the most serious plot "
            "faults; an extended one is auspicious."
        ),
        modern_rationale=(
            "Little support. A cut corner slightly reduces the best-oriented "
            "facade, which is a marginal daylight loss, but the severity the "
            "tradition assigns to it is not proportionate to any measurable "
            "effect."
        ),
        remedy="Square off the north-east corner of the built form or the plot boundary.",
        tags=("advisory",),
    ),
    VastuRule(
        id="VS.OPENINGS.NORTH_EAST_MORE",
        title="More and larger openings to the north and east",
        category=RuleCategory.OPENINGS,
        school=School.MAYAMATA,
        citation="Mayamata, ch. 7",
        weight=0.6,
        modern_validity=0.85,
        traditional_rationale="Openings admit beneficial influence and should favour the auspicious quarters.",
        modern_rationale=(
            "Strongly supported, and the clearest case of a Vastu rule encoding "
            "sound tropical building science. North and east glazing brings "
            "daylight with minimal heat gain; west glazing brings low-angle "
            "glare and peak cooling load together. A modern energy model reaches "
            "the same conclusion by a different route."
        ),
        remedy="Increase north and east glazing; reduce and shade west-facing glazing.",
        tags=("high-confidence", "climatic"),
    ),
    VastuRule(
        id="VS.GARAGE.NORTHWEST_SOUTHEAST",
        title="Parking in the north-west or south-east",
        category=RuleCategory.ZONE_PLACEMENT,
        school=School.CONTEMPORARY,
        citation="Contemporary practitioner consensus",
        subject=RoomType.GARAGE,
        ideal=_d("NW", "SE", "WNW", "ESE"),
        acceptable=_d("N", "E", "S", "W"),
        prohibited=_d("NE",),
        weight=0.35,
        modern_validity=0.4,
        traditional_rationale="Vehicles belong in the sector of movement.",
        modern_rationale=(
            "Weak directionally. What is real is that parking should not occupy "
            "the best-daylit frontage, and should sit near the plot entrance."
        ),
        remedy="Move parking to the north-west or south-east of the plot.",
    ),
)


RULES_BY_ID: dict[str, VastuRule] = {rule.id: rule for rule in RULES}


def rules_for_room(room_type: RoomType) -> list[VastuRule]:
    """Zone-placement rules governing a specific room type."""
    return [rule for rule in RULES if rule.subject is room_type]


def rules_in_category(category: RuleCategory) -> list[VastuRule]:
    return [rule for rule in RULES if rule.category is category]


def ideal_direction(room_type: RoomType) -> Direction | None:
    """Single best direction for a room type, for use by the layout generator.

    The generator needs one target to steer toward during optimisation, so the
    ideal set is collapsed to the highest-weighted rule's first cardinal
    preference. The full engine still evaluates the complete rule set afterwards.
    """
    candidates = [r for r in rules_for_room(room_type) if r.ideal]
    if not candidates:
        return None
    best = max(candidates, key=lambda r: r.weight)
    ordered = sorted(best.ideal, key=lambda d: (len(d.value), d.value))
    return ordered[0] if ordered else None


def corpus_statistics() -> dict[str, object]:
    """Summary of the knowledge base, surfaced in the UI and the paper."""
    by_school: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for rule in RULES:
        by_school[rule.school.value] = by_school.get(rule.school.value, 0) + 1
        by_category[rule.category.value] = by_category.get(rule.category.value, 0) + 1
    validities = [r.modern_validity for r in RULES]
    return {
        "total_rules": len(RULES),
        "by_school": by_school,
        "by_category": by_category,
        "textual_rules": sum(1 for r in RULES if r.school.is_textual),
        "mean_modern_validity": round(sum(validities) / len(validities), 3),
        "high_confidence_rules": sum(1 for r in RULES if r.modern_validity >= 0.7),
        "advisory_only_rules": sum(1 for r in RULES if r.modern_validity < 0.3),
    }
