#!/usr/bin/env python3
"""
build_static_risk.py - multi-factor static wildfire susceptibility for Crete forest zones.

Run:   python build_static_risk.py

Inputs (all under data/, see data/README.md):
  forests_with_risk_score.geojson   zones prepared in QGIS: needs mean_slope, dist_power_m,
                                    dist_roads_m, is_wui (and optionally an old static_risk_score)
  DEM.tiff / DEM.tif                elevation raster of Crete (any CRS)
  burned_areas_crete_small.geojson  EFFIS burnt areas (needs a date or year column)
  clc2012.gpkg                      CORINE Land Cover 2012. If missing, the script runs WITHOUT
                                    the fuel factor and re-normalises the weights.

Outputs:
  data/forests_with_risk_score_v2.geojson   zones + f_* factor scores + static_risk_score
  model.json                                weights, class breaks, train_end, validation results
                                            (served by /api/model and read by the docs page)
  dem_2100.tif, aspect_score.tif, aspect_vec.tif   cached rasters (delete to rebuild)

Install: pip install -r requirements.txt
"""
from __future__ import annotations

import json
import os
import warnings
from pathlib import Path

# GDAL refuses single GeoJSON features above a size limit (CORINE exports have huge
# multipolygons). 0 = no limit. Must be set before geopandas/pyogrio are imported.
os.environ.setdefault("OGR_GEOJSON_MAX_OBJ_SIZE", "0")

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import rasterio
from rasterio.warp import Resampling, calculate_default_transform, reproject
from rasterstats import zonal_stats
from shapely.geometry import box

from common import parse_fire_dates

warnings.filterwarnings("ignore", category=RuntimeWarning)

# =========================================================================== #
# CONFIG - edit here
# =========================================================================== #
HERE = Path(__file__).resolve().parent
CRS_M = 2100                      # GGRS87 / Greek Grid (metres)
TRAIN_END = 2021                  # fires <= this year feed f_history; later ones validate
BURNED_MIN_FRAC = 0.05            # zone counts as "burned later" if >= 5 % of it burned
FIT_AFTER_YEAR = 2012             # CORINE 2012 predates these fires, so only later fires score fuel

FOREST_IN = "data/forests_with_risk_score.geojson"
FOREST_OUT = "data/forests_with_risk_score_v2.geojson"
MODEL_OUT = "model.json"
DEM_CANDIDATES = ["data/DEM.tiff", "data/DEM.tif"]
BURNT_FILE = "data/burned_areas_crete_small.geojson"
CLC_FILE = "data/clc2012.gpkg"    # set to "" to auto-detect a file with clc/corine in its name

WEIGHTS = {                       # expert placeholders, deliberately NOT tuned on the test fires
    "fuel": 0.25,
    "slope": 0.15,
    "aspect": 0.10,
    "history": 0.10,
    "power": 0.12,
    "roads": 0.12,
    "wui": 0.16,
}
assert abs(sum(WEIGHTS.values()) - 1) < 1e-9, "weights must sum to 1"

# Fuel scores (0-100, higher = burns more readily).
#
# Normal path: scores come from the burn rate of each CORINE class in the fit period
# (see fuel_from_burn_rates). Three scores are then set by hand (MANUAL_FUEL).
# Classes below MIN_CLASS_KM2 inside the zones are too small to trust and get a default
# from FUEL_DEFAULT_BY_DIGIT, keyed on the first digit of the CORINE code.
MIN_CLASS_KM2 = 10.0
MANUAL_FUEL = {
    312: 50,  # conifer: Pinus brutia is highly flammable; zero burns in 2016-21 is likely chance
    334: 15,  # burnt area: little fuel left in the short term
    332: 5,   # bare rock: no continuous fuel (the data gives ~23 only through shrinkage to the mean)
}
FUEL_DEFAULT_BY_DIGIT = {1: 10, 2: 40, 3: 20, 4: 5, 5: 0}   # 1 urban, 2 agriculture, 3 natural, ...

# Fallback used ONLY when there is a CORINE file but no burnt-area file to derive scores from.
# Tune with a fire ecologist.
FUEL_FALLBACK = {
    333: 75, 321: 75,            # sparse vegetation, natural grassland
    223: 65, 242: 65,            # olive groves, complex cultivation
    243: 55, 231: 50, 323: 50,   # agriculture with vegetation, pastures, maquis
    322: 40,                     # heathland
    324: 25, 311: 25,            # transitional woodland, broadleaf forest
    **MANUAL_FUEL,
}

