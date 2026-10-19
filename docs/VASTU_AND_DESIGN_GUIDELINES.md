# Vastu and Indian house design guidelines

The rulebook Atri Arch designs and checks houses against: every point from the
guideline review, where it came from, and how the project uses it. When sources
disagree, the disagreement is written down here, not hidden.

## How each point is used

| Status | Meaning |
|---|---|
| **Scored** | A Vastu rule in `backend/aip/engines/vastu/knowledge.py` measures it on every plan. The rule id is given. |
| **Shapes the plan** | Also weighed by the layout optimiser (`quick_vastu_score`), so generated plans lean towards it. |
| **Graph** | No text rule names the room; the knowledge graph (`engines/vastu/graph.py`, `reasoner.py`) derives a verdict from what the room is used for. |
| **Code check** | A building-code check in `backend/aip/engines/architecture/codes.py` (NBC 2016 or the local bye-law). |
| **Site checklist** | Decided on the plot, not in the drawings. Listed in the Vastu view for the builder, never guessed at in the score. |
| **Interior stage** | Decided when the furniture is laid out, not at plan stage. |
| **Built in** | The 3D model and drawings use this value as a constant. |

A Vastu rule's influence on the score depends on the client's stance (the
Vastu slider): `effective weight = classical weight × (tradition + (1 − tradition) × modern validity)`.
A purely traditional client weighs every rule fully; a purely modern one weighs
each rule only as far as it has a functional basis (light, air, heat, hygiene).

---

## Part 1: Vastu Shastra

### Plot and site (G-S)

| # | Guideline | Status |
|---|---|---|
| G-S1 | The plot and the plan should be square or rectangular, not irregular. | Scored: `VS.PROPORTION.SQUARE` |
| G-S2 | The north-east corner must not be cut; an extension towards the north-east is welcome, elsewhere it is not. | Scored: `VS.CORNER.NORTHEAST_EXTENSION` |
| G-S3 | Ground slopes down towards the north-east (rain runs to the north and east). Some current writers treat this as site-dependent rather than a law. | Scored where levels are recorded: `VS.SLOPE.NORTHEAST_LOW` |
| G-S4 | Tall trees and higher, thicker boundary walls on the south and west; low planting in the north-east. | Site checklist: `VS.SITE.TREES_SOUTHWEST` |
| G-S5 | More open space in the north and east than in the south and west. | Scored: `VS.OPEN.NORTHEAST`, `VS.MASS.SOUTHWEST_HEAVY` |
| G-S6 | Lawn and garden are best in the north and east. | Shapes the plan: lawn share in the brief holds coverage down; planting is placed in the open setbacks |

### Entrance (G-E)

| # | Guideline | Status |
|---|---|---|
| G-E1 | Main entrance in the north, east or north-east; south-west is most avoided, south-east and west are workable but second tier. | Scored: `VS.ENTRANCE.NORTH_EAST` |
| G-E2 | The entrance addresses the approach road. | Scored: `VS.ENTRANCE.ROAD_FACING` |
| G-E3 | Door position along its wall (the nine padas per side): towards the north-east on the north and east sides, towards the south-east on the south side, towards the north-west on the west side. Sources disagree on pada numbering and names, so the rule scores thirds of the side rather than named padas. | Scored and shapes the plan: `VS.ENTRANCE.PADA` |
| G-E4 | The main door is the largest door in the house, opens inwards, and is well lit. | Code check (width): `DOOR_MAIN`; leaf and lighting at interior stage |
| G-E5 | No staircase straight ahead of the main door. | Scored and shapes the plan: `VS.ENTRANCE.STAIR_NOT_FACING` |
| G-E6 | No toilet straight ahead of the main door. | Scored and shapes the plan: `VS.ENTRANCE.TOILET_NOT_FACING` |
| G-E7 | No obstruction in front of the door (a pillar, a tree, a pole). | Site checklist (not modelled) |

### Room zones (G-Z)

The plan is read as the nine-square Vastu Purusha mandala: Ishanya (north-east, water),
Agneya (south-east, fire), Nairutya (south-west, earth), Vayavya (north-west, air)
and the Brahmasthan (centre, space).

