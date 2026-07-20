from vn_admin_units.district_model import (
    unit_tier, classify_change, window_events,
    group_by_event, source_survives, resolve_merge_target,
)
from vn_admin_units.crosswalk import read_district_crosswalk

def test_unit_tier_longest_prefix():
    assert unit_tier("Thành phố Lai Châu") == "Thành phố"
    assert unit_tier("Thị xã Ba Đồn") == "Thị xã"
    assert unit_tier("Huyện Từ Liêm") == "Huyện" and unit_tier("Quận 9") == "Quận"

def _row(bt, bm, bn, st, sm, sn):
    return {"base_tinh": bt, "base_ma": bm, "base_ten": bn,
            "succ_tinh": st, "succ_ma": sm, "succ_ten": sn,
            "base_hieu_luc": "", "succ_hieu_luc": "2013-12-28",
            "succ_nghi_dinh": "", "ghi_chu": ""}

def test_classify_from_structured_columns():
    assert classify_change(_row("", "", "", "01", "021", "Quận Bắc Từ Liêm")) == "create"
    assert classify_change(_row("04", "044", "Huyện Thông Nông", "", "", "")) == "dissolve"
    assert classify_change(_row("28", "271", "Huyện Ba Vì", "01", "271", "Huyện Ba Vì")) == "reparent"
    assert classify_change(_row("14", "116", "Thị xã Sơn La", "14", "116", "Thành phố Sơn La")) == "retype"
    assert classify_change(_row("01", "019", "Huyện Từ Liêm", "01", "019", "Quận Nam Từ Liêm")) == "retype_rename"

def test_window_events_isolates_2013_changes_from_real_window():
    rows = read_district_crosswalk("data/raw/crosswalk/district_2013-01-01_2014-01-01.xls")
    ev = window_events(rows)
    assert len(ev) == 17                                    # journal 2026-07-13.02
    tl = [e for e in ev if e["code_from"] == "019" or e["code_to"] == "019"]
    assert tl and tl[0]["kind"] == "retype_rename" and tl[0]["eff_date"] == "2013-12-28"
    assert any(e["kind"] == "create" and e["code_to"] == "021" for e in ev)   # Bắc Từ Liêm

def test_group_by_event_buckets_same_date_and_province():
    ev = [{"eff_date": "2020-03-01", "tinh_to": "04", "tinh_from": "04", "code_to": "049"},
          {"eff_date": "2020-03-01", "tinh_to": "", "tinh_from": "04", "code_to": ""},
          {"eff_date": "2020-06-01", "tinh_to": "38", "tinh_from": "38", "code_to": "407"}]
    g = group_by_event(ev)
    assert len(g[("2020-03-01", "04")]) == 2 and len(g[("2020-06-01", "38")]) == 1

def test_discriminator_carve_vs_split():
    roster_next = {"quangtrach", "badon"}            # both survive -> Quảng Trạch persists = carve
    assert source_survives("Huyện Quảng Trạch", roster_next) is True
    roster_no_tu_liem = {"namtuliem", "bactuliem"}
    assert source_survives("Huyện Từ Liêm", roster_no_tu_liem) is False   # gone -> split

def test_resolve_merge_target_prefers_ghichu_then_survivor():
    ev = {"ghi_chu": "Nhập toàn bộ ... của huyện Thông Nông  vào huyện Hà Quảng",
          "name_from": "Huyện Thông Nông"}
    assert resolve_merge_target(ev, {"haquang": "041"}) == "041"    # target CODE via prose 'vào Y'
    ev2 = {"ghi_chu": "", "name_from": "Huyện Phục Hoà"}
    assert resolve_merge_target(ev2, {"quanghoa": "049"}) is None   # no prose target -> unresolved
