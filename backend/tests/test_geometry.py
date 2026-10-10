"""Geometry primitives.

These are the foundation everything else stands on: a wrong centroid silently
corrupts every Vastu direction, and a wrong area silently corrupts every cost.
"""

from __future__ import annotations

import math

import pytest

from aip.domain.geometry import (
    BoundingBox,
    Direction,
    Vec2,
    bearing_to_direction,
    centroid,
    compactness,
    convex_hull,
    direction_of,
    is_axis_aligned_rect,
    largest_inscribed_square,
    perimeter,
    point_in_polygon,
    polygon_area,
    rectangle,
    segments_intersect,
    shared_edge,
    shrink_polygon,
    signed_area,
)


def test_polygon_area_and_perimeter():
    square = rectangle(Vec2(0, 0), 4, 3)
    assert polygon_area(square) == pytest.approx(12.0)
    assert perimeter(square) == pytest.approx(14.0)


def test_signed_area_encodes_winding():
    ccw = rectangle(Vec2(0, 0), 2, 2)
    assert signed_area(ccw) > 0
    assert signed_area(ccw[::-1]) < 0


def test_centroid_of_l_shape_is_not_the_vertex_average():
    """An L-shape is exactly where the naive vertex mean goes wrong.

    Vastu direction is computed from the centroid, so using the vertex average
    would misplace rooms into neighbouring compass sectors.

    The L below decomposes into a 4x1 arm (area 4, centroid (2, 0.5)) and a 1x3
    arm (area 3, centroid (0.5, 2.5)), so the true area centroid is at
    (9.5/7, 9.5/7). Note it lies in the notch, *outside* the polygon - that is
    correct for a concave shape, and asserting containment here would be
    asserting something false.
    """
    l_shape = [
        Vec2(0, 0), Vec2(4, 0), Vec2(4, 1), Vec2(1, 1), Vec2(1, 4), Vec2(0, 4),
    ]
    area_centroid = centroid(l_shape)
    vertex_mean = Vec2(
        sum(p.x for p in l_shape) / len(l_shape),
        sum(p.y for p in l_shape) / len(l_shape),
    )

    assert area_centroid.x == pytest.approx(9.5 / 7)
    assert area_centroid.y == pytest.approx(9.5 / 7)
    assert area_centroid.distance_to(vertex_mean) > 0.2

    # For a convex room the centroid must be inside, and that is the case the
    # layout engine actually produces.
    square = rectangle(Vec2(0, 0), 4, 3)
    assert point_in_polygon(centroid(square), square)


def test_point_in_polygon_boundary_counts_as_inside():
    square = rectangle(Vec2(0, 0), 2, 2)
    assert point_in_polygon(Vec2(1, 1), square)
    assert point_in_polygon(Vec2(0, 1), square)      # exactly on an edge
    assert point_in_polygon(Vec2(0, 0), square)      # exactly on a corner
    assert not point_in_polygon(Vec2(2.01, 1), square)


@pytest.mark.parametrize(
    "bearing,expected",
    [
        (0, Direction.N), (22.5, Direction.NNE), (45, Direction.NE),
        (90, Direction.E), (180, Direction.S), (270, Direction.W),
        (359, Direction.N), (11.24, Direction.N), (11.26, Direction.NNE),
    ],
)
def test_bearing_maps_to_sixteen_sectors(bearing, expected):
    assert bearing_to_direction(bearing) is expected


def test_direction_of_respects_plan_rotation():
    """A rotated site must rotate the compass, not the plan."""
    origin, target = Vec2(0, 0), Vec2(0, 10)
    assert direction_of(target, origin, north_angle=0.0) is Direction.N
    # Rotating true north 90 degrees puts the same point to the east.
    assert direction_of(target, origin, north_angle=90.0) is Direction.E


def test_direction_of_centre_radius():
    assert direction_of(Vec2(0.1, 0.1), Vec2(0, 0), centre_radius=1.0) is Direction.CENTRE
    assert direction_of(Vec2(5, 0), Vec2(0, 0), centre_radius=1.0) is not Direction.CENTRE


