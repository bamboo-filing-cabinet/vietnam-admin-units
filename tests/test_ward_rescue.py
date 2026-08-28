import json
from datetime import date
from pathlib import Path

from vn_admin_units import rawcache
from vn_admin_units.ward_rescue import (
    SnapshotRequest,
    build_plan,
    cache_snapshot,
    roster_metrics,
)


def test_build_plan_prioritizes_critical_dates_and_adds_effective_dates():
    records = [
        {"code": "WARD/NQ", "hieu_luc": "01/01/2020",
         "noi_dung": "Sắp xếp đơn vị hành chính cấp xã"},
        {"code": "PROVINCE/NQ", "hieu_luc": "01/02/2020",
         "noi_dung": "Điều chỉnh địa giới tỉnh"},
        {"code": "BAD/NQ", "hieu_luc": "not-a-date", "noi_dung": "thành lập phường"},
    ]
    today = date(2026, 8, 27)
    plan = build_plan(records, "history", today)

    assert [item.snapshot_date for item in plan[:5]] == [
        date(2025, 6, 30), date(2025, 7, 1),
        date(2026, 4, 29), date(2026, 4, 30), today,
    ]
    by_date = {item.snapshot_date: item for item in plan}
    assert date(2019, 12, 31) not in by_date
    assert "effective event: WARD/NQ" in by_date[date(2020, 1, 1)].reasons
    assert "annual audit anchor" in by_date[date(2020, 1, 1)].reasons
    assert date(2020, 2, 1) not in by_date
    assert len(plan) == len({item.snapshot_date for item in plan})


def test_bracketed_history_adds_explicit_pre_event_dates():
    records = [{
        "code": "WARD/NQ", "hieu_luc": "02/01/2020",
        "noi_dung": "Sắp xếp đơn vị hành chính cấp xã",
    }]
    plan = build_plan(records, "history-bracketed", date(2026, 8, 27))
    by_date = {item.snapshot_date: item for item in plan}

    assert "pre-event: WARD/NQ" in by_date[date(2020, 1, 1)].reasons
    assert "effective event: WARD/NQ" in by_date[date(2020, 1, 2)].reasons


def test_cache_snapshot_retries_manifests_and_resumes(tmp_path, monkeypatch):
    monkeypatch.setattr(rawcache, "RAW", tmp_path)
    monkeypatch.setattr(rawcache, "MANIFEST", tmp_path / "manifest.jsonl")
    content = Path("tests/fixtures/danhmucphuongxa_sample.xml").read_bytes()
    calls = []
    sleeps = []

    def flaky_fetch(tier, dmy, timeout):
        calls.append((tier, dmy, timeout))
        if len(calls) == 1:
            raise OSError("temporary outage")
        return content

    request = SnapshotRequest(date(2025, 6, 30), ("critical test",))
    assert cache_snapshot(
        request, max_attempts=2, base_delay=0.25, timeout=9,
        fetcher=flaky_fetch, sleeper=sleeps.append,
    ) == "fetched"
    assert calls == [("ward", "30/06/2025", 9), ("ward", "30/06/2025", 9)]
    assert sleeps == [0.25]
    assert rawcache.raw_is_verified(request.relpath)

    entry = json.loads(rawcache.MANIFEST.read_text(encoding="utf-8"))
    assert entry["method"] == "DanhMucPhuongXa"
    assert entry["params"] == {"DenNgay": "30/06/2025", "Tinh": "", "QuanHuyen": ""}
    assert entry["rows"] == 3 and entry["distinct_codes"] == 2
    assert entry["distinct_identity_keys"] == 3
    assert entry["duplicate_identity_rows"] == 0
    assert entry["duplicate_rows"] == 0
    assert entry["conflicting_identity_rows"] == 0
    assert entry["missing_parent_codes"] == 0 and entry["parent_pairs"] == 2
    assert entry["reasons"] == ["critical test"]

    def must_not_fetch(*args, **kwargs):
        raise AssertionError("verified payload should be resumed without a network call")

    assert cache_snapshot(request, fetcher=must_not_fetch) == "cached"


def test_cache_snapshot_rejects_empty_soap_response(tmp_path, monkeypatch):
    monkeypatch.setattr(rawcache, "RAW", tmp_path)
    monkeypatch.setattr(rawcache, "MANIFEST", tmp_path / "manifest.jsonl")
    request = SnapshotRequest(date(2025, 7, 1), ("empty test",))

    try:
        cache_snapshot(request, max_attempts=1, fetcher=lambda *args, **kwargs: b"<xml/>")
    except RuntimeError as exc:
        assert "no ward rows" in str(exc)
    else:
        raise AssertionError("empty SOAP response was accepted")

    assert not rawcache.raw_is_verified(request.relpath)


def test_cache_snapshot_migrates_verified_plain_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(rawcache, "RAW", tmp_path)
    monkeypatch.setattr(rawcache, "MANIFEST", tmp_path / "manifest.jsonl")
    request = SnapshotRequest(date(2025, 6, 30), ("migration test",))
    content = Path("tests/fixtures/danhmucphuongxa_sample.xml").read_bytes()
    rawcache.save_raw(request.legacy_relpath, content, {
        "retrieved_at": "2026-08-28T01:06:32Z", "rows": 3,
    })

    assert cache_snapshot(
        request, fetcher=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("migration should not fetch"))
    ) == "compressed"
    assert not (tmp_path / request.legacy_relpath).exists()
    assert rawcache.read_raw(request.relpath) == content


def test_roster_metrics_separates_exact_duplicates_from_identity_conflicts():
    base = {
        "MaTinh": "70", "TenTinh": "Tỉnh X", "MaQuanHuyen": "694",
        "TenQuanHuyen": "Huyện Y", "MaPhuongXa": "7070901",
        "TenPhuongXa": "Thị trấn An Lộc", "LoaiHinh": "Thị trấn",
    }
    exact_duplicate = dict(base)
    conflicting_type = {**base, "LoaiHinh": "Phường"}
    other = {**base, "MaPhuongXa": "7070902", "TenPhuongXa": "Xã Khác"}

    metrics = roster_metrics([base, exact_duplicate, conflicting_type, other])

    assert metrics == {
        "rows": 4,
        "distinct_codes": 2,
        "distinct_identity_keys": 2,
        "duplicate_identity_rows": 2,
        "duplicate_rows": 1,
        "conflicting_identity_rows": 1,
        "missing_parent_codes": 0,
        "parent_pairs": 1,
    }
