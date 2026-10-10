"""Uploading a plan: it must come back as the same plan, and get every analysis.

The strongest test of an importer is the round trip. A scheme the platform
drew is exported, uploaded, and compared room for room with what went out.
Anything the importer loses or invents shows up as a number that moved.
"""

from __future__ import annotations

import asyncio
import io
import re

import pytest
from fastapi.testclient import TestClient

from aip.api.app import app
from aip.domain.brief import default_residence_brief
from aip.domain.geometry import Vec2
from aip.domain.plan import RoomType
from aip.engines.architecture import importer
from aip.engines.architecture.drawings import floor_plan_svg
from aip.engines.architecture.dxf import export_dxf
from aip.engines.architecture.importer import (
    ImportError_,
    classify,
    import_floorplan,
    parse_dxf,
    parse_svg,
)
from aip.engines.architecture.layout import GeneratorConfig, LayoutGenerator
from aip.engines.architecture.programme import walkability
from aip.engines.architecture.raster import local_vision_available
from aip.engines.architecture.recover import rooms_from_linework, strip_cad_formatting
from scripts.import_bench import score
from scripts.import_fixtures import raster, walls_dxf, walls_svg


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def original():
    brief = default_residence_brief()
    return LayoutGenerator(
        brief, GeneratorConfig(population=36, generations=32, seed=23)
    ).generate(1)[0]


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("label", "kind"), [
    ("MASTER BEDROOM", RoomType.MASTER_BEDROOM),
    ("Bedroom 2", RoomType.BEDROOM),
    ("BED ROOM 12'x10'", RoomType.BEDROOM),
    ("Living / Hall", RoomType.LIVING),
    ("DINING 15.5 m2", RoomType.DINING),
    ("Kit.", RoomType.KITCHEN),
    ("Pooja", RoomType.PUJA),
    ("W.C.", RoomType.TOILET),
    ("Att. Toilet", RoomType.TOILET),
    ("Bath", RoomType.BATHROOM),
    ("Utility / Wash", RoomType.UTILITY),
    ("Car Parking", RoomType.GARAGE),
    ("Sit-out", RoomType.VERANDAH),
    ("Passage", RoomType.CORRIDOR),
    ("Title block", None),
    ("", None),
])
def test_labels_classify_the_way_a_drawing_writes_them(label, kind):
    assert classify(label) is kind


# ---------------------------------------------------------------------------
# DXF round trip
# ---------------------------------------------------------------------------


def test_dxf_round_trip_is_exact(original):
    """What went out comes back: same rooms, same types, same areas."""
    dxf = export_dxf(original, 0).encode()
    result = _run(import_floorplan(dxf, "scheme.dxf", plot_width=12.0, plot_depth=18.0))

    assert result.source == "dxf"
    assert result.rooms_kept == len(original.level_at(0).rooms)
    assert result.unrecognised == []

    out = sorted((r.type.value, round(r.area, 1)) for r in original.level_at(0).rooms)
    back = sorted((r.type.value, round(r.area, 1)) for r in result.plan.level_at(0).rooms)
    assert out == back


def test_dxf_round_trip_keeps_its_own_margins(original):
    """A drawing with units is never inflated to fill a larger plot."""
    dxf = export_dxf(original, 0).encode()
    result = _run(import_floorplan(dxf, "scheme.dxf", plot_width=12.0, plot_depth=18.0))
    total_out = sum(r.area for r in original.level_at(0).rooms)
    total_back = sum(r.area for r in result.plan.level_at(0).rooms)
    assert total_back == pytest.approx(total_out, rel=1e-3)