| # | Guideline | Status |
|---|---|---|
| G-Z1 | Master bedroom in the south-west. | Scored and shapes the plan: `VS.MASTER.NAIRUTYA` |
| G-Z2 | The master bedroom is the largest bedroom. | Scored and shapes the plan: `VS.MASTER.LARGEST` |
| G-Z3 | Other bedrooms in the south, west or north-west; never the north-east. | Scored and shapes the plan: `VS.BEDROOM.SOUTH_WEST_WEST` |
| G-Z4 | Children's room in the west or north-west. Sources differ: some put it in the east. | Scored and shapes the plan: `VS.CHILDREN.WEST_NORTH` |
| G-Z5 | Kitchen in the south-east (Agneya); north-west as the second choice. | Scored and shapes the plan: `VS.KITCHEN.AGNEYA` |
| G-Z6 | Guest room in the north-west. Some sources put it in the east. | Scored and shapes the plan: `VS.GUEST.NORTHWEST` |
| G-Z7 | Puja room in the north-east, on the ground floor. | Scored and shapes the plan: `VS.PUJA.ISHANYA` |
| G-Z8 | Study and home office in the north, east or north-east. | Scored for the study: `VS.STUDY.NORTHEAST_EAST`; Graph for the home office |
| G-Z9 | Balconies on the north or east. | Scored and shapes the plan: `VS.BALCONY.NORTH_EAST` |
| G-Z10 | Verandahs and sit-outs on the north or east. | Scored and shapes the plan: `VS.VERANDAH.NORTH_EAST` |
| G-Z11 | Living room in the north, east or north-east. | Scored and shapes the plan: `VS.LIVING.NORTH_EAST` |
| G-Z12 | Utility, laundry and wash area in the north-west. | Scored: `VS.UTILITY.NORTHWEST`; Graph for the laundry |
| G-Z13 | Dining in the west (or east), near the kitchen. | Scored and shapes the plan: `VS.DINING.WEST` |
| G-Z14 | Store rooms and heavy storage in the south-west or south. | Scored and shapes the plan: `VS.STORE.SOUTHWEST` |
| G-Z15 | Toilets in the north-west or west; never in the north-east. Sources differ on the south-east and east. | Scored and shapes the plan: `VS.TOILET.NORTHWEST_SOUTH` |
| G-Z16 | Bathrooms (bathing only) in the east or north. | Scored and shapes the plan: `VS.BATHROOM.EAST_NORTH` |
| G-Z17 | Parking in the north-west or south-east. | Scored and shapes the plan: `VS.GARAGE.NORTHWEST_SOUTHEAST` |
| G-Z18 | Staircase in the south, west or south-west; never in the north-east or the centre. | Scored: `VS.STAIR.SOUTHWEST`, `VS.BRAHMASTHAN.NO_STAIR` |
| G-Z19 | Stairs climb clockwise. | Scored: `VS.STAIR.CLOCKWISE` |
| G-Z20 | Gym in the north-west; home theatre in a heavy south or west quarter. | Graph |

### Centre (G-B)

| # | Guideline | Status |
|---|---|---|
| G-B1 | The Brahmasthan (centre) is kept open, ideally a courtyard or light-weight living space. | Scored: `VS.BRAHMASTHAN.OPEN` |
| G-B2 | No toilet at the centre. | Scored: `VS.BRAHMASTHAN.NO_TOILET` |
| G-B3 | No staircase at the centre. | Scored: `VS.BRAHMASTHAN.NO_STAIR` |
| G-B4 | No heavy columns or beams at the centre. | Not modelled (structural grid stage) |

### Water (G-W)

| # | Guideline | Status |
|---|---|---|
| G-W1 | Borewell or well in the north-east, about a third in from the corner, off the boundary, far from the septic tank. | Site checklist: `VS.SITE.BOREWELL_NORTHEAST` |
| G-W2 | Underground sump in the north, east or north-east. | Site checklist: `VS.SITE.SUMP_NORTHEAST` |
| G-W3 | A pool or water feature in the north, north-east or east; never the south-west or south-east. | Scored: `VS.POOL.NORTH_EAST` (when the brief asks for a pool) |
| G-W4 | Overhead tank over the south-west or west, never the north-east. | Site checklist: `VS.SITE.OVERHEAD_TANK_SOUTHWEST` (the 3D model seats it over the stair head) |
| G-W5 | Septic tank in the north-west; never the north-east or south-west. Some sources also allow the south-east. Outlet north or west. | Site checklist: `VS.SITE.SEPTIC_NORTHWEST` |
| G-W6 | Water sources in general sit in the north-east. | Scored: `VS.WATER.NORTHEAST` |

