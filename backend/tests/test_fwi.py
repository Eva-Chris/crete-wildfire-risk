from fwi import calc_ffmc, calc_dmc, calc_dc, calc_isi, calc_bui, calc_fwi


def test_reference_day():
    f = calc_ffmc(17, 42, 25, 0, 85)
    m = calc_dmc(17, 42, 0, 6, 4)
    d = calc_dc(17, 0, 15, 4)
    i, b = calc_isi(f, 25), calc_bui(m, d)
    assert abs(f - 87.69) < 0.02 and abs(m - 8.55) < 0.02 and abs(d - 19.01) < 0.02
    assert abs(i - 10.85) < 0.02 and abs(b - 8.49) < 0.02 and abs(calc_fwi(i, b) - 10.10) < 0.02


def test_september_day_length():
    # official code uses 9.4 h for September; a wrong table value shifts DMC by ~0.1
    rk = calc_dmc(30, 30, 0, 50, 9) - 50
    assert abs(rk - 1.894 * 31.1 * 70 * 9.4e-4) < 1e-9
