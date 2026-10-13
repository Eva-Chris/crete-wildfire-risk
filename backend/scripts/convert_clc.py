#!/usr/bin/env python3
"""One-off: convert the CORINE Land Cover 2012 geodatabase to a GeoPackage.

Download U2018_CLC2012_V2020_20u1 from the Copernicus Land Monitoring Service
(https://land.copernicus.eu/), unzip it into backend/data/, then run from backend/:

    python scripts/convert_clc.py
"""
import geopandas as gpd
import pyogrio

GDB = "data/U2018_CLC2012_V2020_20u1.gdb"
OUT = "data/clc2012.gpkg"

layers = pyogrio.list_layers(GDB)
print("layers:", layers)
layer = layers[0][0]            # change this if the geodatabase has more than one layer
print("reading", layer)
gpd.read_file(GDB, layer=layer).to_file(OUT, driver="GPKG")
print("wrote", OUT)
