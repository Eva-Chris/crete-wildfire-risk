"""Fetches weather and FWI once and writes weather.json / fwi.json. Run by GitHub Actions."""
import json, sys, time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from fwi import compute_fwi
from stations import STATIONS

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "out")
OUT.mkdir(parents=True, exist_ok=True)
ATHENS = ZoneInfo("Europe/Athens")


def get_with_retry(url, params, tries=4):
    for i in range(tries):
        r = requests.get(url, params=params, timeout=20)
        if r.status_code != 429:
            r.raise_for_status()
            return r
        time.sleep(min(int(r.headers.get("Retry-After", 5 * 2 ** i)), 60))
    r.raise_for_status()


def weather():
    r = get_with_retry("https://api.open-meteo.com/v1/forecast", {
        "latitude": ",".join(str(s["lat"]) for s in STATIONS),
        "longitude": ",".join(str(s["lon"]) for s in STATIONS),
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m",
        "wind_speed_unit": "kmh", "timezone": "Europe/Athens"})
    res = r.json()
    res = [res] if isinstance(res, dict) else res
    st = [{**s, "temp_c": x["current"]["temperature_2m"],
           "humidity_pct": x["current"]["relative_humidity_2m"],
           "wind_kmh": x["current"]["wind_speed_10m"],
           "wind_dir": x["current"]["wind_direction_10m"]} for s, x in zip(STATIONS, res)]
    return {"updated": res[0]["current"]["time"], "stale": False, "stations": st}


def fwi():
    now = datetime.now(ATHENS)
    return {"live": True, "stale": False, "in_season": 4 <= now.month <= 10,
            "computed": now.strftime("%Y-%m-%dT%H:%M"), "stations": compute_fwi(STATIONS)}


done = 0
for name, fn in (("weather", weather), ("fwi", fwi)):
    try:
        (OUT / f"{name}.json").write_text(json.dumps(fn()))
        print("wrote", name)
        done += 1
    except Exception as e:
        print("FAILED", name, e)   # the previous file stays in OUT, if the workflow downloaded one
sys.exit(0 if done else 1)