def test_imported_plan_gets_every_downstream_analysis(original):
    from aip.engines.architecture.airflow import airflow_svg
    from aip.engines.architecture.metrics import analyse_all
    from aip.engines.cost.estimator import estimate_cost
    from aip.engines.vastu.engine import analyse_vastu

    brief = default_residence_brief()
    result = _run(import_floorplan(export_dxf(original, 0).encode(), "s.dxf",
                                   plot_width=12.0, plot_depth=18.0))
    plan = result.plan

    assert analyse_vastu(plan).score > 0
    assert estimate_cost(plan, brief).total > 0
    assert all(0.0 <= r.score <= 1.0 for r in analyse_all(plan, brief).values())
    assert "<svg" in airflow_svg(plan, 0)
    assert export_dxf(plan, 0).rstrip().endswith("EOF")


def test_imported_plan_is_walkable(original):
    """Doors placed on an upload obey the same circulation rules."""
    result = _run(import_floorplan(export_dxf(original, 0).encode(), "s.dxf",
                                   plot_width=12.0, plot_depth=18.0))
    assert result.openings_added
    illegal = [r for r in walkability(result.plan) if not r.legal]
    assert not illegal, [f"{r.room}: {' > '.join(r.path)}" for r in illegal]


def test_dxf_wall_outlines_are_not_read_as_rooms(original):
    """The walls are closed polylines too; only the area layer is rooms."""
    rooms, _ = parse_dxf(export_dxf(original, 0))
    assert len(rooms) == len(original.level_at(0).rooms)


def test_dxf_units_are_guessed_from_extent(original):
    """A millimetre drawing must not come back as a 9-kilometre house."""
    dxf = export_dxf(original, 0)

    def mm(match):
        return f"{float(match.group(0)) * 1000:.3f}"

    lines = dxf.split("\n")
    for i in range(0, len(lines) - 1, 2):
        if lines[i].strip() in {"10", "20", "11", "21"}:
            lines[i + 1] = re.sub(r"-?\d+\.\d+", mm, lines[i + 1])
    result = _run(import_floorplan("\n".join(lines).encode(), "mm.dxf"))
    assert "millimetres" in result.scale_note
    total = sum(r.area for r in result.plan.level_at(0).rooms)
    assert total == pytest.approx(sum(r.area for r in original.level_at(0).rooms), rel=0.02)


# ---------------------------------------------------------------------------
# SVG
# ---------------------------------------------------------------------------


def test_svg_round_trip_recovers_every_room(original):
    svg = floor_plan_svg(original, 0, show_dimensions=False, show_grid=False,
                         show_furniture=False).encode()
    result = _run(import_floorplan(svg, "scheme.svg", plot_width=12.0, plot_depth=18.0))
    assert result.source == "svg"
    out = sorted(r.type.value for r in original.level_at(0).rooms)
    back = sorted(r.type.value for r in result.plan.level_at(0).rooms)
    assert out == back
    # Unitless: fitted to the footprint, so areas are close but not exact.
    total = sum(r.area for r in result.plan.level_at(0).rooms)
    assert total == pytest.approx(sum(r.area for r in original.level_at(0).rooms), rel=0.25)


def test_svg_with_no_shapes_is_refused():
    with pytest.raises(ImportError_):
        parse_svg('<svg xmlns="http://www.w3.org/2000/svg"><text x="1" y="1">Hi</text></svg>')


