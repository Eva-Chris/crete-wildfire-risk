import numpy as np
import pytest

from routing import (M_PER_DEG_LNG, OFFROAD_MS, RoadNet, build_csr, largest_scc, point_times,
                     to_minutes, zone_times)


def chain(n=4, hop_s=100.0, spacing_m=1000.0):
    """Nodes 0..n-1 on a west-east line, two-way roads, hop_s seconds per hop."""
    lon = 25.0 + np.arange(n) * spacing_m / M_PER_DEG_LNG
    lat = np.full(n, 35.2)
    u = np.r_[np.arange(n - 1), np.arange(1, n)]
    v = np.r_[np.arange(1, n), np.arange(n - 1)]
    return RoadNet(lon, lat, u, v, np.full(len(u), hop_s))


def test_parallel_edges_keep_the_fastest_not_the_sum():
    g = build_csr(2, [0, 0], [1, 1], [100.0, 40.0])
    assert g[0, 1] == 40.0


def test_one_way_roads_are_respected():
    net = RoadNet([25.0, 25.01], [35.2, 35.2], [0], [1], [60.0])
    assert net.times_from(0, 1e6)[1] == 60.0
    assert np.isinf(net.times_from(1, 1e6)[0])


def test_limit_stops_the_search():
    t = chain().times_from(0, 250.0)
    assert list(t[:3]) == [0, 100, 200] and np.isinf(t[3])


def test_several_sources_give_the_fastest_of_them():
    assert list(chain().times_from([0, 3], 1e6)) == [0, 100, 100, 0]


def test_snap_finds_the_nearest_node_and_its_distance():
    net = chain()
    idx, dist = net.snap([25.0 + 1000 / M_PER_DEG_LNG + 0.0001], [35.2])
    assert idx[0] == 1 and 5 < dist[0] < 20


def test_points_off_the_road_pay_for_the_leg_to_it():
    net = chain()
    lon = 25.0 - 50 / M_PER_DEG_LNG            # 50 m west of node 0
    t, snap = net.times_from_points([lon], [35.2], 1e6)
    lead = snap[0] / OFFROAD_MS
    assert abs(t[0] - lead) < 1e-6 and abs(t[1] - (lead + 100)) < 1e-6


def test_zone_time_is_the_fastest_of_its_nodes():
    node_t = np.array([0.0, 100.0, 200.0, np.inf])
    out = zone_times(node_t, np.array([0, 0, 1, 2]), np.array([2, 1, 2, 3]), 4)
    assert list(out[:3]) == [100.0, 200.0, np.inf] and np.isinf(out[3])


def test_far_points_count_as_not_reached():
    t = point_times(np.array([10.0]), np.array([0, 0]), np.array([100.0, 5000.0]))
    assert np.isfinite(t[0]) and np.isinf(t[1])


def test_to_minutes_turns_unreached_and_slow_into_none():
    assert to_minutes(np.array([60.0, np.inf, 3600.0]), 45) == [1.0, None, None]


def test_largest_component_drops_isolated_fragments():
    keep = largest_scc(5, [0, 1, 1, 2, 3], [1, 0, 2, 1, 4])   # 0-1-2 two-way; 3->4 one-way
    assert list(keep) == [True, True, True, False, False]


def test_zone_node_pairs_includes_nodes_within_the_buffer():
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import box
    net = chain(n=4, spacing_m=1000)
    # zone covers node 1 only; buffer of 250 m must not reach node 0 or 2 (1000 m away)
    x1 = 25.0 + 1000 / M_PER_DEG_LNG
    zone = gpd.GeoDataFrame(geometry=[box(x1 - 0.0005, 35.1995, x1 + 0.0005, 35.2005)], crs=4326)
    z, n = net.zone_node_pairs(zone, buffer_m=250)
    assert list(n) == [1] and list(z) == [0]