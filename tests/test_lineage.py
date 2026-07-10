from vn_admin_units.model import build_entities, build_lineage


def _rows():
    pre = [{"ma": "10", "ten": "Tỉnh Lào Cai", "loai_hinh": "Tỉnh"},
           {"ma": "15", "ten": "Tỉnh Yên Bái", "loai_hinh": "Tỉnh"}]
    post = [{"ma": "15", "ten": "Tỉnh Lào Cai", "loai_hinh": "Tỉnh"}]
    xwalk = [
        {"base_ma": "10", "base_ten": "Tỉnh Lào Cai", "succ_ma": "15", "succ_ten": "Tỉnh Lào Cai",
         "nghi_dinh": "Số: 202/2025/QH15; Ngày: 12/06/2025", "hieu_luc": "2025-07-01", "ghi_chu": ""},
        {"base_ma": "15", "base_ten": "Tỉnh Yên Bái", "succ_ma": "", "succ_ten": "",
         "nghi_dinh": "Số: 202/2025/QH15; Ngày: 12/06/2025", "hieu_luc": "2025-07-01",
         "ghi_chu": "Sắp xếp toàn bộ diện tích tự nhiên, quy mô dân số của tỉnh Yên Bái và tỉnh Lào Cai thành tỉnh mới có tên gọi là tỉnh Lào Cai"},
    ]
    return pre, post, xwalk


def test_lineage_primary_and_absorbed():
    pre, post, xwalk = _rows()
    ents = build_entities(pre, post)
    edges = build_lineage(ents, xwalk)
    prim = [e for e in edges if e.predecessor == "p-10-pre2025"]
    assert len(prim) == 1 and prim[0].successor == "p-15-post2025" and prim[0].primary is True
    yb = [e for e in edges if e.predecessor == "p-15-pre2025"]
    assert len(yb) == 1 and yb[0].successor == "p-15-post2025" and yb[0].primary is False
    assert yb[0].relation == "merged_into" and yb[0].decree.startswith("Số: 202/2025")
