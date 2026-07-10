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
- `src/vn_admin_units/soap.py` — GSO SOAP client (`DanhMucTinh`) + diffgram parser.
- `src/vn_admin_units/crosswalk.py` — read Đối Chiếu province `.xls` → rows.
- `src/vn_admin_units/ghichu.py` — parse `Ghi Chú` → structured events.
- `src/vn_admin_units/model.py` — `Entity`/`Observation`/`LineageEdge` + builders.
- `src/vn_admin_units/reconcile.py` — entity → Wikidata QID (province level).
- `src/vn_admin_units/emit.py` — QuickStatements v2 generation.
- `src/vn_admin_units/cli.py` — wire ingest→build→reconcile→emit.
- `data/raw/` — committed cache: `provinces-{date}.json`, `crosswalk-tinh-2025.xls`.
- `data/` — built artifacts: `entities.json`, `observations.json`, `lineage.json`.
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
    """Extract province rows from a DanhMucTinh SOAP diffgram response."""
    rows = []
    for block in re.findall(r"<TABLE\b[^>]*>(.*?)</TABLE>", xml, re.S):
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

## Task 2: Cache province snapshots (raw data)

**Files:**
- Create: `src/vn_admin_units/cli.py`, `data/raw/provinces-2025-06-30.json`, `data/raw/provinces-2026-07-10.json`

- [ ] **Step 1: Add a `cache_snapshots` function to `cli.py`**

```python
import json
from pathlib import Path
from vn_admin_units.soap import fetch_provinces

BOUNDARY_DATES = {"2025-06-30": "30/06/2025", "2026-07-10": "10/07/2026"}
RAW = Path("data/raw")

def cache_snapshots() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    for iso, ddmmyyyy in BOUNDARY_DATES.items():
        rows = fetch_provinces(ddmmyyyy)
        (RAW / f"provinces-{iso}.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"cached {len(rows)} provinces @ {iso}")

if __name__ == "__main__":
    cache_snapshots()
```

- [ ] **Step 2: Run it (live) to produce the cache**

Run: `uv run python -m vn_admin_units.cli`
Expected: prints `cached 63 provinces @ 2025-06-30` and `cached 34 provinces @ 2026-07-10`. Verify counts are exactly 63 and 34.

- [ ] **Step 3: Commit the raw cache**

```bash
git add src/vn_admin_units/cli.py data/raw/provinces-2025-06-30.json data/raw/provinces-2026-07-10.json
git commit -m "feat: cache province snapshots (63 pre-reform, 34 current)"
```

---

## Task 3: Crosswalk Excel reader

**Files:**
- Create: `src/vn_admin_units/crosswalk.py`, `tests/test_crosswalk.py`, `data/raw/crosswalk-tinh-2025.xls` (copy the province export from `~/Downloads/Đối chiếu đơn vị hành chính cấp Tỉnh _ 30_06_2025 và 10_07_2026.xls`)

- [ ] **Step 1: Copy the province crosswalk export into the repo**

```bash
cp "$HOME/Downloads/Đối chiếu đơn vị hành chính cấp Tỉnh _ 30_06_2025 và 10_07_2026.xls" data/raw/crosswalk-tinh-2025.xls
```

- [ ] **Step 2: Write the failing test** (`tests/test_crosswalk.py`)

