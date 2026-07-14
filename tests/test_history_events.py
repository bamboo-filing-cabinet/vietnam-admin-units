from vn_admin_units.province_history import diff_roster


def test_diff_detects_retype_and_rename_not_orthography_or_renumber():
    # ADJACENT within-era snapshots (stable 2-digit codes). Huế = same code 46,
    # name+type change -> retype (SAME entity), NOT dissolve+create.
    a = [{"ma": "46", "ten": "Tỉnh Thừa Thiên Huế", "loai_hinh": "Tỉnh"},
         {"ma": "17", "ten": "Tỉnh Hòa Bình", "loai_hinh": "Tỉnh"}]
    b = [{"ma": "46", "ten": "Thành phố Huế", "loai_hinh": "Thành phố Trung ương"},
         {"ma": "17", "ten": "Tỉnh Hoà Bình", "loai_hinh": "Tỉnh"},      # tone-mark variant only
         {"ma": "93", "ten": "Tỉnh Hậu Giang", "loai_hinh": "Tỉnh"}]
    d = diff_roster(a, b)
    assert d["created"] == ["Tỉnh Hậu Giang"]
    assert [(x["from"], x["to"]) for x in d["retyped"]] == [("Tỉnh Thừa Thiên Huế", "Thành phố Huế")]
    assert d["dissolved"] == []                                    # Huế=retype (code 46); Hòa Bình=orthography
