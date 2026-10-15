#!/usr/bin/env python3
"""Does the Fire Weather Index separate fire days from other summer days (Jun-Sep)?

Compares FWI and its components against the simple temperature/wind/humidity index the
project used before (kept here only as a baseline). A "fire day" is a (station, date)
pair with an EFFIS fire whose centroid is nearest to that station.

Run from this folder:  python validate_fwi.py
Downloads ERA5 noon weather from Open-Meteo once per year and caches it in data/noon_<year>.pkl.
"""
import json
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

import fwi as F
from common import parse_fire_dates
from stations import STATIONS, nearest_station_ids

HERE = Path(__file__).resolve().parent
BURNT = HERE / "data/burned_areas_crete_small.geojson"
model_path = HERE / "model.json"
YEARS = range(2016, pd.Timestamp.now().year + 1)
HIGH_FWI = 21.3     # lower bound of the EFFIS "High" class


def old_multiplier(t, w, rh):
    """The earlier weather index: 0.8 to 1.3 from temperature, wind and dryness."""
    c = lambda v, lo, hi: np.clip((v - lo) / (hi - lo), 0, 1)
    return 0.8 + 0.175 * c(t, 10, 40) + 0.175 * c(w, 0, 50) + 0.15 * c(70 - rh, 0, 60)


def year_noon(year: int) -> dict:
    cache = HERE / f"data/noon_{year}.pkl"
    if cache.exists():
        return pd.read_pickle(cache)
    end = min(pd.Timestamp(f"{year}-10-31"), pd.Timestamp.now() - pd.Timedelta(days=6)).date()
    res = F._get(F.ARCHIVE, STATIONS, start_date=f"{year}-03-01", end_date=end.isoformat())
    out = {st["id"]: F._noon(r["hourly"]) for st, r in zip(STATIONS, res)}
    if year < pd.Timestamp.now().year:      # the running year is still incomplete
        pd.to_pickle(out, cache)
    time.sleep(5)                           # be polite to the free API
    return out


def main():
    fires = gpd.read_file(BURNT).to_crs(2100)
    cent = gpd.GeoSeries(fires.geometry.centroid, crs=2100).to_crs(4326)
    fires["station"] = nearest_station_ids(cent.x.values, cent.y.values)
    _, dates, _ = parse_fire_dates(fires)
    if dates is None:
        raise SystemExit("The burnt-area file only has a year column; this check needs exact dates.")
    fires["day"] = dates.dt.date
    fire_days = set(zip(fires["station"], fires["day"]))

    rows = []
    for y in YEARS:
        for sid, noon in year_noon(y).items():
            s = F.series_for(noon).join(noon)
            s["station"], s["year"] = sid, y
            rows.append(s.reset_index().rename(columns={"index": "day"}))
    df = pd.concat(rows, ignore_index=True)
    df = df[pd.to_datetime(df["day"]).dt.month.between(6, 9)].copy()
    df["fire"] = np.array([(s, d) in fire_days for s, d in zip(df["station"], df["day"])]).astype(int)
    df["old"] = old_multiplier(df["temperature_2m"], df["wind_speed_10m"], df["relative_humidity_2m"])

    print(f"{int(df['fire'].sum())} fire station-days vs {int((1 - df['fire']).sum())} other June-Sep station-days")
    for c in ("fwi", "isi", "bui", "ffmc", "old"):
        print(f"  AUC {c:<5} {roc_auc_score(df['fire'], df[c]):.3f}")
    hi = df["fwi"] >= HIGH_FWI
    model = json.loads(model_path.read_text()) if model_path.exists() else {}
    model["fwi_validation"] = {
        "n_fire_days": int(df["fire"].sum()),
        "auc_fwi": round(float(roc_auc_score(df["fire"], df["fwi"])), 2),
        "auc_simple": round(float(roc_auc_score(df["fire"], df["old"])), 2),
    }
    model_path.write_text(json.dumps(model, indent=1))
    print("Wrote fwi_validation to model.json")
    print(f"  share of fire days with FWI >= {HIGH_FWI} (High): {hi[df['fire'] == 1].mean():.0%}"
          f" vs {hi[df['fire'] == 0].mean():.0%} of other days")


if __name__ == "__main__":
    main()
