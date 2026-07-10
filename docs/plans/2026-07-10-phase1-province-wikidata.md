# Phase 1 — Province-tier 2025-reform Wikidata correction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the full admin-units pipeline end-to-end on the province tier (63 pre-reform → 34 post-reform), producing a referenced Wikidata QuickStatements batch that encodes the 2025 province reform (inception/dissolution/lineage + fixes), validated to 100% against the known 63→34 outcome.

**Architecture:** A small Python package that (1) ingests province snapshots from the GSO SOAP service and the Đối Chiếu crosswalk Excel, (2) parses the `Ghi Chú` prose into structured merge events, (3) builds `entities` + `observations` + `lineage` records (new-entity-per-reform + lineage per `DESIGN.md`), (4) reconciles entities to Wikidata QIDs, (5) emits QuickStatements v2. Data is the product; code regenerates it. Raw inputs are committed as fixtures for reproducibility and tests.

**Tech Stack:** Python 3.11+, `uv`; `pandas` + `xlrd` (read `.xls`); stdlib `urllib` (SOAP + WD API); `pytest`. Matches `vietnam-elections-wikidata` conventions.

**Read first:** `docs/DESIGN.md` (decisions log), journals `2026-07-10.02` (SOAP contract), `.04`/`.06` (crosswalk + Excel schema), `.08` (WD identity), `.09` (province Ghi Chú), `.10` (change taxonomy).

---

## File Structure

- `pyproject.toml` — uv project + deps + pytest config.
- `src/vn_admin_units/__init__.py`
- `src/vn_admin_units/rawcache.py` — save exact source bytes + append provenance manifest.
- `src/vn_admin_units/soap.py` — GSO SOAP client (`DanhMucTinh`) + diffgram parser.
- `src/vn_admin_units/crosswalk.py` — read Đối Chiếu province `.xls` → rows.
- `src/vn_admin_units/ghichu.py` — parse `Ghi Chú` → structured events.
- `src/vn_admin_units/model.py` — `Entity`/`Observation`/`LineageEdge` + builders.
- `src/vn_admin_units/reconcile.py` — entity → Wikidata QID (province level).
- `src/vn_admin_units/emit.py` — QuickStatements v2 generation.
- `src/vn_admin_units/cli.py` — wire ingest→build→reconcile→emit.
- `data/raw/` — **exact source bytes + provenance** (decided 2026-07-10):
  - `data/raw/soap/DanhMucTinh_{iso}.xml` — verbatim SOAP responses
  - `data/raw/crosswalk/DoiChieu_Tinh_2025.xls` — verbatim crosswalk download
  - `data/raw/manifest.jsonl` — one JSON line per raw file (source URL, params, retrieved-at, sha256, rows)
- `data/` — **normalized/derived**: `provinces-{iso}.json` (parsed snapshots), `entities.json`, `lineage.json`.
- `mappings/provinces-qid.csv` — curated + reconciled `(gso_code, era) → QID`.
- `statements/na-provinces-2025.qs` — emitted batch.
- `tests/` — one test module per source module; fixtures in `tests/fixtures/`.

Boundary dates for Phase 1 (province snapshots): `30/06/2025` (pre-reform, 63) and `10/07/2026` (current, 34). Đồng Nai's 2026-04-30 city upgrade is an attribute change on the post-reform entity, not a separate entity.

---

## Task 0: Scaffold the uv project

**Files:**
- Create: `pyproject.toml`, `src/vn_admin_units/__init__.py`, `tests/__init__.py`, `tests/fixtures/.gitkeep`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "vn-admin-units"
version = "0.1.0"
description = "Time-versioned Vietnam administrative-unit gazetteer, reconciled to Wikidata"
requires-python = ">=3.11"
dependencies = ["pandas>=2.0", "xlrd>=2.0"]

