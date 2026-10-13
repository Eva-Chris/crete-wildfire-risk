#!/usr/bin/env python3
"""
build_road_network.py - build Crete's drivable road graph (data/road_graph.npz) for the API's
drive-time coverage, from OpenStreetMap data read OFFLINE.

Why offline: the public Overpass servers time out or rate-limit large queries. Instead this
downloads Geofabrik's Greece extract once (a few hundred MB), reads the roads inside Crete's
bounding box with GDAL (already installed with pyogrio) and builds the graph itself.

Run (needs internet for the first download only):

    python build_road_network.py                  # downloads data/greece-latest.osm.pbf if missing
    python build_road_network.py my_extract.pbf   # or use a file you already have (.pbf or .osm)

Reading the whole Greece file takes several minutes and some temporary disk space. If the download
fails, fetch https://download.geofabrik.de/europe/greece-latest.osm.pbf in a browser and save it
as data/greece-latest.osm.pbf.

Speeds are ASSUMED fire-engine speeds by road class (CLASS_SPEED_KMH), not measured. They are the
main uncertainty of the result, so adjust them with someone who knows the local fire service.
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from routing import largest_scc

HERE = Path(__file__).resolve().parent
OUT = HERE / "data/road_graph.npz"
PBF = HERE / "data/greece-latest.osm.pbf"
PBF_URL = "https://download.geofabrik.de/europe/greece-latest.osm.pbf"

BBOX = (23.4, 34.8, 26.4, 35.75)   # west, south, east, north: Crete with a margin
INCLUDE_TRACKS = False             # True also routes over dirt tracks (slowly). Many are unsuitable for engines.

# Assumed fire-engine speeds in km/h. Lower than the speed limits: mountain roads are winding.
CLASS_SPEED_KMH = {
    "motorway": 80, "motorway_link": 50,
    "trunk": 65, "trunk_link": 40,
    "primary": 55, "primary_link": 35,
    "secondary": 45, "secondary_link": 30,
    "tertiary": 38, "tertiary_link": 25,
    "unclassified": 30,
    "residential": 25,
    "living_street": 15,
    "track": 15,
}
DEFAULT_SPEED_KMH = 25
MAXSPEED_FACTOR = 0.85             # where a speed limit is tagged and lower, drive at this share of it

ROAD_CLASSES = {h for h in CLASS_SPEED_KMH if h != "track"}
ONEWAY_BY_DEFAULT = {"motorway", "motorway_link"}


def parse_maxspeed(value) -> float | None:
    """OSM maxspeed ('50', '50 mph', ['50', '30'], 'none') -> km/h, or None if it can't be read."""
    if isinstance(value, (list, tuple)):
        speeds = [s for s in (parse_maxspeed(v) for v in value) if s]
        return min(speeds) if speeds else None
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(mph)?\s*$", str(value))
    if not m:
        return None
    kmh = float(m.group(1)) * (1.609 if m.group(2) else 1.0)
    return kmh if kmh > 0 else None


def edge_speed_kmh(highway, maxspeed=None) -> float:
    classes = highway if isinstance(highway, (list, tuple)) else [highway]
    speed = min(CLASS_SPEED_KMH.get(h, DEFAULT_SPEED_KMH) for h in classes)   # the slowest listed class
    limit = parse_maxspeed(maxspeed)
    if limit:
        speed = min(speed, limit * MAXSPEED_FACTOR)
    return max(speed, 5.0)


def _keep_largest(lon, lat, u, v, t) -> dict[str, np.ndarray]:
    """Keep only the largest strongly connected part (every node can reach every other)."""
    u, v, t = np.array(u, int), np.array(v, int), np.array(t, float)
    keep = largest_scc(len(lon), u, v)
    new_id = np.cumsum(keep) - 1
    ok = keep[u] & keep[v]
    return {"lon": lon[keep], "lat": lat[keep], "u": new_id[u[ok]], "v": new_id[v[ok]], "t": t[ok]}


# --------------------------------------------------------------------------- #
# Offline route: OSM file -> graph
# --------------------------------------------------------------------------- #
_TAG = re.compile(r'"((?:[^"\\]|\\.)*)"=>"((?:[^"\\]|\\.)*)"')


def parse_tags(other_tags) -> dict[str, str]:
    """GDAL stores extra OSM tags as an hstore string: "maxspeed"=>"50","oneway"=>"yes"."""
    if not isinstance(other_tags, str):
        return {}
    return {k: v for k, v in _TAG.findall(other_tags)}


def oneway_direction(highway: str, tags: dict[str, str]) -> int:
    """+1 = drivable along the drawn direction only, -1 = against it only, 0 = both ways."""
    ow = tags.get("oneway", "").lower()
    if ow in ("yes", "true", "1"):
        return 1
    if ow in ("-1", "reverse"):
        return -1
    if ow in ("no", "false", "0"):
        return 0
    if tags.get("junction") in ("roundabout", "circular") or highway in ONEWAY_BY_DEFAULT:
        return 1
    return 0