CLC_NAMES = {
    111: "Continuous urban", 112: "Urban fabric", 121: "Industrial / commercial",
    131: "Mines", 132: "Dump sites", 133: "Construction sites", 141: "Green urban areas",
    142: "Sport and leisure", 211: "Arable land", 221: "Vineyards", 222: "Fruit orchards",
    223: "Olive groves", 231: "Pastures", 241: "Annual + permanent crops",
    242: "Complex cultivation", 243: "Agriculture with natural vegetation",
    311: "Broadleaf forest", 312: "Conifer forest", 313: "Mixed forest",
    321: "Natural grassland", 322: "Heathland", 323: "Maquis / sclerophyllous scrub",
    324: "Transitional woodland-scrub", 331: "Beaches and dunes", 332: "Bare rock",
    333: "Sparse vegetation", 334: "Burnt area", 411: "Inland marsh", 512: "Water bodies",
}

# Distance caps for "closer = riskier" factors
POWER_CAP_M = 2000
ROADS_CAP_M = 1000
SLOPE_MAX_DEG = 35
HISTORY_FULL_AT = 0.5             # 50 % of the zone burned -> history score 100

SOUTHWEST_DEG = 202.5             # aspect with the most afternoon sun


# =========================================================================== #
# Helpers
# =========================================================================== #
def say(msg: str) -> None:
    print(msg, flush=True)


def find_file(name_or_list) -> Path | None:
    names = [name_or_list] if isinstance(name_or_list, str) else name_or_list
    for n in names:
        p = HERE / n
        if p.exists():
            return p
    return None


def union_all(gs):
    return gs.union_all() if hasattr(gs, "union_all") else gs.unary_union


def clean(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    bad = ~gdf.geometry.is_valid
    if bad.any():
        gdf.loc[bad, "geometry"] = gdf.loc[bad, "geometry"].buffer(0)
    return gdf


def read_metric(path: Path, assume_epsg: int = 4326) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)
    if gdf.crs is None:
        say(f"  ! {path.name} has no CRS, assuming EPSG:{assume_epsg}")
        gdf = gdf.set_crs(assume_epsg)
    return clean(gdf.to_crs(CRS_M))


def near_score(d: pd.Series, cap: float) -> pd.Series:
    """100 at distance 0, falling linearly to 0 at `cap` metres and beyond."""
    return 100 * (1 - d / cap).clip(0, 1)


def need_cols(df: pd.DataFrame, cols: list[str], where: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise SystemExit(f"{where} is missing columns {missing}.\nIt has: {df.columns.tolist()}")


# =========================================================================== #
# DEM -> EPSG:2100 @ 30 m -> aspect rasters
# =========================================================================== #
def prepare_dem(dem_path: Path, out_path: Path, res: float = 30.0) -> None:
    with rasterio.open(dem_path) as src:
        if src.crs is None:
            raise SystemExit(f"{dem_path.name} has no CRS; assign one in QGIS first.")
        dst_crs = f"EPSG:{CRS_M}"
        transform, w, h = calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds, resolution=res
        )
        dst = np.full((h, w), -9999, dtype="float32")
        reproject(
            source=rasterio.band(src, 1),
            destination=dst,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=src.nodata,
            dst_transform=transform,
            dst_crs=dst_crs,
            dst_nodata=-9999,
            resampling=Resampling.bilinear,
        )
    dst[dst < -500] = -9999
    profile = dict(driver="GTiff", dtype="float32", count=1, width=w, height=h,
                   crs=dst_crs, transform=transform, nodata=-9999, compress="deflate")
    with rasterio.open(out_path, "w", **profile) as out:
        out.write(dst, 1)
    say(f"  wrote {out_path.name}  ({w} x {h} px @ {res:.0f} m)")


def build_aspect_score(dem_path: Path, out_path: Path) -> None:
    """0-100 per pixel: 100 = faces SSW (hottest/driest), 0 = faces NNE. Flat pixels = 50."""
    with rasterio.open(dem_path) as src:
        z = src.read(1).astype("float32")
        profile = src.profile
        res = abs(src.res[0])
    z[z == -9999] = np.nan

    gy, gx = np.gradient(z, res)          # gy = change per row (rows go southwards)
    dz_north = -gy
    steep = np.hypot(gx, dz_north)        # rise / run
    # compass bearing of the DOWNSLOPE direction = the direction the slope faces
    aspect = (np.degrees(np.arctan2(-gx, -dz_north)) + 360) % 360
    score = (1 + np.cos(np.radians(aspect - SOUTHWEST_DEG))) / 2 * 100
    score[steep < np.tan(np.radians(2))] = 50        # flat: aspect is meaningless
    score[np.isnan(z) | np.isnan(steep)] = -9999

    profile.update(dtype="float32", nodata=-9999, compress="deflate")
    with rasterio.open(out_path, "w", **profile) as out:
        out.write(score.astype("float32"), 1)
    say(f"  wrote {out_path.name}")