def test_hand_drawn_svg_with_labels():
    """The shape a drawing app exports: rects with a label inside each."""
    svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 1400">
      <rect x="0" y="0" width="500" height="400"/><text x="200" y="200">LIVING</text>
      <rect x="500" y="0" width="400" height="400"/><text x="650" y="200">KITCHEN</text>
      <rect x="0" y="400" width="450" height="500"/><text x="150" y="650">MASTER BED</text>
      <rect x="450" y="400" width="450" height="500"/><text x="600" y="650">BEDROOM</text>
      <rect x="0" y="900" width="900" height="500"/><text x="400" y="1150">DINING</text>
    </svg>"""
    result = _run(import_floorplan(svg.encode(), "hand.svg", plot_width=10.0, plot_depth=15.0))
    kinds = sorted(r.type.value for r in result.plan.level_at(0).rooms)
    assert kinds == ["bedroom", "dining", "kitchen", "living", "master_bedroom"]
    assert result.unrecognised == []


# ---------------------------------------------------------------------------
# Real-world files: walls as linework, not closed room outlines
# ---------------------------------------------------------------------------


@pytest.fixture
def no_network(monkeypatch):
    """Any call to the remote vision model fails the test."""
    def boom(*_a, **_k):
        raise AssertionError("the remote vision model must not be called")

    monkeypatch.setattr("aip.core.llm.get_router", boom)


def _import(data: bytes, name: str):
    return _run(import_floorplan(data, name))


def _rescale_dxf(text: str, factor: float, insunits: int | None) -> str:
    """The walls DXF with every coordinate multiplied and $INSUNITS rewritten (or dropped)."""
    lines = text.split("\n")
    for i in range(0, len(lines) - 1, 2):
        if lines[i].strip() in {"10", "20", "11", "21", "30", "31", "40"}:
            lines[i + 1] = repr(float(lines[i + 1]) * factor)
    out = "\n".join(lines)
    header = "9\n$INSUNITS\n70\n4\n"
    return out.replace(header, "" if insunits is None else f"9\n$INSUNITS\n70\n{insunits}\n")


def _footprint(plan) -> float:
    return sum(r.area for r in plan.level_at(0).rooms)


def test_walls_dxf_is_read_from_linework(original):
    """Wall faces as LINEs with door gaps, MTEXT labels, a dimension layer: no closed outline anywhere."""
    result = _import(walls_dxf(original).encode(), "walls.dxf")
    s = score(original, result.plan)
    assert s["matched"] >= 11 and s["iou"] >= 0.8 and s["named"] >= 10, s
    assert "millimetres" in result.scale_note
    assert any("wall linework" in w for w in result.warnings)
    # The dimension line and its text sit outside every room and name none.
    assert "12000" not in " ".join(result.unrecognised)
    # Millimetres were read as millimetres: the footprint is a house, not a hamlet.
    assert _footprint(result.plan) == pytest.approx(_footprint(original), rel=0.1)


def test_walls_dxf_labels_lose_their_mtext_codes(original):
    rooms, _ = parse_dxf(walls_dxf(original))
    labels = {r.label for r in rooms}
    assert "MASTER BEDROOM" in labels and "LIVING" in labels
    assert not any("\\" in label or "Arial" in label or "SQ" in label for label in labels)


def test_walls_dxf_without_a_wall_layer_uses_everything_but_annotation(original):
    """No layer is called WALL: take all layers except dimensions, furniture, text and the like."""
    renamed = walls_dxf(original).replace("A-WALL", "0")
    rooms, warnings = parse_dxf(renamed)
    assert len(rooms) == len(original.level_at(0).rooms)
    assert any("all layers except" in w for w in warnings)


@pytest.mark.parametrize(("factor", "insunits", "note"), [
    (1 / 1000, 6, "metres"),
    (1 / 10, 5, "centimetres"),
    (1 / 25.4, 1, "inches"),
    (1 / 304.8, 2, "feet"),
    (1.0, 4, "millimetres"),
])
def test_dxf_insunits_gives_the_scale(original, factor, insunits, note):
    """The header's own units win over a guess from the extent."""
    result = _import(_rescale_dxf(walls_dxf(original), factor, insunits).encode(), "w.dxf")
    assert note in result.scale_note
    assert _footprint(result.plan) == pytest.approx(_footprint(original), rel=0.1)


def test_dxf_without_insunits_still_guesses_from_extent(original):
    result = _import(_rescale_dxf(walls_dxf(original), 1.0, None).encode(), "w.dxf")
    assert "millimetres" in result.scale_note
    assert _footprint(result.plan) == pytest.approx(_footprint(original), rel=0.1)


