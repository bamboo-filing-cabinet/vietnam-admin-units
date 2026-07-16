from vn_admin_units.names import fold_name


def test_tone_mark_variants_fold_equal():
    assert fold_name("Tỉnh Hòa Bình") == fold_name("Tỉnh Hoà Bình")


def test_strips_tier_prefix_and_lowercases():
    assert fold_name("Thành phố Cần Thơ") == fold_name("thành phố  cần thơ")
    assert fold_name("Tỉnh Lào Cai") == "lao cai"


def test_distinct_names_stay_distinct():
    assert fold_name("Tỉnh Lai Châu") != fold_name("Tỉnh Điện Biên")


from vn_admin_units.names import fold_district_name

def test_strips_all_four_district_prefixes():
    assert fold_district_name("Huyện Hà Quảng") == "ha quang"
    assert fold_district_name("Quận Nam Từ Liêm") == "nam tu liem"
    assert fold_district_name("Thị xã Ba Đồn") == "ba don"
    assert fold_district_name("Thành phố Lai Châu") == "lai chau"

def test_folds_tone_and_case_and_keeps_distinct():
    assert fold_district_name("Huyện Hoà Bình") == fold_district_name("huyện  hòa bình")
    assert fold_district_name("Huyện Đạ Tẻh") != fold_district_name("Huyện Đạ Huoai")
