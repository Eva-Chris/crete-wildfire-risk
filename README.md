# Crete wildfire risk

An interactive map that ranks Cretan forest zones by **relative wildfire susceptibility**, shows where
fire station coverage is thin, and lists the settlements with the most high-risk forest around them.
It also shows today's Fire Weather Index (FWI) at eight weather stations.

> **This is a planning aid, not a warning system.** It does not predict where or when fires start.
> For alerts use the Civil Protection services (112) and [EFFIS](https://effis.jrc.ec.europa.eu/).

![Screenshot](docs/screenshot.png)

## How it works

```
 QGIS-prepared zones ─┐
 DEM, CORINE, EFFIS ──┴─► backend/build_static_risk.py ─► forests_with_risk_score_v2.geojson + model.json
                                                                   │
 Open-Meteo ─► backend/fwi.py ─┐                                   ▼
                               └──────────────► backend/main.py (FastAPI) ──► crete-wildfire-dashboard (Angular + Leaflet)
```

- **Static score:** seven factors (fuel, slope, aspect, fire history, distance to power lines, distance to
  roads, next to settlements) scored 0-100 and combined with expert weights. Classes are percentile bands.
- **Validation:** the build script tests the score against fires after 2021 and writes the results to
  `model.json`; the docs page reads them from there.
- **Fire Weather Index:** the Canadian FWI system (Van Wagner 1987), computed from Open-Meteo noon weather.
  Shown beside the score, never mixed into it.

The in-app **Docs** page explains the method, its reliability and its limits in more detail.

## Run it

You need Python 3.10+ and Node 18+.

**1. Data.** See [`backend/data/README.md`](backend/data/README.md).

**2. Backend**

```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python build_static_risk.py          # writes the scored zones and model.json
uvicorn main:app --reload            # http://127.0.0.1:8000/docs for the API
```

**3. Frontend**

```bash
cd crete-wildfire-dashboard
npm install
npm install leaflet xlsx && npm install -D @types/leaflet
ng serve                             # http://localhost:4200
```

The API address is set in `src/environments/`. `environment.development.ts` (used by `ng serve`) points
to `http://127.0.0.1:8000/api`. For a deployment, serve the API under the same origin or edit
`environment.ts`, and set `CORS_ORIGINS` on the API to the site's address.

Leaflet's CSS must be loaded, for example in `angular.json` under `styles`:
`"node_modules/leaflet/dist/leaflet.css"`.

## Tests

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

`validate_fwi.py` is a separate analysis (it downloads weather) that checks whether the FWI separates
fire days from other summer days.

## Limitations

Short fire record (about six years), only larger fires mapped, land cover from 2012, straight-line
distances instead of travel time, Crete only. See the Docs page for the full list.

## QGIS Project

The original QGIS project file used for data preparation and styling is available in the [`qgis/`](qgis/) folder.

## Data and attribution

- Contains Copernicus Land Monitoring Service information, © European Union, EEA (CORINE Land Cover 2012).
- Burnt areas: EFFIS. Weather: [Open-Meteo.com](https://open-meteo.com/) (CC BY 4.0; the free API is for
  non-commercial use).
- Base maps: © OpenTopoMap, OpenStreetMap contributors, SRTM; Esri World Imagery.
- Other layers: see [`backend/data/README.md`](backend/data/README.md).

## Licence

This project is licensed under the terms of the **MIT License**. See the [LICENSE](LICENSE) file for details.
_(Note: Spatial data and external layers maintain their own respective licences and attribution terms)._

## Author

- Eva Chrysostomaki - _Initial work & development_ - [GitHub Profile](https://github.com/Eva-Chris)
