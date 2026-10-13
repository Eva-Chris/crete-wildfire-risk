"""End to end: files on disk -> FastAPI endpoints, on a tiny hand-checkable road.

    node 0 ---- node 1 ---- node 2 ---- node 3        (1 km apart, 100 s per hop = 1.7 min)
    station     settlement  zone B      settlement (a polygon)
    zone A

Zone C lies far from any road.
"""
import numpy as np
import pytest

gpd = pytest.importorskip("geopandas")
from fastapi.testclient import TestClient
from shapely.geometry import Point, box

import main
from routing import M_PER_DEG_LNG

LAT = 35.2


def lon_of(k):
    return 25.0 + k * 1000 / M_PER_DEG_LNG


def square(lon, lat, half=0.0004):
    return box(lon - half, lat - half, lon + half, lat + half)


def pts(*nodes):
    return [f"{LAT},{lon_of(k)}" for k in nodes]


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    lon = np.array([lon_of(k) for k in range(4)])
    u = np.r_[np.arange(3), np.arange(1, 4)]
    v = np.r_[np.arange(1, 4), np.arange(3)]
    np.savez(d / "road_graph.npz", lon=lon, lat=np.full(4, LAT), u=u, v=v, t=np.full(6, 100.0))

    gpd.GeoDataFrame({"static_risk_score": [60.0, 50.0, 40.0]},
                     geometry=[square(lon_of(0), LAT), square(lon_of(2), LAT), square(25.5, 35.6)], crs=4326
                     ).to_file(d / "forests_with_risk_score_v2.geojson", driver="GeoJSON")
    gpd.GeoDataFrame({"name": ["Point village", "Polygon town"]},
                     geometry=[Point(lon_of(1), LAT), square(lon_of(3), LAT)], crs=4326
                     ).to_file(d / "settlements.geojson", driver="GeoJSON")
    gpd.GeoDataFrame({"name": ["Station"]}, geometry=[square(lon_of(0), LAT)], crs=4326
                     ).to_file(d / "fire-stations.geojson", driver="GeoJSON")

    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "ROAD_FILE", d / "road_graph.npz")
    monkeypatch.setattr(main, "_layer_cache", {})
    main._access_state.cache_clear()
    yield d
    main._access_state.cache_clear()


@pytest.fixture
def client(data_dir):
    return TestClient(main.app)


def test_zones_are_numbered_for_the_browser(client):
    feats = client.get("/api/risk-zones").json()["features"]
    assert [f["properties"]["zid"] for f in feats] == [0, 1, 2]


def test_missing_layer_file_gives_an_empty_layer_not_a_crash(client):
    r = client.get("/api/helipads")                      # no such file in the fixture
    assert r.status_code == 200 and r.json()["features"] == []


def test_base_drive_times(client):
    a = client.get("/api/access").json()
    assert a["available"] and a["max_min"] == 45 and a["n_zones"] == 3 and a["n_settlements"] == 2
    assert a["zones"] == [0.0, 3.3, None]                # zone C: no road nearby
    assert a["settlements"] == [1.7, 5.0]
    names = [f["properties"]["name"] for f in client.get("/api/settlements").json()["features"]]
    assert names == ["Point village", "Polygon town"]    # the order the times were computed in


def test_proposed_station_times(client):
    a = client.get("/api/access/proposed", params={"p": pts(3)}).json()
    assert a["zones"] == [5.0, 1.7, None] and a["settlements"] == [3.3, 0.0] and a["snap_m"] == [0]


def test_several_proposed_stations(client):
    a = client.get("/api/access/proposed", params={"p": pts(3, 1)}).json()
    assert a["zones"] == [1.7, 1.7, None] and len(a["snap_m"]) == 2


def test_no_proposed_stations_means_nothing_reached(client):
    a = client.get("/api/access/proposed").json()
    assert a["zones"] == [None] * 3 and a["settlements"] == [None] * 2


@pytest.mark.parametrize("bad", [["abc"], ["35.2"], ["10.0,25.0"], ["35.2,25.0"] * 11])
def test_bad_points_are_rejected(client, bad):
    assert client.get("/api/access/proposed", params={"p": bad}).status_code == 422


def test_without_a_road_graph_the_app_falls_back(client, data_dir):
    (data_dir / "road_graph.npz").unlink()
    main._access_state.cache_clear()
    assert client.get("/api/access").json() == {"available": False}
    assert client.get("/api/access/proposed", params={"p": pts(0)}).status_code == 503