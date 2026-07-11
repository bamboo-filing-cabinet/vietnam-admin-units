from pathlib import Path
from vn_admin_units.soap import parse_rows, parse_rows_all, TIERS
from vn_admin_units.fetch import code_stats, duplicate_detail


def test_parse_rows_scopes_to_documentelement_and_extracts_fields():
    xml = Path("tests/fixtures/danhmucphuongxa_sample.xml").read_text(encoding="utf-8")
    fields = TIERS["ward"][1]
    rows = parse_rows(xml, fields)
    # 3 rows in DocumentElement; the diffgr:before stale row (99999) is ignored
    assert len(rows) == 3
    assert [r["MaPhuongXa"] for r in rows] == ["00004", "00008", "00004"]
    assert rows[0]["TenPhuongXa"] == "Phường Ba Đình"
    assert rows[0]["MaQuanHuyen"] == "001"
    assert "99999" not in [r["MaPhuongXa"] for r in rows]


def test_code_stats_counts_duplicates():
    xml = Path("tests/fixtures/danhmucphuongxa_sample.xml").read_text(encoding="utf-8")
    rows = parse_rows(xml, TIERS["ward"][1])
    st = code_stats(rows, "ward")
    assert st["rows"] == 3 and st["distinct"] == 2 and st["duplicates"] == 1
    assert "00004" in st["dup_codes"]


def test_duplicate_detail_flags_differing_fields():
    xml = Path("tests/fixtures/danhmucphuongxa_sample.xml").read_text(encoding="utf-8")
    rows_full = parse_rows_all(xml)                 # all fields per row
    detail = duplicate_detail(rows_full, "ward")
    assert "00004" in detail
    d = detail["00004"]
    # the two 00004 rows are different wards (different district/name), NOT identical
    assert d["count"] == 2 and d["identical"] is False
    assert "MaQuanHuyen" in d["differing_fields"]
    assert "TenPhuongXa" in d["differing_fields"]
