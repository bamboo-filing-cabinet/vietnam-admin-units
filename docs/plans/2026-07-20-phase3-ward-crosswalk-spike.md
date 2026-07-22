# Phase 3 Ward-Crosswalk Spike Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the district-proven Đối Chiếu crosswalk-sweep method works at ward (Cấp=Xã) scale, measure ward-event volume across representative windows, settle the yearly-window blind-spot question, and produce a probe journal with a go/no-go and a recommended build order for the ward build.

**Architecture:** Minimally extend the existing Playwright fetcher (`crosswalk_fetch.py`) to drive Cấp=Xã, add a positional-column reader (`read_ward_crosswalk`) mirroring `read_district_crosswalk`, pull a handful of representative windows into the verbatim raw cache, then characterize them and write a decision journal. No entity/lineage build, no Wikidata output.

**Tech Stack:** Python 3.11+, `uv`, `pandas`+`xlrd` (parse), Playwright/chromium (`ingest` dep group, drives the DevExpress WebForms export), `pytest`.

**Design spec:** `docs/DESIGN-phase3-ward-crosswalk-spike.md`.

**Repo conventions that override skill defaults:** solo repo, work on `main` (no branch/worktree — see README Phase-2 note). Commit granularity mirrors the existing history (small `feat:`/`chore:` commits); the maintainer gates when commits actually happen — treat the `Commit` steps as "changes are commit-ready," and get the go-ahead before pushing.

**Live-data note (inherent to a spike):** the parser ground-truth (Task 3, Step 6) and the volume numbers (Task 5) come from live GSO data this spike fetches. Where a literal value cannot be known until the fetch runs, the step gives an exact, mechanical procedure to derive and lock it — that is deliberate, not a placeholder.

---

## Files

- **Modify** `src/vn_admin_units/crosswalk_fetch.py` — add `ward` to `TIER_CAP`/`TIER_VI`/`TIER_READER`; guard the reader lookup so a window can be fetched before its reader exists; add `ward` to the `--tier` choices.
- **Modify** `src/vn_admin_units/crosswalk.py` — add `read_ward_crosswalk` + its `_WARD_COLS` positional column list.
- **Create** `tests/test_ward_crosswalk.py` — reader tests against a real cached ward window.
- **Create (data, cached)** `data/raw/crosswalk/ward_*.xls` + `manifest.jsonl` entries — the representative windows.
- **Modify** `docs/DESIGN.md` — retire the stale "hybrid: Lịch Sử events" assumption (decision 4).
- **Modify** `docs/DESIGN-phase3.md` — its lineage-source row still lists "Lịch Sử events"; add a tight superseding note so the phase doc does not give future workers conflicting source guidance.
- **Create** `docs/journals/2026-07-20.NN.ward-crosswalk-spike.md` — the deliverable (volume table, go/no-go, recommended window list + build order).

---

## Task 1: Add Cấp=Xã support to the fetcher

**Files:**
- Modify: `src/vn_admin_units/crosswalk_fetch.py`

Rationale: `TIER_READER` is called during fetch to count rows for the manifest, but `read_ward_crosswalk` does not exist yet (Task 3 needs a fetched file to test against). So this task also guards the reader lookup so the first ward window can be fetched with `rows=None`.

- [ ] **Step 1: Add the ward tier entries and guard the reader lookup**

In `src/vn_admin_units/crosswalk_fetch.py`, change the three tier maps:

```python
TIER_CAP = {"province": "1", "district": "2", "ward": "3"}   # DevExpress cmbCap values (ward "3" to confirm live in Task 2)
TIER_VI = {"province": "Tỉnh", "district": "Huyện", "ward": "Xã"}    # manifest label
TIER_READER = {"province": read_province_history_crosswalk,
               "district": read_district_crosswalk}
               # ward reader wired in Task 3 (read_ward_crosswalk) once the schema is known
```

Then in `fetch_windows`, make the row count tolerate a missing reader:

```python
    reader = TIER_READER.get(tier)
    ...
        for base, compare in windows:
            data = _fetch_window_bytes(page, base, compare)
            rows = reader(io.BytesIO(data)) if reader else []
            relpath = cache_relpath(tier, base, compare)
            save_raw(relpath, data, {
                "source_url": URL, "method": "Excel export (Playwright)",
                "params": {"Cap": TIER_VI[tier], "base": base, "compare": compare},
                "rows": len(rows)})
            print(f"  [{relpath}] {len(data)} bytes, {len(rows)} rows"
                  + ("" if reader else "  (unparsed — no ward reader yet)"))
            results.append({"path": relpath, "rows": len(rows), "bytes": len(data)})
```

And add `ward` to the CLI `--tier` choices — this is automatic because `choices=list(TIER_CAP)` already derives from the map. Confirm the help text still reads sensibly.

- [ ] **Step 2: Verify the module imports and CLI parses**

Run: `uv run python -c "import vn_admin_units.crosswalk_fetch as m; print(m.TIER_CAP, m.TIER_VI)"`
Expected: `{'province': '1', 'district': '2', 'ward': '3'} {'province': 'Tỉnh', 'district': 'Huyện', 'ward': 'Xã'}`

- [ ] **Step 3: Confirm the existing suite still passes (no regression)**

Run: `uv run pytest -q`
Expected: PASS, same count as before this task (127).