### Fire and kitchen (G-F)

| # | Guideline | Status |
|---|---|---|
| G-F1 | Kitchen in the south-east. | Scored: `VS.KITCHEN.AGNEYA` |
| G-F2 | The cook faces east; hob on the south-east side of the platform, sink apart from the hob (water and fire separated). | Interior stage: `VS.KITCHEN.COOK_FACES_EAST` |

### Relations between rooms (G-R)

| # | Guideline | Status |
|---|---|---|
| G-R1 | No toilet directly above or below the kitchen. | Scored and shapes the plan: `VS.STACK.KITCHEN_TOILET` |
| G-R2 | The puja room shares no wall, floor or ceiling with a toilet; never under a stair. | Scored and shapes the plan: `VS.PUJA.AWAY_FROM_TOILET` |
| G-R3 | Toilet doors do not face the bed or the kitchen. | Interior stage |

### Mass and openings (G-M)

| # | Guideline | Status |
|---|---|---|
| G-M1 | More mass and height to the south and west. | Scored: `VS.MASS.SOUTHWEST_HEAVY` |
| G-M2 | More and larger windows on the north and east. | Scored: `VS.OPENINGS.NORTH_EAST_MORE` |
| G-M3 | Doors are placed off-centre on their walls. | Partly: `VS.ENTRANCE.PADA` for the main door |

### Sleeping and interiors (G-I)

| # | Guideline | Status |
|---|---|---|
| G-I1 | Sleep with the head towards the south (east is also given); never towards the north. | Interior stage: `VS.SLEEP.HEAD_SOUTH` |
| G-I2 | No mirror facing the bed or the main door. | Interior stage (not modelled) |
| G-I3 | Puja idols on the east or west wall, a few inches off the wall. | Interior stage (not modelled) |
| G-I4 | Heavy furniture against the south and west walls. | Interior stage (not modelled) |

---

## Part 2: Designing realistic Indian houses

These are the numbers a house must meet to be approved and lived in. The NBC is a
model code: state and municipal bye-laws override it where they differ, so a
local bye-law always wins. Values here are the NBC 2016 figures as commonly cited.

### Rooms (NBC 2016 Part 3)

| # | Requirement | Value | Status |
|---|---|---|---|
| D-1 | Habitable room area | 9.5 m² for a single-room dwelling; 7.5 m² for each room in a larger home | Code check: `AREA_MIN` |
| D-2 | Habitable room width | 2.4 m minimum | Code check: `WIDTH_MIN` |
| D-3 | Habitable room height | 2.75 m floor to ceiling | Code check: `HEIGHT_MIN` |
| D-4 | Kitchen | 5.0 m² minimum in the NBC; the checker uses a stricter 5.5 m² with a 1.8 m width | Code check: `KITCHEN_MIN` |
| D-5 | Kitchen, bath and WC height | 2.4 m minimum | Covered by the plan's floor-to-floor heights |
| D-6 | Bathroom | 1.8 m² minimum | Code check: `BATH_MIN` |
| D-7 | Separate WC | 1.1 m² with 0.9 m width | Code check: `BATH_MIN` |
| D-8 | Light and ventilation | Openings of at least one-tenth of the floor area (some cite one-eighth openable) | Code check: `LIGHT_MIN`, `VENT_MIN` |
| D-9 | Plinth | 450 mm above ground | Built in: 3D model plinth |

### Stairs and doors (NBC 2016 Parts 3 and 4)

| # | Requirement | Value | Status |
|---|---|---|---|
| D-10 | Stair width, residential | 1.0 m (0.9 m in some bye-laws for a single family) | Code check: `STAIR_WIDTH` |
| D-11 | Riser and tread, residential | Riser at most 190 mm, tread at least 250 mm | Code check: `STAIR_RISER` |
| D-12 | Headroom over a flight | 2.1 m | Code check: `STAIR_HEADROOM` |
| D-13 | Comfort rule | Two risers plus one tread ≈ 600 to 640 mm (a guideline, not code) | Practice target |
| D-14 | Main door | At least 0.9 m clear; about 1.0 m in practice | Code check: `DOOR_MAIN` |
| D-15 | Internal doors | About 0.9 m; bathroom doors about 0.75 m | Practice target |
| D-16 | Parapet | About 1.0 m on an accessible roof | Built in: 3D model parapet |

### Plot (local development control rules)