def test_dxf_door_swings_and_furniture_blocks_do_not_close_rooms(original):
    """Arcs, circles and block definitions are not wall linework."""
    text = walls_dxf(original)
    arc = "0\nARC\n8\nA-WALL\n10\n3000\n20\n9000\n40\n900\n50\n0\n51\n90\n"
    blocks = ("0\nSECTION\n2\nBLOCKS\n0\nBLOCK\n2\nSOFA\n0\nLINE\n8\nA-WALL\n10\n0\n20\n0\n"
              "11\n9000\n21\n9000\n0\nENDBLK\n0\nENDSEC\n")
    text = text.replace("0\nSECTION\n2\nENTITIES\n", blocks + "0\nSECTION\n2\nENTITIES\n" + arc)
    rooms, _ = parse_dxf(text)
    assert len(rooms) == len(original.level_at(0).rooms)


def test_walls_svg_is_read_from_stroked_lines(original):
    """<line>s with stroke widths inside a translated group, <text> labels."""
    result = _import(walls_svg(original).encode(), "walls.svg")
    s = score(original, result.plan)
    assert s["matched"] >= 11 and s["iou"] >= 0.8 and s["named"] >= 10, s
    assert not any("transform" in w for w in result.warnings)


def test_svg_hairlines_beside_thick_walls_are_not_walls(original):
    """Dimension leaders and hatching are thin; walls are thick. A hairline across the plan must not split rooms."""
    svg = walls_svg(original).replace(
        "</g>", '<line x1="0" y1="200" x2="400" y2="200" stroke="#000" stroke-width="0.5"/></g>')
    rooms, warnings = parse_svg(svg)
    assert len(rooms) == len(original.level_at(0).rooms)
    assert any("thin line" in w for w in warnings)


def _rect_svg(inner: str) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg">{inner}</svg>'


def _bounds(room):
    xs, ys = [p.x for p in room.polygon], [p.y for p in room.polygon]
    return min(xs), min(ys), max(xs), max(ys)


def test_svg_transforms_compose_down_the_tree():
    """A plan in a translated, scaled group lands where it is drawn, with nothing warned about transforms."""
    inner = (
        '<g transform="translate(100 50) scale(2)">'
        '<rect x="0" y="0" width="100" height="50"/><text x="50" y="25">LIVING</text>'
        '<g transform="translate(110 0)"><rect x="0" y="0" width="80" height="50"/>'
        '<text x="40" y="25">KITCHEN</text></g></g>'
    )
    rooms, warnings = parse_svg(_rect_svg(inner))
    assert not warnings
    by_label = {r.label: _bounds(r) for r in rooms}
    # Widths and heights are doubled; the second room is shifted by 110 * 2 along x.
    x0, y0, x1, y1 = by_label["LIVING"]
    assert (x1 - x0, y1 - y0) == pytest.approx((200, 100))
    k0, _, k1, _ = by_label["KITCHEN"]
    assert (k1 - k0, k0 - x0) == pytest.approx((160, 220))


def test_svg_matrix_rotate_and_chained_transforms():
    """rotate(90) swaps a rect's width and height; matrix() and a translate-rotate-translate chain agree."""
    rect = '<rect x="0" y="0" width="100" height="40"/>'
    variants = (
        f'<g transform="rotate(90)">{rect}</g>',
        f'<g transform="translate(5 5) rotate(90) translate(-5 -5)">{rect}</g>',
        f'<g transform="matrix(0 1 -1 0 0 0)">{rect}</g>',
    )
    for inner in variants:
        rooms, _ = parse_svg(_rect_svg(inner + '<rect x="500" y="500" width="60" height="60"/>'))
        shapes = sorted(((b[2] - b[0], b[3] - b[1]) for b in map(_bounds, rooms)), key=lambda wh: wh[0])
        assert shapes[0] == pytest.approx((40, 100)), inner


