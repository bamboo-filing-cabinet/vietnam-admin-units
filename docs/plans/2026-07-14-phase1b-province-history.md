# Phase 1b — Province history 2002→2025 (Wikidata Goal B) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the province tier backward to 2002 — the 2004 code-scheme renumber, the three 2004 carve-outs (Điện Biên←Lai Châu, Đắk Nông←Đắk Lắk, Hậu Giang←Cần Thơ, from NQ 22/2003/QH11), and the 2008 Hà Tây→Hà Nội absorption — chained onto Phase 1a's 2025-reform entities, reconciled to Wikidata QIDs, and emitted as a referenced QuickStatements batch. Completes the province tier and produces the historical province QIDs Phase 2 districts need for `P131`.

**Architecture:** A new `province_history.py` assembles a continuous-entity graph (one entity across recode/retype; carve-out children and the ended Hà Tây as their own entities) from two independent instruments — a yearly SOAP roster walk (event discovery, name/type-normalized diff; the only source that sees 2002→2004) and yearly Đối Chiếu Tỉnh windows (lineage/prose/effective-dates from mid-2004 on) — plus a small curated decree file for the carve-out parentage the crosswalk omits. Reconciliation reuses 1a's QIDs and writes a **separate** `local_id`-keyed mapping. Emit extends `emit.py` with relation-aware statements (`P571`/`P807`/`P31`-retype/`P576`+succession). Phase 1a code (`model.py`, `emit_quickstatements`, `reconcile._write_csv`) stays untouched; the tier-neutral-core refactor is deferred to Phase 2 (Approach 1).

**Tech Stack:** Python 3.11+, `uv`; `pandas`+`xlrd` (`.xls`); Playwright (`ingest` group, browser fetch); stdlib `urllib` (SOAP + WD API); `pytest`.

**Read first:** `docs/DESIGN-phase1b.md` (the spec — decisions, in-scope events, model, reconcile, emit), journal `2026-07-14.01` (Đối Chiếu Tỉnh 9-col layout + 2004 floor + SOAP roster walk), `2026-07-10.15` (2004 code-scheme), `2026-07-10.10` (change taxonomy). Existing code this plan extends/mirrors: `src/vn_admin_units/{crosswalk,crosswalk_fetch,soap,cli,model,reconcile,emit,constraints}.py`.

**Scope discipline:** Terminal boundary is the 2025 reform. The 2026-04-30 Đồng Nai retype is **out of scope** (post-reform freshness). Pre-2002 ancestry is out of scope (below the GSO floor). District/ward-level 2008 partial transfers are other tiers.

---

## File Structure

- Create `src/vn_admin_units/province_history.py` — entity+lineage assembly for the 2002→2025 province tier (new relations: `carved_from`, `absorbed_into`; recode/retype as attribute spans). One responsibility: turn snapshots+windows+decrees into `Entity`/`LineageEdge` lists.
- Create `src/vn_admin_units/names.py` — `fold_name()` tone-mark/diacritic normalization (shared by assembly, event-diff, reconcile). Small, pure.
- Modify `src/vn_admin_units/crosswalk.py` — add `read_province_history_crosswalk()` (9-col positional reader). Leave `read_province_crosswalk` (7-col reform reader) and `read_district_crosswalk` untouched.
- Modify `src/vn_admin_units/crosswalk_fetch.py` — parameterize tier (`--tier {province,district}`; Cấp value + cache path + parser by tier). Leave district behavior identical.
- Modify `src/vn_admin_units/cli.py` — add `cache_history_snapshots()` (parameterized yearly SOAP walk) + `build_province_history()`.
- Modify `src/vn_admin_units/reconcile.py` — add history-mapping load (`load_history_seed`) + `audit_history_qids` (all entities, not just `pre2025`). Do **not** change `HEADER`/`_write_csv`/`audit_province_qids`.
- Modify `src/vn_admin_units/emit.py` — add `emit_history_quickstatements()` (relation-aware). Leave `emit_quickstatements` (1a) untouched.
- Modify `src/vn_admin_units/constraints.py` — check `P580`/`P582` qualifier allowances + `P807` subject/value-type.
- Create `data/decrees/2004-splits.json` — curated carve-out pairings + decree ref.
- Produce: `data/raw/crosswalk/province_*.xls` (windows), extra `data/raw/soap/DanhMucTinh_*.xml` (yearly), `data/provinces-{iso}.json` (yearly), `data/provinces-history.json`, `data/province-history-lineage.json`, `mappings/provinces-history-qid.csv`, `statements/na-provinces-history.qs`.
- Tests: `tests/test_names.py`, `tests/test_province_history_crosswalk.py`, `tests/test_province_history_model.py`, `tests/test_province_history_groundtruth.py`, `tests/test_history_reconcile.py`, `tests/test_history_emit.py`, and additions to `tests/test_crosswalk_fetch.py` (if present) / a new `tests/test_history_events.py`.

**Model shape (defined once, used throughout).** `province_history.Entity`:
`local_id: str`, `gso_codes: list[str]` (chronological; `[-1]` = terminal/reconcile code), `name_vi: str` (terminal), `loai_hinh: str` (terminal), `type_spans: list[dict]` (`{loai_hinh, from, to}`), `aliases: list[str]` (former names+codes), `valid_from: Optional[str]`, `valid_to: Optional[str]`, `wikidata_qid: Optional[str]`, `qid_status: Optional[str]`.
`province_history.LineageEdge`: `predecessor: str`, `successor: str`, `relation: str` (`carved_from`|`absorbed_into`), `decree: str`, `effective_date: str`.

---

## Task 0: Branch check + move recon crosswalk leftovers into the raw cache

**Files:**
- Produce: `data/raw/crosswalk/` (any ward exports still in `~/Downloads` are **not** needed here — province only).

- [ ] **Step 1: Confirm branch + clean tree**

Run: `git -C /Users/viett/personal/bamboo-filing-cabinet/vietnam-admin-units branch --show-current && git status --short`
Expected: branch `docs/phase1b-province-history`, clean tree (the spec + decree are already committed).

- [ ] **Step 2: Confirm the decree + manifest are present**

Run: `ls data/raw/decrees/ && grep -c decrees data/raw/manifest.jsonl`
Expected: `nq-22-2003-qh11.html` present; manifest count `1`.

- [ ] **Step 3: No commit** (verification only).

---

## Task 1: Parameterize the crosswalk fetcher for the province tier

**Files:**
- Modify: `src/vn_admin_units/crosswalk_fetch.py`
- Test: `tests/test_crosswalk_fetch.py` (create if absent)

The district fetcher is hard-coded to Cấp=Huyện (`_switch_to_huyen`, value `2`, `district_` path, `read_district_crosswalk`). Generalize to a `tier` parameter. Probe-confirmed: **Tỉnh = combo value `1`**; the province Excel export is the same mechanism. Keep district behavior byte-identical.

- [ ] **Step 1: Write the failing test** (`tests/test_crosswalk_fetch.py`)

```python
from vn_admin_units import crosswalk_fetch as cf

def test_tier_config_province_and_district():
    assert cf.TIER_CAP["province"] == "1"
    assert cf.TIER_CAP["district"] == "2"

def test_cache_relpath_by_tier():
    assert cf.cache_relpath("province", "01/01/2004", "01/01/2005") \
        == "crosswalk/province_2004-01-01_2005-01-01.xls"
    assert cf.cache_relpath("district", "01/01/2013", "01/01/2014") \
        == "crosswalk/district_2013-01-01_2014-01-01.xls"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_crosswalk_fetch.py -q`
Expected: FAIL — `TIER_CAP` / new `cache_relpath` signature missing.

- [ ] **Step 3: Refactor `crosswalk_fetch.py` to be tier-parameterized**

Replace the district-specific pieces with tier-keyed config. Full new module:

