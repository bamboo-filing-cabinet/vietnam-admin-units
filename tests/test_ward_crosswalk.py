from vn_admin_units.crosswalk import read_ward_crosswalk

# The probe window cached in Task 2 (a 2019 commune-merger-wave year).
PATH = "data/raw/crosswalk/ward_2019-01-01_2020-01-01.xls"


def test_reads_thousands_of_ward_rows():
    rows = read_ward_crosswalk(PATH)
    assert len(rows) > 9000          # ~11k national wards in 2019


def test_expected_normalized_keys_present():
    rows = read_ward_crosswalk(PATH)
    r = rows[0]
    for key in ("base_tinh", "base_ma", "base_ten", "succ_ma", "succ_hieu_luc", "ghi_chu"):
        assert key in r


def test_effective_dates_are_iso_or_blank():
    rows = read_ward_crosswalk(PATH)
    for r in rows:
        v = r["succ_hieu_luc"]
        assert v == "" or (len(v) == 10 and v[4] == "-" and v[7] == "-"), v


def test_codes_are_verbatim_strings_not_excel_floats():
    rows = read_ward_crosswalk(PATH)
    for r in rows:
        assert not r["base_ma"].endswith(".0")
        assert not r["succ_ma"].endswith(".0")


def test_ground_truth_2019_wave_row():
    # Xã Hòa Long → Phường Hòa Long (type upgrade), effective 2019-12-01;
    # derived mechanically from the cached window (plan Task 3 Step 6).
    rows = read_ward_crosswalk(PATH)
    r = next(x for x in rows if x["base_ma"] == "09214")
    assert r["base_ten"] == "Xã Hòa Long"
    assert r["succ_ma"] == "09214"
    assert r["succ_ten"] == "Phường Hòa Long"
    assert r["succ_hieu_luc"] == "2019-12-01"   # ISO, 2019
