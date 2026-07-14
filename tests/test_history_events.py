from vn_admin_units.province_history import diff_roster
from vn_admin_units.cli import history_snapshot_dates


def test_history_snapshot_dates_span_2002_to_2025():
    dates = history_snapshot_dates()
    assert dates[0] == ("2002-01-01", "01/01/2002")
    assert ("2005-01-01", "01/01/2005") in dates
    assert ("2008-09-01", "01/09/2008") in dates          # post-Hà Tây boundary
    assert ("2025-06-30", "30/06/2025") in dates          # 1a pre-reform boundary
    assert ("2026-07-10", "10/07/2026") not in dates      # 2026 out of scope


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
