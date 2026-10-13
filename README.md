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
 DEM, CORINE, EFFIS ──┴─► backend/build_static_risk.py ─► forests_with_risk_score_v2.geojson ─┐
                                                          + model.json                        │
                                                                                              │
 OSM Greece extract ──────► backend/build_road_network.py ─► data/road_graph.npz ────────────┤
 (Geofabrik)                                                                                  │
                                                                                              ▼
 Open-Meteo ─► backend/fwi.py ───────────────────────────► backend/main.py (FastAPI)
                                                                      │
                                                                      ▼
                                                  crete-wildfire-dashboard (Angular + Leaflet)
```

- **Static score:** seven factors (fuel, slope, aspect, fire history, distance to power lines, distance to
  roads, next to settlements) scored 0-100 and combined with expert weights. Classes are percentile bands.
- **Validation:** the build script tests the score against fires after 2021 and writes the results to
  `model.json`; the docs page reads them from there.
- **Fire Weather Index:** the Canadian FWI system (Van Wagner 1987), computed from Open-Meteo noon weather.
  Shown beside the score, never mixed into it.
- **Drive-time coverage:** `build_road_network.py` builds a road graph from OpenStreetMap
  (`data/road_graph.npz`). The API uses it to compute minutes from fire stations, including proposed
  ones, to every zone and settlement, and to draw the reachable roads. Speeds are assumptions by road class.

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
python build_road_network.py         # optional: downloads Greece's OSM extract (a few hundred MB) once
uvicorn main:app --reload            # http://127.0.0.1:8000/docs for the API
```

> Without `data/road_graph.npz` the app still works, in straight-line mode only.
> Restart the API after building the graph, because it is loaded once at start-up.

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

## API

Interactive documentation is served at `/docs` (Swagger UI) when the API is running.

### Drive-time coverage

| Endpoint                                       | Description                                                                                                                                                                                                |
| :--------------------------------------------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /api/access`                              | Drive times (minutes) from the existing fire stations to every zone and every settlement. Returns `{"available": false}` if the road graph has not been built. `null` means not reached within 45 minutes. |
| `GET /api/access/proposed?p=lat,lng&p=lat,lng` | Same, for proposed stations. Repeat `p` for each station (at most 10, inside Crete). Also returns `snap_m`, the distance from each point to its nearest road.                                              |
| `GET /api/access/roads?max_min=15&p=lat,lng`   | Road segments reachable from the existing stations, plus any proposed `p`, within `max_min` minutes (1 to 45). GeoJSON `MultiLineString` features with a `band` property in 5-minute steps.                |

Zone and settlement results are arrays in the same order as the `/api/risk-zones` (by `zid`) and
`/api/settlements` layers, so the map can match them by position.

### Other endpoints

| Endpoint                         | Description                                                                                                                                         |
| :------------------------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /api/model`                 | Weights, class breaks, `train_end` and validation results from `model.json`.                                                                        |
| `GET /api/risk-zones`            | Scored forest zones (GeoJSON) with factor scores, `zid`, `station_id` and `dist_fire_m`.                                                            |
| `GET /api/burned-areas`          | EFFIS burnt areas with `year`, `date` and `area_ha`.                                                                                                |
| `GET /api/weather?refresh=false` | Current weather at the eight stations (cached 10 minutes).                                                                                          |
| `GET /api/fwi?refresh=false`     | Fire Weather Index per station (cached 3 hours).                                                                                                    |
| `GET /api/{layer}`               | Map layers: `power-lines`, `power-nodes`, `power-stations`, `settlements`, `rivers`, `lakes`, `roads`, `fire-stations`, `water-points`, `helipads`. |

## Deployment

The frontend is a static Angular build. The backend needs a real server.

**Frontend.** `ng build` writes static files to `dist/`. Any static host works (Cloudflare Pages,
Netlify, Vercel, GitHub Pages, or your own web server). Configure it to serve `index.html` for unknown
paths, because the app uses client-side routes such as `/docs`. Set the production API address in
`src/environments/environment.ts` before building.

**Backend.** Run FastAPI with uvicorn behind a reverse proxy (nginx, Caddy) or on a platform such as
Render, Fly.io or Railway.

- **Memory:** plan for roughly **1 to 2 GB of RAM**. geopandas, the zone geometries and the road graph are
  all held in memory. A 512 MB free tier will probably not be enough. Measure on your host.
- **Files:** upload the `data/` folder, including `road_graph.npz`. Build the graph on your own machine,
  because reading the Greece extract takes several minutes and temporary disk space. Don't build it on the
  server.
- **CORS:** set `CORS_ORIGINS` to the address of the frontend, comma-separated if there are several:

```bash
  CORS_ORIGINS=https://wildfire.example.org uvicorn main:app --host 0.0.0.0 --port 8000
```

- **Start-up:** the API loads the road graph and zone data when it starts, so the first start takes a
  little while. Use a health check on `/`.
- **Workers:** the caches live in each process's memory. One worker is simplest. With several workers,
  each keeps its own copy of the data and its own cache.

**Rate limiting.** `/api/access/proposed` and `/api/access/roads` run a graph search for every request, and
anyone can send up to 10 points repeatedly. Before making the API public, limit these routes, either at
the proxy or in the app (for example with [`slowapi`](https://github.com/laurentS/slowapi)). The weather and
FWI endpoints already limit forced refreshes (`?refresh=true`) to protect the upstream API.

**Third-party services and their limits**

| Service                               | Used for                          | Limit to check                                                                                                                                                |
| :------------------------------------ | :-------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| [Open-Meteo](https://open-meteo.com/) | Weather and FWI                   | The free API is for **non-commercial use** only. A commercial or high-traffic site needs a paid plan.                                                         |
| OpenTopoMap tiles                     | Terrain basemap                   | Public tile servers are meant for light use, and heavy traffic can be blocked. Use a provider with a plan (for example MapTiler or Stadia) or your own tiles. |
| Esri World Imagery                    | Satellite basemap                 | Has its own terms for production apps. Check them before launch.                                                                                              |
| OpenStreetMap data                    | Road graph, stations, settlements | ODbL. Keep the attribution visible.                                                                                                                           |

**Before going public:** keep the planning-aid disclaimer visible, check that the fire station data is
complete (uncovered counts are only as good as the station list), and have someone from the fire service
review the assumed speeds in `build_road_network.py`.

## Tests

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

`validate_fwi.py` is a separate analysis (it downloads weather) that checks whether the FWI separates
fire days from other summer days.

## Limitations

Short fire record (about six years), only larger fires mapped, land cover from 2012, assumed (not measured)
fire-engine speeds for drive times, Crete only. See the Docs page for the full list.

## QGIS Project

The original QGIS project file used for data preparation and styling is available in the [`qgis/`](qgis/) folder.

## Data and attribution

- Contains Copernicus Land Monitoring Service information, © European Union, EEA (CORINE Land Cover 2012).
- Burnt areas: EFFIS. Weather: [Open-Meteo.com](https://open-meteo.com/) (CC BY 4.0; the free API is for
  non-commercial use).
- Base maps: © OpenTopoMap, OpenStreetMap contributors, SRTM; Esri World Imagery.
- Road network: © OpenStreetMap contributors (ODbL), via Geofabrik.
- Other layers: see [`backend/data/README.md`](backend/data/README.md).

## Licence

This project is licensed under the terms of the **MIT License**. See the [LICENSE](LICENSE) file for details.
_(Note: Spatial data and external layers maintain their own respective licences and attribution terms)._

## Author

- Eva Chrysostomaki - _Initial work & development_ - [GitHub Profile](https://github.com/Eva-Chris)