def build_aspect_vec(dem_path: Path, out_path: Path) -> None:
    """2 bands: east and north component of the downslope direction (unit vectors, flat = 0).

    Averaging these vectors per zone gives the zone's dominant aspect without the
    359 deg / 1 deg wrap-around problem.
    """
    with rasterio.open(dem_path) as src:
        z = src.read(1).astype("float32")
        profile = src.profile
        res = abs(src.res[0])
    z[z == -9999] = np.nan

    gy, gx = np.gradient(z, res)
    east, north = -gx, gy                 # downslope direction (rows run southwards)
    steep = np.hypot(gx, gy)
    ok = steep >= np.tan(np.radians(2))
    with np.errstate(invalid="ignore", divide="ignore"):
        e = np.where(ok, east / steep, 0.0).astype("float32")
        n = np.where(ok, north / steep, 0.0).astype("float32")
    bad = np.isnan(z) | np.isnan(steep)
    e[bad] = -9999
    n[bad] = -9999

    profile.update(count=2, dtype="float32", nodata=-9999, compress="deflate")
    with rasterio.open(out_path, "w", **profile) as out:
        out.write(e, 1)
        out.write(n, 2)
    say(f"  wrote {out_path.name}")


def zonal_mean(geoms: gpd.GeoSeries, raster: Path, band: int = 1) -> pd.Series:
    stats = zonal_stats(list(geoms), str(raster), stats=["mean"], nodata=-9999,
                        all_touched=True, band=band)
    return pd.Series([s["mean"] for s in stats], index=geoms.index, dtype="float64")


# =========================================================================== #
# Fuel from CORINE
# =========================================================================== #
def find_clc() -> Path | None:
    if CLC_FILE:
        p = HERE / CLC_FILE
        return p if p.exists() else None
    for p in sorted((HERE / "data").iterdir()):
        n = p.name.lower()
        if p.suffix.lower() in (".gpkg", ".geojson", ".json", ".shp") and (
            "clc" in n or "corine" in n or n.startswith("u2018")
        ):
            return p
    return None


