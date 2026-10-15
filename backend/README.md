## Inputs for `build_static_risk.py`

| File                               | What it is                                                               | Where it comes from                                                                                                                                                                                                                                |
| :--------------------------------- | :----------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `forests_with_risk_score.geojson`  | Forest zones with `mean_slope`, `dist_power_m`, `dist_roads_m`, `is_wui` | **QGIS Processing:** Derived from Corine Land Cover forest polygons. `mean_slope` calculated via Zonal Statistics using `DEM.tif`, `dist_power_m` and `dist_roads_m` via Distance Matrix/NN tools, and `is_wui` via Spatial Join with settlements. |
| `DEM.tif`                          | Elevation raster of Crete                                                | **EU-DEM (Copernicus):** Elevation model of Crete, 25m resolution, free and open licence under Copernicus Programme.                                                                                                                               |
| `clc2012.gpkg`                     | CORINE Land Cover 2012                                                   | Download CORINE Land Cover 2012 (Greece) from [land.copernicus.eu](https://land.copernicus.eu/), unzip here, then run `python scripts/convert_clc.py`                                                                                              |
| `burned_areas_crete_small.geojson` | EFFIS burnt areas, with a date or year column                            | EFFIS: [effis.jrc.ec.europa.eu](https://effis.jrc.ec.europa.eu/) (fires of roughly 30 ha and larger, filtered for Crete)                                                                                                                           |

## Inputs for `build_road_network.py` (drive-time coverage)

| File                    | What it is                                          | Where it comes from                                                                                                                                       |
| :---------------------- | :-------------------------------------------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `greece-latest.osm.pbf` | OpenStreetMap extract for Greece (a few hundred MB) | [Geofabrik](https://download.geofabrik.de/europe/greece-latest.osm.pbf), ODbL. Downloaded automatically on the first run if missing, or save it yourself. |

**Output:** `road_graph.npz` - a compact drivable road graph for Crete (nodes, directed edges, travel time in seconds per edge).

- Only drivable road classes are used. Dirt tracks, private ways and motor-vehicle-free ways are excluded.
- Travel times use **assumed fire-engine speeds by road class** (`CLASS_SPEED_KMH` in `build_road_network.py`), lowered where a tagged speed limit is slower. These are assumptions, not measurements. Should be adjusted with someone from the fire service.
- Restart the API after rebuilding the graph, because it loads the file once at start-up.
- **If `road_graph.npz` is missing, the app still works** in straight-line mode only. The "By road" option is hidden.

`road_graph.npz` is not the same as the **Roads** layer below. The Roads layer is a display-only overlay from data.gov.gr. The graph comes from OpenStreetMap and is what drive times are computed on.

## Layers served by the API (`main.py`)

| File                                 | Layer                                                 | Source and licence                                                                                                    |
| :----------------------------------- | :---------------------------------------------------- | :-------------------------------------------------------------------------------------------------------------------- |
| `forests_with_risk_score_v2.geojson` | Risk zones                                            | Output of `build_static_risk.py`                                                                                      |
| `power_lines.geojson`                | Lines, towers, substations (needs a `power` column)   | OpenStreetMap (via Overpass Turbo), Open Database License (ODbL)                                                      |
| `settlements.geojson`                | Settlements                                           | OpenStreetMap / Corine Land Cover Urban Fabric, ODbL                                                                  |
| `pxs_lin_odiko_diktyo.geojson`       | Roads (display only)                                  | [data.gov.gr](https://data.gov.gr/dataset/gis-perifereia-kritis-wms-gisvec-pxs_lin_odiko_diktyo) (Periphery of Crete) |
| `env_lin_rivers.geojson`             | Rivers                                                | [data.gov.gr](https://data.gov.gr/dataset/gis-perifereia-kritis-wms-gisvec-env_lin_rivers) (Periphery of Crete)       |
| `pxs_pol_limnes.geojson`             | Lakes                                                 | [data.gov.gr](https://data.gov.gr/dataset/gis-perifereia-kritis-wms-gisvec-pxs_pol_limnes) (Periphery of Crete)       |
| `fire-stations.geojson`              | Fire stations (also the start points for drive times) | OpenStreetMap (Extracted via Overpass Turbo `amenity=fire_station`), ODbL                                             |
| `waterwells_firehydrants.geojson`    | Hydrants and water wells                              | OpenStreetMap (Extracted via Overpass Turbo `emergency=fire_hydrant`), ODbL                                           |
| `helipads.geojson`                   | Helipads                                              | OpenStreetMap (Extracted via Overpass Turbo `aeroway=helipad`), ODbL                                                  |

## Used by the drive-time endpoints

| File                    | Used by                                                    | Notes                                                                                                                                                        |
| :---------------------- | :--------------------------------------------------------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `road_graph.npz`        | `/api/access`, `/api/access/proposed`, `/api/access/roads` | Built by `build_road_network.py` (see above).                                                                                                                |
| `fire-stations.geojson` | the same endpoints                                         | Coverage counts only the stations in this file. If volunteer brigades or forest service units are missing, the number of uncovered zones will be overstated. |
| `settlements.geojson`   | the same endpoints                                         | The order of features in this file is used to match drive times to settlements, so don't re-sort it without rebuilding.                                      |