| # | Requirement | Status |
|---|---|---|
| D-17 | Floor area ratio (FAR) | Code check: `FAR_MAX` (byelaw table by plot size) |
| D-18 | Ground coverage, held down further by any lawn or pool the client asks for | Code check: `COVERAGE_MAX` |
| D-19 | Setbacks on every side | Code check: `SETBACK` (auto setbacks by plot size) |
| D-20 | Building height | Code check: `HEIGHT_MAX` |

### Practice targets used in layout (Indian practice and ergonomics)

| # | Target |
|---|---|
| D-21 | Kitchen work aisle at least about 1.0 m; counter 850 to 900 mm high; sink under a window, hob on an outer wall for an exhaust. |
| D-22 | Wet rooms stacked over wet rooms; one service shaft per stack. |
| D-23 | A foyer or shoe space inside the main door before the living room. |
| D-24 | Puja visible from the living room but not on the route to the toilets. |
| D-25 | Bedrooms off a corridor or lobby, not opening off the living room where it can be avoided. |
| D-26 | Deep overhangs (chajjas) of 450 to 600 mm over windows on the south and west. |

---

## Part 3: Exterior signatures and garden features

Current Indian elevation guides favour "a box plus one or two signature moves"
rather than stacking many. Each design in the studio carries one signature
element, drawn in its own character (column, arch, canopy, rhythm and framing
follow its materials and roof; see `traits()` in `engines/experience/exteriors.py`).

| Element | Idea it comes from | Styles it leans to |
|---|---|---|
| Brick curtain | Houses wrapped in perforated brick jaali (Brick House, Pune; Thiruvananthapuram brick house) | Contemporary, industrial, Kerala, traditional |
| Wave screen | Wavy perforated brick-and-stone screen (Gadi House, PMA Madhushala) | Tropical, biophilic |
| Moon gate | A round aperture in a square screen (Safdarjung Residence) | Contemporary, Japandi, Indo-Saracenic |
| Cantilever room | A first-floor room projecting 0.9 to 1.5 m over the porch | Contemporary, minimal, Scandinavian |
| Fluted bands | Full-height fluted brick or cement-board bands | Contemporary, minimal |
| Brise-soleil | Deep egg-crate sun-breakers (Chandigarh) | Minimal, mid-century, industrial |
| Planter bands | Planter troughs at every slab edge | Tropical, biophilic |
| Crown frame | A thin concrete frame crowning the roof | Contemporary, minimal, industrial |
| Earlier elements | Jharokha, colonnade, chhatri, cornice, breeze-block, green wall, balcony, arcade, portico, bay window, floating box, monolith wall, thinnai, bangla pavilion, pergola frame, glass corner | By style |

Garden features (the `yard` option), each placed in its traditional quarter
when the plot has room (`landscape.yard_spot`):

| Feature | Quarter | Basis |
|---|---|---|
| Tulsi platform (Vrindavan) | North-east | Raised tulsi in the north or east |
| Water wall | North-east | A small, clean water feature in the north-east; trickling water masks traffic noise |
| Koi pond | North / north-east | Water to the north-east; keep it clean against mosquitoes |
| Jhoola swing | North-west | A bench or swing in the north-west facing east or north |
| Gazebo | South-west | Heavier structures to the south and west |
| Rock garden | South-west / west | Stone and gravel paths over manufactured paving |
| Garden sit-out | North | Shade tree and benches; tall trees kept south and west |