def usable(highway, tags: dict[str, str]) -> bool:
    """Same rules as the old Overpass filter: road classes only, no private or motor-vehicle-free ways."""
    if highway not in ROAD_CLASSES and not (INCLUDE_TRACKS and highway == "track"):
        return False
    if tags.get("motor_vehicle") == "no" or tags.get("access") in ("private", "no"):
        return False
    return True


def _haversine_m(lon1, lat1, lon2, lat2) -> float:
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return float(2 * 6_371_000 * np.arcsin(np.sqrt(a)))


def _key(x: float, y: float) -> tuple[float, float]:
    return (round(x, 7), round(y, 7))      # OSM stores 1e-7 degree precision


def lines_to_arrays(ways) -> dict[str, np.ndarray]:
    """GeoDataFrame of OSM ways (columns highway, other_tags, geometry) -> routing arrays.

    Ways are cut at junctions (points shared by two ways) and at their ends. Each piece becomes
    one edge per allowed direction, weighted with its travel time in seconds.
    """
    pieces = []     # (coords, highway, tags)
    for geom, hw, other in zip(ways.geometry, ways["highway"], ways["other_tags"]):
        tags = parse_tags(other)
        if geom is None or not usable(hw, tags):
            continue
        parts = geom.geoms if geom.geom_type == "MultiLineString" else [geom]
        for part in parts:
            coords = [_key(x, y) for x, y, *_ in part.coords]
            if len(coords) >= 2:
                pieces.append((coords, hw, tags))

    uses = Counter(pt for coords, _, _ in pieces for pt in coords)
    node_id: dict[tuple[float, float], int] = {}
    lon, lat = [], []

    def node(pt):
        i = node_id.get(pt)
        if i is None:
            i = node_id[pt] = len(lon)
            lon.append(pt[0]); lat.append(pt[1])
        return i

    u, v, t = [], [], []
    for coords, hw, tags in pieces:
        direction = oneway_direction(hw, tags)
        speed_ms = edge_speed_kmh(hw, tags.get("maxspeed")) / 3.6
        start, length = 0, 0.0
        for k in range(1, len(coords)):
            length += _haversine_m(*coords[k - 1], *coords[k])
            if k == len(coords) - 1 or uses[coords[k]] > 1:      # junction or end: close the edge
                a, b = node(coords[start]), node(coords[k])
                if a != b and length > 0:
                    secs = length / speed_ms
                    if direction >= 0:
                        u.append(a); v.append(b); t.append(secs)
                    if direction <= 0:
                        u.append(b); v.append(a); t.append(secs)
                start, length = k, 0.0
    if not u:
        raise SystemExit("No drivable roads found inside BBOX. Is this the right file?")
    return _keep_largest(np.array(lon), np.array(lat), u, v, t)


def read_ways(path: Path):
    import pyogrio
    print(f"Reading roads inside {BBOX} from {path.name} (several minutes for the Greece file)...")
    try:
        return pyogrio.read_dataframe(path, layer="lines", bbox=BBOX,
                                      where="highway IS NOT NULL", columns=["highway", "other_tags"])
    except Exception as exc:
        raise SystemExit(
            f"Could not read {path.name} with GDAL's OSM driver ({type(exc).__name__}: {exc}).\n"
            "Check that the file is a complete .osm.pbf download.")


def download(url: str, dest: Path) -> None:
    import requests
    # Some networks advertise IPv6 but can't route it, which makes downloads stall until the timeout.
    import urllib3.util.connection as cn
    cn.HAS_IPV6 = False
    dest.parent.mkdir(exist_ok=True)
    tmp = dest.with_suffix(".part")
    print(f"Downloading {url}")
    with requests.get(url, stream=True, timeout=(30, 120), headers={"User-Agent": "wildfire-risk-pipeline"}) as r:
        r.raise_for_status()
        total, done = int(r.headers.get("content-length", 0)), 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r  {done / 1e6:.0f} / {total / 1e6:.0f} MB", end="", flush=True)
    tmp.replace(dest)
    print()


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else PBF
    if not src.exists():
        if len(sys.argv) > 1:
            raise SystemExit(f"{src} not found.")
        download(PBF_URL, src)
    arrays = lines_to_arrays(read_ways(src))
    OUT.parent.mkdir(exist_ok=True)
    np.savez_compressed(OUT, **arrays)
    print(f"Wrote {OUT.name}: {len(arrays['lon'])} nodes, {len(arrays['u'])} directed edges "
          f"({OUT.stat().st_size / 1e6:.1f} MB). Restart the API to load it.")


if __name__ == "__main__":
    main()