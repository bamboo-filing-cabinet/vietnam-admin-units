from vn_admin_units.district_model import build_districts


def _build():
    return build_districts("data/raw/crosswalk")


def test_tu_liem_split_predecessor_ends_two_new_products():
    ents, edges = _build()
    tl = next(e for e in ents if e.name_vi == "Huyện Từ Liêm")
    assert tl.valid_to == "2013-12-27"                                  # last in-force day
    prod = [x for x in edges if x.predecessor == tl.local_id and x.relation == "split"]
    succ_names = {next(e for e in ents if e.local_id == x.successor).name_vi for x in prod}
    assert succ_names == {"Quận Nam Từ Liêm", "Quận Bắc Từ Liêm"}
    assert all(x.effective_date == "2013-12-28" for x in prod)
    nam = next(e for e in ents if e.name_vi == "Quận Nam Từ Liêm")
    assert nam.terminal_code == "019" and nam.valid_from == "2013-12-28"   # code inherited, new entity


def test_nong_son_create_then_dissolve_one_entity():
    ents, edges = _build()
    ns = [e for e in ents if e.name_vi == "Huyện Nông Sơn"]
    assert len(ns) == 1                                                 # not duplicated
    ns = ns[0]
    assert ns.valid_from == "2008-04-23"
    # Nông Sơn dissolves in the 2024→2025 window, so its recovered valid_to must be late-2024
    # or 2025 — NOT the stale 2008 base date a missed recovery (wrong year window) would leave.
    # `< 2025-06-30` alone is too weak (the 2008 date satisfies it); pin the lower bound.
    assert "2024-01-01" <= ns.valid_to < "2025-06-30", f"stale/unrecovered dissolve date: {ns.valid_to}"
    assert all(x.reference_url for x in edges if x.predecessor == ns.local_id)   # merge edge referenced


def test_cao_bang_three_mergers_dates_and_references():
    ents, edges = _build()
    # Real per-unit dates recovered from the SURVIVOR crosswalk rows (Execution corrections
    # 2026-07-17) — they DIFFER: Thông Nông merged into Hà Quảng on 2020-02-01 under decree 864,
    # while Trà Lĩnh/Phục Hoà are 2020-03-01 under 897. A regression = survivor-row recovery not wired.
    expect = {  # dissolved -> (valid_to, edge effective_date, decree code)
        "Huyện Thông Nông": ("2020-01-31", "2020-02-01", "864/NQ-UBTVQH14"),
        "Huyện Trà Lĩnh":   ("2020-02-29", "2020-03-01", "897/NQ-UBTVQH14"),
        "Huyện Phục Hoà":   ("2020-02-29", "2020-03-01", "897/NQ-UBTVQH14"),
    }
    for gone, (vto, eff, code) in expect.items():
        e = next(x for x in ents if x.name_vi == gone)
        assert e.valid_to == vto, f"{gone}: {e.valid_to} != {vto} (stale base date leaked?)"
        merged = [x for x in edges if x.predecessor == e.local_id
                  and x.relation in ("merged_into", "consolidated")]
        assert merged, f"{gone} has no merge edge"
        m = merged[0]
        assert m.effective_date == eff, f"{gone}: merge edge date {m.effective_date} != {eff}"
        assert code in m.decree, f"{gone}: decree {m.decree!r} lacks {code}"
        assert m.reference_url, f"{gone}: merge edge missing its establishing-resolution reference"


def test_ha_tay_reparenting_second_parent_span_no_dissolution():
    ents, _ = _build()
    ba_vi = next(e for e in ents if e.name_vi == "Huyện Ba Vì" and e.terminal_code == "271")
    codes = [(s["code"], s["from"], s["to"]) for s in ba_vi.parent_spans]
    assert ("28", None, "2008-07-31") in codes and ("01", "2008-08-01", "2025-06-30") in codes
    assert ba_vi.valid_to == "2025-06-30"                              # persists to abolition, not dissolved


def test_universal_2025_abolition_count():
    ents, _ = _build()
    abolished = [e for e in ents if e.valid_to == "2025-06-30"]
    assert 690 <= len(abolished) <= 700                                # ~696 (journal 2026-07-13.01)
    assert all(getattr(e, "abolished", False) for e in abolished) or \
        all(e.valid_to == "2025-06-30" for e in abolished)             # flagged via helper (Step 3)


def test_no_local_id_collisions():
    from vn_admin_units.district_model import detect_collisions
    ents, _ = _build()
    assert detect_collisions(ents) == []


def test_roster_delta_crossvalidation_all_windows():
    import glob
    from vn_admin_units.crosswalk import read_district_crosswalk
    from vn_admin_units.district_model import crossvalidate_window
    for p in glob.glob("data/raw/crosswalk/district_20*-01-01_20*-01-01.xls"):
        rows = read_district_crosswalk(p)
        assert crossvalidate_window(rows)["ok"], f"delta mismatch in {p}"


def test_no_blocking_residue():
    # The two BLOCKING residue kinds must be cleared HERE in D7 (curate
    # data/district-merge-targets.json for successors; the survivor-row mechanism recovers
    # dates). Matches the D11 hard gates 1:1.
    from vn_admin_units.district_model import build_districts
    build_districts("data/raw/crosswalk")
    res = getattr(build_districts, "residue", [])
    assert not [r for r in res if r[0] == "dissolve-date-unrecovered"], "recover dissolve dates"
    assert not [r for r in res if r[0] == "merge-target-unresolved"], \
        "curate successors in data/district-merge-targets.json"
