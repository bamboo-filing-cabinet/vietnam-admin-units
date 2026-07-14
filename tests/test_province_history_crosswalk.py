from vn_admin_units.crosswalk import read_province_history_crosswalk


def test_reads_9col_and_isolates_ha_tay_merge():
    rows = read_province_history_crosswalk("tests/fixtures/province_2008_2009.xls")
    by_base = {r["base_ma"]: r for r in rows}
    # Hà Tây (28) dissolved, prose names the successor
    assert by_base["28"]["succ_ma"] == ""
    assert "Hà Nội" in by_base["28"]["ghi_chu"]           # "Sáp nhập vào Thành phố Hà Nội"
    # Hà Nội (01) is the surviving successor with the 2008-08-01 effective date
    han = by_base["01"]
    assert han["succ_ma"] == "01" and han["succ_hieu_luc"] == "2008-08-01"


def test_rows_expose_the_9_normalized_fields():
    rows = read_province_history_crosswalk("tests/fixtures/province_2008_2009.xls")
    assert all({"base_ma", "succ_ma", "succ_ten", "succ_hieu_luc", "ghi_chu"} <= set(r) for r in rows)