- [ ] **Step 4: Commit**

```bash
git add src/vn_admin_units/crosswalk_fetch.py
git commit -m "feat: add Cấp=Xã (ward) tier support to crosswalk fetcher"
```

---

## Task 2: Fetch one probe ward window + confirm the combo value live

**Files:**
- Create (data): `data/raw/crosswalk/ward_2019-01-01_2020-01-01.xls` + manifest entry

This is an exploratory task against the live GSO site. It confirms Cấp=Xã actually drives the page (the served combo is populated client-side, so the `"3"` value is a hypothesis until proven) and produces the real `.xls` that Task 3's reader tests are written against.

- [ ] **Step 1: Ensure the ingest browser is installed**

Run: `uv run --group ingest playwright install chromium`
Expected: chromium present (no-op if already installed).

- [ ] **Step 2: Fetch a 2019-wave ward window (headed, so a wrong combo value is visible)**

Run: `uv run --group ingest python -m vn_admin_units.crosswalk_fetch --tier ward --window 01/01/2019 01/01/2020 --headed`
Expected: prints a line like `[crosswalk/ward_2019-01-01_2020-01-01.xls] <N> bytes, 0 rows  (unparsed — no ward reader yet)` and the file exists.

- [ ] **Step 3: Verify the fetched file is a real ward export, not an empty/error page**

Run:
```bash
uv run python -c "import pandas as pd; df = pd.read_excel('data/raw/crosswalk/ward_2019-01-01_2020-01-01.xls', engine='xlrd', dtype=str, header=0); print(df.shape); print(list(df.columns)); print(df.head(3).to_string())"
```
Expected: a DataFrame with **thousands of rows** (2019 national wards ≈ 11k) and the fixed **13-column, province-parented** header journal `2026-07-10.06` recorded from real ward exports — `Tỉnh · Tên Tỉnh · Xã · Tên Xã · Nghị định · Ngày hiệu lực` (base) · `Tên Xã DC · Xã DC · Nghị định · Ngày hiệu lực · Tên Tỉnh DC · Tỉnh DC` (compare) · `Ghi Chú`. **The export DROPS the district (`Mã QH` / `Tên QH`) columns** shown in the on-screen grid — do NOT expect them. The pre-2025 ward's district code (the disambiguation key) is therefore not in the crosswalk; it comes from SOAP at build time, out of scope here. Record the **exact column count and order** in scratch notes; Task 3 needs it. (The journal examined reform-era exports; note whether this 2019 window matches — it is expected to.)

**If Step 2 produced 0 real rows or an error page:** the ward combo value is not `"3"`. Recover it with a one-off headed probe that reads the value the page assigns when Xã is selected:
```bash
uv run --group ingest python -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(headless=False)
    pg = b.new_page(); pg.goto('https://danhmuchanhchinh.nso.gov.vn/Doi_Chieu_Moi.aspx', wait_until='networkidle')
    input('Select \"Xã\" in the Cấp dropdown in the browser window, then press Enter here... ')
    print('cmbCap value =', pg.evaluate(\"ASPxClientControl.GetControlCollection().Get('ctl00_PlaceHolderMain_cmbCap').GetValue()\"))
    b.close()
"
```
Set `TIER_CAP["ward"]` to the printed value, re-commit Task 1 Step 4 with the correction, and re-run this step. (Province=1, District=2 were confirmed the same way in `2026-07-13.02`.)

- [ ] **Step 4: Commit the cached window**

```bash
git add data/raw/crosswalk/ward_2019-01-01_2020-01-01.xls data/raw/manifest.jsonl
git commit -m "chore: cache probe ward crosswalk window 2019→2020"
```

---

## Task 3: Add `read_ward_crosswalk` (TDD against the cached window)

**Files:**
- Modify: `src/vn_admin_units/crosswalk.py`
- Test: `tests/test_ward_crosswalk.py`

The district reader reads by **positional index** because the export has duplicate `Nghị định`/`Ngày hiệu lực` headers (base + compare side). The ward export has the **same fixed 13-column shape** (journal `2026-07-10.06`), province-parented with the district columns dropped — so `_WARD_COLS` is structurally identical to `_DISTRICT_COLS`, only the unit slot is the ward code. Confirm against Task 2 Step 3's recorded column order before locking it.

- [ ] **Step 1: Define `_WARD_COLS` from the observed schema**

In `src/vn_admin_units/crosswalk.py`, add the ward column list. Journal `2026-07-10.06` recorded the ward export as a fixed 13-column, province-parented schema that **drops the district (QH) columns** — identical in shape to `_DISTRICT_COLS`, with the ward code in the `base_ma`/`succ_ma` slots. Field names are reused from the district reader so downstream code stays uniform:

