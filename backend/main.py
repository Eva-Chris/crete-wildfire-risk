"""
Crete Wildfire Risk Platform - API

Run from this folder:  uvicorn main:app --reload
GeoJSON files are looked up next to this file (see DATA_DIR).

Environment variables:
  CORS_ORIGINS   comma-separated list of allowed browser origins
                 (default: the Angular dev server on port 4200)
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple
from zoneinfo import ZoneInfo

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import Response

from common import parse_fire_dates
from fwi import compute_fwi
from routing import RoadNet, point_times, to_minutes, zone_times
from stations import STATIONS, nearest_station_ids

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("wildfire.api")

DATA_DIR = Path(__file__).resolve().parent
METRIC_CRS = 2100  # GGRS87 / Greek Grid - metric CRS, used for simplify + centroids
ATHENS = ZoneInfo("Europe/Athens")
EMPTY = '{"type":"FeatureCollection","features":[]}'

MODEL_FILE = DATA_DIR / "model.json"
FOREST_FILE = "data/forests_with_risk_score_v2.geojson"
FIRE_STATIONS_FILE = "data/fire-stations.geojson"
BURNT_FILE = "data/burned_areas_crete_small.geojson"

# Cache lifetimes. "refresh=true" can bypass the cache, but never more often than MIN_REFRESH,
# so nobody can use this server to hammer the free Open-Meteo API.
WEATHER_TTL, WEATHER_MIN_REFRESH = 600, 60
FWI_TTL, FWI_MIN_REFRESH = 3 * 3600, 300
RETRY_AFTER_FAILURE = 60

app = FastAPI(
    title="Crete Wildfire Risk Platform API",
    description="Static susceptibility zones, infrastructure layers, live weather and Fire Weather Index.",
    version="2.0.0",
)
_origins = os.environ.get("CORS_ORIGINS", "http://localhost:4200,http://127.0.0.1:4200").split(",")
app.add_middleware(
    CORSMiddleware, allow_origins=[o.strip() for o in _origins if o.strip()],
    allow_methods=["GET"], allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1024)  # GeoJSON compresses ~8-10x


# --------------------------------------------------------------------------- #
# Weather
# --------------------------------------------------------------------------- #
_weather_cache: dict = {"t": 0.0, "data": None}


def fetch_weather(force: bool = False) -> dict:
    """Current conditions per station. Returns the last good data (marked stale) if Open-Meteo fails."""
    now = time.time()
    cached = _weather_cache["data"]
    max_age = WEATHER_MIN_REFRESH if force else WEATHER_TTL
    if cached and now - _weather_cache["t"] < max_age:
        return cached

    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": ",".join(str(s["lat"]) for s in STATIONS),
                "longitude": ",".join(str(s["lon"]) for s in STATIONS),
                "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m",
                "wind_speed_unit": "kmh",
                "timezone": "Europe/Athens",
            },
            timeout=8,
        )
        r.raise_for_status()
        results = r.json()
        if isinstance(results, dict):  # single-location response shape
            results = [results]

        stations = []
        for st, res in zip(STATIONS, results):
            cur = res["current"]
            stations.append({
                **st,
                "temp_c": cur["temperature_2m"],
                "humidity_pct": cur["relative_humidity_2m"],
                "wind_kmh": cur["wind_speed_10m"],
                "wind_dir": cur["wind_direction_10m"],
            })
        data = {"updated": results[0]["current"]["time"], "stale": False, "stations": stations}
    except Exception as exc:  # network down, quota, bad payload...
        log.warning("Weather API error: %s", exc)
        if not cached:
            raise
        # Keep serving the last good reading, but say so, and retry soon.
        data = {**cached, "stale": True}
        _weather_cache.update(t=now - WEATHER_TTL + RETRY_AFTER_FAILURE, data=data)
        return data

    _weather_cache.update(t=now, data=data)
    return data


@app.get("/api/weather")
def weather_endpoint(refresh: bool = False):
    """Current conditions at the stations. ?refresh=true skips the cache (rate limited)."""
    try:
        return fetch_weather(force=refresh)
    except Exception:
        raise HTTPException(status_code=503, detail="Weather service unavailable")


_fwi_cache: dict = {"t": 0.0, "data": None, "retry_at": 0.0}
_fwi_lock = threading.Lock()
EMPTY_FWI = {"live": False, "stale": False, "in_season": True, "stations": []}


@app.get("/api/fwi")
def fwi_endpoint(refresh: bool = False):
    """Fire Weather Index per station, computed from Open-Meteo noon weather."""
    def fresh_enough() -> bool:
        age = time.time() - _fwi_cache["t"]
        return bool(_fwi_cache["data"]) and age < (FWI_MIN_REFRESH if refresh else FWI_TTL)

    if fresh_enough():
        return _fwi_cache["data"]
    with _fwi_lock:
        if fresh_enough():          # another request refreshed it while we waited
            return _fwi_cache["data"]
        old = _fwi_cache["data"]
        if time.time() < _fwi_cache["retry_at"]:   # a recent attempt failed: don't call out again yet
            return {**old, "stale": True} if old else EMPTY_FWI
        try:
            data = {
                "live": True, "stale": False,
                "in_season": 4 <= datetime.now(ATHENS).month <= 10,
                "computed": datetime.now(ATHENS).strftime("%Y-%m-%dT%H:%M"),
                "stations": compute_fwi(STATIONS),
            }
        except Exception as exc:
            log.warning("FWI error: %s", exc)
            _fwi_cache["retry_at"] = time.time() + RETRY_AFTER_FAILURE
            return {**old, "stale": True} if old else EMPTY_FWI
        _fwi_cache.update(t=time.time(), data=data, retry_at=0.0)
        return data


# --------------------------------------------------------------------------- #
# GeoJSON helpers
# --------------------------------------------------------------------------- #
_layer_cache: dict[str, str] = {}
_COORD_RE = re.compile(r"(\d+\.\d{5})\d+")  # trim coordinates to ~1 m precision


def read_geo(path: Path) -> gpd.GeoDataFrame | None:
    """Read a file and guarantee a valid EPSG:4326 GeoDataFrame."""
    if not path.exists():
        log.warning("File not found: %s", path)
        return None

    gdf = gpd.read_file(path)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    if gdf.empty:
        return None

    if gdf.crs is None:
        # A GeoJSON without a CRS is WGS84 by spec, but exports from Greek
        # datasets are often GGRS87 metres. Coordinates > 360 can't be degrees.
        minx, miny, maxx, maxy = gdf.total_bounds
        guess = METRIC_CRS if max(abs(minx), abs(miny), abs(maxx), abs(maxy)) > 360 else 4326
        log.warning("%s has no CRS - assuming EPSG:%s", path.name, guess)
        gdf = gdf.set_crs(guess)

    if gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(4326)

    # Timestamps etc. are not JSON serialisable
    for col in gdf.columns:
        if col != "geometry" and str(gdf[col].dtype).startswith("datetime"):
            gdf[col] = gdf[col].astype(str)
    return gdf


def to_geojson_str(gdf: gpd.GeoDataFrame) -> str:
    return _COORD_RE.sub(r"\1", gdf.to_json(drop_id=True, show_bbox=False))


def simplify(gdf: gpd.GeoDataFrame, tolerance_m: float) -> gpd.GeoDataFrame:
    if tolerance_m <= 0:
        return gdf
    proj = gdf.to_crs(METRIC_CRS)
    proj["geometry"] = proj.geometry.simplify(tolerance_m, preserve_topology=True)
    return proj.to_crs(4326)


def geojson_response(body: str) -> Response:
    return Response(content=body, media_type="application/json")


def load_layer(
    filenames: list[str],
    tolerance_m: float = 0.0,
    power: set[str] | None = None,   # keep rows whose `power` tag is in this set
    kinds: set[str] | None = None,   # keep rows whose geometry type is in this set
) -> str:
    """Read, filter, de-duplicate, simplify and cache one or more files as a GeoJSON string.

    Missing files give an empty layer (with a warning). Other errors propagate as HTTP 500.
    """
    key = f"{'|'.join(filenames)}::{sorted(power or [])}::{sorted(kinds or [])}::{tolerance_m}"
    if key in _layer_cache:
        return _layer_cache[key]

    frames = []
    for name in filenames:
        gdf = read_geo(DATA_DIR / name)
        if gdf is None:
            continue
        if power:
            if "power" not in gdf.columns:
                # Without the tag we can't tell lines from towers; showing everything would be wrong.
                log.warning("%s has no 'power' column, skipping it for power=%s", name, sorted(power))
                continue
            gdf = gdf[gdf["power"].isin(power)]
        if kinds:
            gdf = gdf[gdf.geom_type.isin(kinds)]
        if not gdf.empty:
            frames.append(gdf)

    if not frames:
        log.warning("Nothing matched power=%s kinds=%s in %s", sorted(power or []), sorted(kinds or []), filenames)
        return EMPTY

    gdf = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=4326)
    gdf = gdf[~gdf.geometry.apply(lambda g: g.wkb).duplicated()]
    body = to_geojson_str(simplify(gdf, tolerance_m))
    log.info("%d features from %s power=%s", len(gdf), filenames, sorted(power or []))

    _layer_cache[key] = body
    return body


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.get("/")
def root():
    return {"status": "online", "system": "Crete Wildfire Risk Engine"}


@app.get("/api/model")
def get_model():
    """Weights, class breaks, train_end and validation results written by build_static_risk.py."""
    if not MODEL_FILE.exists():
        log.warning("%s not found - run build_static_risk.py first", MODEL_FILE)
        return {"weights": {}, "breaks": [], "train_end": 2021}
    return json.loads(MODEL_FILE.read_text())


FOREST_COLS = [
    "zid", "gid", "static_risk_score", "old_score", "elev_m",
    "mean_slope", "dist_power_m", "dist_roads_m", "is_wui", "dist_fire_m",
    "f_fuel", "f_slope", "f_aspect", "f_history", "f_power", "f_roads", "f_wui",
    "dominant_clc", "dominant_clc_pct", "aspect_deg", "aspect_str",
]


def load_zones() -> gpd.GeoDataFrame | None:
    """The scored zones, numbered 0..n-1 in `zid`.

    /api/risk-zones and the drive-time answers both start from here, so the browser can look up
    a zone's drive time by its zid and be sure they refer to the same zone.
    """
    gdf = read_geo(DATA_DIR / FOREST_FILE)
    if gdf is None:
        return None
    gdf = gdf.reset_index(drop=True)
    gdf["zid"] = gdf.index
    return gdf


@app.get("/api/risk-zones")
def get_risk_zones():
    """
    Static forest zones as GeoJSON. Each zone carries its factor scores, `zid`, `station_id`
    (nearest weather station) and `dist_fire_m` (straight-line distance to the nearest fire station).
    """
    if FOREST_FILE in _layer_cache:
        return geojson_response(_layer_cache[FOREST_FILE])

    gdf = load_zones()
    if gdf is None:
        return geojson_response(EMPTY)

    # Nearest station from each zone centroid (computed in metres, not degrees)
    cent = gpd.GeoSeries(gdf.to_crs(METRIC_CRS).geometry.centroid, crs=METRIC_CRS).to_crs(4326)
    gdf["station_id"] = nearest_station_ids(cent.x.values, cent.y.values)

    fs = read_geo(DATA_DIR / FIRE_STATIONS_FILE)
    if fs is not None:
        pts = fs.to_crs(METRIC_CRS).geometry.centroid  # polygons -> points
        allpts = pts.union_all() if hasattr(pts, "union_all") else pts.unary_union
        gdf["dist_fire_m"] = gdf.to_crs(METRIC_CRS).geometry.distance(allpts).round(0)

    gdf = gdf[[c for c in FOREST_COLS if c in gdf.columns] + ["station_id", "geometry"]]
    body = to_geojson_str(simplify(gdf, 25))  # 25 m tolerance - invisible at web zoom levels
    _layer_cache[FOREST_FILE] = body
    return geojson_response(body)


@app.get("/api/burned-areas")
def get_burned_areas():
    """EFFIS burnt areas with a numeric `year`, `date` and `area_ha` per fire."""
    key = "burned_areas"
    if key in _layer_cache:
        return geojson_response(_layer_cache[key])

    gdf = read_geo(DATA_DIR / BURNT_FILE)
    if gdf is None:
        return geojson_response(EMPTY)
    try:
        years, dates, _ = parse_fire_dates(gdf)
    except ValueError as exc:
        log.error("%s: %s", BURNT_FILE, exc)
        raise HTTPException(status_code=500, detail="Burnt-area file has no date column")

    gdf["year"] = years
    gdf["date"] = dates.dt.strftime("%Y-%m-%d") if dates is not None else None
    gdf["area_ha"] = (gdf.to_crs(METRIC_CRS).area / 10_000).round(1)
    gdf = gdf[gdf["year"].notna()].copy()
    gdf["year"] = gdf["year"].astype(int)
    gdf = gdf[["year", "date", "area_ha", "geometry"]]

    body = to_geojson_str(simplify(gdf, 25))
    _layer_cache[key] = body
    log.info("%d burned areas", len(gdf))
    return geojson_response(body)


# --------------------------------------------------------------------------- #
# Drive-time coverage (needs data/road_graph.npz from build_road_network.py)
# --------------------------------------------------------------------------- #
ROAD_FILE = DATA_DIR / "data/road_graph.npz"
ACCESS_MAX_MIN = 45          # search limit: anything slower counts as "not reached"
ZONE_ACCESS_BUFFER_M = 250   # a zone is reached through road nodes within this distance of it
MAX_PROPOSED = 10            # the map should stop letting the user place stations at this number too


class AccessState(NamedTuple):
    net: RoadNet
    zone_idx: np.ndarray     # zone positions ...
    zone_node: np.ndarray    # ... and the road nodes that serve them
    n_zones: int
    s_node: np.ndarray       # nearest road node of each settlement
    s_snap: np.ndarray       # and the distance to it in metres
    base: dict               # drive times from the existing fire stations
    node_t: np.ndarray | None = None   # drive seconds from existing stations to every road node
    edges: tuple | None = None         # (lon, lat, u, v): unique undirected road segments


def _centroids_lonlat(gdf: gpd.GeoDataFrame) -> tuple[np.ndarray, np.ndarray]:
    c = gdf.to_crs(METRIC_CRS).geometry.centroid.to_crs(4326)
    return c.x.to_numpy(), c.y.to_numpy()


def _pack(st: AccessState, node_t: np.ndarray) -> dict:
    return {
        "zones": to_minutes(zone_times(node_t, st.zone_idx, st.zone_node, st.n_zones), ACCESS_MAX_MIN),
        "settlements": to_minutes(point_times(node_t, st.s_node, st.s_snap), ACCESS_MAX_MIN),
    }


@lru_cache(maxsize=1)
def _access_state() -> AccessState | None:
    """Road graph plus everything that doesn't change between requests. None if the graph isn't built."""
    if not ROAD_FILE.exists():
        log.warning("%s not found - run build_road_network.py for drive-time coverage", ROAD_FILE)
        return None
    zones = load_zones()
    stations = read_geo(DATA_DIR / FIRE_STATIONS_FILE)
    if zones is None or stations is None:
        return None

    net = RoadNet.load(ROAD_FILE)
    zone_idx, zone_node = net.zone_node_pairs(zones, ZONE_ACCESS_BUFFER_M)

    # Settlements in the order the /api/settlements layer serves them (the map matches them by position)
    spec = LAYERS["settlements"]
    feats = json.loads(load_layer(spec.files, spec.tolerance_m, spec.power, spec.kinds))["features"]
    if feats:
        s_lon, s_lat = _centroids_lonlat(gpd.GeoDataFrame.from_features(feats, crs=4326))
        s_node, s_snap = net.snap(s_lon, s_lat)
    else:
        s_node, s_snap = np.array([], dtype=int), np.array([])

    f_lon, f_lat = _centroids_lonlat(stations)
    # Same method as proposed stations (including the off-road leg to the nearest road),
    # so an existing and a proposed station that stand in the same place get the same times.
    node_t, f_snap = net.times_from_points(f_lon, f_lat, ACCESS_MAX_MIN * 60)
    if (f_snap > 1000).any():
        log.warning("%d fire station(s) are more than 1 km from the nearest road", int((f_snap > 1000).sum()))

    g = np.load(ROAD_FILE)
    lon, lat = g["lon"], g["lat"]
    lo, hi = np.minimum(g["u"], g["v"]), np.maximum(g["u"], g["v"])
    # two-way roads are stored as two directed edges: keep one of each pair
    _, keep = np.unique(lo.astype(np.int64) * len(lon) + hi, return_index=True)
    edges = (lon, lat, lo[keep], hi[keep])

    st = AccessState(net, zone_idx, zone_node, len(zones), s_node, s_snap, {}, node_t, edges)
    st = st._replace(base=_pack(st, node_t))
    log.info("Road access ready: %d zones, %d settlements, %d fire stations", len(zones), len(s_node), len(f_lon))
    return st


@app.get("/api/access")
def access_base():
    """Drive times (minutes) from the existing fire stations to every zone and settlement."""
    st = _access_state()
    if st is None:
        return {"available": False}
    return {"available": True, "max_min": ACCESS_MAX_MIN, "zone_buffer_m": ZONE_ACCESS_BUFFER_M,
            "n_zones": st.n_zones, "n_settlements": len(st.s_node), **st.base}

def _parse_points(p: list[str]) -> tuple[list[float], list[float]]:
    if len(p) > MAX_PROPOSED:
        raise HTTPException(status_code=422, detail=f"At most {MAX_PROPOSED} proposed stations")
    lats, lons = [], []
    for s in p:
        try:
            la, lo = (float(x) for x in s.split(","))
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Bad point: {s!r}")
        if not (33.8 <= la <= 36.7 and 22.4 <= lo <= 27.4):
            raise HTTPException(status_code=422, detail="Point outside Crete")
        lats.append(la)
        lons.append(lo)
    return lats, lons


@app.get("/api/access/proposed")
def access_proposed(p: list[str] = Query(default=[])):
    """Drive times from proposed stations. Each `p` is 'lat,lng' (at most MAX_PROPOSED)."""
    st = _access_state()
    if st is None:
        raise HTTPException(status_code=503, detail="Road network not built")
    lats, lons = _parse_points(p)
    base = {"available": True, "n_zones": st.n_zones, "n_settlements": len(st.s_node)}
    if not lats:
        return {**base, "zones": [None] * st.n_zones, "settlements": [None] * len(st.s_node), "snap_m": []}
    node_t, snap = st.net.times_from_points(lons, lats, ACCESS_MAX_MIN * 60)
    return {**base, **_pack(st, node_t), "snap_m": [round(float(d)) for d in snap]}


_roads_cache: dict[int, str] = {}


@app.get("/api/access/roads")
def access_roads(max_min: int = Query(15, ge=1, le=ACCESS_MAX_MIN), p: list[str] = Query(default=[])):
    """Road segments reachable from the fire stations (existing + proposed `p`) within max_min,
    as MultiLineString features with a `band` property (5-minute steps)."""
    st = _access_state()
    if st is None or st.node_t is None or st.edges is None:
        raise HTTPException(status_code=503, detail="Road network not built")
    if not p and max_min in _roads_cache:
        return geojson_response(_roads_cache[max_min])

    node_t = st.node_t
    lats, lons = _parse_points(p)
    if lats:
        extra, _ = st.net.times_from_points(lons, lats, ACCESS_MAX_MIN * 60)
        node_t = np.minimum(node_t, extra)

    lon, lat, ea, eb = st.edges
    t = np.maximum(node_t[ea], node_t[eb])          # a segment is reached when both ends are
    ok = np.isfinite(t) & (t <= max_min * 60)
    ea, eb, t = ea[ok], eb[ok], t[ok]
    band = np.minimum(np.maximum(np.ceil(t / 300) * 5, 5), max_min).astype(int)

    feats = []
    for bnd in np.unique(band):
        m = band == bnd
        segs = np.stack([np.column_stack([lon[ea[m]], lat[ea[m]]]),
                         np.column_stack([lon[eb[m]], lat[eb[m]]])], axis=1).round(5)
        feats.append({"type": "Feature", "properties": {"band": int(bnd)},
                      "geometry": {"type": "MultiLineString", "coordinates": segs.tolist()}})
    body = json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":"))
    if not p:
        _roads_cache[max_min] = body
    return geojson_response(body)


# --------------------------------------------------------------------------- #
# Simple file-backed layers: one table instead of one function per layer
# --------------------------------------------------------------------------- #
POINTS = {"Point", "MultiPoint"}
LINES = {"LineString", "MultiLineString"}
POWER_FILES = ["data/power_lines.geojson"]


class LayerSpec(NamedTuple):
    files: list[str]
    tolerance_m: float = 0           # simplification, in metres (0 = none)
    power: set[str] | None = None    # filter on the `power` column
    kinds: set[str] | None = None    # filter on geometry type


LAYERS: dict[str, LayerSpec] = {
    "power-lines":    LayerSpec(POWER_FILES, 0, {"line"}, LINES),
    "power-nodes":    LayerSpec(POWER_FILES, 0, {"tower"}, POINTS),
    "power-stations": LayerSpec(POWER_FILES, 0, {"substation"}),
    "settlements":    LayerSpec(["data/settlements.geojson"]),
    "rivers":         LayerSpec(["data/env_lin_rivers.geojson"], 20),
    "lakes":          LayerSpec(["data/pxs_pol_limnes.geojson"], 20),
    "roads":          LayerSpec(["data/pxs_lin_odiko_diktyo.geojson"], 25),
    "fire-stations":  LayerSpec(["data/fire-stations.geojson"]),
    "water-points":   LayerSpec(["data/waterwells_firehydrants.geojson"]),
    "helipads":       LayerSpec(["data/helipads.geojson"]),
}


def _make_handler(spec: LayerSpec):
    def handler():
        return geojson_response(load_layer(spec.files, spec.tolerance_m, spec.power, spec.kinds))
    return handler


for _route, _spec in LAYERS.items():
    app.add_api_route(f"/api/{_route}", _make_handler(_spec), methods=["GET"], name=_route)

try:
    _access_state()          # build it now rather than on the first request
except Exception:
    log.exception("Road access could not be prepared")