"""The exterior grammar: diverse batches, customised ids, buildable fits."""

from __future__ import annotations

from aip.engines.experience.arch3d import build_scene
from aip.engines.experience.exteriors import Exterior, distance, generate


def test_default_set_is_stable_and_distinct(plan):
    a, b = generate(plan, 10), generate(plan, 10)
    assert [e.id for e in a] == [e.id for e in b]
    assert len({e.form for e in a}) == len(a) == 10
    assert len({e.roof for e in a}) >= 3                      # spread, not near-duplicates


def test_seeded_batches_are_fresh_and_avoid_what_was_shown(plan):
    first = generate(plan, 12, seed="1")
    second = generate(plan, 12, seed="2", avoid={e.id for e in first})
    assert {e.form for e in first}.isdisjoint({e.form for e in second})
    assert all(e.wall for e in first)                          # fresh batches vary colour too
    assert min(distance(x, y) for i, x in enumerate(first) for y in first[i + 1:]) > 0


def test_id_round_trips_with_tints_and_old_ids_still_parse():
    e = Exterior("gable", "timber", "stone", "jaali", "band", True, "copper", "balcony",
                 wall="efe9dc", clad="8a6a4c", roof_tint="a8553a", metal="2b2a29")
    assert Exterior.parse(e.id) == e
    assert Exterior.parse("ex:flat.stone.plaster.fins.punched.n.bronze") is not None
    assert Exterior.parse("ex:flat.stone.plaster.fins.punched.n.bronze.none~w:zzzzzz").wall == ""


def test_fit_repairs_what_the_house_cannot_carry():
    e, notes = Exterior(roof="hip", feature="chhatri").fitted(one_floor=False)
    assert e.roof == "flat" and notes
    e, notes = Exterior(upper="timber", feature="balcony").fitted(one_floor=True)
    assert e.upper == "plaster" and e.feature == "none" and len(notes) == 2


def test_every_roof_and_signature_builds_with_tints(plan):
    for roof, feature in (("butterfly", "balcony"), ("slab", "greenwall"), ("flat", "chhatri"), ("gable", "colonnade")):
        ex = Exterior(roof, "metal", "concrete", "louvres", "band", True, "verdigris", feature,
                      wall="c9cfb7", clad="59626b", roof_tint="3d3f42", metal="b08a3e")
        scene = build_scene(plan, include_furniture=False, design_id=ex.id)
        names = {g.visual.material.name for g in scene.geometry.values()}
        assert "exterior_accent" in names



def test_exterior_schemes_are_valid_tints():
    from aip.engines.experience.exteriors import EXTERIOR_SCHEMES, _hex6, grammar

    assert len(EXTERIOR_SCHEMES) >= 16 and len({s["id"] for s in EXTERIOR_SCHEMES}) == len(EXTERIOR_SCHEMES)
    assert all(_hex6(s[k]) for s in EXTERIOR_SCHEMES for k in ("wall", "clad", "roof", "metal"))
    assert grammar()["schemes"]


def test_site_options_and_extra_tints_round_trip_and_build(plan):
    e = Exterior("flat", "stone", "plaster", "fins", "punched", False, "brass", "none",
                 frame="1c1b1a", door="1f5a5e", boundary="hedge", railing="metal")
    assert Exterior.parse(e.id) == e
    assert Exterior.parse(e.id.replace("b:hedge", "b:moat")).boundary == ""     # unknown options are dropped
    for boundary, railing in (("stone", "solid"), ("grille", "metal"), ("hedge", "glass")):
        ex = Exterior(boundary=boundary, railing=railing, frame="efece6")
        names = {g.visual.material.name for g in build_scene(plan, include_furniture=False, design_id=ex.id).geometry.values()}
        assert ("compound_stone" in names) == (boundary == "stone")


def test_style_led_batches_differ(plan):
    from aip.engines.experience.exteriors import grammar

    haveli = generate(plan, 12, seed="s", style="rajasthani_haveli")
    nordic = generate(plan, 12, seed="s", style="scandinavian")
    assert {e.form for e in haveli} != {e.form for e in nordic}
    assert sum(e.screen == "jaali" for e in haveli) > sum(e.screen == "jaali" for e in nordic)
    g = grammar()
    assert len(g["schemes"]) >= 30 and len(g["paints"]["wall"]) >= 20 and g["styles"]


