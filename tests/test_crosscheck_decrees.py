from vn_admin_units.crosscheck_decrees import decree_code, is_district_structural


def test_decree_code_extracts_core_from_crosswalk_string():
    assert decree_code("Số:  132/NQ-CP; Ngày: 27/12/2013") == "132/NQ-CP"
    assert decree_code("897/NQ-UBTVQH14") == "897/NQ-UBTVQH14"
    assert decree_code("") == ""


def test_district_structural_true_when_district_is_the_object():
    assert is_district_structural("Thành lập thành phố Thái Bình thuộc tỉnh Thái Bình")
    assert is_district_structural("Chia tách huyện Ayun Pa thành hai huyện Ia Pa và Ayun Pa, tỉnh Gia Lai")
    assert is_district_structural("Điều chỉnh địa giới hành chính mở rộng thị xã Ninh Bình")


def test_district_structural_false_for_ward_level_within_a_district():
    # a commune/ward created *within* a district — the district itself is unchanged
    assert not is_district_structural("Thành lập 5 xã thuộc các huyện Cái Nước, Phú Tân")
    assert not is_district_structural("Nghị quyết sắp xếp đơn vị hành chính cấp xã của tỉnh Cao Bằng năm 2025")


def test_district_structural_false_for_province_tier():
    # central-government city is the province tier, not a district
    assert not is_district_structural("Về việc thành lập thành phố Huế trực thuộc trung ương")
