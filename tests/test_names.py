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
    # fold is a comparison KEY: leading tier prefix stripped, alnum-only (no spaces)
    assert fold_district_name("Huyện Hà Quảng") == "haquang"
    assert fold_district_name("Quận Nam Từ Liêm") == "namtuliem"
    assert fold_district_name("Thị xã Ba Đồn") == "badon"
    assert fold_district_name("Thành phố Lai Châu") == "laichau"

def test_folds_tone_and_case_and_keeps_distinct():
    assert fold_district_name("Huyện Hoà Bình") == fold_district_name("huyện  hòa bình")
    assert fold_district_name("Huyện Đạ Tẻh") != fold_district_name("Huyện Đạ Huoai")

def test_strips_trailing_disambiguation_parenthetical():
    # the bulk-pull miss: WD labels carry a (tier)/(province) disambiguator the old fold kept
    assert fold_district_name("Đức Phổ (thị xã)") == fold_district_name("Thị xã Đức Phổ")
    assert fold_district_name("Đông Anh (huyện)") == fold_district_name("Huyện Đông Anh")
    assert fold_district_name("Tam Nông (Phú Thọ)") == fold_district_name("Huyện Tam Nông")

def test_normalizes_spacing_apostrophe_hyphen_variants():
    # the audit LABEL false-positives: same place, cosmetic separator differences
    assert fold_district_name("Đa Krông") == fold_district_name("Đakrông")
    assert fold_district_name("Krông A Na") == fold_district_name("Krông Ana")
    assert fold_district_name("Huyện KBang") == fold_district_name("K'Bang")
    assert fold_district_name("Ia H' Drai") == fold_district_name("Ia H'Drai")
    assert fold_district_name("Phan Rang-Tháp Chàm") == fold_district_name("Phan Rang - Tháp Chàm")
