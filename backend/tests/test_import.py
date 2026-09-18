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
from aip.domain.plan import RoomType
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
