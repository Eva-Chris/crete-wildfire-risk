"""
fwi.py - Canadian Fire Weather Index (Van Wagner 1987) from Open-Meteo noon weather.

Per day at local noon it needs temperature (C), relative humidity (%), wind speed (km/h)
and rain over the previous 24 h (mm). The moisture codes carry over from day to day, so
the series runs from 1 March (archive data) through the forecast days.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import pandas as pd
import requests
import time

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
FORECAST = "https://api.open-meteo.com/v1/forecast"
HOURLY = "temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation"
TZ = "Europe/Athens"

FFMC0, DMC0, DC0 = 85.0, 6.0, 15.0   # standard start-of-season values
DAY_LEN = [6.5, 7.5, 9.0, 12.8, 13.9, 13.9, 12.4, 10.9, 9.4, 8.0, 7.0, 6.0]   # DMC, latitude >= 30 N
DC_FL = [-1.6, -1.6, -1.6, 0.9, 3.8, 5.8, 6.4, 5.0, 2.4, 0.4, -1.6, -1.6]     # DC


def calc_ffmc(t, rh, w, p, prev):
    mo = 147.2 * (101 - prev) / (59.5 + prev)
    if p > 0.5:
        rf = p - 0.5
        add = 42.5 * rf * math.exp(-100 / (251 - mo)) * (1 - math.exp(-6.93 / rf))
        if mo > 150:
            add += 0.0015 * (mo - 150) ** 2 * math.sqrt(rf)
        mo = min(mo + add, 250)
    ed = 0.942 * rh ** 0.679 + 11 * math.exp((rh - 100) / 10) + 0.18 * (21.1 - t) * (1 - math.exp(-0.115 * rh))
    if mo > ed:
        ko = 0.424 * (1 - (rh / 100) ** 1.7) + 0.0694 * math.sqrt(w) * (1 - (rh / 100) ** 8)
        m = ed + (mo - ed) * 10 ** (-(ko * 0.581 * math.exp(0.0365 * t)))
    else:
        ew = 0.618 * rh ** 0.753 + 10 * math.exp((rh - 100) / 10) + 0.18 * (21.1 - t) * (1 - math.exp(-0.115 * rh))
        if mo < ew:
            k1 = 0.424 * (1 - ((100 - rh) / 100) ** 1.7) + 0.0694 * math.sqrt(w) * (1 - ((100 - rh) / 100) ** 8)
            m = ew - (ew - mo) * 10 ** (-(k1 * 0.581 * math.exp(0.0365 * t)))
        else:
            m = mo
    return 59.5 * (250 - m) / (147.2 + m)


def calc_dmc(t, rh, p, prev, month):
    t = max(t, -1.1)
    rk = 1.894 * (t + 1.1) * (100 - rh) * DAY_LEN[month - 1] * 1e-4
    pr = prev
    if p > 1.5:
        rw = 0.92 * p - 1.27
        wmi = 20 + 280 / math.exp(0.023 * prev)
        if prev <= 33:
            b = 100 / (0.5 + 0.3 * prev)
        elif prev <= 65:
            b = 14 - 1.3 * math.log(prev)
        else:
            b = 6.2 * math.log(prev) - 17.2
        wmr = wmi + 1000 * rw / (48.77 + b * rw)
        pr = 43.43 * (5.6348 - math.log(wmr - 20))
    return max(pr, 0) + rk


def calc_dc(t, p, prev, month):
    t = max(t, -2.8)
    pe = max((0.36 * (t + 2.8) + DC_FL[month - 1]) / 2, 0)
    if p > 2.8:
        rw = 0.83 * p - 1.27
        smi = 800 * math.exp(-prev / 400)
        dr = max(prev - 400 * math.log(1 + 3.937 * rw / smi), 0)
        return dr + pe
    return prev + pe


def calc_isi(ffmc, w):
    fm = 147.2 * (101 - ffmc) / (59.5 + ffmc)
    sf = 19.115 * math.exp(-0.1386 * fm) * (1 + fm ** 5.31 / 4.93e7)
    return sf * math.exp(0.05039 * w)


def calc_bui(dmc, dc):
    if dmc <= 0.4 * dc:
        bui = 0.8 * dmc * dc / (dmc + 0.4 * dc) if (dmc + 0.4 * dc) else 0
    else:
        bui = dmc - (1 - 0.8 * dc / (dmc + 0.4 * dc)) * (0.92 + (0.0114 * dmc) ** 1.7)
    return max(bui, 0)


def calc_fwi(isi, bui):
    fd = 0.626 * bui ** 0.809 + 2 if bui <= 80 else 1000 / (25 + 108.64 * math.exp(-0.023 * bui))
    b = 0.1 * isi * fd
    return math.exp(2.72 * (0.434 * math.log(b)) ** 0.647) if b > 1 else b


# --------------------------------------------------------------------------- #
# Weather -> daily noon table
# --------------------------------------------------------------------------- #
def _get(url: str, stations: list[dict], **extra) -> list[dict]:
    params = {
        "latitude": ",".join(str(s["lat"]) for s in stations),
        "longitude": ",".join(str(s["lon"]) for s in stations),
        "hourly": HOURLY, "wind_speed_unit": "kmh", "timezone": TZ, **extra,
    }
    for i in range(5):
        r = requests.get(url, params=params, timeout=90)
        if r.status_code != 429:
            break
        try:
            wait = int(r.headers.get("Retry-After", ""))
        except ValueError:
            wait = 15 * 2 ** i
        time.sleep(min(wait, 120))
    r.raise_for_status()
    res = r.json()
    return res if isinstance(res, list) else [res]


def _noon(hourly: dict) -> pd.DataFrame:
    """One row per day: noon temp / RH / wind and the 24 h rain ending at noon."""
    df = pd.DataFrame(hourly)
    df["time"] = pd.to_datetime(df["time"])
    df = df.set_index("time")
    for c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["precip24"] = df["precipitation"].rolling(24, min_periods=24).sum()
    noon = df[df.index.hour == 12][["temperature_2m", "relative_humidity_2m", "wind_speed_10m", "precip24"]].copy()
    noon.index = noon.index.date
    return noon


def series_for(noon: pd.DataFrame) -> pd.DataFrame:
    """Run the FWI system day by day. Index = date, columns = fwi, isi, bui, ffmc, dmc, dc."""
    f, m, d = FFMC0, DMC0, DC0
    rows = {}
    for day, r in noon.iterrows():
        if r.isna().any():
            continue
        t, rh = r["temperature_2m"], min(100.0, max(1.0, r["relative_humidity_2m"]))
        w, p = max(0.0, r["wind_speed_10m"]), max(0.0, r["precip24"])
        f = calc_ffmc(t, rh, w, p, f)
        m = calc_dmc(t, rh, p, m, day.month)
        d = calc_dc(t, p, d, day.month)
        i, b = calc_isi(f, w), calc_bui(m, d)
        rows[day] = {"fwi": calc_fwi(i, b), "isi": i, "bui": b, "ffmc": f, "dmc": m, "dc": d}
    return pd.DataFrame.from_dict(rows, orient="index")


def season_start(today: date) -> date:
    return date(today.year if today.month >= 3 else today.year - 1, 3, 1)


def _summary(st: dict, s: pd.DataFrame, today: date) -> dict:
    base = {"id": st["id"], "name": st["name"], "lat": st["lat"], "lon": st["lon"]}
    days = [d for d in s.index if d <= today]
    if not days:
        return {**base, "fwi": None}
    cur = max(days)
    row = {k: round(float(v), 1) for k, v in s.loc[cur].items()}
    fut = [d for d in sorted(s.index) if d > today][:3]
    return {**base, "date": cur.isoformat(), **row,
            "forecast": [{"date": d.isoformat(), "fwi": round(float(s.loc[d, "fwi"]), 1)} for d in fut]}


def compute_fwi(stations: list[dict], today: date | None = None) -> list[dict]:
    today = today or pd.Timestamp.now(tz=TZ).date()
    start = season_start(today)
    arch_end = max(start, today - timedelta(days=6))     # ERA5 archive lags a few days
    arch = _get(ARCHIVE, stations, start_date=start.isoformat(), end_date=arch_end.isoformat())
    fcst = _get(FORECAST, stations, past_days=10, forecast_days=4)
    out = []
    for st, a, f in zip(stations, arch, fcst):
        noon = _noon(a["hourly"]).combine_first(_noon(f["hourly"])).sort_index()
        out.append(_summary(st, series_for(noon), today))
    return out