# ---------------------------------------------------------------------------
# Wall linework in isolation
# ---------------------------------------------------------------------------


def _wall(a, b):
    return (Vec2(*a), Vec2(*b))


def test_linework_bridges_a_door_without_filling_the_corridor_beside_it():
    """A door is as wide as the passage next to it; the closing that bridges the one must not fill the other."""
    # Rooms either side of a 1.1 m corridor, each opening onto it through a 1.0 m door.
    walls = [
        _wall((0, 0), (10, 0)), _wall((0, 6), (10, 6)), _wall((0, 0), (0, 6)), _wall((10, 0), (10, 6)),
        _wall((4.5, 0), (4.5, 2.0)), _wall((4.5, 3.0), (4.5, 6.0)),      # left room | corridor, door 2..3
        _wall((5.6, 0), (5.6, 4.0)), _wall((5.6, 5.0), (5.6, 6.0)),      # corridor | right room, door 4..5
    ]
    rooms, _ = rooms_from_linework(walls, [("BED", Vec2(2, 3)), ("KITCHEN", Vec2(8, 3))], door_gap=1.2)
    assert len(rooms) == 3
    narrow = min(rooms, key=lambda r: _bounds(r)[2] - _bounds(r)[0])
    x0, _, x1, _ = _bounds(narrow)
    assert x1 - x0 == pytest.approx(1.1, abs=0.1)


def test_unlabelled_rooms_get_a_guess_at_low_confidence():
    walls = [_wall((0, 0), (12, 0)), _wall((12, 0), (12, 5)), _wall((12, 5), (0, 5)), _wall((0, 5), (0, 0)),
             _wall((8, 0), (8, 5)), _wall((0, 2.2), (4, 2.2)), _wall((4, 0), (4, 5))]
    rooms, warnings = rooms_from_linework(walls, [("LIVING", Vec2(6, 3))])
    assert len(rooms) >= 3
    unlabelled = [r for r in rooms if not r.label]
    assert unlabelled and all(r.confidence == 0.4 and r.type is not None for r in unlabelled)
    assert any("guessed" in w for w in warnings)
    living = next(r for r in rooms if r.label == "LIVING")
    assert living.confidence > 0.4


def test_mtext_formatting_is_stripped():
    assert strip_cad_formatting("\\fArial|b1;MASTER BEDROOM\\P19.4 SQ.M") == "MASTER BEDROOM 19.4 SQ.M"
    assert strip_cad_formatting("{\\H0.7x;LIVING}") == "LIVING"
    assert strip_cad_formatting("\\pxqc;KITCHEN") == "KITCHEN"


# ---------------------------------------------------------------------------
# Images, read on this machine
# ---------------------------------------------------------------------------

needs_vision = pytest.mark.skipif(
    not local_vision_available(), reason="needs the `vision` extra (opencv + rapidocr)"
)


@needs_vision
def test_scan_png_is_read_locally(original, tmp_path, no_network):
    """Thick walls, door gaps, labels with sizes, a dimension string, 1.2 degrees of skew, noise, blur."""
    path = tmp_path / "scan.png"
    raster(original, path=path)
    result = _import(path.read_bytes(), "scan.png")
    s = score(original, result.plan)
    assert s["matched"] >= 10 and s["iou"] >= 0.75 and s["named"] >= 9, s
    # The scale came from the drawing's own writing, so the plan is its real size without a plot.
    assert "dimension strings" in result.scale_note
    assert _footprint(result.plan) == pytest.approx(_footprint(original), rel=0.15)
    assert any("on this server" in w for w in result.warnings)


@needs_vision
def test_sketch_jpg_is_read_locally(original, tmp_path, no_network):
    """Thin 4 px walls, washed out, JPEG, tilted -2 degrees."""
    path = tmp_path / "sketch.jpg"
    raster(original, px_per_m=45, wall_px=4, rotate=-2.0, jpeg=True, path=path)
    result = _import(path.read_bytes(), "sketch.jpg")
    s = score(original, result.plan)
    assert s["matched"] >= 9 and s["iou"] >= 0.7 and s["named"] >= 7, s
    assert _footprint(result.plan) == pytest.approx(_footprint(original), rel=0.2)


