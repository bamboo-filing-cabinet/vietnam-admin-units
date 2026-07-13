from vn_admin_units.crosswalk import read_district_crosswalk

PATH = "data/raw/crosswalk/Đối chiếu đơn vị hành chính cấp Huyện _ 01_01_2002 và 30_06_2025 .xls"


def test_reads_all_rows():
    rows = read_district_crosswalk(PATH)
    assert len(rows) == 713


def test_split_primary_row():
    # Huyện Từ Liêm (5-digit old code) -> Quận Nam Từ Liêm (3-digit new code),
    # the code-inheriting split primary; effective 2013-12-28.
    rows = read_district_crosswalk(PATH)
    tu_liem = next(r for r in rows if r["base_ma"] == "10121")
    assert tu_liem["base_ten"] == "Huyện Từ Liêm"
    assert tu_liem["succ_ma"] == "019"
    assert tu_liem["succ_ten"] == "Quận Nam Từ Liêm"
    assert tu_liem["succ_hieu_luc"] == "2013-12-28"  # Excel serial -> ISO date


def test_dissolved_row_has_blank_successor():
    rows = read_district_crosswalk(PATH)
    thong_nong = next(r for r in rows if r["base_ten"] == "Huyện Thông Nông")
    assert thong_nong["succ_ma"] == ""


def test_new_district_row_has_blank_base():
    # Quận Bắc Từ Liêm is the split sibling created 2013 — appears with no base side.
    rows = read_district_crosswalk(PATH)
    bac_tu_liem = next(r for r in rows if r["succ_ten"] == "Quận Bắc Từ Liêm")
    assert bac_tu_liem["base_ma"] == ""
    assert bac_tu_liem["succ_ma"] == "021"