```python
"""Fetch Đối Chiếu crosswalk windows (province or district) from the GSO web UI.

DevExpress WebForms app; the Excel export is only reachable by driving the page.
Probe-confirmed Cấp combo values: Tỉnh=1, Huyện=2 (2026-07-13.02 / 2026-07-14.01).
Use the Excel download (clean server-side file) — DOM scraping suffers stale-row
contamination across tiers. See docs/journals/2026-07-14.01.

Usage (needs the `ingest` group + `playwright install chromium`):
  uv run --group ingest python -m vn_admin_units.crosswalk_fetch --tier province --sweep 2004 2024
  uv run --group ingest python -m vn_admin_units.crosswalk_fetch --tier province --window 01/01/2008 01/01/2009
"""
from __future__ import annotations

import argparse
import io

from vn_admin_units.crosswalk import read_district_crosswalk, read_province_history_crosswalk
from vn_admin_units.rawcache import save_raw

URL = "https://danhmuchanhchinh.nso.gov.vn/Doi_Chieu_Moi.aspx"

_CAP = "ctl00_PlaceHolderMain_cmbCap"
_BASE = "ctl00_PlaceHolderMain_txtNgay"
_COMPARE = "ctl00_PlaceHolderMain_txtNgayDC"
_RUN = "ctl00_PlaceHolderMain_cmdThucHien"
_EXCEL = "ctl00_PlaceHolderMain_cmdExcel"

TIER_CAP = {"province": "1", "district": "2"}          # DevExpress cmbCap values
TIER_VI = {"province": "Tỉnh", "district": "Huyện"}    # manifest label
TIER_READER = {"province": read_province_history_crosswalk,
               "district": read_district_crosswalk}


def _iso(ddmmyyyy: str) -> str:
    d, m, y = ddmmyyyy.split("/")
    return f"{y}-{m.zfill(2)}-{d.zfill(2)}"


def cache_relpath(tier: str, base: str, compare: str) -> str:
    """Deterministic raw-cache path for a window, namespaced by tier."""
    return f"crosswalk/{tier}_{_iso(base)}_{_iso(compare)}.xls"


def _set_date(page, control_id: str, ddmmyyyy: str) -> None:
    d, m, y = (int(x) for x in ddmmyyyy.split("/"))
    page.evaluate(
        "([id, y, m, d]) => ASPxClientControl.GetControlCollection().Get(id)"
        ".SetDate(new Date(y, m - 1, d))",
        [control_id, y, m, d],
    )


def _switch_cap(page, cap_value: str) -> None:
    """Set Cấp and fire its autopostback (server switches tier mode)."""
    with page.expect_navigation(wait_until="networkidle", timeout=60000):
        page.evaluate(
            "(v) => { ASPxClientControl.GetControlCollection().Get('%s').SetValue(v);"
            " __doPostBack('ctl00$PlaceHolderMain$cmbCap',''); }" % _CAP,
            cap_value,
        )


def _fetch_window_bytes(page, base: str, compare: str) -> bytes:
    _set_date(page, _BASE, base)
    _set_date(page, _COMPARE, compare)
    page.click(f"#{_RUN}")
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("tr[class*=dxgvDataRow]", timeout=30000)
    with page.expect_download(timeout=60000) as dl:
        page.click(f"#{_EXCEL}")
    with open(dl.value.path(), "rb") as f:
        return f.read()


def fetch_windows(tier: str, windows: list[tuple[str, str]], headless: bool = True) -> list[dict]:
    """Fetch + verbatim-cache each (base, compare) window for a tier."""
    from playwright.sync_api import sync_playwright

    reader = TIER_READER[tier]
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page(accept_downloads=True)
        page.goto(URL, wait_until="networkidle", timeout=60000)
        page.wait_for_function("() => typeof ASPxClientControl !== 'undefined'")
        _switch_cap(page, TIER_CAP[tier])
        for base, compare in windows:
            data = _fetch_window_bytes(page, base, compare)
            rows = reader(io.BytesIO(data))
            relpath = cache_relpath(tier, base, compare)
            save_raw(relpath, data, {
                "source_url": URL, "method": "Excel export (Playwright)",
                "params": {"Cap": TIER_VI[tier], "base": base, "compare": compare},
                "rows": len(rows)})
            print(f"  [{relpath}] {len(data)} bytes, {len(rows)} rows")
            results.append({"path": relpath, "rows": len(rows), "bytes": len(data)})
        browser.close()
    return results


def yearly_windows(start_year: int, end_year: int) -> list[tuple[str, str]]:
    return [(f"01/01/{y}", f"01/01/{y + 1}") for y in range(start_year, end_year + 1)]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Fetch Đối Chiếu crosswalk windows.")
    ap.add_argument("--tier", choices=list(TIER_CAP), required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--window", nargs=2, metavar=("BASE", "COMPARE"))
    g.add_argument("--sweep", nargs=2, type=int, metavar=("START_YEAR", "END_YEAR"))
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args(argv)
    windows = [tuple(a.window)] if a.window else yearly_windows(*a.sweep)
    print(f"Fetching {len(windows)} {a.tier} window(s)...")
    fetch_windows(a.tier, windows, headless=not a.headed)
    print("Done.")


if __name__ == "__main__":
    main()
```