def test_shared_edge_between_touching_rectangles():
    a = rectangle(Vec2(0, 0), 3, 2)
    b = rectangle(Vec2(3, 0), 2, 2)
    edge = shared_edge(a, b)
    assert edge is not None
    assert edge[0].distance_to(edge[1]) == pytest.approx(2.0)


def test_shared_edge_partial_overlap_is_found():
    """T-junctions are the common case in a slicing partition, not the exception.

    Missing these is what made generated rooms unreachable: a door can only be
    placed where two rooms genuinely share boundary.
    """
    a = rectangle(Vec2(0, 0), 4, 3)
    b = rectangle(Vec2(4, 1), 2, 1)          # touches only the middle third
    edge = shared_edge(a, b)
    assert edge is not None
    assert edge[0].distance_to(edge[1]) == pytest.approx(1.0)


def test_shared_edge_returns_none_for_separated_rectangles():
    a = rectangle(Vec2(0, 0), 2, 2)
    b = rectangle(Vec2(2.5, 0), 2, 2)
    assert shared_edge(a, b) is None


def test_largest_inscribed_square_exact_for_rectangles():
    assert largest_inscribed_square(rectangle(Vec2(0, 0), 5, 3)) == pytest.approx(3.0)
    assert largest_inscribed_square(rectangle(Vec2(2, 7), 2.5, 9)) == pytest.approx(2.5)


def test_largest_inscribed_square_handles_non_convex():
    l_shape = [
        Vec2(0, 0), Vec2(6, 0), Vec2(6, 2), Vec2(2, 2), Vec2(2, 6), Vec2(0, 6),
    ]
    side = largest_inscribed_square(l_shape)
    # The widest limb is 2 units, so nothing larger can fit.
    assert 1.5 <= side <= 2.05


def test_is_axis_aligned_rect():
    assert is_axis_aligned_rect(rectangle(Vec2(0, 0), 3, 2))
    assert not is_axis_aligned_rect([Vec2(0, 0), Vec2(3, 0.4), Vec2(3, 2), Vec2(0, 2)])
    assert not is_axis_aligned_rect([Vec2(0, 0), Vec2(1, 0), Vec2(1, 1)])


def test_segments_intersect():
    assert segments_intersect(Vec2(0, 0), Vec2(2, 2), Vec2(0, 2), Vec2(2, 0))
    assert not segments_intersect(Vec2(0, 0), Vec2(1, 0), Vec2(0, 1), Vec2(1, 1))


def test_shrink_polygon_reduces_area_and_keeps_containment():
    square = rectangle(Vec2(0, 0), 10, 10)
    inner = shrink_polygon(square, 1.5)
    assert inner
    assert polygon_area(inner) == pytest.approx(49.0, rel=0.05)
    assert all(point_in_polygon(p, square) for p in inner)


def test_shrink_polygon_returns_empty_when_over_shrunk():
    assert shrink_polygon(rectangle(Vec2(0, 0), 2, 2), 5.0) == []


def test_compactness_ranks_shapes_correctly():
    square = compactness(rectangle(Vec2(0, 0), 4, 4))
    slot = compactness(rectangle(Vec2(0, 0), 16, 1))
    assert 0 < slot < square <= 1.0
    # A square's Polsby-Popper score is pi/4.
    assert square == pytest.approx(math.pi / 4, rel=1e-3)


def test_convex_hull_drops_interior_points():
    points = [Vec2(0, 0), Vec2(4, 0), Vec2(4, 4), Vec2(0, 4), Vec2(2, 2)]
    hull = convex_hull(points)
    assert len(hull) == 4
    assert polygon_area(hull) == pytest.approx(16.0)


def test_bounding_box_geometry():
    box = BoundingBox(1, 2, 5, 8)
    assert box.width == 4 and box.height == 6
    assert box.area == 24
    assert box.centre.x == 3 and box.centre.y == 5
    assert box.aspect_ratio == pytest.approx(1.5)
    assert box.contains(Vec2(3, 5))
    assert not box.contains(Vec2(0, 5))


def test_vec2_rotation_round_trips():
    p = Vec2(3, 0)
    assert p.rotated(90).x == pytest.approx(0, abs=1e-9)
    assert p.rotated(90).y == pytest.approx(3)
    assert p.rotated(360).x == pytest.approx(3)
