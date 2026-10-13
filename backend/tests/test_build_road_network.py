import numpy as np
import pytest

gpd = pytest.importorskip("geopandas")
from shapely.geometry import LineString, MultiLineString

import build_road_network as B
from build_road_network import (edge_speed_kmh, lines_to_arrays, oneway_direction,
                                parse_maxspeed, parse_tags, usable)


# ---------------------------------------------------------------- speeds
def test_maxspeed_parsing():
    assert parse_maxspeed("50") == 50
    assert abs(parse_maxspeed("30 mph") - 48.27) < 0.01
    assert parse_maxspeed(["50", "30"]) == 30
    assert parse_maxspeed("none") is None and parse_maxspeed("GR:urban") is None


def test_speed_uses_class_unless_the_limit_is_lower():
    assert edge_speed_kmh("secondary") == 45
    assert edge_speed_kmh("secondary", "30") == 30 * 0.85
    assert edge_speed_kmh("secondary", "90") == 45            # a high limit never speeds the engine up
    assert edge_speed_kmh(["residential", "tertiary"]) == 25  # slowest listed class
    assert edge_speed_kmh("something_new") == 25


# ---------------------------------------------------------------- tag handling
def test_parse_tags_reads_gdal_hstore_strings():
    assert parse_tags('"maxspeed"=>"50","oneway"=>"yes"') == {"maxspeed": "50", "oneway": "yes"}
    assert parse_tags(None) == {} and parse_tags(float("nan")) == {}


@pytest.mark.parametrize("highway, tags, expected", [
    ("residential", {}, 0),                                   # two-way by default
    ("residential", {"oneway": "yes"}, 1),
    ("residential", {"oneway": "-1"}, -1),                    # drawn against the allowed direction
    ("residential", {"junction": "roundabout"}, 1),
    ("motorway", {}, 1),                                      # one-way by default
    ("motorway", {"oneway": "no"}, 0),                        # an explicit tag wins
])
def test_oneway_direction(highway, tags, expected):
    assert oneway_direction(highway, tags) == expected


@pytest.mark.parametrize("highway, tags, ok", [
    ("primary", {}, True),
    ("footway", {}, False),                                   # not a road class
    ("service", {}, False),
    ("track", {}, False),                                     # excluded while INCLUDE_TRACKS is False
    ("primary", {"access": "private"}, False),
    ("primary", {"motor_vehicle": "no"}, False),
])
def test_usable(highway, tags, ok):
    assert usable(highway, tags) is ok


def test_tracks_can_be_switched_on(monkeypatch):
    monkeypatch.setattr(B, "INCLUDE_TRACKS", True)
    assert usable("track", {}) is True


# ---------------------------------------------------------------- ways -> graph
def ways(*rows):
    """rows: (highway, other_tags or None, geometry)"""
    return gpd.GeoDataFrame(
        {"highway": [r[0] for r in rows], "other_tags": [r[1] for r in rows]},
        geometry=[r[2] for r in rows], crs=4326,
    )


P0, P1, P2, P3 = (25.00, 35.2), (25.01, 35.2), (25.02, 35.2), (25.01, 35.21)


def test_ways_are_cut_at_junctions_and_get_both_directions():
    # A runs P0-P1-P2, B leaves from P1: the shared point P1 becomes a node
    a = lines_to_arrays(ways(
        ("secondary", None, LineString([P0, P1, P2])),
        ("secondary", None, LineString([P1, P3])),
    ))
    assert len(a["lon"]) == 4              # P0, P1, P2, P3
    assert len(a["u"]) == 6                # 3 pieces x 2 directions


def test_travel_time_is_length_over_class_speed():
    a = lines_to_arrays(ways(("secondary", None, LineString([P0, P1]))))
    metres = B._haversine_m(*P0, *P1)
    assert np.allclose(a["t"], metres / (45 / 3.6))


def test_tagged_speed_limit_slows_the_edge():
    a = lines_to_arrays(ways(("secondary", '"maxspeed"=>"30"', LineString([P0, P1]))))
    assert np.allclose(a["t"], B._haversine_m(*P0, *P1) / (30 * 0.85 / 3.6))


def test_roundabout_is_one_way_but_still_connected():
    ring = [P0, P1, P3, P0]
    a = lines_to_arrays(ways(
        ("secondary", '"junction"=>"roundabout"', LineString(ring)),
        ("secondary", None, LineString([P1, (25.03, 35.2)])),    # spurs leave the ring at two points
        ("secondary", None, LineString([P3, (25.01, 35.22)])),
    ))
    assert len(a["lon"]) == 5
    assert len(a["u"]) == 3 + 4            # ring pieces in one direction only + 2 two-way spurs


def test_unusable_roads_are_not_part_of_the_graph():
    a = lines_to_arrays(ways(
        ("secondary", None, LineString([P0, P1])),
        ("secondary", '"access"=>"private"', LineString([P1, P3])),
        ("footway", None, LineString([P1, P2])),
    ))
    assert len(a["lon"]) == 2


def test_only_the_largest_connected_part_is_kept():
    far = [(25.5, 35.0), (25.51, 35.0)]                       # a small road not connected to the rest
    a = lines_to_arrays(ways(
        ("secondary", None, LineString([P0, P1, P2])),
        ("secondary", None, LineString([P1, P3])),            # main network: 4 nodes
        ("secondary", None, LineString(far)),
    ))
    assert len(a["lon"]) == 4
    assert a["lon"].max() < 25.1                              # nothing from the far fragment


def test_multilinestrings_are_handled():
    a = lines_to_arrays(ways(("secondary", None, MultiLineString([[P0, P1], [P1, P2]]))))
    assert len(a["lon"]) == 3 and len(a["u"]) == 4


def test_no_roads_stops_with_a_clear_message():
    with pytest.raises(SystemExit):
        lines_to_arrays(ways(("footway", None, LineString([P0, P1]))))