[dependency-groups]
dev = ["pytest>=8.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 2: Create package + test init files**

```python
# src/vn_admin_units/__init__.py
"""Time-versioned Vietnam administrative-unit gazetteer."""
```
```python
# tests/__init__.py
```
Also create empty `tests/fixtures/.gitkeep`.

- [ ] **Step 3: Sync and verify**

Run: `uv sync && uv run pytest -q`
Expected: pytest runs, "no tests ran" (exit 5) or 0 collected — no import errors.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml src/ tests/ uv.lock
git commit -m "chore: scaffold uv project for vn-admin-units"
```

---

## Task 1: SOAP client — `DanhMucTinh` + diffgram parser

**Files:**
- Create: `src/vn_admin_units/soap.py`, `tests/test_soap.py`, `tests/fixtures/danhmuctinh_sample.xml`

- [ ] **Step 1: Write the fixture** (`tests/fixtures/danhmuctinh_sample.xml`) — a trimmed real diffgram (2 rows):

```xml
<?xml version="1.0" encoding="utf-8"?><soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body><DanhMucTinhResponse xmlns="http://tempuri.org/"><DanhMucTinhResult><diffgr:diffgram xmlns:msdata="urn:schemas-microsoft-com:xml-msdata" xmlns:diffgr="urn:schemas-microsoft-com:xml-diffgram-v1"><DocumentElement xmlns=""><TABLE diffgr:id="TABLE1"><MaTinh>15</MaTinh><TenTinh>Tỉnh Lào Cai</TenTinh><LoaiHinh>Tỉnh</LoaiHinh></TABLE><TABLE diffgr:id="TABLE2"><MaTinh>01</MaTinh><TenTinh>Thành phố Hà Nội</TenTinh><LoaiHinh>Thành phố Trung ương</LoaiHinh></TABLE></DocumentElement></diffgr:diffgram></DanhMucTinhResult></DanhMucTinhResponse></soap:Body></soap:Envelope>
```

- [ ] **Step 2: Write the failing test** (`tests/test_soap.py`)

```python
from pathlib import Path
from vn_admin_units.soap import parse_province_diffgram

def test_parse_province_diffgram():
    xml = Path("tests/fixtures/danhmuctinh_sample.xml").read_text(encoding="utf-8")
    rows = parse_province_diffgram(xml)
    assert rows == [
        {"ma": "15", "ten": "Tỉnh Lào Cai", "loai_hinh": "Tỉnh"},
        {"ma": "01", "ten": "Thành phố Hà Nội", "loai_hinh": "Thành phố Trung ương"},
    ]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_soap.py -q`
Expected: FAIL — `ModuleNotFoundError: vn_admin_units.soap`.

- [ ] **Step 4: Implement `soap.py`**

```python
import re
import urllib.request

URL = "https://danhmuchanhchinh.nso.gov.vn/DMDVHC.asmx"
NS = "http://tempuri.org/"

def parse_province_diffgram(xml: str) -> list[dict]:
    """Extract province rows from a DanhMucTinh SOAP diffgram response.

    Scoped to the current-state <DocumentElement>; any <diffgr:before> block is
    ignored (.02 confirmed reads return a single DocumentElement, no before-block —
    this guard prevents double-counting if that ever changes)."""
    m = re.search(r"<DocumentElement\b[^>]*>(.*?)</DocumentElement>", xml, re.S)
    scope = m.group(1) if m else xml
    rows = []
    for block in re.findall(r"<TABLE\b[^>]*>(.*?)</TABLE>", scope, re.S):
        def field(name: str) -> str:
            m = re.search(rf"<{name}>(.*?)</{name}>", block)
            return m.group(1) if m else ""
        rows.append({
            "ma": field("MaTinh"),
            "ten": field("TenTinh"),
            "loai_hinh": field("LoaiHinh"),
        })
    return rows

def fetch_provinces(den_ngay: str, timeout: int = 90) -> list[dict]:
    """Call DanhMucTinh for an as-of date (dd/mm/yyyy). Live network call."""
    env = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        f'<soap:Body><DanhMucTinh xmlns="{NS}"><DenNgay>{den_ngay}</DenNgay>'
        "</DanhMucTinh></soap:Body></soap:Envelope>"
    )
    req = urllib.request.Request(
        URL, data=env.encode("utf-8"),
        headers={"Content-Type": "text/xml; charset=utf-8",
                 "SOAPAction": f'"{NS}DanhMucTinh"'},
    )
    return parse_province_diffgram(urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8"))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_soap.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/vn_admin_units/soap.py tests/test_soap.py tests/fixtures/danhmuctinh_sample.xml
git commit -m "feat: SOAP DanhMucTinh client + diffgram parser"
```

---

## Task 2: Raw cache (verbatim + manifest) + derived snapshots

Storage policy (decided 2026-07-10): `data/raw/` holds **exact source bytes** +
`manifest.jsonl` provenance; `data/` holds the **parsed/derived** JSON. This task
builds the manifest helper, saves the verbatim SOAP responses, and emits the
derived snapshot JSON.

**Files:**
- Create: `src/vn_admin_units/rawcache.py`, `tests/test_rawcache.py`, `src/vn_admin_units/cli.py`
- Modify: `src/vn_admin_units/soap.py` (add `fetch_provinces_raw`)
- Produces: `data/raw/soap/DanhMucTinh_{iso}.xml`, `data/raw/manifest.jsonl`, `data/provinces-{iso}.json`

- [ ] **Step 1: Write the failing test** (`tests/test_rawcache.py`)

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_rawcache.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `rawcache.py`**

```python
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

RAW = Path("data/raw")
MANIFEST = RAW / "manifest.jsonl"

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_rawcache.py -q`
Expected: PASS.

- [ ] **Step 5: Add `fetch_provinces_raw` to `soap.py`** (return the verbatim response so raw can be stored before parsing)

```python
def fetch_provinces_raw(den_ngay: str, timeout: int = 90) -> str:
    """Return the verbatim DanhMucTinh SOAP XML response for an as-of date (dd/mm/yyyy)."""
    env = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        f'<soap:Body><DanhMucTinh xmlns="{NS}"><DenNgay>{den_ngay}</DenNgay>'
        "</DanhMucTinh></soap:Body></soap:Envelope>"
    )
    req = urllib.request.Request(
        URL, data=env.encode("utf-8"),
        headers={"Content-Type": "text/xml; charset=utf-8",
                 "SOAPAction": f'"{NS}DanhMucTinh"'},
    )
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8")
```

Then simplify `fetch_provinces` to `return parse_province_diffgram(fetch_provinces_raw(den_ngay, timeout))`. Re-run `uv run pytest tests/test_soap.py -q` — still PASS.

- [ ] **Step 6: Write `cache_snapshots` in `cli.py`** (verbatim XML → raw + manifest; parsed → derived)

```python
import json
from pathlib import Path
from vn_admin_units.soap import fetch_provinces_raw, parse_province_diffgram
from vn_admin_units.rawcache import save_raw

BOUNDARY_DATES = {"2025-06-30": "30/06/2025", "2026-07-10": "10/07/2026"}
SOAP_URL = "https://danhmuchanhchinh.nso.gov.vn/DMDVHC.asmx"
DATA = Path("data")

