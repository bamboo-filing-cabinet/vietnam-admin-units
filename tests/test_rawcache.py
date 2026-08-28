import json
import vn_admin_units.rawcache as rc


def test_save_raw_writes_bytes_and_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "RAW", tmp_path)
    monkeypatch.setattr(rc, "MANIFEST", tmp_path / "manifest.jsonl")
    dest = rc.save_raw("soap/x.xml", b"<hello/>", {"source_url": "http://e", "rows": 1})
    assert dest.read_bytes() == b"<hello/>"
    line = json.loads((tmp_path / "manifest.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert line["path"] == "soap/x.xml" and line["rows"] == 1
    assert len(line["sha256"]) == 64 and "retrieved_at" in line


def test_save_raw_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "RAW", tmp_path)
    monkeypatch.setattr(rc, "MANIFEST", tmp_path / "manifest.jsonl")
    rc.save_raw("soap/x.xml", b"<a/>", {"rows": 1})
    rc.save_raw("soap/x.xml", b"<b/>", {"rows": 2})   # re-run same path
    lines = (tmp_path / "manifest.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["rows"] == 2   # replaced, not duplicated


def test_raw_is_verified_detects_missing_or_corrupt_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "RAW", tmp_path)
    monkeypatch.setattr(rc, "MANIFEST", tmp_path / "manifest.jsonl")
    assert not rc.raw_is_verified("soap/x.xml")

    dest = rc.save_raw("soap/x.xml", b"<good/>", {"rows": 1})
    assert rc.raw_is_verified("soap/x.xml")

    dest.write_bytes(b"<corrupt/>")
    assert not rc.raw_is_verified("soap/x.xml")
