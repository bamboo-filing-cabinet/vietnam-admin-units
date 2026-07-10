from vn_admin_units.ghichu import parse_ghichu


def test_merge_two_provinces():
    gc = ("Sắp xếp toàn bộ diện tích tự nhiên, quy mô dân số của tỉnh Yên Bái "
          "và tỉnh Lào Cai thành tỉnh mới có tên gọi là tỉnh Lào Cai")
    r = parse_ghichu(gc)
    assert r["event"] == "merge"
    assert r["constituents"] == ["tỉnh Yên Bái", "tỉnh Lào Cai"]
    assert r["result"] == "tỉnh Lào Cai"


def test_three_way_merge():
    gc = ("Sắp xếp toàn bộ diện tích tự nhiên, quy mô dân số của tỉnh Vĩnh Phúc, "
          "tỉnh Hòa Bình và tỉnh Phú Thọ thành tỉnh mới có tên gọi là tỉnh Phú Thọ")
    r = parse_ghichu(gc)
    assert r["constituents"] == ["tỉnh Vĩnh Phúc", "tỉnh Hòa Bình", "tỉnh Phú Thọ"]
    assert r["result"] == "tỉnh Phú Thọ"


def test_unchanged():
    assert parse_ghichu("Giữ nguyên, không sắp xếp")["event"] == "unchanged"


def test_blank():
    assert parse_ghichu("")["event"] == "none"