@needs_vision
def test_local_image_reader_reports_what_it_assumed(original, tmp_path):
    path = tmp_path / "scan.png"
    raster(original, path=path)
    rooms, warnings, meta = importer.parse_image_local(path.read_bytes())
    assert meta["model"] == "local-cv" and meta["north"] == "unknown"
    assert meta["px_per_m"] == pytest.approx(60, rel=0.1)
    assert meta["building_w_m"] == pytest.approx(8.94, rel=0.1)
    assert meta["building_h_m"] == pytest.approx(14.5, rel=0.1)
    assert any("rotated" in w for w in warnings)
    # Fractions of the building, y up: every corner is inside the unit box.
    assert all(-0.01 <= p.x <= 1.01 and -0.01 <= p.y <= 1.01 for r in rooms for p in r.polygon)
    assert all(0.0 < r.confidence <= 0.85 for r in rooms)


def test_unreadable_image_falls_back_to_the_model_within_its_time_limit(monkeypatch):
    """The remote vision model is a fallback, it is bounded, and the error says what to do next."""
    import time

    monkeypatch.setattr(importer, "parse_image_local", lambda data: ([], ["No walls were found."], {}))

    async def never(data, mime):
        await asyncio.sleep(60)

    monkeypatch.setattr(importer, "parse_image", never)
    monkeypatch.setattr(importer, "VISION_TIMEOUT_S", 0.05)
    t0 = time.perf_counter()
    with pytest.raises(ImportError_) as err:
        _run(import_floorplan(b"\x89PNG", "plan.png"))
    assert time.perf_counter() - t0 < 5
    assert "DXF or SVG" in str(err.value) and "No walls were found" in str(err.value)


def test_missing_vision_stack_degrades_with_an_install_hint(monkeypatch):
    from aip.engines.architecture.raster import LocalVisionUnavailable

    def missing(data):
        raise LocalVisionUnavailable("install the extra")

    async def down(data, mime):
        raise ImportError_("No free vision model was reachable just now.")

    monkeypatch.setattr(importer, "parse_image_local", missing)
    monkeypatch.setattr(importer, "parse_image", down)
    with pytest.raises(ImportError_) as err:
        _run(import_floorplan(b"\x89PNG", "plan.png"))
    assert "pip install" in str(err.value) and "no free vision model" in str(err.value).lower()


def test_model_answer_is_used_when_the_local_reader_finds_nothing(monkeypatch):
    """The fallback still works: the model's rooms go through the same assembly."""
    monkeypatch.setattr(importer, "parse_image_local", lambda data: ([], ["nothing"], {}))
    box = [Vec2(0, 0), Vec2(0.5, 0), Vec2(0.5, 0.5), Vec2(0, 0.5)]

    def shift(dx, dy):
        return [Vec2(p.x + dx, p.y + dy) for p in box]

    async def model(data, mime):
        return ([importer.ParsedRoom(label="LIVING", polygon=shift(0, 0)),
                 importer.ParsedRoom(label="KITCHEN", polygon=shift(0.5, 0)),
                 importer.ParsedRoom(label="BEDROOM", polygon=shift(0, 0.5)),
                 importer.ParsedRoom(label="DINING", polygon=shift(0.5, 0.5))], [], {})

    monkeypatch.setattr(importer, "parse_image", model)
    result = _run(import_floorplan(b"\x89PNG", "plan.png", plot_width=12.0, plot_depth=15.0))
    assert result.source == "image"
    assert sorted(r.type.value for r in result.plan.level_at(0).rooms) == [
        "bedroom", "dining", "kitchen", "living"]


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_unknown_format_is_refused():
    with pytest.raises(ImportError_):
        _run(import_floorplan(b"hello", "plan.docx"))


