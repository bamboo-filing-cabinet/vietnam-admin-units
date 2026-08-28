import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

RAW = Path("data/raw")
MANIFEST = RAW / "manifest.jsonl"


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


def raw_is_verified(relpath: str) -> bool:
    """Whether a raw payload exists and matches its manifest size and SHA-256."""
    entry = manifest_entry(relpath)
    path = RAW / relpath
    if entry is None or not path.is_file():
        return False
    content = path.read_bytes()
    return (
        entry.get("bytes") == len(content)
        and entry.get("sha256") == hashlib.sha256(content).hexdigest()
    )


def save_raw(relpath: str, content: bytes, meta: dict) -> Path:
    """Write verbatim bytes to data/raw/<relpath>; upsert a provenance manifest
    line keyed on `path` (idempotent — re-running replaces, never duplicates)."""
    dest = RAW / relpath
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    entry = {
        "path": relpath,
        "sha256": hashlib.sha256(content).hexdigest(),
        "bytes": len(content),
        "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **meta,
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if MANIFEST.exists():
        for line in MANIFEST.read_text(encoding="utf-8").splitlines():
            if line.strip() and json.loads(line).get("path") != relpath:
                existing.append(line)
    existing.append(json.dumps(entry, ensure_ascii=False))
    MANIFEST.write_text("\n".join(existing) + "\n", encoding="utf-8")
    return dest
