from vn_admin_units.ghichu import parse_district_ghichu

def test_merge_names_source_and_target():
    p = parse_district_ghichu(
        "Nhập toàn bộ 357,38 km2 diện tích tự nhiên, 24.441 người của huyện Thông Nông  vào huyện Hà Quảng")
    assert p["event"] == "merge" and p["source"] == "Thông Nông" and p["target"] == "Hà Quảng"

def test_merge_target_only_when_no_source_clause():
    p = parse_district_ghichu("nhập vào huyện Quảng Uyên, thành lập huyện Quảng Hòa")
    assert p["event"] == "merge" and p["target"] == "Quảng Uyên"

def test_carve_names_source_stripping_cu():
    p = parse_district_ghichu("Chia tách từ huyện Quảng Trạch cũ")
    assert p["event"] == "carve" and p["source"] == "Quảng Trạch"

def test_establish_and_retype_and_rename():
    assert parse_district_ghichu(
        "thành lập thị xã Lai Châu trên cơ sở tự nhiên và dân số của thị trấn Phong Thổ")["event"] == "establish"
    assert parse_district_ghichu("Thay đổi loại hình")["event"] == "retype"
    assert parse_district_ghichu("Đổi tên huyện")["event"] == "rename"

def test_blank_is_none():
    assert parse_district_ghichu("")["event"] == "none"