Sources: [Contemporary house elevation, Studio Matrx](https://www.studiomatrx.org/guides/contemporary-house-elevation),
[Box-type elevation ideas, Ongrid](https://elevations.ongrid.design/learn/box-type-elevation-design-ideas/),
[Elevation design styles, Ongrid](https://elevations.ongrid.design/learn/topics/elevation-design-styles/),
[Award-winning Kerala brick house, Onmanorama](https://onmanorama.com/lifestyle/decor/2020/09/25/award-winning-house-kerala-garner-global-attention.html),
[Gadi House, Dezeen](https://www.dezeen.com/2022/09/15/pma-madhushala-gadi-house-resdential-architecture-india/amp/),
[Brick House Pune, Architizer](https://architizer.com/projects/brick-house-28/),
[18 Screens House, Global Design News](https://globaldesignnews.com/18-screen-house-by-sanjay-puri-architects-design-a-mega-residence-of-concrete/),
[Vastu for gardens, BricknBolt](https://www.bricknbolt.com/blogs-and-articles/home-design-guide/vastu-for-gardens-tips-guidelines),
[Water features in Indian landscapes, Studio Matrx](https://www.studiomatrx.org/guides/water-features-landscape-design-india),
[Vastu-compliant landscaping, JSW One Homes](https://www.jswonehomes.com/blogs/design/vastucompliant-landscaping-to-enhance-indian-homes).

## Part 4: Signature homes (whole houses after admired ones)

Beyond single elements, the studio offers complete houses designed as a whole
after house types people travel to see (`engines/experience/looks.py`, the
"Signature homes" chip in the Exterior tab). Each comes fitted to the plan and
in three colourways; every part stays customisable afterwards.

| Signature home | After | What makes it |
|---|---|---|
| Goan Villa | Portuguese-era villas of Goa | Pastel plaster, verandah of columns (balcão), white-framed windows, tiled hip roof |
| Chettinad Mansion | Chettiar mansions, Karaikudi | Stone plinth, carved-pillar thinnai, jaali, stepped parapet, Athangudi colours |
| Kerala Nalukettu | Kerala tharavads | Tiled hip roof on deep eaves, timber upper over laterite, verandah posts, lush garden |
| Mumbai Art Deco | Marine Drive and Oval Maidan | Eyebrow chajjas, curving balconies, grooved parapet bands, pastel walls |
| Laurie Baker Brick House | Laurie Baker's Kerala houses | Exposed brick, brick jaali curtain for air, sloping roof, nothing plastered |
| Bawa Tropical House | Geoffrey Bawa's tropical modernism | White walls, terracotta hip roof, colonnade, deep overhangs, water |
| Chandigarh Modernist | Le Corbusier's Chandigarh | Raw concrete, brick panels, egg-crate brise-soleil |
| Rajput Haveli | Havelis of Jaipur and Jaisalmer | Sandstone, jaali, jharokhas, stepped parapet, water wall |
| Jodhpur Blue House | Jodhpur's old city | Indigo walls, white trims, rooftop chhatris |
| Bengal Terracotta Bari | Bishnupur temples and Bengal baris | Terracotta skin, bangla-roofed pavilion |
| Mughal Garden Pavilion | Mughal garden pavilions | Red sandstone, pointed-arch arcade, water channel |
| Colonial Bungalow | Cantonment bungalows, Bengaluru and Pune | Portico, white trims, tiled hip roof, grille boundary |
| Pondicherry French House | White Town, Pondicherry | Ochre or yellow walls, white columns, grooved parapet, swing |
| Japandi Courtyard House | Japanese calm in Indian timber | Slats, moon gate, gravel and rock garden |
| Brutalist Concrete Villa | Contemporary Indian concrete houses | Board-marked concrete, cantilevered room, LED strips |
| Glass Pavilion | Minimal modern houses | White box, glass corner, glass parapet, water wall |
| Tropical Resort Villa | Kerala and Bali resort houses | Butterfly roof, timber and bamboo, planter bands, koi pond |
| Nordic Black Cabin | Scandinavian cabins | Black timber gable, glass corner |

Sources: [South Indian house design, BricknBolt](https://www.bricknbolt.com/blogs-and-articles/home-design-guide/south-indian-house-design),
[Kerala architecture, Housing.com](https://housing.com/news/kerala-architecture/),
[Kerala and Chettinad in contemporary homes, Benny Kuriakose](https://www.bennykuriakose.com/post/kerala-traditional-houses-and-chettinad-architecture-in-contemporary-homes),
[Stunning traditional homes in India, Buildofy](https://www.buildofy.com/blog/5-most-stunning-traditional-homes-in-india-as-featured-on-buildofy/),
[Guide to Art Deco in India, Lonely Planet](https://www.lonelyplanet.com/articles/guide-to-art-deco-in-india),
[Geoffrey Bawa's tropical modernism, Commune](https://communedesign.com/post/geoffrey-bawas-tropical-modernism/),
[Geoffrey Bawa, Ampersand Travel](https://ampersandtravel.com/blog/2024/geoffrey-bawa-the-pioneer-of-tropical-modernism),
[Award-winning Kerala brick house, Onmanorama](https://onmanorama.com/lifestyle/decor/2020/09/25/award-winning-house-kerala-garner-global-attention.html).

## Part 5: Temperature and thermal comfort

The Air tab's Temperature view (`engines/architecture/thermal.py`) runs every
indoor room hour by hour through a design day of the client's city:

- **Climate:** monthly averages for 19 Indian cities (mean daily maximum and
  minimum, mean humidity), after IMD climatological normals, rounded. The
  city is the one named in the brief, or the nearest to the plot. "Hottest",
  "wettest" and "coolest" pick that city's own months; any month can be chosen.
- **Model:** two nodes per room (air, and the brick and RCC mass), driven by
  the sun on each wall and the roof (NOAA sun position, clear-sky beam and
  diffuse, cut by monsoon cloud), glass with chajja shading, air changes from
  the breeze solve, and people and cooking.
- **Construction defaults:** 230 mm brick U 2.1 W/m2K, 150 mm RCC roof U 3.0
  (1.2 with a cool roof), single glass U 5.7, SHGC 0.6.
- **Comfort:** IMAC (India Model for Adaptive Comfort, 2016), neutral
  temperature 0.54 x outdoor mean + 12.83 C, +/-2.4 C for 90% acceptability;
  moving air from the breeze or a ceiling fan feels cooler (ASHRAE 55).
- **AC:** sensible load to hold 26 C (BEE default) with windows shut, +25%
  for latent load and pull-down.
- **Thermal camera:** inside surface temperatures of each outside wall,
  window glass with the sun through it, the ceiling under an exposed slab and
  the open ground, drawn in an infrared palette.

It ranks rooms and sizes fixes at concept stage; it is not a full simulation.

---

## Where sources disagree

- **Toilets:** north-west and west are agreed; some sources allow the south-east and east, others forbid them. The rule favours north-west and west and forbids only the north-east.
- **Children's and guest rooms:** west or north-west in most sources, east in some.
- **Bed direction:** head south is common; some sources also give east. Never north is agreed.
- **Door padas:** sources use eight or nine padas a side and name them differently; the rule scores thirds of the side rather than named padas.
- **Septic tank:** north-west in most sources; some also allow the south-east.
- **Slope:** traditional texts require a north-east fall; current writers treat it as site-dependent.
- **Stair riser:** 150, 175 or 190 mm depending on source and occupancy; the checker uses 190 mm for one- or two-family homes.

## Sources

Vastu (popular and practitioner sources, read as conventions, not a canon):
- [Vastu for Home, JK Cement](https://www.jkcement.com/blog/vastu/vastu-shastra-for-home/amp/)
- [Vastu Shastra basics for your home, ICICI Lombard](https://www.icicilombard.com/blog/home-insurance/hoi/vastu-shastra-basics-for-your-home)
- [Essential Vastu principles for home, BricknBolt](https://www.bricknbolt.com/blogs-and-articles/home-design-guide/essential-vastu-principles-for-home)
- [Vastu entrance padas and Ayadi with verse citations, RoxyAPI](https://roxyapi.com/blogs/vastu-api-entrance-padas-ayadi-with-verse-citations)
- [Main door direction, Studio Matrx](https://www.studiomatrx.org/guides/main-door-direction-vastu-india)
- [South-facing house Vastu plan, Design Cafe](https://www.designcafe.com/blog/home-interiors/south-facing-house-vastu-plan-30x40/)
- [Borewell Vastu, BricknBolt](https://www.bricknbolt.com/blogs-and-articles/home-design-guide/borewell-vastu-best-directions-tips)
- [Septic tank Vastu, Housiey](https://housiey.com/blogs/?p=9446)
- [Toilets and drains, Studio Matrx](https://www.studiomatrx.org/students/vastu-building-science/2-4-toilets-and-drains)
- [Vastu rules, Astroyogi](https://www.astroyogi.com/vastu/rules)
- [Mirror direction as per Vastu, UltraTech Cement](https://www.ultratechcement.com/for-homebuilders/home-building-explained-single/descriptive-articles/mirror-direction-as-per-vastu)
- Classical treatises named in the rule corpus: Manasara, Mayamata, Vishvakarma Prakasha, Samarangana Sutradhara, Brihat Samhita (ch. 53).

Design (verify against the BIS text and the local bye-law before relying on a number):
- [NBC 2016 Part 3 quick reference, InfraLens](https://infralens.in/code/NBC-2016-Part-3-2016)
- [Space standards and clearances, Studio Matrx](https://www.studiomatrx.org/students/space-planning-ergonomics/space-standards-and-clearances)
- [Staircase design, InfraLens](https://infralens.in/handbook/staircase-design)