def fuel_for(code, table: dict[int, int]) -> float:
    """Fuel score for one CORINE code: the table value, else the default for its first digit."""
    if pd.isna(code):
        return 20.0
    code = int(code)
    return float(table.get(code, FUEL_DEFAULT_BY_DIGIT.get(code // 100, 20)))


def fuel_scores(forests: gpd.GeoDataFrame, clc_path: Path, table: dict[int, int]):
    """Overlay CORINE on the zones.

    Returns ``(fuel, top, pieces)``: the area-weighted fuel score per zone, the dominant
    class per zone, and the zone/class intersection pieces (reused to re-score fuel later).
    """
    file_crs = pyogrio.read_info(clc_path)["crs"]
    area = gpd.GeoSeries([box(*forests.total_bounds).buffer(5000)], crs=CRS_M).to_crs(file_crs)
    clc = gpd.read_file(clc_path, bbox=tuple(area.total_bounds))
    say(f"  CORINE columns: {clc.columns.tolist()}")
    code_col = next((c for c in clc.columns
                     if c.lower() in ("code_12", "code_18", "code18", "clc_code", "code")), None)
    if code_col is None:
        raise SystemExit("Could not find the CORINE code column; set it by hand in fuel_scores().")
    if clc.crs is None:
        clc = clc.set_crs(4326)
    clc = clc.to_crs(CRS_M)
    minx, miny, maxx, maxy = forests.total_bounds
    clc = clean(clc.cx[minx:maxx, miny:maxy][[code_col, "geometry"]])
    clc["code"] = pd.to_numeric(clc[code_col], errors="coerce")
    clc["fuel"] = clc["code"].map(lambda c: fuel_for(c, table))

    x = gpd.overlay(forests[["_id", "geometry"]], clc[["code", "fuel", "geometry"]],
                    how="intersection", keep_geom_type=True)
    x["a"] = x.area
    x["aw"] = x["a"] * x["fuel"]
    g = x.groupby("_id")
    result = forests["_id"].map(g["aw"].sum() / g["a"].sum())

    share = x.groupby("code")["a"].sum().sort_values(ascending=False)
    share = (share / share.sum() * 100).round(1)
    say("  land-cover share inside forest zones (CORINE code: %):")
    say("    " + ", ".join(f"{int(c)}: {v}" for c, v in share.head(8).items()))

    # dominant class per zone (by area) and its share of the zone
    by = x.groupby(["_id", "code"])["a"].sum().reset_index()
    by["pct"] = by["a"] / by.groupby("_id")["a"].transform("sum") * 100
    top = by.sort_values("a", ascending=False).drop_duplicates("_id").set_index("_id")
    return result, top, x


def burn_rate_by_class(pieces: gpd.GeoDataFrame, burnt_fit: gpd.GeoDataFrame) -> pd.DataFrame:
    """Share of each CORINE class's area (inside forest zones) burned by fit-period fires."""
    one = gpd.GeoDataFrame(geometry=[union_all(burnt_fit.geometry)], crs=CRS_M)
    hit = gpd.overlay(pieces[["code", "geometry"]], one, how="intersection", keep_geom_type=True)
    total = pieces.assign(a=pieces.area).groupby("code")["a"].sum()
    burned = hit.assign(a=hit.area).groupby("code")["a"].sum()
    out = pd.DataFrame({"area_km2": total / 1e6,
                        "burned_pct": burned.reindex(total.index).fillna(0) / total * 100})
    overall = burned.sum() / total.sum() * 100
    out["ratio_to_mean"] = out["burned_pct"] / overall if overall > 0 else 1.0
    return out.sort_values("ratio_to_mean", ascending=False).round(2)


def fuel_from_burn_rates(tbl: pd.DataFrame, k_km2: float = 50.0, min_km2: float = MIN_CLASS_KM2) -> dict:
    """ratio_to_mean -> 0-100 (ratio 1 -> 50, ratio 2 -> 100).

    Classes smaller than `min_km2` are dropped (the caller falls back to FUEL_DEFAULT_BY_DIGIT).
    The rest are pulled toward 'average' (ratio 1) in proportion to how small they are.
    """
    tbl = tbl[tbl["area_km2"] >= min_km2]
    w = tbl["area_km2"] / (tbl["area_km2"] + k_km2)        # trust grows with area
    ratio = w * tbl["ratio_to_mean"] + (1 - w) * 1.0
    return (50 * ratio).clip(0, 100).round(0).astype(int).to_dict()


# =========================================================================== #
# Fire history
# =========================================================================== #
def burned_fraction(forests: gpd.GeoDataFrame, burnt_union) -> pd.Series:
    if burnt_union is None or burnt_union.is_empty:
        return pd.Series(0.0, index=forests.index)
    one = gpd.GeoDataFrame(geometry=[burnt_union], crs=CRS_M)
    x = gpd.overlay(forests[["_id", "geometry"]], one, how="intersection", keep_geom_type=True)
    area = x.area.groupby(x["_id"]).sum()
    return (forests["_id"].map(area).fillna(0) / forests.area).clip(0, 1)


# =========================================================================== #
# Main
# =========================================================================== #
def main() -> None:
    # ---- load zones ------------------------------------------------------- #
    say("1/6 Loading forest zones")
    fpath = HERE / FOREST_IN
    if not fpath.exists():
        raise SystemExit(f"{FOREST_IN} not found next to the script.")
    forests = read_metric(fpath).reset_index(drop=True)
    forests["_id"] = forests.index
    need_cols(forests, ["mean_slope", "dist_power_m", "dist_roads_m", "is_wui"], FOREST_IN)
    if "static_risk_score" in forests.columns:
        forests["old_score"] = forests["static_risk_score"]
    say(f"  {len(forests)} zones")

    # ---- elevation + aspect ---------------------------------------------- #
    say("2/6 Elevation and aspect")
    dem_src = find_file(DEM_CANDIDATES)
    dem_2100, aspect_tif = HERE / "dem_2100.tif", HERE / "aspect_score.tif"
    aspect_vec = HERE / "aspect_vec.tif"
    if dem_src is None:
        say("  ! no DEM found - skipping aspect and elevation (aspect weight is re-spread)")
        forests["f_aspect"] = np.nan
        forests["elev_m"] = np.nan
        forests["aspect_deg"] = np.nan
        forests["aspect_str"] = np.nan
    else:
        if not dem_2100.exists():
            prepare_dem(dem_src, dem_2100)
        if not aspect_tif.exists():
            build_aspect_score(dem_2100, aspect_tif)
        if not aspect_vec.exists():
            build_aspect_vec(dem_2100, aspect_vec)
        forests["f_aspect"] = zonal_mean(forests.geometry, aspect_tif)
        forests["elev_m"] = zonal_mean(forests.geometry, dem_2100)
        east = zonal_mean(forests.geometry, aspect_vec, 1)
        north = zonal_mean(forests.geometry, aspect_vec, 2)
        forests["aspect_deg"] = (np.degrees(np.arctan2(east, north)) + 360) % 360
        forests["aspect_str"] = np.hypot(east, north)   # 1 = one clear direction, ~0 = mixed or flat

    # ---- fuel -------------------------------------------------------------- #
    say("3/6 Fuel (CORINE)")
    clc_path = find_clc()
    pieces = None
    fuel_table: dict[int, int] | None = None
    if clc_path is None:
        say("  ! no CORINE file found - running WITHOUT fuel (weights re-normalised).")
        forests["f_fuel"] = np.nan
        forests["dominant_clc"] = None
        forests["dominant_clc_pct"] = np.nan
    else:
        say(f"  using {clc_path.name}")
        fuel_table = FUEL_FALLBACK
        forests["f_fuel"], top, pieces = fuel_scores(forests, clc_path, fuel_table)
        forests["dominant_clc"] = forests["_id"].map(
            top["code"].map(lambda c: CLC_NAMES.get(int(c), f"CORINE {int(c)}")))
        forests["dominant_clc_pct"] = forests["_id"].map(top["pct"])

    # ---- fire history ------------------------------------------------------ #
    say("4/6 Fire history")
    bpath = HERE / BURNT_FILE
    burnt = None
    if not bpath.exists():
        say(f"  ! {BURNT_FILE} not found - skipping fire history")
        forests["f_history"] = np.nan
    else:
        burnt = read_metric(bpath)
        try:
            burnt["year"], _, col = parse_fire_dates(burnt)
        except ValueError as exc:
            raise SystemExit(f"{BURNT_FILE}: {exc}")
        say(f"  using burnt-area column '{col}'")
        say("  fires per year: " + ", ".join(
            f"{int(y)}:{n}" for y, n in burnt["year"].value_counts().sort_index().items()))
        train = burnt[burnt["year"] <= TRAIN_END]
        frac_train = burned_fraction(forests, union_all(train.geometry) if len(train) else None)
        forests["f_history"] = (frac_train / HISTORY_FULL_AT * 100).clip(0, 100)

        fit = burnt[(burnt["year"] > FIT_AFTER_YEAR) & (burnt["year"] <= TRAIN_END)]
        if pieces is not None and len(fit):
            tbl = burn_rate_by_class(pieces, fit)
            fuel_table = {**fuel_from_burn_rates(tbl), **MANUAL_FUEL}
            say("  burn rate per land-cover class (fit period only):")
            say("    " + tbl.to_string().replace("\n", "\n    "))
            say(f"  fuel scores derived from fit-period burn rates (+ manual overrides): {fuel_table}")
            pieces["fuel"] = pieces["code"].map(lambda c: fuel_for(c, fuel_table))
            aw = (pieces.area * pieces["fuel"]).groupby(pieces["_id"]).sum()
            a = pieces.area.groupby(pieces["_id"]).sum()
            forests["f_fuel"] = forests["_id"].map(aw / a)
        elif pieces is not None:
            say(f"  ! no fires between {FIT_AFTER_YEAR + 1} and {TRAIN_END}; using FUEL_FALLBACK scores")

    # ---- simple factors ---------------------------------------------------- #
    forests["f_slope"] = (forests["mean_slope"] / SLOPE_MAX_DEG).clip(0, 1) * 100
    forests["f_power"] = near_score(forests["dist_power_m"], POWER_CAP_M)
    forests["f_roads"] = near_score(forests["dist_roads_m"], ROADS_CAP_M)
    wui = forests["is_wui"].astype(str).str.lower().isin(["1", "1.0", "true", "yes", "t"])
    forests["f_wui"] = wui.astype(float) * 100
    say("  zones sitting at the maximum score (100) per factor:")
    for c in ("f_power", "f_roads", "f_wui"):
        say(f"    {c:<8} {(forests[c] >= 99.9).mean() * 100:.0f}%")
    say(f"  zones at 0 m from power: {(forests['dist_power_m'] < 1).mean() * 100:.0f}%, "
        f"from roads: {(forests['dist_roads_m'] < 1).mean() * 100:.0f}%")

    # ---- combine ------------------------------------------------------------ #
    say("5/6 Combining")
    active = [k for k in WEIGHTS if forests[f"f_{k}"].notna().any()]
    dropped = [k for k in WEIGHTS if k not in active]
    total = sum(WEIGHTS[k] for k in active)
    weights = {k: round(WEIGHTS[k] / total, 4) for k in active}
    if dropped:
        say(f"  factors skipped: {dropped}; weights re-normalised to {weights}")

    cols = [f"f_{k}" for k in active]
    say("  missing values per factor (filled with the median):")
    say("    " + forests[cols].isna().sum().to_string().replace("\n", "\n    "))
    forests[cols] = forests[cols].fillna(forests[cols].median())

    forests["static_risk_score"] = sum(weights[k] * forests[f"f_{k}"] for k in active)
    breaks = np.percentile(forests["static_risk_score"], [20, 40, 60, 80]).round(1).tolist()
    say(f"  class breaks (20/40/60/80th percentile): {breaks}")

    say("  factor correlations (|r| > 0.6 means the two partly double count):")
    say("    " + forests[cols].corr().round(2).to_string().replace("\n", "\n    "))

    # ---- validation on later fires ------------------------------------------ #
    say("6/6 Validation (fires after %d)" % TRAIN_END)
    validation = None
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import roc_auc_score

        if burnt is None:
            raise RuntimeError("no burnt-area file")
        test = burnt[burnt["year"] > TRAIN_END]
        label = (burned_fraction(forests, union_all(test.geometry) if len(test) else None)
                 >= BURNED_MIN_FRAC).astype(int)
        n_pos = int(label.sum())
        say(f"  {n_pos} of {len(label)} zones burned after {TRAIN_END}")
        if n_pos < 20 or n_pos > len(label) - 20:
            say("  too few positives or negatives for a meaningful AUC - skipped")
        else:
            auc_new = roc_auc_score(label, forests["static_risk_score"])
            say(f"  AUC new model : {auc_new:.3f}")
            auc_old = None
            if "old_score" in forests:
                auc_old = roc_auc_score(label, forests["old_score"])
                say(f"  AUC old model : {auc_old:.3f}")
            say("  AUC per factor (0.5 = no signal, <0.5 = works backwards):")
            auc_factors = {}
            for c in cols:
                auc_factors[c] = round(roc_auc_score(label, forests[c]), 2)
                say(f"    {c:<10} {auc_factors[c]:.3f}")
            validation = {
                "n_zones": int(len(label)),
                "n_positive": n_pos,
                "min_burned_frac": BURNED_MIN_FRAC,
                "auc_model": round(auc_new, 2),
                "auc_previous": None if auc_old is None else round(auc_old, 2),
                "auc_factors": auc_factors,
            }
            lr = LogisticRegression(class_weight="balanced", max_iter=1000).fit(forests[cols], label)
            coef = pd.Series(lr.coef_[0], index=cols).clip(lower=0)
            if coef.sum() > 0:
                say("  data-driven weights (logistic regression, for comparison only):")
                say("    " + (coef / coef.sum()).round(2).to_string().replace("\n", "\n    "))
    except Exception as exc:
        say(f"  validation skipped ({type(exc).__name__}): {exc}")

    # ---- write -------------------------------------------------------------- #
    out = forests.drop(columns=["_id"]).to_crs(4326)
    round_cols = cols + ["static_risk_score", "elev_m", "aspect_deg", "aspect_str", "dominant_clc_pct"]
    round_cols += ["old_score"] if "old_score" in out else []
    round_cols = [c for c in round_cols if c in out.columns]    # some are absent in the fallback paths
    out[round_cols] = out[round_cols].round(1)
    out.to_file(HERE / FOREST_OUT, driver="GeoJSON")

    model = {"weights": weights, "breaks": breaks, "train_end": TRAIN_END, "validation": validation}
    if fuel_table is not None:
        model["fuel_scores"] = {str(k): v for k, v in sorted(fuel_table.items())}
    (HERE / MODEL_OUT).write_text(json.dumps(model, indent=1))
    say(f"\nDone. Wrote {FOREST_OUT} and {MODEL_OUT}. Restart the API to pick them up.")


if __name__ == "__main__":
    main()
