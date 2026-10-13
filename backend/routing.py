"""routing.py - drive-time queries on a compact road graph.

Needs numpy, pandas and scipy (plus geopandas for zone_node_pairs). The graph file is
written by build_road_network.py; the API loads it once at start-up.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.spatial import cKDTree

# Local flat-earth conversion, good to a fraction of a percent across Crete (35.2 N)
M_PER_DEG_LAT = 110_574.0
M_PER_DEG_LNG = 111_320.0 * np.cos(np.radians(35.2))
OFFROAD_MS = 10 / 3.6      # metres per second for the short leg between a point and its nearest road node
MIN_EDGE_S = 0.1           # explicit zeros are ambiguous in sparse graphs, so no edge takes less than this


def to_xy(lon, lat) -> tuple[np.ndarray, np.ndarray]:
    return np.asarray(lon, float) * M_PER_DEG_LNG, np.asarray(lat, float) * M_PER_DEG_LAT


def build_csr(n: int, u, v, t) -> csr_matrix:
    """Directed graph from edge lists. Parallel edges keep the FASTEST one (csr_matrix would add them up)."""
    df = pd.DataFrame({"u": np.asarray(u), "v": np.asarray(v), "t": np.maximum(np.asarray(t, float), MIN_EDGE_S)})
    df = df[df["u"] != df["v"]].groupby(["u", "v"], as_index=False)["t"].min()
    return csr_matrix((df["t"].to_numpy(float), (df["u"].to_numpy(), df["v"].to_numpy())), shape=(n, n))


def largest_scc(n: int, u, v) -> np.ndarray:
    """Boolean mask of the nodes in the largest strongly connected component.

    Keeps only roads you can both enter and leave, so a snapped point never lands on an isolated fragment.
    """
    g = csr_matrix((np.ones(len(u)), (np.asarray(u), np.asarray(v))), shape=(n, n))
    _, labels = connected_components(g, directed=True, connection="strong")
    return labels == np.bincount(labels).argmax()


def to_minutes(t_s: np.ndarray, max_min: float) -> list[float | None]:
    """Seconds -> minutes for JSON. Unreached (inf) or slower than max_min becomes None."""
    m = np.asarray(t_s, float) / 60.0
    return [round(float(x), 1) if np.isfinite(x) and x <= max_min else None for x in m]


def zone_times(node_t: np.ndarray, zone_idx: np.ndarray, node_idx: np.ndarray, n_zones: int) -> np.ndarray:
    """Fastest time (s) to any road node that belongs to each zone. inf when a zone has no node."""
    out = np.full(n_zones, np.inf)
    np.minimum.at(out, zone_idx, node_t[node_idx])
    return out


def point_times(node_t: np.ndarray, node_idx: np.ndarray, snap_m: np.ndarray, max_snap_m: float = 2000.0) -> np.ndarray:
    """Time (s) to points that were snapped to road nodes, plus a slow leg for the snap distance."""
    t = node_t[node_idx] + snap_m / OFFROAD_MS
    t[snap_m > max_snap_m] = np.inf
    return t


class RoadNet:
    def __init__(self, lon, lat, u, v, t):
        self.lon = np.asarray(lon, float)
        self.lat = np.asarray(lat, float)
        self.n = len(self.lon)
        self.graph = build_csr(self.n, u, v, t)
        self.tree = cKDTree(np.column_stack(to_xy(self.lon, self.lat)))

    @classmethod
    def load(cls, path: Path | str) -> "RoadNet":
        d = np.load(path)
        return cls(d["lon"], d["lat"], d["u"], d["v"], d["t"])

    def snap(self, lons, lats) -> tuple[np.ndarray, np.ndarray]:
        """Nearest road node of each point: (node index, distance in metres)."""
        dist, idx = self.tree.query(np.column_stack(to_xy(lons, lats)))
        return np.atleast_1d(idx), np.atleast_1d(dist)

    def times_from(self, nodes, limit_s: float) -> np.ndarray:
        """Fastest time (s) from ANY of the given nodes to every node. inf = not reached within limit_s."""
        nodes = np.atleast_1d(nodes)
        if nodes.size == 0:
            return np.full(self.n, np.inf)
        return dijkstra(self.graph, directed=True, indices=nodes, limit=limit_s, min_only=True)

    def times_from_points(self, lons, lats, limit_s: float) -> tuple[np.ndarray, np.ndarray]:
        """Like times_from, for free points: adds each point's off-road leg to its nearest road.

        Slower than times_from (one search per point), so use it for a handful of points.
        Returns (time to every node, snap distance of each point in metres).
        """
        idx, dist = self.snap(lons, lats)
        best = np.full(self.n, np.inf)
        for node, d in zip(idx, dist):
            lead = d / OFFROAD_MS
            if lead < limit_s:
                best = np.minimum(best, self.times_from(node, limit_s - lead) + lead)
        return best, dist

    def zone_node_pairs(self, zones, buffer_m: float = 250.0) -> tuple[np.ndarray, np.ndarray]:
        """(zone index, node index) pairs: road nodes inside each zone grown by buffer_m metres.

        `zones` is a GeoDataFrame in any CRS; its row order defines the zone index.
        """
        import geopandas as gpd

        pts = gpd.GeoDataFrame({"node": np.arange(self.n)},
                               geometry=gpd.points_from_xy(self.lon, self.lat), crs=4326).to_crs(2100)
        z = zones.reset_index(drop=True).to_crs(2100)[["geometry"]].copy()
        z["geometry"] = z.geometry.buffer(buffer_m)
        j = gpd.sjoin(pts, z, how="inner", predicate="within")
        return j["index_right"].to_numpy(), j["node"].to_numpy()