```python
from vn_admin_units.crosswalk import read_province_crosswalk

def test_read_province_crosswalk():
    rows = read_province_crosswalk("data/raw/crosswalk-tinh-2025.xls")
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

def read_province_crosswalk(path: str) -> list[dict]:
    """Read the Đối Chiếu province .xls export into normalized rows."""
    df = pd.read_excel(path, engine="xlrd", dtype=str).fillna("")
    out = []
    for _, r in df.iterrows():
        out.append({dest: str(r.get(src, "")).strip() for src, dest in _COLS.items()})
    return out
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_crosswalk.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/vn_admin_units/crosswalk.py tests/test_crosswalk.py data/raw/crosswalk-tinh-2025.xls
git commit -m "feat: province crosswalk Excel reader"
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
        decree, eff = row["nghi_dinh"], row["hieu_luc"]
        if row["succ_ma"]:                                   # (a) structured primary
            succ = post_by_code.get(row["succ_ma"])
            if succ:
                edges.append(LineageEdge(pre.local_id, succ.local_id, "replaces",
                                         "whole", True, decree, eff))
            continue
        parsed = parse_ghichu(row["ghi_chu"])               # (b) absorbed via prose
        if parsed["event"] == "merge" and parsed["result"]:
            succ = post_by_name.get(_strip_prefix(parsed["result"]))
            if succ:
                edges.append(LineageEdge(pre.local_id, succ.local_id, "merged_into",
                                         "whole", False, decree, eff))
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

UNCHANGED_CODES = {"01","04","11","12","14","20","22","38","40","42"}  # + verify against 'Giữ nguyên'

def test_every_post_province_has_predecessor():
    pre = json.loads(Path("data/raw/provinces-2025-06-30.json").read_text(encoding="utf-8"))
    post = json.loads(Path("data/raw/provinces-2026-07-10.json").read_text(encoding="utf-8"))
    pre = [{"ma":r["ma"],"ten":r["ten"],"loai_hinh":r["loai_hinh"]} for r in pre]
    post = [{"ma":r["ma"],"ten":r["ten"],"loai_hinh":r["loai_hinh"]} for r in post]
    ents = build_entities(pre, post)
    edges = build_lineage(ents, read_province_crosswalk("data/raw/crosswalk-tinh-2025.xls"))
    post_ids = {e.local_id for e in ents if e.era=="post2025"}
    covered = {e.successor for e in edges}
    missing = post_ids - covered
    assert not missing, f"post-reform provinces with no predecessor edge: {missing}"
    # exactly 34 post entities, 63 pre entities
    assert len(post_ids) == 34
    assert len([e for e in ents if e.era=="pre2025"]) == 63
```

- [ ] **Step 6: Run the ground-truth test**

Run: `uv run pytest tests/test_lineage_groundtruth.py -q`
Expected: PASS. If `missing` is non-empty, inspect those provinces' `Ghi Chú` for template variants (city establishments like Huế/Đà Nẵng/HCMC/Cần Thơ/Hải Phòng use "thành **thành phố** mới"; the regex already allows `thành phố`, but verify) and extend `parse_ghichu` until zero missing. Do not weaken the assertion.

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
gso_code,era,name_vi,wikidata_qid,status
15,pre2025,Tỉnh Yên Bái,Q36349,verified
10,pre2025,Tỉnh Lào Cai,Q36446,seed-check
15,post2025,Tỉnh Lào Cai,Q36446,seed-check
```

- [ ] **Step 2: Write the failing test** (`tests/test_reconcile.py`)

```python
from vn_admin_units.reconcile import load_seed, apply_seed
from vn_admin_units.model import Entity

def test_apply_seed_sets_qid():
    seed = load_seed("mappings/provinces-qid.csv")
    e = Entity("p-15-pre2025","15","pre2025","Tỉnh Yên Bái","Tỉnh",None,"2025-06-30",None)
    [e2] = apply_seed([e], seed)
    assert e2.wikidata_qid == "Q36349"
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
    """(gso_code, era) -> qid from the curated CSV."""
    seed = {}
    for row in csv.DictReader(Path(path).read_text(encoding="utf-8").splitlines()):
        seed[(row["gso_code"], row["era"])] = row["wikidata_qid"]
    return seed

def apply_seed(entities: list[Entity], seed: dict) -> list[Entity]:
    for e in entities:
        qid = seed.get((e.gso_code, e.era))
        if qid:
            e.wikidata_qid = qid
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

QuickStatements v2 syntax: `Q<item>\tP<prop>\t<value>` per line; qualifiers/refs appended tab-separated (`Pxxx\tvalue`); dates as `+2025-07-01T00:00:00Z/11`; item values are bare `Qxxx`; string values quoted. Reference: `S248\tQ<decree>` if the decree has an item, else `S854\t"<url>"` (reference URL). Property map per `DESIGN.md`: new entity `P571` inception + `P1365` replaces (per predecessor, qualified `P585` effective date, referenced); old entity `P576` dissolved + `P7888` merged into (+ `P1366`).

- [ ] **Step 1: Write the failing test** (`tests/test_emit.py`)

```python
from vn_admin_units.model import Entity, LineageEdge
from vn_admin_units.emit import emit_quickstatements

def test_emit_merge_batch():
    ents = [
        Entity("p-15-post2025","15","post2025","Tỉnh Lào Cai","Tỉnh","2025-07-01",None,"Q36446"),
        Entity("p-15-pre2025","15","pre2025","Tỉnh Yên Bái","Tỉnh",None,"2025-06-30","Q36349"),
    ]
    edges = [LineageEdge("p-15-pre2025","p-15-post2025","merged_into","whole",False,
                         "Số: 202/2025/QH15; Ngày: 12/06/2025","2025-07-01")]
    qs = emit_quickstatements(ents, edges)
    # dissolved old province
    assert "Q36349\tP576\t+2025-07-01T00:00:00Z/11" in qs
    assert "Q36349\tP7888\tQ36446" in qs
    # new/surviving province inception + replaces predecessor
    assert "Q36446\tP571\t+2025-07-01T00:00:00Z/11" in qs
    assert "Q36446\tP1365\tQ36349" in qs
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_emit.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `emit.py`**

```python
def _date(d: str) -> str:
    return f"+{d}T00:00:00Z/11"