```python
# Ward crosswalk (Đối Chiếu, Cấp=Xã): 13 positional columns, base side then compare
# side. Same fixed shape as _DISTRICT_COLS (journal 2026-07-10.06) — province-parented,
# the district (QH) columns are DROPPED from the export. The pre-2025 ward's district
# code (the disambiguation key) is NOT here; it comes from SOAP (DanhMucQuanHuyen) at
# build time. Confirm the exact order/count against the cached ward_*.xls (Task 2 Step 3).
_WARD_COLS = [
    "base_tinh", "base_tinh_ten",           # province code + name, base side
    "base_ma", "base_ten",                  # ward code + name, base side
    "base_nghi_dinh", "base_hieu_luc",
    "succ_ten", "succ_ma",                  # ward name + code, compare side
    "succ_nghi_dinh", "succ_hieu_luc",      # decree + effective date, compare side
    "succ_tinh_ten", "succ_tinh",           # province name + code, compare side
    "ghi_chu",
]

# Expected raw header (before pandas dedupes the duplicate base/compare names),
# in file order — the schema guard in read_ward_crosswalk compares against this so
# ANY column reorder raises instead of silently mislabeling. LOCK these strings to
# the exact header recorded in Task 2 Step 3 (verbatim spelling — note "DC" vs the
# province reader's "ĐC", and capitalization of "Nghị định"/"Ngày hiệu lực"); the
# values below are the journal 2026-07-10.06 spelling and MUST be reconciled with
# the real file before this is trusted.
_WARD_HEADER = [
    "Tỉnh", "Tên Tỉnh", "Xã", "Tên Xã", "Nghị định", "Ngày hiệu lực",
    "Tên Xã DC", "Xã DC", "Nghị định", "Ngày hiệu lực",
    "Tên Tỉnh DC", "Tỉnh DC", "Ghi Chú",
]
```

