"""Weather stations shared by the API, the FWI code and the validation script.

Eight points spread over the island. Each forest zone is assigned to its nearest
station, so conditions vary across Crete (the meltemi blows harder in the east,
the south is hotter, and so on) instead of one reading for the whole island.
"""
from __future__ import annotations

import numpy as np

STATIONS = [
    {"id": 0, "name": "Chania", "lat": 35.51, "lon": 24.02},
    {"id": 1, "name": "Sfakia", "lat": 35.20, "lon": 24.15},
    {"id": 2, "name": "Rethymno", "lat": 35.37, "lon": 24.47},
    {"id": 3, "name": "Heraklion", "lat": 35.34, "lon": 25.13},
    {"id": 4, "name": "Messara", "lat": 35.06, "lon": 24.85},
    {"id": 5, "name": "Agios Nikolaos", "lat": 35.19, "lon": 25.72},
    {"id": 6, "name": "Ierapetra", "lat": 35.01, "lon": 25.74},
    {"id": 7, "name": "Sitia", "lat": 35.21, "lon": 26.10},
]

_LAT = np.array([s["lat"] for s in STATIONS])
_LON = np.array([s["lon"] for s in STATIONS])
_COS_LAT = np.cos(np.radians(35.2))  # longitude degrees shrink with latitude


def nearest_station_ids(lons, lats) -> np.ndarray:
    """Index (= station id) of the nearest station for each lon/lat in degrees."""
    dx = (np.asarray(lons, dtype=float)[:, None] - _LON[None, :]) * _COS_LAT
    dy = np.asarray(lats, dtype=float)[:, None] - _LAT[None, :]
    return (dx**2 + dy**2).argmin(axis=1).astype(int)
