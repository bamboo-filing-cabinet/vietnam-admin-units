from vn_admin_units.crosswalk import read_province_crosswalk

def test_read_province_crosswalk():
    rows = read_province_crosswalk("data/raw/crosswalk/DoiChieu_Tinh_2025.xls")
    assert len(rows) == 63
    by_base = {r["base_ma"]: r for r in rows}
    # survivor with code change: old Lào Cai (10) -> new (15)
    assert by_base["10"]["succ_ma"] == "15"
    # absorbed province: Yên Bái (15) has blank successor, prose names the result
    assert by_base["15"]["succ_ma"] == ""
    assert "Lào Cai" in by_base["15"]["ghi_chu"]
