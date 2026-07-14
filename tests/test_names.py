from vn_admin_units.names import fold_name


def test_tone_mark_variants_fold_equal():
    assert fold_name("Tỉnh Hòa Bình") == fold_name("Tỉnh Hoà Bình")


def test_strips_tier_prefix_and_lowercases():
    assert fold_name("Thành phố Cần Thơ") == fold_name("thành phố  cần thơ")
    assert fold_name("Tỉnh Lào Cai") == "lao cai"


def test_distinct_names_stay_distinct():
    assert fold_name("Tỉnh Lai Châu") != fold_name("Tỉnh Điện Biên")
