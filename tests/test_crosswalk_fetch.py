from vn_admin_units import crosswalk_fetch as cf
from vn_admin_units import rawcache


def test_tier_config_all_supported_tiers():
    assert cf.TIER_CAP["province"] == "1"
    assert cf.TIER_CAP["district"] == "2"
    assert cf.TIER_CAP["ward"] == "3"


def test_cache_relpath_by_tier():
    assert cf.cache_relpath("province", "01/01/2004", "01/01/2005") \
        == "crosswalk/province_2004-01-01_2005-01-01.xls"
    assert cf.cache_relpath("district", "01/01/2013", "01/01/2014") \
        == "crosswalk/district_2013-01-01_2014-01-01.xls"


def test_yearly_windows():
    assert cf.yearly_windows(2004, 2005) == [("01/01/2004", "01/01/2005"),
                                             ("01/01/2005", "01/01/2006")]


def test_ward_source_closure_preflight_finds_eighteen_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(rawcache, "RAW", tmp_path)
    monkeypatch.setattr(rawcache, "MANIFEST", tmp_path / "manifest.jsonl")

    existing = (
        "crosswalk/ward_2002-01-01_2025-06-30.xls",
        "crosswalk/ward_2017-01-01_2018-01-01.xls",
        "crosswalk/ward_2019-01-01_2020-01-01.xls",
        "crosswalk/ward_2024-01-01_2025-01-01.xls",
        "crosswalk/ward_2025-06-30_2025-07-01.xls",
        "crosswalk/ward_2025-07-01_2026-08-27.xls",
    )
    for relpath in existing:
        rawcache.save_raw(relpath, relpath.encode(), {"rows": 1})

    report = cf.preflight("ward", cf.yearly_windows(2004, 2024))

    assert report["planned_count"] == 21
    assert report["verified_planned_count"] == 3
    assert report["missing_count"] == 18
    assert report["verified_tier_count"] == 6
    assert report["invalid_tier_paths"] == []
    assert report["missing_windows"][0] == ("01/01/2004", "01/01/2005")


def test_fetch_windows_skips_verified_files_without_launching_browser(monkeypatch):
    window = ("01/01/2019", "01/01/2020")
    relpath = "crosswalk/ward_2019-01-01_2020-01-01.xls"
    monkeypatch.setattr(
        rawcache,
        "raw_is_verified",
        lambda path: path == relpath,
    )
    monkeypatch.setattr(
        rawcache,
        "manifest_entry",
        lambda path: {"path": path, "rows": 10_000, "bytes": 1234},
    )

    assert cf.fetch_windows("ward", [window]) == [{
        "path": relpath,
        "rows": 10_000,
        "bytes": 1234,
        "status": "cached",
    }]


def test_fetch_with_retries_restarts_after_transient_failure(monkeypatch):
    calls = []
    sleeps = []

    def fake_fetch(tier, windows, headless=True, force=False):
        calls.append((tier, windows, headless, force))
        if len(calls) == 1:
            raise RuntimeError("download canceled")
        return [{"status": "fetched"}]

    monkeypatch.setattr(cf, "fetch_windows", fake_fetch)

    result = cf.fetch_with_retries(
        "ward",
        [("01/01/2004", "01/01/2005")],
        max_attempts=3,
        base_delay=0.25,
        sleeper=sleeps.append,
    )

    assert result == [{"status": "fetched"}]
    assert len(calls) == 2
    assert sleeps == [0.25]


def test_real_ward_source_closure_crosswalk_inventory_is_complete():
    report = cf.preflight("ward", cf.yearly_windows(2004, 2024))

    assert report["planned_count"] == 21
    assert report["verified_planned_count"] == 21
    assert report["missing_count"] == 0
    assert report["verified_tier_count"] == 24
    assert report["invalid_tier_paths"] == []