def test_every_new_option_builds_and_round_trips(plan):
    from aip.engines.experience.exteriors import OPTION_KEYS

    for (field, vocab) in OPTION_KEYS.values():
        for v in vocab:
            ex = Exterior(roof="flat", **{field: v})
            assert Exterior.parse(ex.id) == ex
    ex = Exterior(roof="flat", shade="box", canopy="pergola", gate="sliding", paving="gravel", garden="lush", solar="on")
    names = {g.visual.material.name for g in build_scene(plan, include_furniture=False, design_id=ex.id).geometry.values()}
    assert {"solar_panel", "gravel"} <= names
    fitted, notes = Exterior(roof="hip", solar="on").fitted(one_floor=False)
    assert fitted.solar == "" and notes


def test_a_style_shapes_the_whole_design(plan):
    from aip.engines.experience.exteriors import STYLE_DNA

    kerala = generate(plan, 12, seed="k", style="kerala_vernacular")
    assert sum(e.roof in ("hip", "gable") for e in kerala) >= 8               # its tiled roofs
    assert sum(e.shade == "deep" for e in kerala) >= 8                        # and its deep chajjas
    assert sum(e.gate == "timber" for e in kerala) >= 8                       # and a timber gate
    schemes = {s["wall"].lstrip("#") for s in __import__("aip.engines.experience.exteriors", fromlist=["x"]).EXTERIOR_SCHEMES
               if s["id"] in STYLE_DNA["kerala_vernacular"]["schemes"]}
    assert sum(e.wall in schemes for e in kerala) >= 4                        # often in its own colours


def test_the_clients_words_steer_a_batch(plan):
    from aip.engines.experience.exteriors import prefer_from_text

    asked = prefer_from_text("A wooden house with a tiled roof, lots of greenery and solar panels")
    assert "timber" in asked["upper"] and "hip" in asked["roof"] and asked["solar"] > 0.5
    # Against a style that wants none of it, the words still carry the batch.
    batch = generate(plan, 12, seed="w", prefer=asked, style="industrial")
    plain = generate(plan, 12, seed="w", style="industrial")
    assert sum(e.roof in ("hip", "gable") for e in batch) > sum(e.roof in ("hip", "gable") for e in plain)
    assert sum(e.garden == "lush" for e in batch) > sum(e.garden == "lush" for e in plain)
    assert prefer_from_text("") == {}


def test_designer_sketches_get_their_styles_details():
    from aip.engines.experience.exteriors import with_style_details

    e = with_style_details(Exterior(roof="hip"), "kerala_vernacular")
    assert e.shade == "deep" and e.gate == "timber"
    assert with_style_details(Exterior(roof="hip"), "kerala_vernacular") == e      # the same every time


def test_new_finishes_and_options_build(plan):
    ex = Exterior("flat", "terracotta", "acp", "louvres", "band", True, "brass", "none",
                  panel="slate", parapet="glass", deck="garden", lights="strips")
    assert Exterior.parse(ex.id) == ex
    names = {g.visual.material.name for g in build_scene(plan, include_furniture=False, design_id=ex.id).geometry.values()}
    assert {"terracotta_tile", "facade_light", "lawn"} <= names
    for parapet in ("plain", "grooved", "screen", "stepped"):
        build_scene(plan, include_furniture=False, design_id=Exterior(roof="flat", parapet=parapet, lights="washers").id)
    fitted, notes = Exterior(roof="gable", deck="garden", parapet="glass").fitted(one_floor=False)
    assert fitted.deck == "" and fitted.parapet == "" and notes


def test_no_two_houses_share_an_exterior(plan):
    from aip.engines.experience import registry
    from aip.engines.experience.exteriors import combinations

    registry.reset()
    mine = generate(plan, 6, seed="u")
    assert registry.claim("house-a", mine[0].id)["unique"]
    assert registry.claim("house-a", mine[0].id)["unique"]                 # claiming your own again is fine
    other = registry.claim("house-b", mine[0].id)
    assert not other["unique"] and other["shared_with"] == 1
    offered = generate(plan, 12, seed="u", taken=registry.taken_forms("house-b"))
    assert mine[0].form not in {e.form for e in offered}
    registry.reset()
    assert combinations() > 10 ** 18


def test_a_roof_garden_asks_for_a_flat_roof_and_is_heard_once(plan):
    from aip.engines.experience.exteriors import heard, prefer_from_text

    asked = prefer_from_text("contemporary with ACP, lighting and a roof garden")
    assert asked["roof"] == ("flat",) and asked["deck"] == ("garden",)
    assert heard("contemporary with ACP, lighting and a roof garden") == ["roof garden", "contemporary", "acp", "lighting"]
    batch = generate(plan, 12, seed="g", prefer=asked)
    assert sum(e.deck == "garden" for e in batch) >= 8
