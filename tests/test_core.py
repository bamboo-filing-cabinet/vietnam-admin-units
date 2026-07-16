from vn_admin_units.core import (wd_date, ref_s854, p31_target, predecessor_ends,
                                 P31_TARGETS, REFERENCE_URL)

def test_wd_date_is_day_precision_and_defensive():
    assert wd_date("2025-07-01") == "+2025-07-01T00:00:00Z/11"
    assert wd_date("2013-12-28 00:00:00") == "+2013-12-28T00:00:00Z/11"   # datetime tail stripped

def test_ref_is_s854():
    assert ref_s854("https://x") == 'S854\t"https://x"'

def test_p31_target_maps_by_loai_hinh():
    assert p31_target("Tỉnh") == P31_TARGETS["Tỉnh"]
    assert p31_target("Thành phố Trung ương") == P31_TARGETS["Thành phố Trung ương"]

def test_predecessor_ends_only_for_ending_relations():
    assert predecessor_ends("merged_into") and predecessor_ends("split")
    assert predecessor_ends("absorbed_into") and predecessor_ends("replaces")
    assert not predecessor_ends("carved_from")      # parent persists
    assert not predecessor_ends("renamed_to") and not predecessor_ends("retyped")