> Note: `read_province_history_crosswalk` is created in Task 2. This import will fail until then — that's why Task 2 follows immediately. To keep Task 1's unit test green now, Task 2's test-first step defines the function; run Task 1's test again after Task 2 if needed. (The two config tests don't import the reader path.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_crosswalk_fetch.py -q`
Expected: PASS (2 tests). If an ImportError on `read_province_history_crosswalk` appears, do Task 2 first, then re-run.

- [ ] **Step 5: Commit**

```bash
git add src/vn_admin_units/crosswalk_fetch.py tests/test_crosswalk_fetch.py
git commit -m "feat(phase1b): parameterize crosswalk fetcher by tier (province=Cấp 1)"
```

---

## Task 2: 9-column province-history crosswalk reader

**Files:**
- Modify: `src/vn_admin_units/crosswalk.py`
- Test: `tests/test_province_history_crosswalk.py`, `tests/fixtures/province_2008_2009.xls` (a real fetched window, added in Step 0)

Probe-confirmed 9-column positional layout (wider than the 7-col named reform export):
`[base_ma, base_ten, base_ND, base_hieuluc, succ_ten, succ_ma, succ_ND, succ_hieuluc, ghi_chu]`.

- [ ] **Step 0: Fetch the fixture window live** (2008→2009 — the clean Hà Tây case)

Run: `uv run --group ingest python -m vn_admin_units.crosswalk_fetch --tier province --window 01/01/2008 01/01/2009`
Expected: caches `data/raw/crosswalk/province_2008-01-01_2009-01-01.xls`. Copy it to the fixture path:
`cp data/raw/crosswalk/province_2008-01-01_2009-01-01.xls tests/fixtures/province_2008_2009.xls`
(If Playwright/browser is unavailable in the exec environment, ask the user to run the fetch line; it needs their Chrome session per journal `.01`.)

- [ ] **Step 1: Write the failing test** (`tests/test_province_history_crosswalk.py`)

```python
from vn_admin_units.crosswalk import read_province_history_crosswalk

def test_reads_9col_and_isolates_ha_tay_merge():
    rows = read_province_history_crosswalk("tests/fixtures/province_2008_2009.xls")
    by_base = {r["base_ma"]: r for r in rows}
    # Hà Tây (28) dissolved, prose names the successor
    assert by_base["28"]["succ_ma"] == ""
    assert "Hà Nội" in by_base["28"]["ghi_chu"]           # "Sáp nhập vào Thành phố Hà Nội"
    assert by_base["28"]["succ_hieuluc"] == "" or by_base["28"]["succ_hieuluc"]
    # Hà Nội (01) is the surviving successor with the 2008-08-01 effective date
    han = by_base["01"]
    assert han["succ_ma"] == "01" and han["succ_hieuluc"] == "2008-08-01"

def test_new_side_rows_have_blank_base():
    rows = read_province_history_crosswalk("tests/fixtures/province_2008_2009.xls")
    # every row exposes the 9 normalized fields
    assert all({"base_ma","succ_ma","succ_ten","succ_hieuluc","ghi_chu"} <= set(r) for r in rows)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_province_history_crosswalk.py -q`
Expected: FAIL — `read_province_history_crosswalk` not defined.

- [ ] **Step 3: Add the reader to `crosswalk.py`** (reuse the existing `_clean`/`_excel_date`/`_code` helpers already in the module)

```python
# Province HISTORY crosswalk (Đối Chiếu, Cấp=Tỉnh, base pre-reform) has 9 positional
# columns with duplicate base/compare "Nghị định"/"Ngày hiệu lực" — read by index,
# like the district reader. Distinct from read_province_crosswalk (7-col reform export).
_PROVINCE_HISTORY_COLS = [
    "base_ma", "base_ten", "base_nghi_dinh", "base_hieu_luc",
    "succ_ten", "succ_ma", "succ_nghi_dinh", "succ_hieu_luc", "ghi_chu",
]


def read_province_history_crosswalk(path) -> list[dict]:
    """Read a 9-col Đối Chiếu province-history window (.xls or file-like) into rows.

    Province codes are NOT zero-padded to 2 digits here: pre-2004 codes are 3-digit
    (e.g. '301') and post-2004 are 2-digit (e.g. '12'); keep both verbatim via _clean."""
    df = pd.read_excel(path, engine="xlrd", dtype=str, header=0).fillna("")
    out = []
    for _, r in df.iterrows():
        row = {name: _clean(r.iloc[i]) for i, name in enumerate(_PROVINCE_HISTORY_COLS)}
        row["base_hieu_luc"] = _excel_date(row["base_hieu_luc"])
        row["succ_hieu_luc"] = _excel_date(row["succ_hieu_luc"])
        out.append(row)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_province_history_crosswalk.py -q`
Expected: PASS. If the effective-date column parses to a different string, adjust the `_excel_date` expectation to the ISO the fixture actually carries (`2008-08-01`), not the assertion's intent.

- [ ] **Step 5: Commit**

```bash
git add src/vn_admin_units/crosswalk.py tests/test_province_history_crosswalk.py tests/fixtures/province_2008_2009.xls data/raw/crosswalk/province_2008-01-01_2009-01-01.xls data/raw/manifest.jsonl
git commit -m "feat(phase1b): 9-col province-history crosswalk reader + 2008 fixture"
```

---

## Task 3: Sweep the province windows + parameterized yearly SOAP roster walk

**Files:**
- Modify: `src/vn_admin_units/cli.py`
- Test: `tests/test_history_events.py` (date-generator part only here)
- Produce: `data/raw/crosswalk/province_*.xls` (sweep), `data/raw/soap/DanhMucTinh_*.xml` + `data/provinces-*.json` (yearly)

- [ ] **Step 1: Write the failing test** (`tests/test_history_events.py`) — the yearly-date generator (pure)

```python
from vn_admin_units.cli import history_snapshot_dates

def test_history_snapshot_dates_span_2002_to_2025():
    dates = history_snapshot_dates()
    assert dates[0] == ("2002-01-01", "01/01/2002")
    assert ("2005-01-01", "01/01/2005") in dates
    assert ("2008-09-01", "01/09/2008") in dates          # post-Hà Tây boundary
    assert ("2025-06-30", "30/06/2025") in dates          # 1a pre-reform boundary
    assert ("2026-07-10", "10/07/2026") not in [d for d in dates]   # 2026 out of scope
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_history_events.py -q`
Expected: FAIL — `history_snapshot_dates` not defined.

- [ ] **Step 3: Add the walk to `cli.py`**

```python
def history_snapshot_dates() -> list[tuple[str, str]]:
    """(iso, dd/mm/yyyy) yearly 01/01 snapshots 2002..2025 + the event boundaries
    that a 01/01 grid would straddle (2004 renumber service-date, 2008 Hà Tây,
    2025 pre-reform). Terminal boundary = the 2025 reform; 2026 is out of scope."""
    pairs = [(f"{y}-01-01", f"01/01/{y}") for y in range(2002, 2026)]
    pairs += [("2004-07-01", "01/07/2004"),   # just after the 30/06/2004 renumber+carve-outs
              ("2008-09-01", "01/09/2008"),   # just after 2008-08-01 Hà Tây
              ("2025-06-30", "30/06/2025")]   # 1a pre-reform boundary (already cached by 1a)
    seen, out = set(), []
    for iso, ddmm in pairs:
        if iso not in seen:
            seen.add(iso); out.append((iso, ddmm))
    return sorted(out)


def cache_history_snapshots() -> None:
    """Yearly SOAP DanhMucTinh walk 2002→2025 (event-discovery backbone).
    Reuses fetch_provinces_raw; caches verbatim + manifest + derived JSON, like
    cache_snapshots but over the historical date set (cli.py hardcodes only the two
    2025-reform boundary dates)."""
    DATA.mkdir(exist_ok=True)
    for iso, ddmmyyyy in history_snapshot_dates():
        xml = fetch_provinces_raw(ddmmyyyy)
        rows = parse_province_diffgram(xml)
        save_raw(f"soap/DanhMucTinh_{iso}.xml", xml.encode("utf-8"),
                 {"source_url": SOAP_URL, "method": "DanhMucTinh",
                  "params": {"DenNgay": ddmmyyyy}, "rows": len(rows)})
        (DATA / f"provinces-{iso}.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"cached {len(rows)} provinces @ {iso}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_history_events.py -q`
Expected: PASS.

- [ ] **Step 5: Acquire the data live** (SOAP walk + province window sweep)

Run:
```
uv run python -c "from vn_admin_units.cli import cache_history_snapshots; cache_history_snapshots()"
uv run --group ingest python -m vn_admin_units.crosswalk_fetch --tier province --sweep 2004 2024
uv run --group ingest python -m vn_admin_units.crosswalk_fetch --tier province --window 01/01/2002 01/01/2004
```
Expected: ~27 `provinces-*.json` (61 rows through 2004-01, 64 from 2004-07, 63 from 2008-09); ~22 `province_*.xls` windows cached. Spot-check `data/provinces-2004-07-01.json` has 64 and `data/provinces-2004-01-01.json` has 61.

- [ ] **Step 6: Commit**

```bash
git add src/vn_admin_units/cli.py tests/test_history_events.py data/raw/soap/ data/raw/crosswalk/province_*.xls data/raw/manifest.jsonl data/provinces-*.json
git commit -m "feat(phase1b): yearly SOAP roster walk + province window sweep 2002-2024"
```

---

## Task 4: Name normalization (tone-mark folding)

**Files:**
- Create: `src/vn_admin_units/names.py`, `tests/test_names.py`

The SOAP roster diff produced a phantom event `Tỉnh Hòa Bình` vs `Tỉnh Hoà Bình` (journal `.01`). Fold names before any comparison. (Mirror the `_bare` helper already inside `reconcile.audit_province_qids`, but as a shared function.)

- [ ] **Step 1: Write the failing test** (`tests/test_names.py`)

```python
from vn_admin_units.names import fold_name

def test_tone_mark_variants_fold_equal():
    assert fold_name("Tỉnh Hòa Bình") == fold_name("Tỉnh Hoà Bình")

def test_strips_tier_prefix_and_lowercases():
    assert fold_name("Thành phố Cần Thơ") == fold_name("thành phố  cần thơ")
    assert fold_name("Tỉnh Lào Cai") == "lao cai"

def test_distinct_names_stay_distinct():
    assert fold_name("Tỉnh Lai Châu") != fold_name("Tỉnh Điện Biên")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_names.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `names.py`**

```python
import re
import unicodedata


def fold_name(s: str) -> str:
    """Fold a VN admin-unit name for comparison: strip tier prefix, lowercase,
    collapse whitespace, and normalize tone-mark placement by dropping combining
    marks (NFD) so 'Hoà'=='Hòa'; đ→d. Keeps distinct names distinct."""
    s = re.sub(r"^(tỉnh|thành phố)\s+", "", s.strip(), flags=re.IGNORECASE).lower()
    s = re.sub(r"\s+", " ", s)
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").strip()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_names.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/vn_admin_units/names.py tests/test_names.py
git commit -m "feat(phase1b): shared name folding (tone-mark normalization)"
```

---

## Task 5: `province_history` model types

**Files:**
- Create: `src/vn_admin_units/province_history.py`
- Test: `tests/test_province_history_model.py`

- [ ] **Step 1: Write the failing test**

```python
from vn_admin_units.province_history import Entity, LineageEdge, hist_local_id

def test_local_id_is_scheme_era_aware_not_bare_code():
    # entity anchored on first-known code + valid_from; NOT p-{code}
    assert hist_local_id("11", "2004-01-01") == "ph-11-2004-01-01"
    assert hist_local_id("28", None) == "ph-28-base"          # baseline (pre-2004) root
    # a reused code with a different valid_from → distinct id
    assert hist_local_id("11", "2004-01-01") != hist_local_id("11", None)

def test_entity_terminal_code_and_roundtrip():
    e = Entity(local_id="ph-10-base", gso_codes=["205", "10"], name_vi="Tỉnh Lào Cai",
               loai_hinh="Tỉnh", type_spans=[{"loai_hinh":"Tỉnh","from":None,"to":"2025-06-30"}],
               aliases=["205"], valid_from=None, valid_to="2025-06-30",
               wikidata_qid=None, qid_status=None)
    assert e.terminal_code == "10"
    assert e.to_dict()["gso_codes"] == ["205", "10"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_province_history_model.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the types in `province_history.py`**

```python
from dataclasses import dataclass, asdict, field
from typing import Optional


def hist_local_id(first_code: str, valid_from: Optional[str]) -> str:
    """Entity-anchored id: first-known code + inception ('base' if pre-2004 root).
    Codes reuse across reforms and the scheme changes at 2004 (journal .15), so the
    bare code is never a key; valid_from disambiguates reused codes."""
    return f"ph-{first_code}-{valid_from or 'base'}"


@dataclass
class Entity:
    local_id: str
    gso_codes: list                      # chronological; [-1] = terminal/reconcile code
    name_vi: str                         # terminal name
    loai_hinh: str                       # terminal type
    type_spans: list                     # [{loai_hinh, from, to}]
    aliases: list                        # former names + former codes
    valid_from: Optional[str]
    valid_to: Optional[str]
    wikidata_qid: Optional[str]
    qid_status: Optional[str] = None     # "existing" | "new"

    @property
    def terminal_code(self) -> str:
        return self.gso_codes[-1] if self.gso_codes else ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LineageEdge:
    predecessor: str                     # local_id
    successor: str                       # local_id
    relation: str                        # "carved_from" | "absorbed_into"
    decree: str
    effective_date: str

    def to_dict(self) -> dict:
        return asdict(self)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_province_history_model.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vn_admin_units/province_history.py tests/test_province_history_model.py
git commit -m "feat(phase1b): province-history entity/lineage model types"
```

---

## Task 6: Curated 2004 carve-out decree file + loader

**Files:**
- Create: `data/decrees/2004-splits.json`
- Modify: `src/vn_admin_units/province_history.py`
- Test: `tests/test_province_history_model.py` (add)

The 2004 carve-out parentage is not in Đối Chiếu (2004 floor). Encode the three famous pairings from NQ 22/2003/QH11 (cached in `data/raw/decrees/`).

- [ ] **Step 1: Create `data/decrees/2004-splits.json`**

```json
{
  "decree": "Số: 22/2003/QH11; Ngày: 26/11/2003",
  "source": "data/raw/decrees/nq-22-2003-qh11.html",
  "reference_url": "https://thuvienphapluat.vn/van-ban/Bo-may-hanh-chinh/Nghi-quyet-22-2003-QH11-chia-va-dieu-chinh-dia-gioi-hanh-chinh-tinh-51694.aspx",
  "effective_date": "2004-01-01",
  "carve_outs": [
    {"child_code": "11", "child_name": "Tỉnh Điện Biên",  "parent_code": "12", "parent_name": "Tỉnh Lai Châu"},
    {"child_code": "67", "child_name": "Tỉnh Đắk Nông",   "parent_code": "66", "parent_name": "Tỉnh Đắk Lắk"},
    {"child_code": "93", "child_name": "Tỉnh Hậu Giang",  "parent_code": "92", "parent_name": "Thành phố Cần Thơ"}
  ]
}
```

- [ ] **Step 2: Write the failing test** (append to `tests/test_province_history_model.py`)

```python
from vn_admin_units.province_history import load_carve_outs

def test_load_carve_outs():
    co = load_carve_outs("data/decrees/2004-splits.json")
    assert co["effective_date"] == "2004-01-01"
    pairs = {(c["child_code"], c["parent_code"]) for c in co["carve_outs"]}
    assert pairs == {("11","12"), ("67","66"), ("93","92")}
    assert co["decree"].startswith("Số: 22/2003/QH11")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_province_history_model.py::test_load_carve_outs -q`
Expected: FAIL — `load_carve_outs` not defined.

- [ ] **Step 4: Add the loader to `province_history.py`**

```python
import json
from pathlib import Path


def load_carve_outs(path: str = "data/decrees/2004-splits.json") -> dict:
    """The curated 2004 carve-out pairings + decree/reference (parentage the GSO
    Đối Chiếu omits below the 2004 floor)."""
    return json.loads(Path(path).read_text(encoding="utf-8"))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_province_history_model.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add data/decrees/2004-splits.json src/vn_admin_units/province_history.py tests/test_province_history_model.py
git commit -m "feat(phase1b): curated 2004 carve-out pairings (NQ 22/2003/QH11)"
```

---

## Task 7: Event discovery — normalized roster diff

**Files:**
- Modify: `src/vn_admin_units/province_history.py`
- Test: `tests/test_history_events.py` (add)

Diff consecutive yearly snapshots on folded `(name, type)` to discover create/dissolve/retype events independently of Đối Chiếu (and it is the only view of 2002→2004).

- [ ] **Step 1: Write the failing test** (append to `tests/test_history_events.py`)

```python
from vn_admin_units.province_history import diff_roster

def test_diff_detects_create_and_retype_not_orthography():
    a = [{"ma":"815","ten":"Tỉnh Cần Thơ","loai_hinh":"Tỉnh"},
         {"ma":"305","ten":"Tỉnh Hòa Bình","loai_hinh":"Tỉnh"}]
    b = [{"ma":"92","ten":"Thành phố Cần Thơ","loai_hinh":"Thành phố Trung ương"},
         {"ma":"93","ten":"Tỉnh Hậu Giang","loai_hinh":"Tỉnh"},
         {"ma":"17","ten":"Tỉnh Hoà Bình","loai_hinh":"Tỉnh"}]   # tone-mark variant only
    d = diff_roster(a, b)
    assert d["created"] == ["Tỉnh Hậu Giang"]                    # by folded name
    assert ("Tỉnh Cần Thơ", "Thành phố Cần Thơ") in [(x["from"], x["to"]) for x in d["retyped"]]
    assert d["dissolved"] == []                                  # Hòa Bình is NOT dissolved
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_history_events.py::test_diff_detects_create_and_retype_not_orthography -q`
Expected: FAIL — `diff_roster` not defined.

- [ ] **Step 3: Add `diff_roster` to `province_history.py`**

```python
from vn_admin_units.names import fold_name


def diff_roster(before: list[dict], after: list[dict]) -> dict:
    """Folded (name→type) diff between two province snapshots. Keyed by folded name
    so the 2004 renumber (code change, same name) is NOT a create/dissolve, and
    'Hoà'/'Hòa' orthography is NOT an event. Detects created / dissolved / retyped."""
    b = {fold_name(r["ten"]): r for r in before}
    a = {fold_name(r["ten"]): r for r in after}
    created = [a[k]["ten"] for k in a.keys() - b.keys()]
    dissolved = [b[k]["ten"] for k in b.keys() - a.keys()]
    retyped = [{"from": b[k]["ten"], "to": a[k]["ten"],
                "loai_hinh_from": b[k]["loai_hinh"], "loai_hinh_to": a[k]["loai_hinh"]}
               for k in a.keys() & b.keys() if b[k]["loai_hinh"] != a[k]["loai_hinh"]]
    return {"created": sorted(created), "dissolved": sorted(dissolved), "retyped": retyped}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_history_events.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vn_admin_units/province_history.py tests/test_history_events.py
git commit -m "feat(phase1b): normalized roster-diff event discovery"
```

---

## Task 8: Assemble entities + lineage (ground-truth gated)

**Files:**
- Modify: `src/vn_admin_units/province_history.py`
- Test: `tests/test_province_history_groundtruth.py`

Assembly: start from 1a's `pre2025` province entities (the terminal roster), walk the SOAP snapshots + Đối Chiếu windows backward to attach each entity's earlier codes (2004 renumber → alias), retype spans (Cần Thơ 2004, Huế), and `valid_from` (2004-01-01 for carve-out children, else `None`/`base`); add the ended **Hà Tây** entity (`absorbed_into` Hà Nội, 2008-08-01) and the three `carved_from` edges from the decree file. This is the data-shaped step — the **ground-truth test is the gate** (like Phase-1a Task 7): extend the assembly until it passes; never weaken the assertion.

- [ ] **Step 1: Write the ground-truth test** (`tests/test_province_history_groundtruth.py`)

```python
from vn_admin_units.province_history import build_province_history

def _build():
    return build_province_history(
        snapshot_dir="data",
        window_dir="data/raw/crosswalk",
        carve_outs_path="data/decrees/2004-splits.json",
        seed_1a="mappings/provinces-qid.csv")

def test_2004_carve_outs_are_edges_children_have_inception():
    ents, edges = _build()
    by_code = {e.terminal_code: e for e in ents}
    for child, parent in [("11","12"), ("67","66"), ("93","92")]:
        ce = by_code[child]
        assert ce.valid_from == "2004-01-01"                       # inception filled in
        ed = [x for x in edges if x.successor == ce.local_id and x.relation == "carved_from"]
        assert len(ed) == 1 and by_code[parent].local_id == ed[0].predecessor
        # parent persists: no dissolution
        assert by_code[parent].valid_to in (None, "2025-06-30")

def test_carve_out_children_are_not_duplicated():
    ents, _ = _build()
    for code in ("11","67","93"):
        assert len([e for e in ents if e.terminal_code == code]) == 1

def test_2004_renumber_is_alias_not_new_entity():
    ents, _ = _build()
    lao_cai = next(e for e in ents if e.terminal_code == "10")     # survivor to 2025-reform era
    assert "205" in lao_cai.aliases and lao_cai.gso_codes[0] == "205"
    assert lao_cai.valid_to == "2025-06-30" and lao_cai.valid_from in (None,)

def test_2008_ha_tay_absorbed_into_ha_noi():
    ents, edges = _build()
    ha_tay = next(e for e in ents if e.terminal_code == "28")
    assert ha_tay.valid_to == "2008-07-31"
    ed = [x for x in edges if x.predecessor == ha_tay.local_id]
    assert len(ed) == 1 and ed[0].relation == "absorbed_into" and ed[0].effective_date == "2008-08-01"
    ha_noi = next(e for e in ents if e.terminal_code == "01")
    assert ed[0].successor == ha_noi.local_id and ha_noi.valid_to in (None, "2025-06-30")

def test_cantho_retype_span():
    ents, _ = _build()
    ct = next(e for e in ents if e.terminal_code == "92")
    types = {(s["loai_hinh"]) for s in ct.type_spans}
    assert "Tỉnh" in types and any("Thành phố" in t for t in types)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_province_history_groundtruth.py -q`
Expected: FAIL — `build_province_history` not defined.

- [ ] **Step 3: Implement `build_province_history` in `province_history.py`**

```python
import glob
from vn_admin_units.crosswalk import read_province_history_crosswalk


def _load_json(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_province_history(snapshot_dir: str, window_dir: str,
                           carve_outs_path: str, seed_1a: str):
    """Assemble the 2002→2025 province entity+lineage graph.

    Spine = the 1a pre-reform (2025-06-30) roster: one continuous Entity per
    surviving/absorbed province. Enrich each with earlier codes (2004 renumber →
    alias), retype spans, and valid_from; add the ended Hà Tây; attach the 2004
    carve-out edges from the decree and the 2008 absorption from the window."""
    terminal = _load_json(f"{snapshot_dir}/provinces-2025-06-30.json")      # 63 rows
    base2002 = _load_json(f"{snapshot_dir}/provinces-2002-01-01.json")      # 61 rows
    post2004 = _load_json(f"{snapshot_dir}/provinces-2004-07-01.json")      # 64 rows
    co = load_carve_outs(carve_outs_path)
    carve_child_codes = {c["child_code"] for c in co["carve_outs"]}

    # 2004 renumber map: old 3-digit -> new 2-digit, by folded name, from the
    # 2002→2004 window (blank-succ rows excluded).
    renumber = {}   # folded name -> {"old": code3, "new": code2}
    for row in read_province_history_crosswalk(f"{window_dir}/province_2002-01-01_2004-01-01.xls"):
        if row["base_ma"] and row["succ_ma"]:
            renumber[fold_name(row["base_ten"])] = {"old": row["base_ma"], "new": row["succ_ma"]}

    ents: list[Entity] = []
    by_code: dict[str, Entity] = {}
    for r in terminal:
        code2 = r["ma"]
        fn = fold_name(r["ten"])
        old3 = renumber.get(fn, {}).get("old")
        gso_codes = [old3, code2] if old3 else [code2]
        aliases = [old3] if old3 else []
        is_child = code2 in carve_child_codes
        vf = co["effective_date"] if is_child else None
        e = Entity(local_id=hist_local_id(gso_codes[0], vf), gso_codes=gso_codes,
                   name_vi=r["ten"], loai_hinh=r["loai_hinh"],
                   type_spans=[{"loai_hinh": r["loai_hinh"], "from": vf, "to": "2025-06-30"}],
                   aliases=aliases, valid_from=vf, valid_to="2025-06-30",
                   wikidata_qid=None, qid_status=None)
        ents.append(e); by_code[code2] = e

    edges: list[LineageEdge] = []

    # 2004 carve-outs: child (already in ents) carved_from parent; both from decree.
    for c in co["carve_outs"]:
        child, parent = by_code.get(c["child_code"]), by_code.get(c["parent_code"])
        if child and parent:
            edges.append(LineageEdge(parent.local_id, child.local_id, "carved_from",
                                     co["decree"], co["effective_date"]))

    # Cần Thơ retype (province -> city) at 2004: prepend a Tỉnh span before the city span.
    ct = by_code.get("92")
    if ct and ct.loai_hinh.startswith("Thành phố"):
        ct.type_spans = [{"loai_hinh": "Tỉnh", "from": None, "to": "2004-06-30"}] + ct.type_spans
        ct.aliases.append("Tỉnh Cần Thơ")

    # 2008 Hà Tây absorption: Hà Tây is NOT in the 2025 roster -> add it, ended.
    ht_window = read_province_history_crosswalk(f"{window_dir}/province_2008-01-01_2009-01-01.xls")
    ht = next((r for r in ht_window if fold_name(r["base_ten"]) == "ha tay"), None)
    if ht:
        ht_e = Entity(local_id=hist_local_id(ht["base_ma"], None), gso_codes=[ht["base_ma"]],
                      name_vi=ht["base_ten"], loai_hinh="Tỉnh",
                      type_spans=[{"loai_hinh": "Tỉnh", "from": None, "to": "2008-07-31"}],
                      aliases=[], valid_from=None, valid_to="2008-07-31",
                      wikidata_qid=None, qid_status=None)
        ents.append(ht_e)
        ha_noi = by_code.get("01")
        if ha_noi:
            edges.append(LineageEdge(ht_e.local_id, ha_noi.local_id, "absorbed_into",
                                     "Số: 15/2008/QH12", "2008-08-01"))

    return ents, edges
```

> **Iteration note (house style):** run Step 4; if a ground-truth assertion fails, extend `build_province_history` against the *real* fetched data — e.g. the Huế retype (add a span when the terminal type is a city and a pre-2025 snapshot shows a province), or a renumber-map miss. Do **not** weaken the tests. Log any province the assembly can't classify to a manual-curation file (`data/province-history-residue.json`) rather than dropping it silently.

- [ ] **Step 4: Run the ground-truth suite**

Run: `uv run pytest tests/test_province_history_groundtruth.py -q`
Expected: all PASS. The 2008 decree number `15/2008/QH12` is the Hà Tây resolution — verify against the Nghị quyết list during Task 10's reference step; if unconfirmed, source it there and update the string.

- [ ] **Step 5: Commit**

```bash
git add src/vn_admin_units/province_history.py tests/test_province_history_groundtruth.py
git commit -m "feat(phase1b): assemble province history (carve-outs, renumber, 2008); ground-truth gated"
```

---

## Task 9: Reconciliation — separate local_id-keyed mapping + extended audit

**Files:**
- Modify: `src/vn_admin_units/reconcile.py`
- Test: `tests/test_history_reconcile.py`
- Produce: `mappings/provinces-history-qid.csv`

Reuse 1a QIDs (read-only); reconcile fresh only Hà Tây; write a **new** file (never grow `provinces-qid.csv` — its `_write_csv` would clobber extra columns/rows). Extend the audit to cover all historical entities.

- [ ] **Step 1: Write the failing test** (`tests/test_history_reconcile.py`)

```python
from vn_admin_units.reconcile import reuse_1a_qids
from vn_admin_units.province_history import Entity

def _ent(code, name, valid_from=None):
    return Entity(f"ph-{code}-x", [code], name, "Tỉnh",
                  [{"loai_hinh":"Tỉnh","from":valid_from,"to":"2025-06-30"}], [],
                  valid_from, "2025-06-30", None, None)

def test_reuse_1a_qids_by_terminal_code_and_era():
    ents = [_ent("11","Tỉnh Điện Biên","2004-01-01"), _ent("28","Tỉnh Hà Tây")]
    out = reuse_1a_qids(ents, "mappings/provinces-qid.csv")
    d = {e.terminal_code: e for e in out}
    assert d["11"].wikidata_qid == "Q36955" and d["11"].qid_status == "existing"  # from 1a pre2025
    assert d["28"].wikidata_qid is None                                           # Hà Tây not in 1a -> fresh
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_history_reconcile.py -q`
Expected: FAIL — `reuse_1a_qids` not defined.

- [ ] **Step 3: Add to `reconcile.py`** (new functions; do not touch `HEADER`/`_write_csv`/`load_seed`/`audit_province_qids`)

```python
HISTORY_HEADER = ["local_id", "terminal_code", "name_vi", "wikidata_qid", "qid_status", "match_status"]


def reuse_1a_qids(entities: list, seed_1a_path: str = "mappings/provinces-qid.csv") -> list:
    """Fill wikidata_qid/qid_status from 1a's (gso_code, era='pre2025') mapping by
    terminal_code. Entities absent from 1a (e.g. Hà Tây, dissolved 2008) stay None
    for fresh reconciliation."""
    seed = {}
    import csv as _csv
    from pathlib import Path as _P
    for row in _csv.DictReader(_P(seed_1a_path).read_text(encoding="utf-8").splitlines()):
        if row["era"] == "pre2025":
            seed[row["gso_code"]] = (row["wikidata_qid"], row.get("qid_status", "existing"))
    for e in entities:
        hit = seed.get(e.terminal_code)
        if hit:
            e.wikidata_qid, e.qid_status = hit
    return entities


def write_history_mapping(entities: list, out_path: str = "mappings/provinces-history-qid.csv") -> None:
    """Write the local_id-keyed history mapping (separate file — never mutates
    provinces-qid.csv)."""
    from pathlib import Path as _P
    lines = [",".join(HISTORY_HEADER)]
    for e in entities:
        lines.append(",".join([e.local_id, e.terminal_code, e.name_vi,
                               e.wikidata_qid or "", e.qid_status or "",
                               "reused" if e.wikidata_qid else "needs-lookup"]))
    _P(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def audit_history_qids(mapping_path: str = "mappings/provinces-history-qid.csv") -> list[str]:
    """Pre-upload audit over ALL history entities (1a's audit only checks era==pre2025).
    Flags unresolved QIDs and runs the name+type instance-of check on every row."""
    import csv as _csv
    from pathlib import Path as _P
    rows = list(_csv.DictReader(_P(mapping_path).read_text(encoding="utf-8").splitlines()))
    issues = [f"UNRESOLVED {r['local_id']} {r['name_vi']}" for r in rows if not r["wikidata_qid"]]
    qids = sorted({r["wikidata_qid"] for r in rows if r["wikidata_qid"]})
    inst = wd_claims_ids(qids, "P31")                       # reuse 1a helper
    tl = wd_labels(sorted({t for v in inst.values() for t in v}))
    for r in rows:
        if not r["wikidata_qid"]:
            continue
        labels = [tl.get(t, t).lower() for t in inst.get(r["wikidata_qid"], [])]
        want_city = r["name_vi"].startswith("Thành phố")
        type_ok = any(("city" in l or "municipal" in l) for l in labels) if want_city \
            else any("province" in l for l in labels)
        if not type_ok:
            issues.append(f"TYPE {r['local_id']} {r['name_vi']} {r['wikidata_qid']} -> {labels}")
    return issues
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_history_reconcile.py -q`
Expected: PASS.

- [ ] **Step 5: Produce + manually verify the mapping** — build the entities (Task 8), `reuse_1a_qids`, `write_history_mapping`, then for the `needs-lookup` rows (Hà Tây) run `wd_search("Tỉnh Hà Tây")`, confirm the item is the dissolved province (P31 former province / P131 Vietnam; NOT the modern-day misuse), and set its QID + `match_status=verified` by hand. Run `audit_history_qids()` and resolve every flagged row.

```bash
uv run python -c "from vn_admin_units.province_history import build_province_history as B; from vn_admin_units.reconcile import reuse_1a_qids, write_history_mapping; e,_=B('data','data/raw/crosswalk','data/decrees/2004-splits.json','mappings/provinces-qid.csv'); write_history_mapping(reuse_1a_qids(e))"
```

- [ ] **Step 6: Commit**

```bash
git add src/vn_admin_units/reconcile.py tests/test_history_reconcile.py mappings/provinces-history-qid.csv
git commit -m "feat(phase1b): history reconciliation (reuse 1a QIDs; separate mapping; extended audit)"
```

---

## Task 10: Emit — relation-aware history QuickStatements

**Files:**
- Modify: `src/vn_admin_units/emit.py`
- Test: `tests/test_history_emit.py`

Add `emit_history_quickstatements` (leave 1a's `emit_quickstatements` untouched). Rules from `DESIGN-phase1b.md` §Emit:
- **`P571`** on carve-out children (child `valid_from` known) — **gated on `valid_from`, not `qid_status`** (children reuse existing items yet still need inception).
- **`P807`** child→parent for `carved_from`.
- **`P31` retype** date-qualified (`P580`) per non-terminal type span.
- **`P576`+`P7888`+`P1366`** on an `absorbed_into` predecessor; successor **`P1365`**→predecessor; `P585`=effective date.
- **Recode** → no statement (former code is an alias).
- **Skip same-QID edges.** Every statement referenced (`S854` reference URL; carve-outs use the decree's `reference_url`).

- [ ] **Step 1: Write the failing test** (`tests/test_history_emit.py`)

```python
from vn_admin_units.province_history import Entity, LineageEdge
from vn_admin_units.emit import emit_history_quickstatements

def _e(code, name, qid, vf=None, status="existing", vto="2025-06-30", spans=None):
    return Entity(f"ph-{code}-x", [code], name, "Tỉnh",
                  spans or [{"loai_hinh":"Tỉnh","from":vf,"to":vto}], [], vf, vto, qid, status)

def test_carve_out_emits_p571_despite_existing_item_and_p807():
    parent = _e("12","Tỉnh Lai Châu","Q19608")
    child = _e("11","Tỉnh Điện Biên","Q36955", vf="2004-01-01", status="existing")
    edges = [LineageEdge(parent.local_id, child.local_id, "carved_from",
                         "Số: 22/2003/QH11; Ngày: 26/11/2003", "2004-01-01")]
    qs = emit_history_quickstatements([parent, child], edges,
                                      ref_url="https://thuvienphapluat.vn/...51694.aspx")
    assert "Q36955\tP571\t+2004-01-01T00:00:00Z/11" in qs        # inception even though existing
    assert "Q36955\tP807\tQ19608" in qs                          # separated from parent
    assert "Q19608\tP576" not in qs                              # parent persists

def test_absorption_emits_dissolution_and_succession():
    ha_tay = _e("28","Tỉnh Hà Tây","Q158668", vto="2008-07-31")
    ha_noi = _e("01","Thành phố Hà Nội","Q1858")
    edges = [LineageEdge(ha_tay.local_id, ha_noi.local_id, "absorbed_into",
                         "Số: 15/2008/QH12", "2008-08-01")]
    qs = emit_history_quickstatements([ha_tay, ha_noi], edges, ref_url="https://x")
    assert "Q158668\tP576\t+2008-08-01T00:00:00Z/11" in qs
    assert "Q158668\tP7888\tQ1858\tP585\t+2008-08-01T00:00:00Z/11" in qs
    assert "Q1858\tP1365\tQ158668" in qs
    assert "Q1858\tP576" not in qs                               # absorber persists

def test_retype_span_is_dated():
    ct = _e("92","Thành phố Cần Thơ","Q1552", vf=None, status="existing",
            spans=[{"loai_hinh":"Tỉnh","from":None,"to":"2004-06-30"},
                   {"loai_hinh":"Thành phố Trung ương","from":"2004-06-30","to":"2025-06-30"}])
    qs = emit_history_quickstatements([ct], [], ref_url="https://x")
    assert "Q1552\tP31\t" in qs and "P580\t+2004-06-30T00:00:00Z/11" in qs
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_history_emit.py -q`
Expected: FAIL — `emit_history_quickstatements` not defined.

- [ ] **Step 3: Add `emit_history_quickstatements` to `emit.py`** (reuse the existing `_date`)

```python
# WD item QIDs for the two admin-unit types (verify at emit time; overridable).
P31_PROVINCE = "Q13079705"       # province of Vietnam
P31_CITY_TW = "Q3623867"         # centrally-run city of Vietnam


def emit_history_quickstatements(entities: list, edges: list, ref_url: str) -> str:
    """Relation-aware QuickStatements for the 2002→2025 province history.
    See DESIGN-phase1b.md §Emit. `ref_url` backs S854 (use the decree URL for
    carve-outs / 2008; the NSO source otherwise)."""
    by_id = {e.local_id: e for e in entities}
    ref = f'S854\t"{ref_url}"'
    out: list[str] = []
    seen: set[str] = set()

    def add(line: str) -> None:
        if line not in seen:
            seen.add(line); out.append(line)

    # Entity-level: retype spans (date-qualified P31) + carve-out inception (P571).
    for e in entities:
        if not e.wikidata_qid:
            continue
        # P571 gated on known valid_from (NOT qid_status). Audit existing claims first
        # in the manual pre-upload step; emit unconditionally here so it is never skipped.
        if e.valid_from:
            add(f"{e.wikidata_qid}\tP571\t{_date(e.valid_from)}\t{ref}")
        # retype: emit a dated P31 for each span whose start date is known (skip the
        # open-ended baseline span so we never backdate).
        for span in e.type_spans:
            if not span.get("from"):
                continue
            target = P31_CITY_TW if span["loai_hinh"].startswith("Thành phố") else P31_PROVINCE
            add(f"{e.wikidata_qid}\tP31\t{target}\tP580\t{_date(span['from'])}\t{ref}")

    # Edges.
    for ed in edges:
        pre, post = by_id[ed.predecessor], by_id[ed.successor]
        if not (pre.wikidata_qid and post.wikidata_qid):
            continue
        if pre.wikidata_qid == post.wikidata_qid:
            continue                                    # same-QID survivor edited in place
        eff = _date(ed.effective_date)
        if ed.relation == "carved_from":
            # predecessor is the PARENT (persists); successor is the new CHILD.
            add(f"{post.wikidata_qid}\tP807\t{pre.wikidata_qid}\t{ref}")
        elif ed.relation == "absorbed_into":
            add(f"{pre.wikidata_qid}\tP576\t{eff}\t{ref}")
            add(f"{pre.wikidata_qid}\tP7888\t{post.wikidata_qid}\tP585\t{eff}\t{ref}")
            add(f"{pre.wikidata_qid}\tP1366\t{post.wikidata_qid}\tP585\t{eff}\t{ref}")
            add(f"{post.wikidata_qid}\tP1365\t{pre.wikidata_qid}\tP585\t{eff}\t{ref}")
    return ("\n".join(out) + "\n") if out else ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_history_emit.py -q`
Expected: PASS (3 tests). The `P31` target QIDs (`Q13079705`, `Q3623867`) must be confirmed against live WD in Task 11; if different, update the constants (the tests only assert the `P31`+`P580` shape, so they stay green).

- [ ] **Step 5: Commit**

```bash
git add src/vn_admin_units/emit.py tests/test_history_emit.py
git commit -m "feat(phase1b): relation-aware history emitter (P571/P807/P31-retype/absorption)"
```

---

## Task 11: Extend the constraints gate (P580/P582 + P807 value-type)

**Files:**
- Modify: `src/vn_admin_units/constraints.py`
- Test: `tests/test_constraints.py` (add)

1a's tool only checks allowed qualifiers for one hard-coded qualifier (`P585`). Phase 1b needs: is `P580`/`P582` an allowed qualifier on `P31`, and do `P807`'s subject/value-type constraints admit administrative-territorial-entity.

- [ ] **Step 1: Write the failing test** (append to `tests/test_constraints.py`)

```python
from vn_admin_units import constraints as C

def test_allowed_qualifiers_accepts_a_qualifier_param(monkeypatch):
    # allowed_qualifiers should report the set; caller checks membership for any PID.
    monkeypatch.setattr(C, "_get_json", lambda *a, **k: {
        "entities": {"P31": {"claims": {C.PROPERTY_CONSTRAINT: []}}}})
    assert C.allowed_qualifiers("P31") in (None, set())   # declared-none or unconstrained

def test_check_qualifier_membership_helper():
    assert C.qualifier_allowed({"P580", "P582"}, "P580") is True
    assert C.qualifier_allowed({"P585"}, "P580") is False
    assert C.qualifier_allowed(None, "P580") is True      # no constraint declared => allowed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_constraints.py -q`
Expected: FAIL — `qualifier_allowed` not defined.

- [ ] **Step 3: Add the membership helper + widen `main` to report the Phase-1b combos**

```python
def qualifier_allowed(allowed: set | None, qualifier_pid: str) -> bool:
    """True if `qualifier_pid` is permitted: None = no allowed-qualifiers constraint
    declared (anything allowed); otherwise membership in the allowed set."""
    return True if allowed is None else qualifier_pid in allowed
```

Then extend `main` to check the Phase-1b property/qualifier pairs and the `P807` value-type (report-only, like the existing tool):

```python
PHASE1B_CHECKS = [("P31", "P580"), ("P31", "P582"), ("P7888", "P585"),
                  ("P1365", "P585"), ("P1366", "P585")]
# P807 value-type: fetch its constraints and print the allowed value-type classes so
# the operator can confirm "administrative territorial entity" is admitted.
```

Add, inside `main`, after the existing loop:

```python
    print("\n=== Phase-1b qualifier checks ===")
    for pid, qual in PHASE1B_CHECKS:
        aq = allowed_qualifiers(pid)
        print(f"  {pid} + {qual}: {'OK' if qualifier_allowed(aq, qual) else 'DISALLOWED'}")
    print("  P807 value-type: inspect https://www.wikidata.org/wiki/Property:P807 "
          "for 'administrative territorial entity' in the value-type constraint.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_constraints.py -q`
Expected: PASS.

- [ ] **Step 5: Run the gate live (report)**

Run: `uv run python -m vn_admin_units.constraints P31 P7888 P1365 P1366 P807`
Expected: prints OK/DISALLOWED per combo. Record the result in the plan's Task-12 spot-check; if any combo is DISALLOWED, adjust emit (e.g. move a qualifier) before upload.

- [ ] **Step 6: Commit**

```bash
git add src/vn_admin_units/constraints.py tests/test_constraints.py
git commit -m "feat(phase1b): extend constraints gate (P580/P582, P807 value-type)"
```

---

## Task 12: Wire the pipeline + produce artifacts (no upload)

**Files:**
- Modify: `src/vn_admin_units/cli.py`
- Test: `tests/test_pipeline.py` (add)
- Produce: `data/provinces-history.json`, `data/province-history-lineage.json`, `statements/na-provinces-history.qs`

- [ ] **Step 1: Add `build_province_history_all` to `cli.py`**

```python
def build_province_history_all() -> None:
    from vn_admin_units.province_history import build_province_history, load_carve_outs
    from vn_admin_units.reconcile import reuse_1a_qids, write_history_mapping
    from vn_admin_units.emit import emit_history_quickstatements
    ents, edges = build_province_history("data", "data/raw/crosswalk",
                                         "data/decrees/2004-splits.json",
                                         "mappings/provinces-qid.csv")
    ents = reuse_1a_qids(ents, "mappings/provinces-qid.csv")
    # (Hà Tây QID filled in by the manual verify step, Task 9 Step 5, then re-run.)
    write_history_mapping(ents)
    DATA.mkdir(exist_ok=True)
    (DATA / "provinces-history.json").write_text(
        json.dumps([e.to_dict() for e in ents], ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA / "province-history-lineage.json").write_text(
        json.dumps([e.to_dict() for e in edges], ensure_ascii=False, indent=2), encoding="utf-8")
    ref = load_carve_outs("data/decrees/2004-splits.json")["reference_url"]
    Path("statements").mkdir(exist_ok=True)
    Path("statements/na-provinces-history.qs").write_text(
        emit_history_quickstatements(ents, edges, ref_url=ref), encoding="utf-8")
    print(f"built {len(ents)} entities, {len(edges)} lineage edges")
```

- [ ] **Step 2: Write the integration test** (`tests/test_pipeline.py`, add)

```python
def test_build_province_history_all_artifacts():
    from vn_admin_units.cli import build_province_history_all
    import json
    from pathlib import Path
    build_province_history_all()
    ents = json.loads(Path("data/provinces-history.json").read_text(encoding="utf-8"))
    codes = {e["gso_codes"][-1] for e in ents}
    assert {"11","67","93","28","01"} <= codes                 # carve-out children + Hà Tây + Hà Nội
    qs = Path("statements/na-provinces-history.qs").read_text(encoding="utf-8")
    # regression guards (DESIGN-phase1b §Testing):
    for line in qs.splitlines():
        p = line.split("\t")
        if len(p) >= 3 and p[1] in {"P7888","P1366","P1365","P807"}:
            assert p[0] != p[2], f"self-referential statement: {line}"
    assert "P576" in qs and "P807" in qs and "P571" in qs
    assert "S854" in qs
```

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest -q`
Expected: all tests PASS (the 27 existing 1a tests are untouched; new Phase-1b tests green).

- [ ] **Step 4: Generate artifacts for real**

Run: `uv run python -c "from vn_admin_units.cli import build_province_history_all; build_province_history_all()"`
Expected: `built N entities, M lineage edges` (N ≈ 64: 63 terminal + Hà Tây; M ≥ 4: 3 carve-outs + 1 absorption).

- [ ] **Step 5: Manual spot-check `statements/na-provinces-history.qs`** — confirm:
  - Three carve-out blocks: `Q<child> P571 +2004-01-01…`, `Q<child> P807 Q<parent>`; **no `P576` on Lai Châu/Đắk Lắk/Cần Thơ**.
  - Hà Tây block: `Q<hatay> P576 +2008-08-01…`, `P7888`/`P1366` → Hà Nội; `Q<hanoi> P1365 → Q<hatay>`; **no `P576` on Hà Nội**.
  - Cần Thơ retype: dated `P31 … P580 +2004-06-30`.
  - Every line carries `S854`; no self-referential `Pxxx Qx Qx`.
  - Run `reconcile.audit_history_qids()` → zero unresolved/type issues. Run the Task-11 constraints gate → all combos OK.
  - **Do not upload** — emission only; upload is a separate reviewed step after the audit + constraints gates pass (personal WD account).

- [ ] **Step 6: Commit**

```bash
git add src/vn_admin_units/cli.py tests/test_pipeline.py data/provinces-history.json data/province-history-lineage.json statements/na-provinces-history.qs mappings/provinces-history-qid.csv
git commit -m "feat(phase1b): wire province-history pipeline; emit 2002-2025 QuickStatements"
```

---

## Deferred / out of scope (explicit)

- **Upload** the batch (separate reviewed step; after audit + constraints gates).
- **Đồng Nai 2026-04-30** retype (post-reform freshness; needs a dated `P31` span when done).
- **Huế 2025-01** retype: if the sweep surfaces it, it is handled by the same retype-span path in Task 8/10; confirm its decree (NQ 175/2024/QH15) in the reference step.
- **Pre-2002 ancestry**, **district/ward tiers**, **Goal A exports** — later phases.
- **Tier-neutral-core refactor** of `model.py`/`emit.py` — Phase 2 kickoff (Approach 1).

## Self-review notes

- **Spec coverage:** data acquisition (T1–T3), name normalization (T4), model (T5–T6), event discovery (T7), assembly (T8, ground-truth gated), reconciliation with separate mapping + extended audit (T9), relation-aware emit (T10), constraints extension (T11), wiring + regression-guarded integration (T12). Maps to every section of `DESIGN-phase1b.md`.
- **Review findings baked in:** carve-outs reuse 1a QIDs (T9), `P571` gated on `valid_from` not `qid_status` (T10 + test), separate `provinces-history-qid.csv` to avoid the `_write_csv` clobber (T9), audit extended past `pre2025` (T9), `cache_snapshots` parameterized not reused (T3), dated retypes / Đồng Nai out of scope (T3/T10), constraints tool extended not just re-run (T11).
- **Type consistency:** `Entity.terminal_code`, `gso_codes`, `type_spans`, `valid_from`; `LineageEdge.relation ∈ {carved_from, absorbed_into}`; `hist_local_id`; `read_province_history_crosswalk`; `emit_history_quickstatements` — names identical across tasks.
- **Data-dependent iteration (house style):** T8 is gated by `tests/test_province_history_groundtruth.py`; extend the assembly against real fetched data until green, never weaken the assertions; unclassifiable provinces go to a logged residue file.
- **Unverified externals to confirm during execution (flagged in-task, not placeholders):** the Hà Tây 2008 decree string (`15/2008/QH12`), the Hà Tây QID (manual verify, T9), and the `P31` type-target QIDs (`Q13079705`/`Q3623867`, T11 gate).
