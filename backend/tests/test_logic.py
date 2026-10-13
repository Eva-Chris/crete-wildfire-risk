import numpy as np
import pandas as pd
import pytest

from common import parse_fire_dates
from stations import STATIONS, nearest_station_ids
import build_static_risk as B


def test_near_score_caps():
    s = B.near_score(pd.Series([0, 500, 1000, 5000]), 1000)
    assert s.tolist() == [100, 50, 0, 0]


def test_fuel_for_uses_table_then_digit_default():
    assert B.fuel_for(323, {323: 61}) == 61
    assert B.fuel_for(324, {}) == B.FUEL_DEFAULT_BY_DIGIT[3]     # forest/semi-natural default
    assert B.fuel_for(211, {}) == B.FUEL_DEFAULT_BY_DIGIT[2]     # agriculture default
    assert B.fuel_for(np.nan, {}) == 20


def test_fuel_from_burn_rates_shrinks_and_drops_small_classes():
    tbl = pd.DataFrame(
        {"area_km2": [1000, 1000, 2], "ratio_to_mean": [1.0, 2.0, 5.0]},
        index=[323, 333, 999],
    )
    out = B.fuel_from_burn_rates(tbl)
    assert 999 not in out                  # below MIN_CLASS_KM2: left to the digit default
    assert out[323] == 50                  # average burn rate -> 50
    assert 50 < out[333] <= 100            # higher than average, pulled slightly toward 50


def test_parse_fire_dates_year_column():
    years, dates, col = parse_fire_dates(pd.DataFrame({"Year": [2018, 2020]}))
    assert years.tolist() == [2018, 2020] and dates is None and col == "Year"


def test_parse_fire_dates_lastupdate_only():
    # this column used to work in the build script but not in the API
    years, dates, col = parse_fire_dates(pd.DataFrame({"LASTUPDATE": ["2019-07-01", "2022-08-15"]}))
    assert years.tolist() == [2019, 2022] and dates is not None and col == "LASTUPDATE"


def test_parse_fire_dates_missing_column():
    with pytest.raises(ValueError):
        parse_fire_dates(pd.DataFrame({"foo": [1]}))


def test_nearest_station():
    ids = nearest_station_ids([s["lon"] + 0.01 for s in STATIONS], [s["lat"] for s in STATIONS])
    assert ids.tolist() == [s["id"] for s in STATIONS]
