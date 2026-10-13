"""Helpers used by both the API (main.py) and the build script (build_static_risk.py)."""
from __future__ import annotations

import pandas as pd

# Checked in this order. The first one present in the file wins.
DATE_COLUMNS = ("firedate", "initialdate", "fire_date", "date", "year", "lastupdate")


def parse_fire_dates(gdf: pd.DataFrame) -> tuple[pd.Series, pd.Series | None, str]:
    """Find the date or year column of a burnt-area file.

    Returns ``(years, dates, column_name)``. ``dates`` is a datetime Series, or ``None``
    when the file only has a plain year column. Raises ``ValueError`` if no column fits.
    """
    lower = {c.lower(): c for c in gdf.columns}
    for cand in DATE_COLUMNS:
        if cand not in lower:
            continue
        col = lower[cand]
        s = gdf[col]
        if pd.api.types.is_numeric_dtype(s) and s.dropna().between(1900, 2100).all():
            return s, None, col
        dates = pd.to_datetime(s, errors="coerce")
        return dates.dt.year, dates, col
    raise ValueError(f"No date or year column found. Columns: {list(gdf.columns)}")