def cache_snapshots() -> None:
    DATA.mkdir(exist_ok=True)
    for iso, ddmmyyyy in BOUNDARY_DATES.items():
        xml = fetch_provinces_raw(ddmmyyyy)
        rows = parse_province_diffgram(xml)
        save_raw(f"soap/DanhMucTinh_{iso}.xml", xml.encode("utf-8"),
                 {"source_url": SOAP_URL, "method": "DanhMucTinh",
                  "params": {"DenNgay": ddmmyyyy}, "rows": len(rows)})
        (DATA / f"provinces-{iso}.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"cached {len(rows)} provinces @ {iso}")

if __name__ == "__main__":
    cache_snapshots()
```

- [ ] **Step 7: Run it live to produce the cache**

Run: `uv run python -m vn_admin_units.cli`
Expected: `cached 63 provinces @ 2025-06-30` and `cached 34 provinces @ 2026-07-10`. Verify: `data/raw/soap/` has 2 `.xml` files, `data/raw/manifest.jsonl` has 2 lines with 64-char sha256 + `rows` 63/34, and `data/provinces-*.json` exist.

- [ ] **Step 8: Commit**

```bash
git add src/vn_admin_units/rawcache.py tests/test_rawcache.py src/vn_admin_units/soap.py src/vn_admin_units/cli.py data/raw/soap/ data/raw/manifest.jsonl data/provinces-2025-06-30.json data/provinces-2026-07-10.json
git commit -m "feat: raw cache (verbatim SOAP + manifest) + derived snapshots"
```

---

## Task 3: Crosswalk Excel reader

**Files:**
- Create: `src/vn_admin_units/crosswalk.py`, `tests/test_crosswalk.py`, `data/raw/crosswalk/DoiChieu_Tinh_2025.xls` (verbatim copy of the province export from `~/Downloads/Đối chiếu đơn vị hành chính cấp Tỉnh _ 30_06_2025 và 10_07_2026.xls`)

- [ ] **Step 1: Copy the verbatim crosswalk export into the raw cache + record provenance**

```bash
mkdir -p data/raw/crosswalk
cp "$HOME/Downloads/Đối chiếu đơn vị hành chính cấp Tỉnh _ 30_06_2025 và 10_07_2026.xls" data/raw/crosswalk/DoiChieu_Tinh_2025.xls
```

Then append a manifest line (the crosswalk was downloaded via the `Doi_Chieu_Moi.aspx` Excel export, not a scriptable URL, so record params by hand):

```bash
uv run python -c "from vn_admin_units.rawcache import save_raw; from pathlib import Path; save_raw('crosswalk/DoiChieu_Tinh_2025.xls', Path('data/raw/crosswalk/DoiChieu_Tinh_2025.xls').read_bytes(), {'source_url':'https://danhmuchanhchinh.nso.gov.vn/Doi_Chieu_Moi.aspx','method':'Excel export','params':{'Cap':'Tỉnh','base':'30/06/2025','compare':'10/07/2026'},'rows':63})"
```

Note: this rewrites the file identically (same bytes) and appends one manifest line — verify `data/raw/manifest.jsonl` now has the crosswalk entry with a 64-char sha256.

- [ ] **Step 2: Write the failing test** (`tests/test_crosswalk.py`)

```python
from vn_admin_units.crosswalk import read_province_crosswalk

def test_read_province_crosswalk():
    rows = read_province_crosswalk("data/raw/crosswalk/DoiChieu_Tinh_2025.xls")
    assert len(rows) == 63
    by_base = {r["base_ma"]: r for r in rows}
    # survivor with code change: old Lào Cai (10) -> new (15)
    assert by_base["10"]["succ_ma"] == "15"
    # absorbed province: Yên Bái (15) has blank successor, prose names the result
    assert by_base["15"]["succ_ma"] == ""
    assert "Lào Cai" in by_base["15"]["ghi_chu"]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_crosswalk.py -q`
Expected: FAIL — module missing.

- [ ] **Step 4: Implement `crosswalk.py`**

```python
import pandas as pd

_COLS = {
    "Tỉnh": "base_ma", "Tên Tỉnh": "base_ten",
    "Nghị định": "nghi_dinh", "Ngày hiệu lực": "hieu_luc",
    "Tên Tỉnh ĐC": "succ_ten", "Tỉnh ĐC": "succ_ma",
    "Ghi Chú": "ghi_chu",
}

def _code(v: str) -> str:
    """Normalize a province code to 2-digit zero-padded (guards Excel numeric coercion)."""
    v = str(v).strip()
    if v.endswith(".0"):        # numeric cell coerced to "1.0"
        v = v[:-2]
    return v.zfill(2) if v.isdigit() else v

def read_province_crosswalk(path: str) -> list[dict]:
    """Read the Đối Chiếu province .xls export into normalized rows."""
    df = pd.read_excel(path, engine="xlrd", dtype=str).fillna("")
    out = []
    for _, r in df.iterrows():
        row = {dest: str(r.get(src, "")).strip() for src, dest in _COLS.items()}
        row["base_ma"] = _code(row["base_ma"])
        row["succ_ma"] = _code(row["succ_ma"]) if row["succ_ma"] else ""
        out.append(row)
    return out
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_crosswalk.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/vn_admin_units/crosswalk.py tests/test_crosswalk.py data/raw/crosswalk/DoiChieu_Tinh_2025.xls data/raw/manifest.jsonl
git commit -m "feat: province crosswalk Excel reader + verbatim raw + manifest"
```

---

## Task 4: Ghi Chú parser

**Files:**
- Create: `src/vn_admin_units/ghichu.py`, `tests/test_ghichu.py`

Event types (from taxonomy `.10`): `merge` (hợp nhất/sắp xếp…thành…mới), `unchanged` (giữ nguyên), `establish` (thành lập…đặc khu/thành phố), `other`.

- [ ] **Step 1: Write the failing test** (`tests/test_ghichu.py`)

```python
from vn_admin_units.ghichu import parse_ghichu

def test_merge_two_provinces():
    gc = ("Sắp xếp toàn bộ diện tích tự nhiên, quy mô dân số của tỉnh Yên Bái "
          "và tỉnh Lào Cai thành tỉnh mới có tên gọi là tỉnh Lào Cai")
    r = parse_ghichu(gc)
    assert r["event"] == "merge"
    assert r["constituents"] == ["tỉnh Yên Bái", "tỉnh Lào Cai"]
    assert r["result"] == "tỉnh Lào Cai"

def test_three_way_merge():
    gc = ("Sắp xếp toàn bộ diện tích tự nhiên, quy mô dân số của tỉnh Vĩnh Phúc, "
          "tỉnh Hòa Bình và tỉnh Phú Thọ thành tỉnh mới có tên gọi là tỉnh Phú Thọ")
    r = parse_ghichu(gc)
    assert r["constituents"] == ["tỉnh Vĩnh Phúc", "tỉnh Hòa Bình", "tỉnh Phú Thọ"]
    assert r["result"] == "tỉnh Phú Thọ"

def test_unchanged():
    assert parse_ghichu("Giữ nguyên, không sắp xếp")["event"] == "unchanged"

def test_blank():
    assert parse_ghichu("")["event"] == "none"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ghichu.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `ghichu.py`**

```python
import re
import unicodedata

_MERGE = re.compile(
    r"của\s+(?P<parts>.+?)\s+thành\s+(?:tỉnh|thành phố)\s+mới\s+có tên gọi là\s+(?P<result>.+)",
    re.IGNORECASE,
)
_SPLIT_PARTS = re.compile(r",\s*|\s+và\s+")

def _norm(s: str) -> str:
    """Normalize whitespace/newlines; keep diacritics (NFC)."""
    return unicodedata.normalize("NFC", re.sub(r"\s+", " ", s)).strip()

def parse_ghichu(text: str) -> dict:
    """Classify a Ghi Chú string and extract merge constituents + result."""
    t = _norm(text)
    if not t:
        return {"event": "none", "constituents": [], "result": None}
    if "giữ nguyên" in t.lower():
        return {"event": "unchanged", "constituents": [], "result": None}
    m = _MERGE.search(t)
    if m and ("sắp xếp" in t.lower() or "hợp nhất" in t.lower()):
        parts = [p.strip().rstrip(".") for p in _SPLIT_PARTS.split(m.group("parts")) if p.strip()]
        return {"event": "merge", "constituents": parts, "result": m.group("result").strip().rstrip(".")}
    if t.lower().startswith("thành lập"):
        return {"event": "establish", "constituents": [], "result": None}
    return {"event": "other", "constituents": [], "result": None}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ghichu.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/vn_admin_units/ghichu.py tests/test_ghichu.py
git commit -m "feat: Ghi Chú parser (merge/unchanged/establish)"
```

---

## Task 5: Data model types

**Files:**
- Create: `src/vn_admin_units/model.py`, `tests/test_model.py`

- [ ] **Step 1: Write the failing test** (`tests/test_model.py`)

```python
from vn_admin_units.model import Entity, LineageEdge, local_id

def test_local_id_is_code_era_stable():
    assert local_id("15", "post2025") == "p-15-post2025"
    # same code, different era -> distinct ids (code reuse safety)
    assert local_id("15", "pre2025") != local_id("15", "post2025")

def test_entity_roundtrip():
    e = Entity(local_id="p-15-post2025", gso_code="15", era="post2025",
               name_vi="Tỉnh Lào Cai", loai_hinh="Tỉnh",
               valid_from="2025-07-01", valid_to=None, wikidata_qid=None)
    assert e.to_dict()["local_id"] == "p-15-post2025"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_model.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `model.py`**

```python
from dataclasses import dataclass, asdict
from typing import Optional

def local_id(gso_code: str, era: str) -> str:
    """Stable repo-owned id, keyed on (code, era) since codes are reused."""
    return f"p-{gso_code}-{era}"

@dataclass
class Entity:
    local_id: str
    gso_code: str
    era: str            # "pre2025" | "post2025"
    name_vi: str
    loai_hinh: str
    valid_from: Optional[str]
    valid_to: Optional[str]
    wikidata_qid: Optional[str]
    qid_status: Optional[str] = None   # "existing" | "new" — set during reconcile; gates P571
    def to_dict(self) -> dict:
        return asdict(self)

@dataclass
class LineageEdge:
    predecessor: str    # local_id
    successor: str      # local_id
    relation: str       # "merged_into" | "replaces" | "renamed_to" | "split_from"
    share: str          # "whole" | "partial"
    primary: bool       # True if predecessor is the code-inheriting/renamed-from primary
    decree: str
    effective_date: str
    def to_dict(self) -> dict:
        return asdict(self)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_model.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vn_admin_units/model.py tests/test_model.py
git commit -m "feat: entity + lineage model types"
```

---

## Task 6: Build entities from snapshots

**Files:**
- Modify: `src/vn_admin_units/model.py`
- Test: `tests/test_build_entities.py`

> **Known Phase-1 debt (per DESIGN §Temporal scope):** `build_entities` hard-codes
> the 2025 reform date (`valid_to="2025-06-30"` / `valid_from="2025-07-01"`) and a
> two-value `era` (`pre2025`/`post2025`) embedded in `local_id`. The full model is
> generic dated records spanning 2002→present. Before Phase 1b, parameterize the
> reform date/era (e.g. `build_entities(pre, post, boundary, era_pre, era_post)`);
> a later hop (2008, 2004) will otherwise require reworking `local_id` and any
> `data/` a downstream consumes. Acceptable for Phase 1; **do not treat the era
> encoding as schema-final.**

- [ ] **Step 1: Write the failing test** (`tests/test_build_entities.py`)

```python
from vn_admin_units.model import build_entities

def test_build_entities_counts():
    pre = [{"ma": "15", "ten": "Tỉnh Yên Bái", "loai_hinh": "Tỉnh"}]
    post = [{"ma": "15", "ten": "Tỉnh Lào Cai", "loai_hinh": "Tỉnh"}]
    ents = build_entities(pre, post)
    ids = {e.local_id for e in ents}
    assert ids == {"p-15-pre2025", "p-15-post2025"}
    post_e = next(e for e in ents if e.era == "post2025")
    assert post_e.name_vi == "Tỉnh Lào Cai"
    assert post_e.valid_from == "2025-07-01"
    pre_e = next(e for e in ents if e.era == "pre2025")
    assert pre_e.valid_to == "2025-06-30"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_build_entities.py -q`
Expected: FAIL — `build_entities` not defined.

- [ ] **Step 3: Add `build_entities` to `model.py`**

```python
def build_entities(pre_rows: list[dict], post_rows: list[dict]) -> list["Entity"]:
    """One entity per (code, era). Pre-reform entities end at the reform date."""
    ents = []
    for r in pre_rows:
        ents.append(Entity(
            local_id=local_id(r["ma"], "pre2025"), gso_code=r["ma"], era="pre2025",
            name_vi=r["ten"], loai_hinh=r["loai_hinh"],
            valid_from=None, valid_to="2025-06-30", wikidata_qid=None))
    for r in post_rows:
        ents.append(Entity(
            local_id=local_id(r["ma"], "post2025"), gso_code=r["ma"], era="post2025",
            name_vi=r["ten"], loai_hinh=r["loai_hinh"],
            valid_from="2025-07-01", valid_to=None, wikidata_qid=None))
    return ents
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_build_entities.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vn_admin_units/model.py tests/test_build_entities.py
git commit -m "feat: build entities from pre/post snapshots"
```

---

## Task 7: Build lineage edges (the core — validate to 100%)

**Files:**
- Modify: `src/vn_admin_units/model.py`
- Test: `tests/test_lineage.py`, `tests/test_lineage_groundtruth.py`

Lineage rule: for each pre-reform province, its successor is (a) the structured `succ_ma` if present → `renamed_to`/`replaces`, `primary=True`; else (b) resolved from its own `Ghi Chú` merge `result` name → the post-reform entity of that name → `merged_into`, `primary=False`. All `share="whole"` at province level.

- [ ] **Step 1: Write the unit test** (`tests/test_lineage.py`)

```python
from vn_admin_units.model import build_entities, build_lineage

def _rows():
    pre = [{"ma":"10","ten":"Tỉnh Lào Cai","loai_hinh":"Tỉnh"},
           {"ma":"15","ten":"Tỉnh Yên Bái","loai_hinh":"Tỉnh"}]
    post = [{"ma":"15","ten":"Tỉnh Lào Cai","loai_hinh":"Tỉnh"}]
    xwalk = [
        {"base_ma":"10","base_ten":"Tỉnh Lào Cai","succ_ma":"15","succ_ten":"Tỉnh Lào Cai",
         "nghi_dinh":"Số: 202/2025/QH15; Ngày: 12/06/2025","hieu_luc":"2025-07-01","ghi_chu":""},
        {"base_ma":"15","base_ten":"Tỉnh Yên Bái","succ_ma":"","succ_ten":"",
         "nghi_dinh":"Số: 202/2025/QH15; Ngày: 12/06/2025","hieu_luc":"2025-07-01",
         "ghi_chu":"Sắp xếp toàn bộ diện tích tự nhiên, quy mô dân số của tỉnh Yên Bái và tỉnh Lào Cai thành tỉnh mới có tên gọi là tỉnh Lào Cai"},
    ]
    return pre, post, xwalk

def test_lineage_primary_and_absorbed():
    pre, post, xwalk = _rows()
    ents = build_entities(pre, post)
    edges = build_lineage(ents, xwalk)
    # old Lào Cai (10) is the primary predecessor of post Lào Cai (15)
    prim = [e for e in edges if e.predecessor=="p-10-pre2025"]
    assert len(prim)==1 and prim[0].successor=="p-15-post2025" and prim[0].primary is True
    # Yên Bái (15) merged into post Lào Cai, not primary
    yb = [e for e in edges if e.predecessor=="p-15-pre2025"]
    assert len(yb)==1 and yb[0].successor=="p-15-post2025" and yb[0].primary is False
    assert yb[0].relation=="merged_into" and yb[0].decree.startswith("Số: 202/2025")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lineage.py -q`
Expected: FAIL — `build_lineage` not defined.

- [ ] **Step 3: Add `build_lineage` to `model.py`**

```python
from vn_admin_units.ghichu import parse_ghichu, _norm

def _strip_prefix(name: str) -> str:
    return _norm(re.sub(r"^(tỉnh|thành phố)\s+", "", name, flags=re.IGNORECASE)).lower()

def build_lineage(entities: list["Entity"], crosswalk: list[dict]) -> list["LineageEdge"]:
    post_by_code = {e.gso_code: e for e in entities if e.era == "post2025"}
    post_by_name = {_strip_prefix(e.name_vi): e for e in entities if e.era == "post2025"}
    pre_by_code = {e.gso_code: e for e in entities if e.era == "pre2025"}
    edges: list[LineageEdge] = []
    for row in crosswalk:
        pre = pre_by_code.get(row["base_ma"])
        if pre is None:
            continue
        decree = row["nghi_dinh"]
        # effective_date = the SUCCESSOR's inception (reform date). The crosswalk
        # base-side `hieu_luc` is the predecessor's own last-change date (e.g. 2004),
        # NOT this succession event — do not use it here.
        if row["succ_ma"]:                                   # (a) structured primary
            succ = post_by_code.get(row["succ_ma"])
            if succ:
                edges.append(LineageEdge(pre.local_id, succ.local_id, "replaces",
                                         "whole", True, decree, succ.valid_from))
            continue
        parsed = parse_ghichu(row["ghi_chu"])               # (b) absorbed via prose
        if parsed["event"] == "merge" and parsed["result"]:
            succ = post_by_name.get(_strip_prefix(parsed["result"]))
            if succ:
                edges.append(LineageEdge(pre.local_id, succ.local_id, "merged_into",
                                         "whole", False, decree, succ.valid_from))
    return edges
```

Add `import re` at the top of `model.py` if not already present.

- [ ] **Step 4: Run unit test to verify it passes**

Run: `uv run pytest tests/test_lineage.py -q`
Expected: PASS.

- [ ] **Step 5: Write the ground-truth test** (`tests/test_lineage_groundtruth.py`) — every post-2025 province must have ≥1 predecessor, and the 11 unchanged provinces map 1:1.

```python
import json
from pathlib import Path
from vn_admin_units.model import build_entities, build_lineage
from vn_admin_units.crosswalk import read_province_crosswalk

# Verified predecessor(pre code) -> successor(post code) from the 63->34 reform.
# Guards result-NAME correctness (a wrong result that still resolves to *some*
# post entity would pass coverage but be wrong).
KNOWN_EDGES = {
    "15": "15",  # Yên Bái  -> merged Lào Cai (post code 15)
    "10": "15",  # old Lào Cai -> merged Lào Cai (survivor, code 10->15)
    "06": "19",  # Bắc Kạn  -> Thái Nguyên
    "02": "08",  # Hà Giang -> Tuyên Quang
    "01": "01",  # Hà Nội   -> unchanged
}

def _load():
    pre = json.loads(Path("data/provinces-2025-06-30.json").read_text(encoding="utf-8"))
    post = json.loads(Path("data/provinces-2026-07-10.json").read_text(encoding="utf-8"))
    ents = build_entities(pre, post)
    edges = build_lineage(ents, read_province_crosswalk("data/raw/crosswalk/DoiChieu_Tinh_2025.xls"))
    return ents, edges

def test_every_post_province_has_predecessor():
    ents, edges = _load()
    post_ids = {e.local_id for e in ents if e.era == "post2025"}
    covered = {e.successor for e in edges}
    missing = post_ids - covered
    assert not missing, f"post-reform provinces with no predecessor edge: {missing}"
    assert len(post_ids) == 34
    assert len([e for e in ents if e.era == "pre2025"]) == 63

def test_known_edges_resolve_to_correct_successor():
    _, edges = _load()
    by_pred = {e.predecessor: e.successor for e in edges}
    for pre_code, post_code in KNOWN_EDGES.items():
        assert by_pred.get(f"p-{pre_code}-pre2025") == f"p-{post_code}-post2025", \
            f"pre {pre_code} should map to post {post_code}"
```

- [ ] **Step 6: Run the ground-truth test**

Run: `uv run pytest tests/test_lineage_groundtruth.py -q`
Expected: both tests PASS. If `missing` is non-empty, inspect those provinces' `Ghi Chú` for template variants (city establishments like Huế/Đà Nẵng/HCMC/Cần Thơ/Hải Phòng use "thành **thành phố** mới"; the regex already allows `thành phố`, but verify) and extend `parse_ghichu` until zero missing. If `test_known_edges…` fails, the parser resolved a *wrong* successor (e.g. greedy `_MERGE` result capture swallowed trailing prose) — fix the parse, don't adjust the expected map. **Do not weaken either assertion.**

- [ ] **Step 7: Commit**

```bash
git add src/vn_admin_units/model.py tests/test_lineage.py tests/test_lineage_groundtruth.py
git commit -m "feat: build province lineage edges; validate all 34 covered"
```

---

## Task 8: Reconcile entities to Wikidata QIDs

**Files:**
- Create: `src/vn_admin_units/reconcile.py`, `tests/test_reconcile.py`, `mappings/provinces-qid.csv`

Province reconciliation is small (~97 entities) and high-stakes, so use a **curated seed CSV** (verified QIDs) plus a WD-API name lookup to fill/verify. Seed from journals: Lào Cai `Q36446`, Yên Bái `Q36349`, Thái Nguyên `Q26575`, Phú Thọ `Q100179`, etc. Post-reform provinces mostly reuse the surviving province's existing item (WD edited provinces in place — verify per entity).

- [ ] **Step 1: Create the seed** (`mappings/provinces-qid.csv`) with header and the verified rows known so far:

```csv
gso_code,era,name_vi,wikidata_qid,qid_status,match_status
15,pre2025,Tỉnh Yên Bái,Q36349,existing,verified
10,pre2025,Tỉnh Lào Cai,Q36446,existing,seed-check
15,post2025,Tỉnh Lào Cai,Q36446,existing,seed-check
```

`qid_status` = `existing` (WD item pre-dates the reform — enrich only, **no
`P571`**) vs `new` (freshly minted). For Phase-1 provinces this is `existing`
for **all** rows: WD edited surviving province items in place and the absorbed
provinces already had items (`.08`). `match_status` is our own confidence
(`verified`/`seed-check`/`needs-item`). Note the survivor maps its pre and post
eras to the **same QID** (`10,pre2025` and `15,post2025` → `Q36446`) — this is
correct; emit guards the same-QID case (Task 9).

- [ ] **Step 2: Write the failing test** (`tests/test_reconcile.py`)

```python
from vn_admin_units.reconcile import load_seed, apply_seed
from vn_admin_units.model import Entity

def test_apply_seed_sets_qid_and_status():
    seed = load_seed("mappings/provinces-qid.csv")
    e = Entity("p-15-pre2025","15","pre2025","Tỉnh Yên Bái","Tỉnh",None,"2025-06-30",None)
    [e2] = apply_seed([e], seed)
    assert e2.wikidata_qid == "Q36349"
    assert e2.qid_status == "existing"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_reconcile.py -q`
Expected: FAIL — module missing.

- [ ] **Step 4: Implement `reconcile.py`**

```python
import csv
import json
import urllib.parse
import urllib.request
from pathlib import Path
from vn_admin_units.model import Entity

def load_seed(path: str) -> dict:
    """(gso_code, era) -> {'qid', 'qid_status'} from the curated CSV."""
    seed = {}
    for row in csv.DictReader(Path(path).read_text(encoding="utf-8").splitlines()):
        seed[(row["gso_code"], row["era"])] = {
            "qid": row["wikidata_qid"], "qid_status": row.get("qid_status", "existing")}
    return seed

def apply_seed(entities: list[Entity], seed: dict) -> list[Entity]:
    for e in entities:
        hit = seed.get((e.gso_code, e.era))
        if hit:
            e.wikidata_qid = hit["qid"]
            e.qid_status = hit["qid_status"]
    return entities

def wd_search(name: str, timeout: int = 30) -> list[dict]:
    """wbsearchentities by Vietnamese label; returns [{id,label,description}]."""
    u = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode({
        "action": "wbsearchentities", "search": name, "language": "vi",
        "type": "item", "format": "json", "limit": 5})
    req = urllib.request.Request(u, headers={"User-Agent": "vn-admin-units/0.1 (research)"})
    data = json.load(urllib.request.urlopen(req, timeout=timeout))
    return [{"id": x["id"], "label": x.get("label",""), "description": x.get("description","")}
            for x in data["search"]]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_reconcile.py -q`
Expected: PASS.

- [ ] **Step 6: Manually complete + verify the seed** — for every entity without a seeded QID, run `wd_search(name)` (via a short `uv run python -c` or a scratch script), confirm the item is the correct province item for that era against its `P31`/`P131`, and add a `verified` row to `mappings/provinces-qid.csv`. Post-reform merged provinces: confirm whether WD kept the surviving province's item (edit-in-place) or minted a new one, and record whichever the community used. Log any that need a new item as `status=needs-item`.

- [ ] **Step 7: Commit**

```bash
git add src/vn_admin_units/reconcile.py tests/test_reconcile.py mappings/provinces-qid.csv
git commit -m "feat: province Wikidata reconciliation (seed + WD search)"
```

---

## Task 9: Emit QuickStatements v2

**Files:**
- Create: `src/vn_admin_units/emit.py`, `tests/test_emit.py`

QuickStatements v2 syntax: `Q<item>\tP<prop>\t<value>` per line; qualifiers/refs appended tab-separated; dates as `+2025-07-01T00:00:00Z/11`; item values bare `Qxxx`; strings quoted; reference URL as `S854\t"<url>"`.

**Emit rules (per DESIGN §Identity, resolving review findings #1–#3):**
1. **Same-QID guard** — skip any edge where `pre.qid == post.qid` (survivor edited in place = one continuing item; emitting dissolved/merged/replaces here would be self-referential garbage).
2. **`P571` inception only when `post.qid_status == "new"`** — never stamp an inception on a pre-existing item (would falsify a decades-old province). For Phase-1 provinces (all `existing`) this emits **zero** `P571`.
3. **Every statement referenced** — `S854` reference URL to the NSO source (operational source; satisfies the `.07` Statistics-Law citation duty). Lineage statements also carry `P585` = effective date. (Refinement for later: `S248` stated-in the Nghị quyết's WD item when it exists.)
4. Skip any edge whose endpoints aren't both reconciled (missing QID) — those are logged, not emitted.

For a distinct-QID absorbed/merged edge: old `P576` dissolved + `P7888` merged into + `P1366` replaced by → new; new `P1365` replaces → old. All dated + referenced.

- [ ] **Step 1: Write the failing test** (`tests/test_emit.py`)

```python
from vn_admin_units.model import Entity, LineageEdge
from vn_admin_units.emit import emit_quickstatements

def test_emit_absorbed_merge_is_referenced_no_p571():
    ents = [
        Entity("p-15-post2025","15","post2025","Tỉnh Lào Cai","Tỉnh","2025-07-01",None,"Q36446","existing"),
        Entity("p-15-pre2025","15","pre2025","Tỉnh Yên Bái","Tỉnh",None,"2025-06-30","Q36349","existing"),
    ]
    edges = [LineageEdge("p-15-pre2025","p-15-post2025","merged_into","whole",False,
                         "Số: 202/2025/QH15","2025-07-01")]
    qs = emit_quickstatements(ents, edges)
    assert "Q36349\tP576\t+2025-07-01T00:00:00Z/11\tS854" in qs        # dissolved, referenced
    assert "Q36349\tP7888\tQ36446\tP585\t+2025-07-01T00:00:00Z/11\tS854" in qs
    assert "Q36446\tP1365\tQ36349" in qs                              # replaces
    assert 'S854\t"https://danhmuchanhchinh.nso.gov.vn/"' in qs        # citation present
    assert "P571" not in qs                                           # existing item -> NO inception

def test_emit_survivor_same_qid_emits_nothing():
    ents = [
        Entity("p-10-pre2025","10","pre2025","Tỉnh Lào Cai","Tỉnh",None,"2025-06-30","Q36446","existing"),
        Entity("p-15-post2025","15","post2025","Tỉnh Lào Cai","Tỉnh","2025-07-01",None,"Q36446","existing"),
    ]
    edges = [LineageEdge("p-10-pre2025","p-15-post2025","replaces","whole",True,
                         "Số: 202/2025/QH15","2025-07-01")]
    assert emit_quickstatements(ents, edges) == ""   # same QID -> no self-referential statements

def test_emit_p571_only_for_new_items():
    ents = [
        Entity("w-x-post","x","post2025","Phường Ba Đình","Phường","2025-07-01",None,"Q135651473","new"),
        Entity("w-y-pre","y","pre2025","Phường Trúc Bạch","Phường",None,"2025-06-30","Q10828647","existing"),
    ]
    edges = [LineageEdge("w-y-pre","w-x-post","merged_into","whole",True,"Số: 1656","2025-07-01")]
    qs = emit_quickstatements(ents, edges)
    assert "Q135651473\tP571\t+2025-07-01T00:00:00Z/11\tS854" in qs   # NEW item -> inception
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_emit.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `emit.py`**

```python
REFERENCE_URL = "https://danhmuchanhchinh.nso.gov.vn/"

def _date(d: str) -> str:
    # take the date part defensively (guards a datetime string like "2025-07-01 00:00:00")
    d = str(d).strip().split(" ")[0].split("T")[0]
    return f"+{d}T00:00:00Z/11"

def emit_quickstatements(entities: list["Entity"], edges: list["LineageEdge"]) -> str:
    by_id = {e.local_id: e for e in entities}
    lines: list[str] = []
    p571_done: set[str] = set()
    ref = f'S854\t"{REFERENCE_URL}"'
    for e in edges:
        pre, post = by_id[e.predecessor], by_id[e.successor]
        if not (pre.wikidata_qid and post.wikidata_qid):
            continue                              # rule 4: unreconciled -> skip
        if pre.wikidata_qid == post.wikidata_qid:
            continue                              # rule 1: survivor edited in place -> no lineage
        eff = _date(e.effective_date)
        # old (absorbed) side: dissolved + merged into + replaced by
        lines.append(f"{pre.wikidata_qid}\tP576\t{eff}\t{ref}")
        lines.append(f"{pre.wikidata_qid}\tP7888\t{post.wikidata_qid}\tP585\t{eff}\t{ref}")
        lines.append(f"{pre.wikidata_qid}\tP1366\t{post.wikidata_qid}\tP585\t{eff}\t{ref}")
        # new/surviving side: replaces predecessor
        lines.append(f"{post.wikidata_qid}\tP1365\t{pre.wikidata_qid}\tP585\t{eff}\t{ref}")
        # rule 2: inception ONLY for genuinely new items, once each
        if post.qid_status == "new" and post.wikidata_qid not in p571_done:
            lines.append(f"{post.wikidata_qid}\tP571\t{eff}\t{ref}")
            p571_done.add(post.wikidata_qid)
    seen, out = set(), []                          # de-dupe, preserve order
    for ln in lines:
        if ln not in seen:
            seen.add(ln); out.append(ln)
    return ("\n".join(out) + "\n") if out else ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_emit.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vn_admin_units/emit.py tests/test_emit.py
git commit -m "feat: QuickStatements v2 emitter for province reform"
```

---

## Task 10: Wire the pipeline + produce artifacts

**Files:**
- Modify: `src/vn_admin_units/cli.py`
- Create: `data/entities.json`, `data/lineage.json`, `statements/na-provinces-2025.qs`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Add a `build_all` function to `cli.py`**

```python
from vn_admin_units.crosswalk import read_province_crosswalk
from vn_admin_units.model import build_entities, build_lineage
from vn_admin_units.reconcile import load_seed, apply_seed
from vn_admin_units.emit import emit_quickstatements

def _load(iso):
    return json.loads((DATA / f"provinces-{iso}.json").read_text(encoding="utf-8"))

def build_all() -> None:
    pre, post = _load("2025-06-30"), _load("2026-07-10")
    ents = apply_seed(build_entities(pre, post), load_seed("mappings/provinces-qid.csv"))
    edges = build_lineage(ents, read_province_crosswalk("data/raw/crosswalk/DoiChieu_Tinh_2025.xls"))
    Path("data").mkdir(exist_ok=True)
    Path("data/entities.json").write_text(
        json.dumps([e.to_dict() for e in ents], ensure_ascii=False, indent=2), encoding="utf-8")
    Path("data/lineage.json").write_text(
        json.dumps([e.to_dict() for e in edges], ensure_ascii=False, indent=2), encoding="utf-8")
    Path("statements").mkdir(exist_ok=True)
    Path("statements/na-provinces-2025.qs").write_text(
        emit_quickstatements(ents, edges), encoding="utf-8")
    print(f"built {len(ents)} entities, {len(edges)} lineage edges")
```

- [ ] **Step 2: Write the pipeline test** (`tests/test_pipeline.py`)

```python
import json
from pathlib import Path
from vn_admin_units.cli import build_all

def test_build_all_produces_artifacts():
    """Integration test: runs the full build against the committed data/ and
    data/raw/ inputs, writing the real data/ + statements/ artifacts. Requires
    Task 2/3 inputs to exist. (No tmp isolation — build_all uses repo-relative
    paths; this is an end-to-end check, not a unit test.)"""
    build_all()
    ents = json.loads(Path("data/entities.json").read_text(encoding="utf-8"))
    assert len([e for e in ents if e["era"] == "post2025"]) == 34
    qs = Path("statements/na-provinces-2025.qs").read_text(encoding="utf-8")
    assert "P576" in qs and "P1365" in qs
    # end-to-end safety net (guards review findings #1/#2 against regression):
    for line in qs.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[1] in {"P7888", "P1366", "P1365"}:
            assert parts[0] != parts[2], f"self-referential statement leaked: {line}"
    assert "P571" not in qs, "no province item should get a (false) 2025 inception"
    assert 'S854' in qs, "every statement must be referenced"
```

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest -q`
Expected: all tests PASS (including the 34-coverage ground truth).

- [ ] **Step 4: Generate the artifacts for real**

Run: `uv run python -c "from vn_admin_units.cli import build_all; build_all()"`
Expected: `built 97 entities, N lineage edges` (63 pre + 34 post = 97; N ≥ 63).

- [ ] **Step 5: Manually spot-check the QuickStatements** — open `statements/na-provinces-2025.qs` and confirm:
  - The Yên Bái→Lào Cai block reads sensibly (`Q36349 P576/P7888 → Q36446`; `Q36446 P1365 → Q36349`).
  - **No self-referential lines** (`Qx P7888/P1366/P1365 Qx`) — the same-QID survivors (Hà Nội, Cao Bằng, etc.) must produce *nothing*.
  - **No `P571`** anywhere (all province items pre-exist; a false 2025 inception would be the #2 defect).
  - **Every line carries an `S854` reference.**
  - Every emitted QID is non-blank; any unreconciled entity was skipped (check the reconcile log / `mappings` for `needs-item`).
  Cross-check 3 rows against `DESIGN.md`'s encoding. **Do not upload in this plan** — emission only; upload is a separate, reviewed step (and the `P1365`/`P7888` qualifier constraint-check must happen first).

- [ ] **Step 6: Commit**

```bash
git add src/vn_admin_units/cli.py data/entities.json data/lineage.json statements/na-provinces-2025.qs
git commit -m "feat: wire province pipeline; emit 2025 reform QuickStatements"
```

---

## Deferred to Phase 1b / later (explicitly out of scope here)

- Ward tier (10,040↔3,321) + the name→code disambiguation step (`.11`). The two
  ward crosswalk exports already downloaded during recon (`~/Downloads/…cấp Xã…
  10_07_2026 và 31_07_2025.xls` and `…30_06_2025 và 10_07_2026.xls`) should be
  moved into `data/raw/crosswalk/` with manifest entries at the start of Phase 1b
  (before they're lost from Downloads).
- Verifying `P1365`/`P7888` allowed-qualifier constraints against live WD before upload.
- The actual QuickStatements **upload** (separate reviewed step; needs personal WD account).
- `P31`/`P131` fix statements (type change, 2-level re-parent) and the đặc-khu items.
- Historical eras (2004/2008) + multi-hop chaining; Lịch Sử scrape; consumer (Goal A) exports.

## Self-review notes

- Spec coverage: ingest (T1–T3), Ghi Chú parse (T4), model+lineage (T5–T7), reconcile (T8), emit (T9), wiring+validation (T10) — covers the Phase-1 slice of `DESIGN.md`. Historical chaining, wards, and upload are explicitly deferred above.
- The `build_lineage` name-matching uses `_strip_prefix` consistently on both sides; province names are unique (`.05`), so name resolution is safe at this tier (ward tier will need disambiguation — deferred).
- Ground-truth test (T7 Step 6) is the gate: if any post-province lacks a predecessor, extend the parser — never weaken the assertion.
- Raw-data storage (decided 2026-07-10): T2 stores verbatim SOAP `.xml` + `manifest.jsonl`; T3 stores the verbatim crosswalk `.xls` + manifest; derived parsed JSON lives in `data/`. Consumers/tests read derived from `data/`, and the crosswalk reader reads the verbatim `.xls` directly (its parsed form is used in-memory, not re-committed).
- Emit safety (T9, resolving review #1–#3): the local model is new-entity-per-reform but reconciliation maps to WD items (many-local→one-QID for edited survivors); emit therefore (1) skips same-QID edges, (2) sets `P571` only for `qid_status=="new"`, (3) references every statement (`S854`) + dates lineage (`P585`). Three emit unit tests + the T10 integration safety net (no self-refs, no `P571`, `S854` present) gate this. For Phase-1 provinces the batch has zero `P571` and zero self-references by construction.