def test_empty_dxf_is_refused():
    with pytest.raises(ImportError_):
        _run(import_floorplan(b"0\nSECTION\n0\nENDSEC\n0\nEOF\n", "empty.dxf"))


# ---------------------------------------------------------------------------
# Through the API
# ---------------------------------------------------------------------------


def test_upload_endpoint_returns_a_usable_plan(client, original):
    dxf = export_dxf(original, 0).encode()
    response = client.post(
        "/api/v1/plans/import",
        files={"file": ("scheme.dxf", io.BytesIO(dxf), "application/dxf")},
        data={"plot_width": "12", "plot_depth": "18", "road_direction": "N"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["import"]["source"] == "dxf"
    assert body["import"]["rooms_kept"] == len(original.level_at(0).rooms)
    assert body["import"]["unrecognised"] == []
    assert body["import"]["openings_added"] is True

    plan_id = body["plan_id"]
    # Every drawing and export must serve for the uploaded plan.
    for url in body["drawing_urls"].values():
        assert client.get(url).status_code == 200, url
    for url in body["export_urls"].values():
        assert client.get(url).status_code == 200, url
    analysis = client.get(f"/api/v1/plans/{plan_id}/analysis").json()
    assert analysis["layout"]["walkable"] == pytest.approx(1.0)


def test_upload_of_garbage_is_a_422_not_a_500(client):
    response = client.post(
        "/api/v1/plans/import",
        files={"file": ("plan.dxf", io.BytesIO(b"not a dxf"), "application/dxf")},
    )
    assert response.status_code == 422
    assert "closed room outlines" in response.json()["detail"]


def test_review_stream_runs_the_committee_on_an_upload(client, original):
    dxf = export_dxf(original, 0).encode()
    plan_id = client.post(
        "/api/v1/plans/import",
        files={"file": ("scheme.dxf", io.BytesIO(dxf), "application/dxf")},
        data={"plot_width": "12", "plot_depth": "18"},
    ).json()["plan_id"]

    with client.stream(
        "POST", f"/api/v1/plans/{plan_id}/review/stream",
        params={"include_generative_critics": "false"},
    ) as response:
        assert response.status_code == 200
        text = "".join(response.iter_text())

    assert "event: result" in text
    assert "Reviewing 1 uploaded scheme" in text
    assert '"imported": true' in text
    assert "event: done" in text


# ---------------------------------------------------------------------------
# Negotiating on an upload must not break how you walk through it
# ---------------------------------------------------------------------------


def test_negotiation_never_makes_an_upload_less_walkable(original):
    """A Vastu swap moved the foyer to the back of an uploaded house once.

    The geometry stayed intact so every old constraint held, and the client
    was left entering their bedroom from the front door. Circulation is now
    judged by route, and the worker will not propose what the manager would
    have to reject.
    """
    from aip.agents.protocol import ConsensusProtocol, ProtocolConfig
    from aip.api.routers.imports import _brief_for
    from aip.domain.brief import VastuStance

    result = _run(import_floorplan(export_dxf(original, 0).encode(), "s.dxf",
                                   plot_width=12.0, plot_depth=18.0))
    plan = result.plan
    before = sum(1 for r in walkability(plan) if r.legal)
    brief = _brief_for(plan, vastu=VastuStance.STRICT, budget=0.0, name="s")

    final, transcript = ConsensusProtocol(
        config=ProtocolConfig(max_rounds=3, time_budget_seconds=60.0)
    ).run(plan, brief)

    after = sum(1 for r in walkability(final) if r.legal)
    assert after >= before, [f"{r.room}: {r.reason}" for r in walkability(final) if not r.legal]
    assert transcript.final_score >= transcript.rounds[0].score_before - 1e-9 if transcript.rounds else True
