import gzip
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


def test_save_raw_gzip_is_deterministic_and_preserves_exact_content(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "RAW", tmp_path)
    monkeypatch.setattr(rc, "MANIFEST", tmp_path / "manifest.jsonl")
    content = b"<ward>exact source bytes</ward>" * 20

    first = rc.deterministic_gzip(content)
    second = rc.deterministic_gzip(content)
    assert first == second
    assert first[:4] == b"\x1f\x8b\x08\x00"
    assert first[4:8] == b"\0\0\0\0"
    assert gzip.decompress(first) == content

    dest = rc.save_raw_gzip("soap/x.xml.gz", content, {"rows": 20})
    entry = json.loads(rc.MANIFEST.read_text(encoding="utf-8"))
    assert dest.read_bytes() == first
    assert entry["storage_encoding"] == "gzip"
    assert entry["content_bytes"] == len(content)
    assert len(entry["content_sha256"]) == 64
    assert entry["compression_level"] == 9 and entry["compression_mtime"] == 0
    assert rc.raw_is_verified("soap/x.xml.gz")
    assert rc.read_raw("soap/x.xml.gz") == content


def test_migrate_raw_to_gzip_preserves_provenance_and_removes_plain_file(
        tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "RAW", tmp_path)
    monkeypatch.setattr(rc, "MANIFEST", tmp_path / "manifest.jsonl")
    content = b"<legacy/>"
    rc.save_raw("soap/x.xml", content, {
        "retrieved_at": "2025-01-02T03:04:05Z", "source_url": "https://example.test",
    })

    dest = rc.migrate_raw_to_gzip("soap/x.xml")

    assert dest == tmp_path / "soap/x.xml.gz"
    assert not (tmp_path / "soap/x.xml").exists()
    assert rc.read_raw("soap/x.xml.gz") == content
    lines = rc.MANIFEST.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["path"] == "soap/x.xml.gz"
    assert entry["retrieved_at"] == "2025-01-02T03:04:05Z"
    assert entry["source_url"] == "https://example.test"


def test_update_raw_metadata_preserves_integrity_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "RAW", tmp_path)
    monkeypatch.setattr(rc, "MANIFEST", tmp_path / "manifest.jsonl")
    rc.save_raw_gzip("soap/x.xml.gz", b"<source/>", {"rows": 1})
    before = rc.manifest_entry("soap/x.xml.gz")

    rc.update_raw_metadata("soap/x.xml.gz", {"rows": 2, "audit": "refined"})

    after = rc.manifest_entry("soap/x.xml.gz")
    for field in rc._ARTIFACT_FIELDS | {"retrieved_at"}:
        assert after.get(field) == before.get(field)
    assert after["rows"] == 2 and after["audit"] == "refined"

    try:
        rc.update_raw_metadata("soap/x.xml.gz", {"content_sha256": "bad"})
    except ValueError as exc:
        assert "integrity" in str(exc)
    else:
        raise AssertionError("integrity metadata was mutable")


def test_raw_is_verified_rejects_unknown_storage_encoding(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "RAW", tmp_path)
    monkeypatch.setattr(rc, "MANIFEST", tmp_path / "manifest.jsonl")
    rc.save_raw("soap/x.bin", b"source", {"storage_encoding": "unknown"})

    assert not rc.raw_is_verified("soap/x.bin")
