from vn_admin_units.crosscheck_decrees import (
    decree_code,
    is_district_structural,
    is_ward_structural,
)


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


def test_ward_structural_accepts_explicit_commune_tier_mentions():
    assert is_ward_structural("Nghị quyết sắp xếp đơn vị hành chính cấp xã của tỉnh Cao Bằng")
    assert is_ward_structural("Thành lập phường mới và thị trấn mới")
    assert is_ward_structural("Điều chỉnh địa giới xã Tân Lập")
    assert is_ward_structural("Sắp xếp các đặc khu")


def test_ward_structural_does_not_match_district_type_thi_xa():
    assert not is_ward_structural("Thành lập thị xã La Gi")
    assert not is_ward_structural("Mở rộng   thị   xã Hà Đông")
    assert is_ward_structural("Thành lập thị xã và các phường trực thuộc")


from vn_admin_units.crosscheck_decrees import decree_index, decree_for

_RECORDS = [
    {"code": "897/NQ-UBTVQH14", "hieu_luc": "01/03/2020", "url": "https://vb/897",
     "noi_dung": "sắp xếp các đơn vị hành chính cấp huyện; nhập huyện Thông Nông vào huyện Hà Quảng"},
    {"code": "132/NQ-CP", "hieu_luc": "28/12/2013", "url": "https://vb/132",
     "noi_dung": "điều chỉnh địa giới hành chính huyện Từ Liêm để thành lập 02 quận"},
    {"code": "999/NQ-CP", "hieu_luc": "28/12/2013", "url": "https://vb/999",
     "noi_dung": "thành lập thị xã khác, không liên quan"},
    {"code": "133/NQ-CP", "hieu_luc": "30/12/2013", "url": "https://vb/133",
     "noi_dung": "thành lập thị xã Ngã Năm thuộc tỉnh Sóc Trăng"},
]

def test_decree_for_matches_source_name_via_alias_on_ambiguous_date():
    idx = decree_index(_RECORDS)
    assert decree_for(idx, "Quận Nam Từ Liêm", "2013-12-28",
                      aliases=["Huyện Từ Liêm"]) == ("132/NQ-CP", "https://vb/132")

def test_decree_for_matches_by_own_name_and_returns_url():
    idx = decree_index(_RECORDS)
    assert decree_for(idx, "Huyện Hà Quảng", "2020-03-01") == ("897/NQ-UBTVQH14", "https://vb/897")

def test_decree_for_single_candidate_falls_back_to_date_only():
    idx = decree_index(_RECORDS)
    assert decree_for(idx, "Thị xã Ngã Năm", "2013-12-30") == ("133/NQ-CP", "https://vb/133")

def test_decree_for_returns_empty_pair_when_ambiguous_and_no_name_hit():
    idx = decree_index(_RECORDS)
    assert decree_for(idx, "Huyện Không Có", "2013-12-28") == ("", "")


from vn_admin_units.crosscheck_decrees import decrees_naming

def test_decrees_naming_recovers_true_date_for_blank_successor_dissolve():
    recs = [
        {"code": "897/NQ-UBTVQH14", "hieu_luc": "01/03/2020", "url": "https://vb/897",
         "noi_dung": "nhập huyện Thông Nông vào huyện Hà Quảng"},               # district merge -> kept
        {"code": "111/NQ-CP", "hieu_luc": "10/01/2004", "url": "https://vb/111",
         "noi_dung": "thành lập xã Cần Nông thuộc huyện Thông Nông"},           # COMMUNE op -> excluded (F3)
    ]
    hits = decrees_naming(recs, "Huyện Thông Nông", years={2019, 2020})
    assert len(hits) == 1                                                      # the commune op is filtered out
    assert hits[0]["effective_date"] == "2020-03-01" and hits[0]["code"] == "897/NQ-UBTVQH14"
    assert hits[0]["url"] == "https://vb/897"

def test_decrees_naming_year_window_and_alias():
    recs = [{"code": "132/NQ-CP", "hieu_luc": "28/12/2013", "url": "https://vb/132",
             "noi_dung": "thành lập quận Nam Từ Liêm và quận Bắc Từ Liêm trên cơ sở huyện Từ Liêm"}]
    assert decrees_naming(recs, "Quận X", aliases=["Huyện Từ Liêm"], years={2013})
    assert decrees_naming(recs, "Huyện Từ Liêm", years={2020}) == []      # out of the year window