(The reader body uses `re.sub` to strip pandas' duplicate-header suffixes, so add `import re` at the top of `crosswalk.py` if it is not already imported.)

If the observed column count/order differs, adjust **both** `_WARD_COLS` and `_WARD_HEADER` to match the file exactly (the field names must stay `base_ma`/`succ_ma`/`base_hieu_luc`/`succ_hieu_luc`/`ghi_chu` for the reader body and tests below to line up). `test_effective_dates_are_iso_or_blank` (Step 2) is a secondary backstop: a mis-placed date column yields non-ISO garbage and fails it.

- [ ] **Step 2: Write the failing invariant tests**

Create `tests/test_ward_crosswalk.py`:

```python
from vn_admin_units.crosswalk import read_ward_crosswalk

# The probe window cached in Task 2 (a 2019 commune-merger-wave year).
PATH = "data/raw/crosswalk/ward_2019-01-01_2020-01-01.xls"


def test_reads_thousands_of_ward_rows():
    rows = read_ward_crosswalk(PATH)
    assert len(rows) > 9000          # ~11k national wards in 2019


def test_expected_normalized_keys_present():
    rows = read_ward_crosswalk(PATH)
    r = rows[0]
    for key in ("base_tinh", "base_ma", "base_ten", "succ_ma", "succ_hieu_luc", "ghi_chu"):
        assert key in r


def test_effective_dates_are_iso_or_blank():
    rows = read_ward_crosswalk(PATH)
    for r in rows:
        v = r["succ_hieu_luc"]
        assert v == "" or (len(v) == 10 and v[4] == "-" and v[7] == "-"), v


def test_codes_are_verbatim_strings_not_excel_floats():
    rows = read_ward_crosswalk(PATH)
    for r in rows:
        assert not r["base_ma"].endswith(".0")
        assert not r["succ_ma"].endswith(".0")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_ward_crosswalk.py -q`
Expected: FAIL with `ImportError: cannot import name 'read_ward_crosswalk'`.

- [ ] **Step 4: Implement `read_ward_crosswalk`**

Add to `src/vn_admin_units/crosswalk.py` (mirrors `read_district_crosswalk` exactly, only the column list differs):

```python
def read_ward_crosswalk(path) -> list[dict]:
    """Read a Đối Chiếu ward (Xã) .xls export into normalized rows.

    Same positional-index approach as read_district_crosswalk (duplicate base/
    compare Nghị định/Ngày hiệu lực headers). Effective dates → ISO; codes kept
    verbatim (no zero-padding — ward codes and district codes vary in width).
    Accepts a path or a file-like object."""
    df = pd.read_excel(path, engine="xlrd", dtype=str, header=0).fillna("")
    # Schema guard — the reader is POSITIONAL, so any column reorder (not just a
    # count change) shifts every field and mislabels SILENTLY. Compare the FULL
    # header against the locked _WARD_HEADER (count + order, including the middle
    # columns) so a deviating window RAISES. pandas suffixes the duplicate base/
    # compare headers (".1"); strip that before comparing. This is what lets Task 4
    # Step 4's parse loop certify every window's schema, not just column count.
    got = [re.sub(r"\.\d+$", "", str(c)).strip() for c in df.columns]
    if got != _WARD_HEADER:
        raise ValueError(
            f"ward crosswalk header does not match the locked schema; the positional "
            f"reader would mislabel. Got {got}, expected {_WARD_HEADER}")
    out = []
    for _, r in df.iterrows():
        row = {name: _clean(r.iloc[i]) for i, name in enumerate(_WARD_COLS)}
        row["base_hieu_luc"] = _excel_date(row["base_hieu_luc"])
        row["succ_hieu_luc"] = _excel_date(row["succ_hieu_luc"])
        out.append(row)
    return out
```

- [ ] **Step 5: Run the invariant tests to verify they pass**

Run: `uv run pytest tests/test_ward_crosswalk.py -q`
Expected: PASS (4 tests).

- [ ] **Step 6: Pin one real ground-truth ward event**

The specific ward values are live-data-derived, so derive them mechanically from the cached file, then hard-code them as a regression test.

Run this to surface a concrete changed row (a 2019-wave merge with a real effective date):
```bash
uv run python -c "
from vn_admin_units.crosswalk import read_ward_crosswalk
rows = read_ward_crosswalk('data/raw/crosswalk/ward_2019-01-01_2020-01-01.xls')
changed = [r for r in rows if r['succ_hieu_luc'].startswith('2019') and r['ghi_chu'].strip()]
r = changed[0]
print(repr(r['base_ma']), repr(r['base_ten']), repr(r['succ_ma']), repr(r['succ_ten']), repr(r['succ_hieu_luc']))
print(repr(r['ghi_chu'][:120]))
"
```
Take the printed values and add one pinned test to `tests/test_ward_crosswalk.py` (substitute the actual printed literals — this locks the reader against schema drift):

```python
def test_ground_truth_2019_wave_row():
    rows = read_ward_crosswalk(PATH)
    r = next(x for x in rows if x["base_ma"] == "<printed base_ma>")
    assert r["base_ten"] == "<printed base_ten>"
    assert r["succ_ma"] == "<printed succ_ma>"
    assert r["succ_hieu_luc"] == "<printed succ_hieu_luc>"   # ISO, 2019
```

Run: `uv run pytest tests/test_ward_crosswalk.py -q`
Expected: PASS (5 tests).

- [ ] **Step 7: Wire the reader into the fetcher**

In `src/vn_admin_units/crosswalk_fetch.py`, import and register it:

```python
from vn_admin_units.crosswalk import (
    read_district_crosswalk, read_province_history_crosswalk, read_ward_crosswalk,
)
...
TIER_READER = {"province": read_province_history_crosswalk,
               "district": read_district_crosswalk,
               "ward": read_ward_crosswalk}
```

- [ ] **Step 8: Full suite green**

Run: `uv run pytest -q`
Expected: PASS (132 = 127 + 5 new).

- [ ] **Step 9: Commit**

```bash
git add src/vn_admin_units/crosswalk.py src/vn_admin_units/crosswalk_fetch.py tests/test_ward_crosswalk.py
git commit -m "feat: add read_ward_crosswalk parser + wire into fetcher"
```

---

## Task 4: Fetch the representative windows

**Files:**
- Create (data): `data/raw/crosswalk/ward_2017-01-01_2018-01-01.xls`, `ward_2024-01-01_2025-01-01.xls`, `ward_2025-06-30_2025-07-01.xls` (clean reform boundary), and the flat `ward_2002-01-01_2025-06-30.xls` (or equivalent) + manifest entries.

The 2019→2020 window is already cached (Task 2). Fetch the rest. Each is one scripted headless call; the fetcher now parses + records `rows` in the manifest.

- [ ] **Step 1: Fetch the quiet-year and 2024→25 wave windows, and re-fetch 2019→2020 to backfill its count**

The 2019→2020 window was cached in Task 2 **before the reader existed**, so its manifest entry recorded `rows: 0`. Re-fetch it now that the reader is wired (Task 3 Step 7) so its manifest count is real — `save_raw` upserts by `path` (`rawcache.py`: it filters the existing same-path line and re-appends), so the re-fetch **replaces** the `rows: 0` entry in place; no stale duplicate line remains to prune.

Run:
```bash
uv run --group ingest python -m vn_admin_units.crosswalk_fetch --tier ward --window 01/01/2019 01/01/2020
uv run --group ingest python -m vn_admin_units.crosswalk_fetch --tier ward --window 01/01/2017 01/01/2018
uv run --group ingest python -m vn_admin_units.crosswalk_fetch --tier ward --window 01/01/2024 01/01/2025
```
Expected: each prints `[crosswalk/ward_...xls] <bytes> bytes, <rows> rows` with rows in the ~10k range (2019 now shows its real count, not 0).

- [ ] **Step 2: Fetch the 2025 reform boundary window + inspect its schema explicitly**

The reform took effect 2025-07-01; use a **clean reform window** — base `30/06/2025` (day before), compare `01/07/2025` (reform day) — so the characterization captures the reform itself and NOT a year of post-reform churn (e.g. the Đồng Nai `2026-04-30` upgrade a current-date export picked up, journal `2026-07-10.06`). This matches the recommended build boundary (deliverable below). A separate current-date pull for post-reform freshness is out of scope for this spike.
Run: `uv run --group ingest python -m vn_admin_units.crosswalk_fetch --tier ward --window 30/06/2025 01/07/2025`
Expected: a window showing the 10,039→3,321 collapse (thousands of dissolved-side rows, ~3.3k compare-side wards).

**Verify the schema on this window explicitly.** The 13-column province-parented schema is journal-confirmed *at the reform boundary* — the two real exports in `2026-07-10.06` were both reform-era (base `30/06/2025`). The district columns are already absent on both sides, so there is no "district column shift" to fear; the residual risk is a **differing column count or order between windows** (e.g. the flat 2002→2025 or a single-era 2019 window deviating), which shifts every positional field. The reader's schema guard (Task 3 Step 4) compares the **full** header against the locked `_WARD_HEADER`, so it **raises** on any count change OR reorder (including middle columns) — Task 4 Step 4's parse loop therefore certifies the schema of every window, not just its column count. Inspect the raw header here anyway, to *lock* `_WARD_HEADER` to the real spelling (this reform window is one of the two journal `2026-07-10.06` exports) before the guard is trusted:
```bash
uv run python -c "import pandas as pd; df = pd.read_excel('data/raw/crosswalk/ward_2025-06-30_2025-07-01.xls', engine='xlrd', dtype=str, header=0); print(df.shape); print(list(df.columns)); print(df.head(3).to_string())"
```
Record: (a) the compare-side distinct ward count (~3.3k expected); (b) that the column count is 13 and matches the 2019 window's order (compare side still carries `Tên Tỉnh DC · Tỉnh DC`). If any window's column count differs from the 2019 window, the positional reader needs a window-shape branch — log it as a build-time finding, do not silently mis-parse.

- [ ] **Step 3: Fetch the flat 2002→2025 code-map export**

Run: `uv run --group ingest python -m vn_admin_units.crosswalk_fetch --tier ward --window 01/01/2002 30/06/2025`
Expected: a large flat file; expect (per the district precedent) mostly `"Chuyển đổi mã 2002-2004"` boilerplate in `Ghi Chú` — this file is kept only as the ward code-remap table across the 2004 code-scheme change. NB: current ward codes are the **5-digit** `MaPhuongXa` (journal `2026-07-10.03`); the district-style "5→3" remap does NOT describe wards — record the actual old→new ward code widths observed in this file rather than assuming them.

- [ ] **Step 4: Confirm all windows parse cleanly**

Run:
```bash
uv run python -c "
from vn_admin_units.crosswalk import read_ward_crosswalk
import glob
for p in sorted(glob.glob('data/raw/crosswalk/ward_*.xls')):
    print(p, len(read_ward_crosswalk(p)))
"
```
Expected: each path prints a plausible row count, no exceptions. The reader's schema guard (Task 3 Step 4) compares each window's **full header** against the locked `_WARD_HEADER`, so this loop certifies the complete column schema (count AND order) of every window — if any window's header deviated in count or order, it would raise here, not mis-parse silently. If any window raises, log it as a build-time finding (that window needs a window-shape branch, or `_WARD_HEADER` was locked wrong), do not loosen the guard.

- [ ] **Step 5: Commit the cached windows**

```bash
git add data/raw/crosswalk/ward_*.xls data/raw/manifest.jsonl
git commit -m "chore: cache representative ward crosswalk windows (spike)"
```

---

## Task 5: Characterize the windows + blind-spot cross-check

**Files:** none (analysis feeds the journal in Task 6). Uses only the canonical `read_ward_crosswalk` parse — no ad-hoc SOAP counting.

- [ ] **Step 1: Compute the per-window volume metrics**

**CRITICAL — count per-window events by STRUCTURAL row classification (the build-proven `window_events`/`classify_change` model in `district_model.py`), NOT by `ghi_chu`-non-empty and NOT by date-filtering `succ_hieu_luc`.** Two wrong measures to avoid:
- **`ghi_chu`-non-empty is cumulative lineage, not this year's events.** A two-date crosswalk reports, for *every current unit*, its latest defining decree and that decree's `Ghi Chú` regardless of window — verified ~90× overcount on the district `2019→2020` window (372 vs. 4 real in-window changes, dates spanning 2004–2020). It reports a near-constant large number for every window.
- **Date-filtering `succ_hieu_luc` into `[base, compare)` is also wrong** — it diverges from `window_events` in *both* directions: it **over**counts rows that are structurally `unchanged` but carry an in-window date (pure code re-codes — the 621/TCTK case `classify_change` drops), and **under**counts genuine changes whose effective date sits in `base_hieu_luc` (which `window_events` falls back to, `district_model.py:76`) or is blank.

The spike's purpose is to validate the *district-proven* method at ward scale, so it must use the district-proven event definition: **a row is an event iff its base/successor columns differ structurally** — create (blank base) / dissolve (blank successor) / reparent (province differs) / rename-or-retype (name differs); a code-only re-code with the same name+province is `unchanged`. The snippet inlines this as a ward analogue of `classify_change` (the build will use a full `classify_ward_change` with ward tier vocab + `fold_ward_name`). `succ_hieu_luc` is kept only as a **date-sanity signal** (`dated_in_window`) and for the net-only probe (Step 2), never as the membership test.

Two more corrections folded in: the exact-duplicate hazard (`2026-07-10.14`) is **exact-duplicate FULL rows**, so dedupe on the full `_WARD_COLS` tuple (empirically this equalled the `base_ma`-repeat count on district data, but full-tuple is the definitionally correct measure); and report **compare-side** distinct counts, because base-side-only undercounts creation-heavy windows. **Mind the two distinct new-ward metrics** (journal `2026-07-10.06`): the reform's ~3.3k new wards are represented as distinct successor codes (`succ_distinct`), most inheriting a predecessor's code via the structured `Xã DC` link, so their rows carry a **non-blank** `base_ma`. Only **~5** rows are blank-`base_ma` "no old counterpart" units (the đặc khu). So the ~3.3k figure is `succ_distinct`, NOT the blank-base `created` count — keep them separate.

```bash
uv run python -c "
from vn_admin_units.crosswalk import read_ward_crosswalk, _WARD_COLS
import glob, os

def classify(r):
    # Ward analogue of district_model.classify_change (the build-proven event model):
    # an event is a STRUCTURAL base-vs-successor difference, NOT a date-window match.
    b, s = r['base_ma'], r['succ_ma']
    if not b and s: return 'create'
    if b and not s: return 'dissolve'
    if r['base_tinh'] != r['succ_tinh']: return 'reparent'
    if r['base_ten'] != r['succ_ten']: return 'rename_retype'    # raw name; build uses fold_ward_name
    return 'unchanged'                                           # incl. pure code re-code (same name+province)

for p in sorted(glob.glob('data/raw/crosswalk/ward_*.xls')):
    name = os.path.basename(p)[:-4]                 # ward_<base>_<compare>
    _, base, compare = name.split('_')              # ISO window bounds from the filename
    raw = read_ward_crosswalk(p)
    # Dedupe exact-duplicate FULL rows (hazard 2026-07-10.14) BEFORE classifying — the
    # ingest dedupes on the full row, so events must be counted on deduped rows. If dups
    # land on changed rows, classifying raw would inflate the headline 'events' count.
    seen = set(); rows = []
    for r in raw:
        key = tuple(r[c] for c in _WARD_COLS)
        if key not in seen:
            seen.add(key); rows.append(r)
    exact_dups = len(raw) - len(rows)               # exact-duplicate FULL rows (the hazard)
    base_distinct = len({r['base_ma'] for r in rows if r['base_ma']})
    succ_distinct = len({r['succ_ma'] for r in rows if r['succ_ma']})
    if base < '2005':          # windows crossing the 2004 code renumber — the flat 2002→2025 export
        # AND the 2004→2005 recode boundary. base/succ codes differ purely from the remap, so
        # classify() would mark nearly every row 'reparent' — a bogus 'events' count (verified:
        # 713/713 on the district flat export, 663/663 on district 2004→2005). district_model.py
        # excludes 2004→2005 as a recode/alias source, not an event window — mirror that here.
        remap = sum(1 for r in rows if 'Chuyển đổi mã' in r['ghi_chu'])
        print(f'{name:38} raw={len(raw):6} dedup={len(rows):6} exact_dup_rows={exact_dups:4} base_distinct={base_distinct:6} succ_distinct={succ_distinct:6}  CODE-MAP/recode (2004 renumber) — events N/A; chuyen_doi_ma_rows={remap}')
        continue
    kinds = [classify(r) for r in rows]                         # classified on DEDUPED rows
    event_rows = [r for r, k in zip(rows, kinds) if k != 'unchanged']
    events = len(event_rows)                                    # the per-window signal (= window_events count), dedup-clean
    created = sum(1 for k in kinds if k == 'create')            # blank base — 'no old counterpart' (~5 at reform per 2026-07-10.06), NOT the ~3.3k new-ward count
    dissolved = sum(1 for k in kinds if k == 'dissolve')
    changed = sum(1 for k in kinds if k in ('reparent', 'rename_retype'))
    # succ_hieu_luc is a DATE SANITY signal, not the membership test: how many events fall in-window
    dated_in_window = sum(1 for r in event_rows if r['succ_hieu_luc'] and base <= r['succ_hieu_luc'] < compare)
    prose = sum(1 for r in event_rows if r['ghi_chu'].strip() and 'Chuyển đổi mã' not in r['ghi_chu'])
    print(f'{name:38} raw={len(raw):6} dedup={len(rows):6} exact_dup_rows={exact_dups:4} base_distinct={base_distinct:6} succ_distinct={succ_distinct:6} events={events:5} created={created:4} dissolved={dissolved:5} changed={changed:5} dated_in_window={dated_in_window:5} prose={prose:5}')
"
```
Expected: a table. Record it verbatim for the journal. Interpretation notes to capture:
- **`events` (structural changed-row count, = the `window_events` measure) is the headline per-window count** and must VARY across windows — small for a quiet year (2017), hundreds for a wave year (2019, 2024), and it should roughly track the `2026-07-10.13` cadence. If `events` is ~constant across windows, the classifier is mis-wired (most likely a column-mapping bug in `_WARD_COLS`) — stop and fix before writing the table.
- **`dated_in_window` is a sanity signal, not the count** — it's how many events carry a `succ_hieu_luc` inside the window. Expect most events dated in-window for a single year, but a shortfall does NOT mean fewer events: it reflects the date-column caveats above (blank date, or the date living in `base_hieu_luc`). Never substitute `dated_in_window` for `events`.
- Real composition prose present per-event in single-code-era windows (`prose` > 0).
- The flat 2002→2025 file prints as a **`CODE-MAP` line, not an event row** — it crosses the 2004 renumber, so `events` is meaningless there (`classify()` would count the whole-file code remap as `reparent`). Expect `chuyen_doi_ma_rows` ≈ its row count (all `"Chuyển đổi mã"` boilerplate); this file contributes the ward code-remap table (old scheme → current 5-digit `MaPhuongXa`), not events.
- `exact_dup_rows` > 0 is the dedupe hazard the ward ingest must handle. Note `events` (and every other classified count) is computed on the **deduped** rows, so a duplicate landing on a changed row does not inflate the headline count; `raw` vs `dedup` shows how many exact-duplicate rows were removed before classification.
- For the reform window, **`succ_distinct` (≈3.3k) is the new-ward count** — new wards mostly inherit a predecessor's code via the structured successor link, so they are NOT blank-base; `created` (blank-`base_ma`, ≈5) is the separate "no old counterpart" metric (the đặc khu). Base-side is the dissolving old structure.
- **Caveat for the journal:** even `events` is a lower bound — the crosswalk is net-only (Step 2), so a ward changing twice within one window year, or created-and-dissolved between the Jan-1 endpoints, is invisible here. Quantifying that gap needs the Nghị quyết list, not the crosswalk.

- [ ] **Step 2: Confirm the crosswalk is net-only (the decisive blind-spot probe)**

The yearly-window blind spot (`2026-07-13.02`, first-class for wards) is: a unit changing **twice within one window**, or **created-and-dissolved between the Jan-1 endpoints**, shows only its net state. Net-only is a *structural* property of a two-snapshot diff — a diff of two Jan-1 states cannot contain an intermediate state — so this probe does not *prove* it from data; it **confirms the export behaves as a pure 2-point diff** and never smuggles in more than one dated row per base unit. Run it across **every sampled event window** (not just 2019 — a single window is not evidence about the others; the flat 2002→2025 and any `base < 2005` recode file is skipped, as a cross-era code-map is not an event window and its recycled `base_ma` slots would fake collisions), grouping by the province-qualified `(base_tinh, base_ma)` key and flagging any base ward with >1 distinct successor effective date:
```bash
uv run python -c "
from vn_admin_units.crosswalk import read_ward_crosswalk
from collections import defaultdict
import glob, os
for p in sorted(glob.glob('data/raw/crosswalk/ward_*.xls')):
    name = os.path.basename(p)[:-4]
    _, base, compare = name.split('_')
    if base < '2005':   # flat 2002→2025 + the 2004→2005 recode are CODE-MAP windows, not event
        print(f'{name:38} SKIP (code-map/recode window — net-only event probe N/A)')   # windows;
        continue                                                                       # cross-era base_ma is a recycled slot, so the by-base grouping is meaningless here
    rows = read_ward_crosswalk(p)
    # Key by (base_tinh, base_ma): MaPhuongXa is a recycled 'slot, not an identity'
    # (2026-07-10.03) and is only unique WITHIN an era, so qualify it by province —
    # base_ma alone could merge two distinct wards and fake a >1-date collision.
    by_base = defaultdict(set)
    for r in rows:
        if r['base_ma'] and r['succ_hieu_luc']:
            by_base[(r['base_tinh'], r['base_ma'])].add(r['succ_hieu_luc'])
    multi = {b: sorted(ds) for b, ds in by_base.items() if len(ds) > 1}
    in_window = sorted({r['succ_hieu_luc'] for r in rows if base <= r['succ_hieu_luc'] < compare})
    print(f'{name:38} base wards with >1 distinct successor effective date: {len(multi):4} (0 => net-only in this window)')
    if multi: print('   sample:', dict(list(multi.items())[:5]))
    print('   distinct in-window effective dates:', in_window)
"
```
Expected (verified on district data): **0 on every sampled window** — the export is a pure net diff. Record this as: net-only is a **structural** property of the two-snapshot diff, **confirmed empirically on all N sampled windows** (state it as sampled confirmation, not an exhaustive proof across all ward history — the untested claim would be that some unsampled window smuggles in intermediate rows, which the structural argument rules out anyway). The consequence stands regardless: **the blind spot is real and cannot be detected or sized from the crosswalk alone.** The distinct in-window dates lines show the waves stepped across several Nghị quyết dates (`2026-07-10.13`), the cross-check the crosswalk *cannot* reconcile by itself.

**Sub-finding for the journal (build-time input):** sizing the missed in-year events needs the per-event **Nghị quyết UBTVQH** list (e.g. `653/2019/UBTVQH14`, `35/2023/UBTVQH15`). This is a *different* source from the `NghiDinh.aspx` list `crosscheck_decrees.py` scraped for districts — the correct GSO page for ward-arrangement Nghị quyết is itself an unresolved discovery. Do NOT assume `NghiDinh.aspx` covers ward waves. Fetching that list is out of scope for this spike (it becomes the first build-time task); record the gap explicitly.

- [ ] **Step 3: Confirm Lịch Sử at Cấp=Xã is still an inventory (retire the stale assumption)**

Run (headed, ~10 min, manual look): open `https://danhmuchanhchinh.nso.gov.vn/Lich_Su_Moi.aspx`, set Cấp=Xã + a point-in-time date, click Thực Hiện; confirm it renders a hierarchical inventory (expand shows child units / decree refs), **not** an old→new change timeline, and note whether the Xuất Excel button is functional at Xã level.
Expected: matches the district finding (`2026-07-13.01`) — inventory, not events. Record one screenshot-or-note of the observed behavior for the journal.

---

## Task 6: Write the deliverable — probe journal + DESIGN update

**Files:**
- Create: `docs/journals/2026-07-20.NN.ward-crosswalk-spike.md` (choose `NN` as the next unused index for 2026-07-20)
- Modify: `docs/DESIGN.md`
- Modify: `docs/DESIGN-phase3.md`

- [ ] **Step 1: Write the probe journal**

Create `docs/journals/2026-07-20.NN.ward-crosswalk-spike.md` with these sections (fill from Tasks 2–5, all values real):
- **What/why** — one paragraph: the spike, and the reframe (Lịch Sử out, crosswalk-sweep in).
- **Cấp=Xã mechanics** — the confirmed combo value; the ward column schema (`_WARD_COLS`, the fixed 13-column province-parented shape); note that the district (QH) columns are **absent** from the export, so the district-code disambiguation key is not in the crosswalk and must come from SOAP (`DanhMucQuanHuyen`) at build time.
- **Per-window volume table** — the Task 5 Step 1 table, verbatim.
- **`Ngày hiệu lực` / `Ghi Chú` behavior** — dates populate? prose present in single-era windows, boilerplate in the flat window?
- **Blind-spot verdict** — Task 5 Step 2 result: the crosswalk is net-only — structural property, confirmed on all sampled windows (0 base wards with >1 in-window date in each), so the blind spot is real and unsizeable from the crosswalk; distinct wave dates observed; the correct decree source for ward waves (Nghị quyết UBTVQH — source page unresolved, first build task).
- **Lịch Sử at Xã** — Task 5 Step 3: still an inventory, not events.
- **GO / NO-GO (nuanced — do NOT pre-write an unconditional GO)** — the honest verdict the spike can produce: **GO for the Đối Chiếu crosswalk as the net per-window lineage backbone** (dates + composition confirmed), **pending a Nghị quyết-list magnitude check** to bound how many in-year multi-events the yearly sweep misses (the net-only proof means that number is not knowable from the crosswalk). State it as GO-pending-magnitude; record the Nghị quyết-source discovery as the first build-time task. Let the real Task-5 numbers, not this expectation, decide the wording.
- **Recommended full-window list** — which yearly EVENT windows `01/01/Y→01/01/(Y+1)`, starting at **`2005→2006`** (per the district precedent: `district_model.py` excludes `2004→2005` as a recode/alias source, not events) through `2024→2025`; plus the `2004→2005` recode boundary and the flat `2002→2025` code map (both CODE-MAP/recode, not event windows), and the `2025-06-30→2025-07-01` reform boundary.
- **Recommended build order** — chronological `2002→forward` vs anchor-2025-back, decided against the real volume data, with the one-line reason.
- **New hazards** — đặc-khu count wobble, ward `Ghi Chú` template variants (city establishment, 3-way split), dedupe cases observed.

- [ ] **Step 2: Update DESIGN.md — retire the stale hybrid assumption**

In `docs/DESIGN.md`, amend decision 4 (change-discovery) and the "Change-discovery mechanism" paragraph to record that **Lịch Sử is an inventory, not an event source** at sub-province level (proven for districts `2026-07-13.01` and wards `2026-07-20.NN`), and the actual mechanism is the **Đối Chiếu crosswalk yearly-sweep + Nghị quyết/Nghị định cross-check**. Add a one-line pointer to this spike journal. Keep the edit tight and consistent with the surrounding prose.

Then, in `docs/DESIGN-phase3.md`, fix the stale guidance the phase doc still carries: its lineage-source row (the Phase-1→Phase-2 table) lists **"Lịch Sử events"** as an event source. Add a tight superseding note (one line, next to that row or in the doc's stale-numbering banner) that Lịch Sử is an inventory, not an event source — the crosswalk yearly-sweep + decree cross-check is the mechanism — and point to this spike journal + `DESIGN.md` decision 4. Do not rewrite the whole doc (its body is revised when the phase is reached); just neutralize the one line that would mislead a future worker.

- [ ] **Step 3: Commit the deliverable**

```bash
git add docs/journals/2026-07-20.*.ward-crosswalk-spike.md docs/DESIGN.md docs/DESIGN-phase3.md
git commit -m "docs: ward-crosswalk spike journal + retire stale Lịch Sử assumption"
```

- [ ] **Step 4: Bump the submodule pointer (monorepo)**

Per the repo's established practice (README resume-point commits), from the monorepo root record the pointer bump so the resume state is captured:
```bash
git -C /Users/viett/personal/bamboo-filing-cabinet add vietnam-admin-units
git -C /Users/viett/personal/bamboo-filing-cabinet commit -m "chore: bump vietnam-admin-units (Phase 3 ward-crosswalk spike; go/no-go recorded)"
```

---

## Self-review notes (author)

- **Spec coverage:** Task 1–2 = spec task 1 (Cấp=Xã mechanics); Task 3 = spec task 2 (`read_ward_crosswalk`); Task 4 = spec task 3 (representative windows); Task 5 Steps 1 = spec task 4 (measure), Steps 2–3 = spec task 5 (blind-spot + Lịch Sử retirement); Task 6 = the deliverable journal + DESIGN update. All spec sections mapped.
- **Non-goals honored:** no entity/lineage/reconcile/emit/full-sweep tasks appear.
- **Type consistency:** reader returns `list[dict]`; field names (`base_ma`/`succ_ma`/`base_hieu_luc`/`succ_hieu_luc`/`ghi_chu`) are identical across `_WARD_COLS`, the reader body, and every test — matching the existing district/province readers so downstream stays uniform.
- **Live-data steps** (Task 2 combo value, Task 3 Step 6 pin, Task 5 numbers) carry explicit derive-and-lock procedures rather than invented literals — deliberate for a reconnaissance spike.
