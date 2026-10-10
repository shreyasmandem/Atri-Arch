"""Seed knowledge corpus.

The passages here are the platform's starting grounding: design-style
definitions expressed as concrete specifications, material properties relevant to
the Indian climate, and passive strategy guidance. They are written as
*specifications an agent can act on*, not as prose - "terracotta jaali, 40-60%
open area, on west and south-west facades" is retrievable and usable, whereas
"traditional Indian architecture is beautiful" is neither.

A practice extends this with its own completed projects, preferred vendors and
detail library. That is where the compounding advantage lives: the corpus that
matters most to a firm is the one describing its own work, and the feedback loop
in `aip.rag.learning` promotes the passages that keep producing accepted designs.
"""

from __future__ import annotations

import hashlib

from aip.rag.store import Document


def _doc(text: str, source: str, kind: str, *tags: str, **metadata) -> Document:
    digest = hashlib.blake2b(f"{source}|{text[:120]}".encode(), digest_size=6).hexdigest()
    return Document(
        id=f"{kind}_{digest}",
        text=" ".join(text.split()),
        source=source,
        kind=kind,
        tags=list(tags),
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Design styles - written as buildable specifications
# ---------------------------------------------------------------------------

STYLES: list[Document] = [
    _doc(
        """Tropical Modern. Deep roof overhangs of 900-1200 mm, continuous horizontal
        chajjas over every opening, and full-height sliding glazing opening onto shaded
        verandahs. Palette: off-white or light grey render, exposed board-marked concrete,
        teak or accoya louvres, kota or grey granite floors. Roofs pitched at 15-22 degrees
        in Mangalore tile or standing-seam metal, or flat with a brickbat coba weathering
        course. Cross ventilation is the organising principle: rooms are one-room deep
        wherever possible with openings on two faces. Ceiling fans in every habitable room
        regardless of air conditioning. Colours are muted and light-reflective to limit
        heat gain; saturated colour appears only in soft furnishing.""",
        "AIP style library", "style", "tropical_modern", "style", "climate:hot_humid",
        palette="warm neutral", typical_cost_index=1.0,
    ),
    _doc(
        """Kerala Vernacular. Steeply pitched roofs at 30-45 degrees in Mangalore tile with
        exposed rafters and generous 1200 mm eaves. Laterite or brick walls, often left
        exposed or lime-plastered. Nadumuttam central courtyard driving stack ventilation.
        Timber columns and beams in anjili or teak; carved brackets at column heads. Floors
        in red oxide, kota, or polished laterite. Verandahs (poomukham) wrap the entrance.
        Deep window reveals with timber louvred shutters rather than glass. Materials are
        local and low-embodied-energy. Works with heavy monsoon: roof pitch and overhang
        are functional, not decorative.""",
        "AIP style library", "style", "kerala_vernacular", "style", "climate:hot_humid",
        palette="earth, terracotta, timber", typical_cost_index=1.08,
    ),
    _doc(
        """Chettinad. Broad linear plans organised around a sequence of courtyards. Athangudi
        handmade tiles in geometric patterns as the signature floor. Burma teak columns,
        heavy carved doors with brass fittings, egg-plastered lime walls with a satin sheen.
        Tall ventilators above doors and windows. Colours: deep ochre, indigo, oxide red,
        mustard, contrasted with white lime. Thick walls of 450-600 mm give thermal mass
        against the dry Tamil Nadu heat. Roofs in Madras terrace or flat RCC with parapet.
        Ornament is concentrated at thresholds, columns and ceilings.""",
        "AIP style library", "style", "chettinad", "style", "climate:hot_dry", "regional:tamil_nadu",
        palette="ochre, indigo, oxide red", typical_cost_index=1.35,
    ),
    _doc(
        """Japandi. Scandinavian restraint crossed with Japanese proportion. Palette of warm
        white, oatmeal, pale oak, charcoal accents. Low-slung furniture, generous negative
        space, no visible clutter or open shelving. Materials: light oak or ash veneer,
        matte lacquer, linen, paper, natural stone in honed finish. Lighting is warm at
        2700K, layered and indirect, never a central ceiling fixture alone. Joinery is
        handleless and full-height. Shoji-inspired sliding screens for room division.
        Restraint is the discipline: every object must earn its place.""",
        "AIP style library", "style", "japandi", "style", "minimal",
        palette="warm white, oak, charcoal", typical_cost_index=1.25,
    ),
    _doc(
        """Contemporary Indian. Clean rectilinear volumes with a strong horizontal emphasis.
        Materials mixed deliberately: exposed concrete or grey render against warm wood
        louvres and a stone-clad feature wall in kota, jaisalmer or granite. Full-height
        glazing to the north and east, screened with jaali or vertical fins to the west.
        Interior palette of white, greys and one warm timber tone, with brass or matte
        black metal detailing. False ceilings carry cove lighting and concealed air
        conditioning. Floors in large-format vitrified tile or Italian marble in formal
        areas, engineered wood in bedrooms.""",
        "AIP style library", "style", "contemporary", "style",
        palette="grey, white, teak", typical_cost_index=1.15,
    ),
    _doc(
        """Industrial. Exposed structure as finish: fair-face concrete soffits, visible
        conduit and cable tray, ducting left open. Exposed brick or block walls, sealed
        rather than plastered. Blackened steel windows with slim sightlines. Floors in
        polished concrete or IPS with a wax finish. Lighting from track spots and pendant
        cages. Furniture in leather, reclaimed timber and raw steel. Works best with
        generous ceiling heights above 3.3 m; in low ceilings it reads as unfinished
        rather than deliberate.""",
        "AIP style library", "style", "industrial", "style",
        palette="concrete grey, black steel, brick red", typical_cost_index=0.88,
    ),
    _doc(
        """Biophilic. Direct nature contact in every habitable room: a window onto planting,
        a courtyard, or a green wall. Materials with visible natural grain and variation -
        timber, stone, rattan, lime plaster, clay. Water feature within earshot of the
        living space. Daylight is prioritised over artificial light, with a target average
        daylight factor above 2.5% in living areas. Indoor planting integrated into the
        joinery rather than added as pots. Palette drawn from foliage and earth: greens,
        browns, sand, terracotta. Ventilation is natural wherever the climate allows.""",
        "AIP style library", "style", "biophilic", "style", "wellness",
        palette="green, sand, terracotta", typical_cost_index=1.2,
    ),
    _doc(
        """Minimal Modern. Reduction to essentials: flush skirting or shadow gaps instead of
        mouldings, concealed door frames, handleless joinery, no visible hardware. A single
        material family per room. Palette of white, off-white and one accent. Lighting is
        entirely concealed - cove, linear recessed, or wall-washing. Every service is
        integrated: air conditioning through linear slot diffusers, curtains in recessed
        pelmets. Demands high build quality; poor workmanship has nowhere to hide, which
        raises the effective cost well above the apparent simplicity.""",
        "AIP style library", "style", "modern_minimal", "style", "minimal",
        palette="white, off-white, single accent", typical_cost_index=1.3,
    ),
]


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------

MATERIALS: list[Document] = [
    _doc(
        """Kota stone. Blue-grey to green limestone from Rajasthan. Honed finish preferred
        over polished for slip resistance. Cool underfoot, extremely durable, ages well and
        develops patina. Low cost relative to granite. Suits high-traffic areas, verandahs,
        kitchens and staircases. Requires periodic sealing against oil staining. Poor choice
        where acidic spills are common. Thermal mass helps moderate room temperature swings
        in hot-dry climates.""",
        "AIP material library", "material", "kota", "flooring", "stone", "budget:low",
    ),
    _doc(
        """AAC block. Autoclaved aerated concrete, density 550-650 kg/m3 against burnt clay
        brick at 1800. Thermal conductivity around 0.16 W/mK versus 0.81 for brick, so a
        200 mm AAC wall substantially outperforms a 230 mm brick wall thermally. Lighter
        dead load reduces structural steel. Faster to lay. Weaker in fixing pull-out, so
        heavy wall-hung items need chemical anchors or embedded inserts. Requires thin-bed
        adhesive mortar, not conventional cement mortar, for the thermal benefit to
        materialise.""",
        "AIP material library", "material", "aac", "masonry", "thermal", "sustainable",
    ),
    _doc(
        """Terracotta jaali. Perforated clay screen with 40-60% open area. Cuts direct solar
        gain while permitting airflow and diffuse light. Most effective on west and
        south-west facades where low-angle afternoon sun defeats horizontal overhangs.
        Provides privacy without blocking ventilation - the reason it recurs across Indian
        vernacular. Evaporative cooling if kept damp. Needs an accessible cleaning
        strategy; dust accumulation in the perforations is the usual maintenance failure.""",
        "AIP material library", "material", "jaali", "facade", "passive_cooling", "traditional",
    ),
    _doc(
        """Athangudi tiles. Handmade cement tiles from the Chettinad region, cast on glass
        plates giving a characteristic sheen. Patterns are geometric and made to order in
        any colour combination. Cooler than vitrified tile and improve with age and
        polishing. Slower to lay and needs skilled masons. Thickness variation demands a
        thicker bedding mortar. Culturally specific: powerful in a regional project,
        incongruous in a minimal one.""",
        "AIP material library", "material", "athangudi", "flooring", "traditional", "regional:tamil_nadu",
    ),
    _doc(
        """Vitrified tile. The default Indian residential floor. Double-charged or full-body
        for high traffic, glazed for lower. 600x600 or 800x800 large format reduces grout
        lines. Water absorption below 0.5% makes it suitable for wet areas in an anti-skid
        finish. Rectified edges permit 2 mm joints. Cost-effective and low-maintenance.
        Thermally cold, which is an advantage in hot climates and a drawback in hill
        stations.""",
        "AIP material library", "material", "vitrified", "flooring", "budget:medium",
    ),
    _doc(
        """Fly ash brick. Made from thermal power station waste, so it diverts an industrial
        by-product and carries a far lower embodied carbon than burnt clay brick, which is
        kiln-fired. Dimensionally accurate, reducing plaster thickness and therefore cost.
        Higher compressive strength than most local clay bricks. Requires thorough wetting
        before laying. Availability varies sharply by region - verify supply before
        specifying.""",
        "AIP material library", "material", "fly_ash", "masonry", "sustainable",
    ),
    _doc(
        """Lime plaster. Breathable, self-healing of hairline cracks, and it regulates
        interior humidity - a genuine advantage in humid coastal climates where cement
        plaster traps moisture and blisters paint. Compatible with historic and laterite
        construction. Slower to cure and needs skilled application, which limits contractor
        availability. Finish ranges from coarse to the polished araish or egg-plaster used
        in Chettinad and Rajasthani work.""",
        "AIP material library", "material", "lime", "plaster", "sustainable", "traditional",
    ),
    _doc(
        """Cool roof coating. High-albedo elastomeric or ceramic coating over a terrace slab.
        Reflects 80% or more of incident solar radiation and can lower the surface
        temperature of the slab by 15-20 degrees C, cutting top-floor cooling load
        materially. Cheap relative to its effect, which makes it one of the highest-return
        interventions available on an Indian residential roof. Needs recoating roughly every
        5-7 years. Combine with a brickbat coba weathering course for thermal mass as well
        as reflectance.""",
        "AIP material library", "material", "cool_roof", "roofing", "thermal", "sustainable",
    ),
]


# ---------------------------------------------------------------------------
# Passive design strategy
# ---------------------------------------------------------------------------

STRATEGIES: list[Document] = [
    _doc(
        """Courtyard cooling. A central open courtyard drives stack ventilation: air heated
        inside rises and escapes, drawing cooler air from shaded ground-level openings.
        Effectiveness rises with courtyard depth-to-width ratio; a proportion between 1:1
        and 1:2 works well in hot-dry climates. Adding water or planting introduces
        evaporative cooling. In hot-humid climates keep the courtyard shaded but open to
        breeze rather than enclosed. This is the mechanism behind the Vastu Brahmasthan
        rule, and it is measurable rather than symbolic.""",
        "AIP passive design guide", "reference", "courtyard", "passive_cooling", "ventilation",
    ),
    _doc(
        """Window shading by orientation. Horizontal overhangs work on south facades in the
        northern hemisphere, where the sun is high. They largely fail on east and west
        facades, where low-angle morning and afternoon sun comes in under the projection -
        those need vertical fins, louvres, jaali screens or landscape shading. Overhang
        depth for a south facade is approximately window height divided by the tangent of
        the summer noon solar altitude. West glazing is the single largest avoidable
        cooling load in Indian residential design.""",
        "AIP passive design guide", "reference", "shading", "solar", "daylight",
    ),
    _doc(
        """Cross ventilation design. Inlet and outlet openings must be on faces with
        different wind pressure - opposite or adjacent walls, not the same one. A smaller
        inlet with a larger outlet increases interior air velocity. Openings positioned at
        occupant height matter more for comfort than high-level openings, which serve heat
        removal instead. Interior doors and transom ventilators maintain the flow path when
        doors are shut. Rooms deeper than about 5 times their ceiling height rarely
        ventilate adequately from one side.""",
        "AIP passive design guide", "reference", "cross_ventilation", "ventilation", "comfort",
    ),
    _doc(
        """Thermal mass strategy. High mass suits hot-dry climates with large day-night
        temperature swings: the wall absorbs heat by day and releases it at night when
        outside air is cooler. It is counterproductive in hot-humid climates where nights
        stay warm, and a lightweight, well-ventilated, well-shaded envelope performs better
        there. Getting this backwards is the most common climate-response error in Indian
        residential design, because the same detail is copied between Rajasthan and Kerala.""",
        "AIP passive design guide", "reference", "thermal_mass", "thermal", "climate",
    ),
    _doc(
        """Daylight without heat. North-facing glazing in the northern hemisphere delivers
        diffuse, steady, glare-free illumination with minimal solar gain, which is why
        studios and workshops face north worldwide. Clerestory windows and light shelves
        push daylight deeper into a plan than tall windows alone. Aim for an average
        daylight factor above 2% in living spaces and above 1% in circulation. Light-toned
        interior surfaces roughly double effective daylight penetration through inter-
        reflection.""",
        "AIP passive design guide", "reference", "daylight", "solar", "comfort",
    ),
    _doc(
        """Rainwater harvesting. Mandatory in most Indian municipalities above a threshold
        plot size. Roof catchment yield in litres is roughly roof area in square metres
        times annual rainfall in millimetres times a runoff coefficient of about 0.8. A
        first-flush diverter is essential to keep the initial dirty runoff out of storage.
        Recharge pits suit high-permeability soils; storage tanks suit clay. Locating
        recharge in the north-east aligns with both the Vastu slope rule and sound surface
        drainage away from the foundations.""",
        "AIP passive design guide", "reference", "rainwater", "sustainable", "water",
    ),
    _doc(
        """Kitchen ergonomics. The work triangle between sink, hob and refrigerator should
        total 4-8 m, with no leg under 1.2 m. Counter height 850-900 mm; 820 mm suits users
        below 160 cm. Minimum 600 mm clear counter beside the hob and 400 mm beside the
        sink. Aisle width 1000-1200 mm for one cook, 1200-1500 mm where two work together.
        Exhaust must discharge outside, not recirculate, in Indian cooking where high-heat
        tempering produces heavy grease and smoke.""",
        "AIP detail library", "reference", "kitchen", "ergonomics", "interior",
    ),
    _doc(
        """Bedroom planning. Minimum 900 mm clear circulation on both sides of a double bed
        and 750 mm at its foot. Wardrobe doors need 600 mm clear swing, or use sliders in
        tight rooms. Bed head against a solid wall rather than a window reduces draught and
        gives acoustic backing. Avoid placing the bed directly in line with the door for
        privacy. Provide switched sockets at bedside height on both sides. Keep the room
        clear of the main circulation route to any other space.""",
        "AIP detail library", "reference", "bedroom", "ergonomics", "interior",
    ),
    _doc(
        """Bathroom layout. Separate wet and dry zones with a threshold or glass partition;
        the wet zone falls 1:80 to the drain. WC needs 700 mm clear front and 350 mm each
        side of centreline. Washbasin 800-850 mm high with 550 mm clear front. Provide
        mechanical extract where there is no external window, at 6-8 air changes per hour.
        Tank waterproofing must return 300 mm up the wall and 150 mm beyond the wet zone.
        Grab-rail blocking should be built in even where rails are not fitted initially -
        retrofitting into tiled walls is disproportionately expensive.""",
        "AIP detail library", "reference", "bathroom", "ergonomics", "accessibility", "interior",
    ),
    _doc(
        """Staircase comfort. The Blondel rule, twice the riser plus the tread, should fall
        between 580 and 650 mm. Residential optimum is a 165-175 mm riser with a 280-300 mm
        tread. All risers in a flight must be identical - variation is the leading cause of
        stair falls. Landings after a maximum of 15 risers. Handrails at 900 mm, extending
        300 mm beyond the top and bottom risers. Provide 2.1 m clear headroom measured
        vertically from the nosing line.""",
        "AIP detail library", "reference", "staircase", "ergonomics", "safety",
    ),
]


# ---------------------------------------------------------------------------
# Precedent patterns
# ---------------------------------------------------------------------------

PRECEDENTS: list[Document] = [
    _doc(
        """Narrow urban plot, 6-9 m frontage. Organise the plan around a side courtyard or
        light well running the full depth, since only the front and rear facades are
        available for openings. Place the staircase against a party wall to preserve
        daylight frontage. Stack wet areas vertically to shorten plumbing runs. Consider a
        double-height void over the living space to bring light down. Parking usually
        consumes the entire ground frontage, which pushes living space to the first floor -
        plan the arrival sequence accordingly.""",
        "AIP precedent library", "precedent", "narrow_plot", "urban", "typology",
    ),
    _doc(
        """Corner plot advantage. Two road frontages allow the entrance and the service
        access to be separated completely, which is worth more than the extra frontage
        itself. Setbacks on two sides give better daylight and ventilation. Place the
        primary entrance on the quieter street, and orient the main living spaces away from
        the busier one for acoustic reasons. Corner plots also permit a genuinely
        north-east entrance more often, which resolves the common conflict between Vastu
        preference and road position.""",
        "AIP precedent library", "precedent", "corner_plot", "urban", "typology",
    ),
    _doc(
        """Multi-generational Indian household. Provide a ground-floor bedroom with an
        attached, step-free bathroom for elderly members - retrofitting this later is
        expensive and disruptive. Separate the formal drawing room from the family living
        area so guests can be received without crossing private zones. A larger kitchen
        with a dedicated utility and provision for a second cooking point is common. Puja
        room in the north-east at ground level with room for gathering. Acoustic separation
        between generations matters more than absolute floor area.""",
        "AIP precedent library", "precedent", "multi_generational", "residential", "accessibility",
    ),
    _doc(
        """Work-from-home provision. A dedicated study with a door beats a corner of the
        bedroom for both concentration and video calls. North light avoids screen glare and
        stays constant through the day. Position it away from the kitchen and the main
        circulation route. Provide structured cabling or a dedicated wireless access point,
        and a UPS circuit. Acoustic isolation from the living area matters most between
        09:00 and 18:00, when the rest of the household is active.""",
        "AIP precedent library", "precedent", "home_office", "residential", "contemporary",
    ),
]


def seed_documents() -> list[Document]:
    """The full built-in corpus."""
    return [*STYLES, *MATERIALS, *STRATEGIES, *PRECEDENTS]


def corpus_summary() -> dict[str, int]:
    return {
        "styles": len(STYLES),
        "materials": len(MATERIALS),
        "strategies": len(STRATEGIES),
        "precedents": len(PRECEDENTS),
        "total": len(seed_documents()),
    }
