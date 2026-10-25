"""Room temperatures through a design day."""

from __future__ import annotations

import pytest

from aip.engines.architecture.thermal import CITIES, room_fields, Options, month_climate, nearest_city, season_month, thermal, thermal_year


def test_rooms_follow_the_day_and_the_season(plan):
    s = thermal(plan, Options(season="summer"))
    w = thermal(plan, Options(season="winter"), with_fixes=False)
    assert s["rooms"] and len(s["outdoor"]) == 24
    for r in s["rooms"]:
        assert len(r["temps"]) == 24 and len(r["feels"]) == 24
        # Mass keeps a room's swing well inside the outdoor one.
        assert max(r["temps"]) - min(r["temps"]) < s["climate"]["max"] - s["climate"]["min"]
    assert s["summary"]["peak"] > w["summary"]["peak"] + 4
    # Fans and the breeze make the warm hours feel cooler, never warmer.
    assert all(f <= t for r in s["rooms"] for f, t in zip(r["feels"], r["temps"]))
    assert any(f < t for r in s["rooms"] for f, t in zip(r["feels"], r["temps"]))


def test_a_cool_roof_cools_the_top_floor_and_the_fixes_are_measured(plan):
    base = thermal(plan, Options(), with_fixes=True)
    cool = thermal(plan, Options(cool_roof=True), with_fixes=False)
    top = [r for r in base["rooms"] if r["roof_exposed"]]
    assert top
    for r in top:
        c = next(x for x in cool["rooms"] if x["id"] == r["id"])
        assert c["peak"] < r["peak"]
    assert any(f["id"] == "cool_roof" and f["peak_drop"] > 0 for f in base["fixes"])


def test_shut_windows_need_ac_and_size_it(plan):
    s = thermal(plan, Options(windows="shut"), with_fixes=False)
    bed = [r for r in s["rooms"] if "bed" in r["type"]]
    assert bed and all(0.75 <= r["ac_tons"] <= 3 for r in bed)


def test_city_and_bad_season(plan):
    assert nearest_city(28.5, 77.2) == "Delhi" and nearest_city(13.0, 80.2) == "Chennai"
    assert nearest_city(13.0, 80.2, "Gachibowli, Hyderabad") == "Hyderabad" and nearest_city(13.0, 80.2, "Gurgaon") == "Delhi"
    with pytest.raises(ValueError):
        thermal(plan, Options(season="spring"))


def test_months_follow_the_citys_averages(plan):
    # Seasons pick the city's own months: Delhi's hottest is May or June, its coolest January.
    assert season_month("Delhi", "summer") in (5, 6) and season_month("Delhi", "winter") == 1
    assert season_month("Chennai", "monsoon") in (10, 11)
    for lat, lon, mx, mn, rh in CITIES.values():
        assert len(mx) == len(mn) == len(rh) == 12 and all(a > b for a, b in zip(mx, mn))
    may = thermal(plan, Options(month=5), with_fixes=False)
    assert may["month"] == 5 and may["climate"]["max"] == month_climate(may["city"], 5)["max"]
    assert len(may["normals"]) == 12


def test_surfaces_for_the_thermal_camera(plan):
    d = thermal(plan, Options(), with_fixes=False)
    assert len(d["ground"]) == 24 and max(d["ground"]) > max(d["outdoor"])
    walled = [r for r in d["rooms"] if r["faces"]]
    assert walled
    for r in walled:
        for f in r["faces"]:
            assert len(f["inside"]) == len(f["outside"]) == 24
            # In the afternoon the sunlit skin outside runs hotter than the plaster inside.
            assert max(f["outside"]) >= max(f["inside"])
    top = [r for r in d["rooms"] if r["roof_exposed"]]
    assert all(r["ceiling"] and max(r["ceiling"]) > r["peak"] for r in top)


def test_the_year_runs_hot_to_cool(plan):
    y = thermal_year(plan)
    assert len(y["months"]) == 12
    hot = max(y["months"], key=lambda m: m["max"])
    cool = min(y["months"], key=lambda m: m["max"])
    assert hot["indoor_peak"] > cool["indoor_peak"]


def test_inside_each_room_the_sun_patch_and_the_people_show(plan):
    import base64

    import numpy as np

    d = room_fields(plan, plan.levels[0].index)
    assert d["rooms"]
    lit = slept = False
    for r in d["rooms"]:
        a = np.frombuffer(base64.b64decode(r["temps"]), dtype="<i2").reshape(24, r["ny"], r["nx"]).astype(float)
        a[a == -32768] = np.nan
        a /= 10
        assert np.isfinite(a).any()
        # A west or east window throws a patch on the floor far warmer than the room's coolest corner.
        if r["windows"] and (np.nanmax(a[15]) - np.nanmin(a[15]) > 4 or np.nanmax(a[9]) - np.nanmin(a[9]) > 4):
            lit = True
        if any(s["name"].endswith("bed") for s in r["sources"]):
            bed = next(s for s in r["sources"] if s["name"].endswith("bed"))
            j, i = int((bed["y"] - r["y0"]) / d["cell"]), int((bed["x"] - r["x0"]) / d["cell"])
            if 0 <= j < r["ny"] and 0 <= i < r["nx"] and a[2, j, i] > np.nanmedian(a[2]):
                slept = True
    assert lit and slept
