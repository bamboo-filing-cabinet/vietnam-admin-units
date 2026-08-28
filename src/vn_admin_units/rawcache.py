import gzip
import hashlib
import io
import json
import zlib
from datetime import datetime, timezone
from pathlib import Path

RAW = Path("data/raw")
MANIFEST = RAW / "manifest.jsonl"

_ARTIFACT_FIELDS = {
    "path", "sha256", "bytes", "storage_encoding", "content_sha256",
    "content_bytes", "compression_level", "compression_mtime",
}


def manifest_entry(relpath: str) -> dict | None:
    """Return the manifest entry for ``relpath``, if one exists."""
    if not MANIFEST.exists():
        return None
    found = None
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entry = json.loads(line)
            if entry.get("path") == relpath:
                found = entry
    return found


def _verified_content(relpath: str) -> bytes | None:
    """Return exact source bytes when both the artifact and content verify."""
    entry = manifest_entry(relpath)
    path = RAW / relpath
    if entry is None or not path.is_file():
        return None
    artifact = path.read_bytes()
    if (
        entry.get("bytes") != len(artifact)
        or entry.get("sha256") != hashlib.sha256(artifact).hexdigest()
    ):
        return None
    encoding = entry.get("storage_encoding")
    if encoding is None:
        return artifact
    if encoding != "gzip":
        return None
    try:
        content = gzip.decompress(artifact)
    except (EOFError, OSError, zlib.error):
        return None
    if (
        entry.get("content_bytes") != len(content)
        or entry.get("content_sha256") != hashlib.sha256(content).hexdigest()
    ):
        return None
    return content


def raw_is_verified(relpath: str) -> bool:
    """Whether a raw artifact and its exact decoded source bytes both verify."""
    return _verified_content(relpath) is not None


def read_raw(relpath: str) -> bytes:
    """Read verified exact source bytes, transparently decoding stored gzip."""
    content = _verified_content(relpath)
    if content is None:
        raise ValueError(f"raw payload is missing or failed verification: {relpath}")
    return content


def deterministic_gzip(content: bytes, compresslevel: int = 9) -> bytes:
    """Return filename-free gzip bytes with a fixed zero modification time."""
    output = io.BytesIO()
    with gzip.GzipFile(
        filename="", mode="wb", fileobj=output,
        compresslevel=compresslevel, mtime=0,
    ) as stream:
        stream.write(content)
    return output.getvalue()


def _upsert_manifest(entry: dict) -> None:
    relpath = entry["path"]
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if MANIFEST.exists():
        for line in MANIFEST.read_text(encoding="utf-8").splitlines():
            if line.strip() and json.loads(line).get("path") != relpath:
                existing.append(line)
    existing.append(json.dumps(entry, ensure_ascii=False))
    temporary = MANIFEST.with_name(f".{MANIFEST.name}.tmp")
    temporary.write_text("\n".join(existing) + "\n", encoding="utf-8")
    temporary.replace(MANIFEST)


def _save_artifact(relpath: str, artifact: bytes, meta: dict) -> Path:
    overlap = {"path", "sha256", "bytes"}.intersection(meta)
    if overlap:
        raise ValueError(f"metadata cannot replace artifact fields: {sorted(overlap)}")
    dest = RAW / relpath
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_name(f".{dest.name}.tmp")
    temporary.write_bytes(artifact)
    temporary.replace(dest)
    entry = {
        "path": relpath,
        "sha256": hashlib.sha256(artifact).hexdigest(),
        "bytes": len(artifact),
        "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **meta,
    }
    _upsert_manifest(entry)
    return dest


def save_raw(relpath: str, content: bytes, meta: dict) -> Path:
    """Write verbatim bytes to data/raw/<relpath>; upsert a provenance manifest
    line keyed on `path` (idempotent — re-running replaces, never duplicates)."""
    return _save_artifact(relpath, content, meta)


def save_raw_gzip(relpath: str, content: bytes, meta: dict,
                  compresslevel: int = 9) -> Path:
    """Store exact source bytes in a deterministic, lossless gzip wrapper.

    The manifest hashes both the stored artifact and the decoded source content,
    allowing compact Git storage without weakening byte-level provenance.
    """
    overlap = _ARTIFACT_FIELDS.intersection(meta)
    if overlap:
        raise ValueError(f"metadata cannot replace gzip integrity fields: {sorted(overlap)}")
    artifact = deterministic_gzip(content, compresslevel)
    return _save_artifact(relpath, artifact, {
        "storage_encoding": "gzip",
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "content_bytes": len(content),
        "compression_level": compresslevel,
        "compression_mtime": 0,
        **meta,
    })


def migrate_raw_to_gzip(relpath: str) -> Path:
    """Losslessly replace one verified plain artifact with ``<relpath>.gz``."""
    if relpath.endswith(".gz"):
        raise ValueError(f"already a gzip path: {relpath}")
    entry = manifest_entry(relpath)
    content = _verified_content(relpath)
    if entry is None or content is None:
        raise ValueError(f"cannot migrate unverified raw payload: {relpath}")
    meta = {key: value for key, value in entry.items() if key not in _ARTIFACT_FIELDS}
    compressed_relpath = f"{relpath}.gz"
    dest = save_raw_gzip(compressed_relpath, content, meta)
    if not raw_is_verified(compressed_relpath):
        raise RuntimeError(f"compressed payload failed verification: {compressed_relpath}")

    (RAW / relpath).unlink()
    remaining = []
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if line.strip() and json.loads(line).get("path") != relpath:
            remaining.append(line)
    temporary = MANIFEST.with_name(f".{MANIFEST.name}.tmp")
    temporary.write_text("\n".join(remaining) + "\n", encoding="utf-8")
    temporary.replace(MANIFEST)
    return dest


def update_raw_metadata(relpath: str, meta: dict) -> None:
    """Update descriptive metadata without changing verified integrity fields."""
    entry = manifest_entry(relpath)
    if entry is None or not raw_is_verified(relpath):
        raise ValueError(f"cannot update unverified raw payload: {relpath}")
    reserved = _ARTIFACT_FIELDS | {"retrieved_at"}
    overlap = reserved.intersection(meta)
    if overlap:
        raise ValueError(f"cannot replace raw integrity/provenance fields: {sorted(overlap)}")
    _upsert_manifest({**entry, **meta})