def emit_quickstatements(entities: list["Entity"], edges: list["LineageEdge"]) -> str:
    by_id = {e.local_id: e for e in entities}
    lines: list[str] = []
    for e in edges:
        pre, post = by_id[e.predecessor], by_id[e.successor]
        if not (pre.wikidata_qid and post.wikidata_qid):
            continue
        eff = _date(e.effective_date)
        # old side: dissolved + merged into
        lines.append(f"{pre.wikidata_qid}\tP576\t{eff}")
        lines.append(f"{pre.wikidata_qid}\tP7888\t{post.wikidata_qid}")
        lines.append(f"{pre.wikidata_qid}\tP1366\t{post.wikidata_qid}")
        # new side: inception + replaces (qualified with effective date)
        lines.append(f"{post.wikidata_qid}\tP571\t{eff}")
        lines.append(f"{post.wikidata_qid}\tP1365\t{pre.wikidata_qid}\tP585\t{eff}")
    # de-dupe while preserving order (P571 emitted once per post entity)
    seen, out = set(), []
    for ln in lines:
        if ln not in seen:
            seen.add(ln); out.append(ln)
    return "\n".join(out) + "\n"
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
    return json.loads((RAW / f"provinces-{iso}.json").read_text(encoding="utf-8"))

def build_all() -> None:
    pre, post = _load("2025-06-30"), _load("2026-07-10")
    ents = apply_seed(build_entities(pre, post), load_seed("mappings/provinces-qid.csv"))
    edges = build_lineage(ents, read_province_crosswalk("data/raw/crosswalk-tinh-2025.xls"))
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

def test_build_all_produces_artifacts(tmp_path, monkeypatch):
    build_all()
    ents = json.loads(Path("data/entities.json").read_text(encoding="utf-8"))
    assert len([e for e in ents if e["era"]=="post2025"]) == 34
    qs = Path("statements/na-provinces-2025.qs").read_text(encoding="utf-8")
    assert "P576" in qs and "P1365" in qs
```

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest -q`
Expected: all tests PASS (including the 34-coverage ground truth).

- [ ] **Step 4: Generate the artifacts for real**

Run: `uv run python -c "from vn_admin_units.cli import build_all; build_all()"`
Expected: `built 97 entities, N lineage edges` (63 pre + 34 post = 97; N ≥ 63).

- [ ] **Step 5: Manually spot-check the QuickStatements** — open `statements/na-provinces-2025.qs`, verify the Yên Bái/Lào Cai block reads sensibly, and confirm every referenced QID is filled (no blank predecessor/successor). Cross-check 3 rows against `DESIGN.md`'s intended encoding before any upload. **Do not upload in this plan** — emission only; upload is a separate, reviewed step.

- [ ] **Step 6: Commit**

```bash
git add src/vn_admin_units/cli.py data/entities.json data/lineage.json statements/na-provinces-2025.qs
git commit -m "feat: wire province pipeline; emit 2025 reform QuickStatements"
```

---

## Deferred to Phase 1b / later (explicitly out of scope here)

- Ward tier (10,040↔3,321) + the name→code disambiguation step (`.11`).
- Verifying `P1365`/`P7888` allowed-qualifier constraints against live WD before upload.
- The actual QuickStatements **upload** (separate reviewed step; needs personal WD account).
- `P31`/`P131` fix statements (type change, 2-level re-parent) and the đặc-khu items.
- Historical eras (2004/2008) + multi-hop chaining; Lịch Sử scrape; consumer (Goal A) exports.

## Self-review notes

- Spec coverage: ingest (T1–T3), Ghi Chú parse (T4), model+lineage (T5–T7), reconcile (T8), emit (T9), wiring+validation (T10) — covers the Phase-1 slice of `DESIGN.md`. Historical chaining, wards, and upload are explicitly deferred above.
- The `build_lineage` name-matching uses `_strip_prefix` consistently on both sides; province names are unique (`.05`), so name resolution is safe at this tier (ward tier will need disambiguation — deferred).
- Ground-truth test (T7 Step 6) is the gate: if any post-province lacks a predecessor, extend the parser — never weaken the assertion.
