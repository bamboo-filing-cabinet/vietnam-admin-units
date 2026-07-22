# vietnam-admin-units — Phase 3 ward-crosswalk spike (design)

Extends `DESIGN.md` (overarching design + decisions log) and `DESIGN-phase3.md`
(the ward-phase design, whose internal numbering is stale). This is the **first
Phase-3 slice**: a scoped reconnaissance spike that de-risks the ward build
*before* committing a build order.

> **Supersedes a stale `DESIGN-phase3.md` assumption.** That doc's lineage-source
> row still lists "Lịch Sử events" as an event source. This spike (and the
> district finding `2026-07-13.01`) retires that: **Lịch Sử is an inventory, not
> an event source** at sub-province level — the Đối Chiếu crosswalk yearly-sweep +
> Nghị quyết/Nghị định cross-check is the actual change-discovery mechanism. Task 6
> records this in both `DESIGN.md` (decision 4) and `DESIGN-phase3.md`.

Phases 1 (provinces) and 2 (districts) are complete and live on Wikidata. Phase 3
is the ward tier (`xã` / `phường`), the largest and highest-churn layer (~10k
units, feeds NA16). The maintainer chose **full ward history 2002→2025** as the
Phase-3 goal, decomposed into ordered sub-slices, with **this spike first** to
prove the one unexercised dependency with real data before the heavy build.

## Why a spike, and why the framing shifted

The original DESIGN "hybrid" assumption was: **Lịch Sử change-log** supplies
events + dates, the **Đối Chiếu crosswalk** supplies lineage, **SOAP `DenNgay`**
supplies snapshots. The Phase-2 district reconnaissance overturned the first leg:

- **Lịch Sử (`Lich_Su_Moi.aspx`) is not an event timeline** at sub-province level
  — it is a hierarchical *inventory* with decree references, its expand view
  shows child units (not history), and its Excel export is non-functional there
  (journal `2026-07-13.01`).
- **The Đối Chiếu crosswalk (`Doi_Chieu_Moi.aspx`) is the workhorse.** Swept as
  **yearly windows `01/01/Y → 01/01/(Y+1)`** — each staying inside a single
  post-2004 code-era — it yields clean per-year change sets with true `Ngày hiệu
  lực` effective dates and (within a single code-era) real `Ghi Chú` composition
  prose (journal `2026-07-13.02`). (That district journal names the district era
  "3-digit"; the **ward** code is a **5-digit** national `MaPhuongXa`, journal
  `2026-07-10.03` — the carried-over invariant is *one code-era per window*, not
  any specific width.) There is a hard **event floor at the 2004 code-scheme
  change**; 2002→2004 is a code-remap boundary, not an event window.
- The existing tool `src/vn_admin_units/crosswalk_fetch.py` already drives the
  DevExpress page via Playwright and its tier dropdown includes **Xã** (wards);
  only `TIER_CAP`/`TIER_VI` and a ward reader are missing.

So the genuine unknown is **not** "can we scrape Lịch Sử" (answered: no, and we
don't need to). It is: **does the district-proven crosswalk-sweep method hold up
at ward scale and volume, and does the yearly-window blind spot actually bite?**
That is what this spike settles.

## The one hazard districts did not exercise

`2026-07-13.02` flags the **yearly-window blind spot** as *negligible for
districts but first-class for Phase 3 wards*: two point-in-time snapshots show
only the *net* change between them, so a unit that changes **twice in one year**
(e.g. rename then type-upgrade) shows only its year-end state, and a unit
**created and dissolved within one year** is net-invisible. Districts were sparse
(0–61 events/year) and no case bit; wards saw merger waves of ~670 (2019–21) and
~970 (2024–25) events (journal `2026-07-10.13`), so the risk is real. Crucially,
the crosswalk is **net-only** by construction (verified on district data: no base
unit ever carries more than one in-window effective date), so this blind spot
**cannot be detected or sized from the crosswalk alone** — the spike proves the
net-only property and defers *quantifying* the gap to a per-event Nghị quyết-list
cross-check at build time. Second known ward hazard: **exact-duplicate rows** in
historical ward snapshots (17 in 2019, 19 in 2020; journal `2026-07-10.14`) — the
ingest must dedupe on the full row within a snapshot.

## Scope — the spike, in five tasks

1. **Confirm Cấp=Xã mechanics.** Load `Doi_Chieu_Moi.aspx`, confirm the ward
   combo value (extend `TIER_CAP`/`TIER_VI` in `crosswalk_fetch.py`; expected
   `"3"`/`"Xã"`, **to verify** — the served combo is populated client-side), and
   confirm the Excel export fires at ward level (it needs a `Thực Hiện` round-trip
   first, per `2026-07-13.02`). One small extension to the existing fetcher.

2. **Add `read_ward_crosswalk`** in `crosswalk.py`, mirroring
   `read_district_crosswalk` (read by positional index; convert Excel-serial
   dates to ISO via the existing `_excel_date`; keep codes verbatim via `_clean`).
   TDD'd against the committed cached ward window (the `.xls` from task 3's probe
   pull), matching the established `test_district_crosswalk.py` pattern — not a
   synthetic fixture. **The export schema is the same fixed 13-column,
   province-parented shape as the district export** — journal `2026-07-10.06`
   (two real ward `.xls` exports) records it as `Tỉnh · Tên Tỉnh · Xã · Tên Xã ·
   Nghị định · Ngày hiệu lực` (base) · `Tên Xã DC · Xã DC · Nghị định · Ngày hiệu
   lực · Tên Tỉnh DC · Tỉnh DC` (compare) · `Ghi Chú`, i.e. structurally identical
   to `_DISTRICT_COLS` with `Xã` in the unit slot. **The export DROPS the district
   (QH / Tên QH) columns** shown in the on-screen grid. So the pre-2025 ward's
   district code — the disambiguation key DESIGN calls for — is **not in the
   crosswalk**; it must come from SOAP (`DanhMucQuanHuyen`) at build time, sourced
   separately. Confirm the schema against the cached file (task 3 probe), and
   record whether a 2019-era window matches the reform-era exports the journal
   examined.

3. **Pull representative windows** (NOT the full sweep). Verbatim-cache each via
   the existing `save_raw` manifest path:
   - one **quiet year** (e.g. `01/01/2017 → 01/01/2018`) — baseline signal;
   - one **2019-wave year** (e.g. `01/01/2019 → 01/01/2020`);
   - the **2024→25 wave** (`01/01/2024 → 01/01/2025`);
   - the **2025 reform boundary** (`30/06/2025 → 01/07/2025`, a clean reform-day
     window — not a current-date pull, which would mix in post-reform churn) — the
     10,039→3,321 collapse and the đặc-khu / new-ward creations;
   - the **flat 2002→2025** export — kept only as the ward code-remap table
     across the 2004 code-scheme change (current ward codes are the 5-digit
     `MaPhuongXa`; the pre-2004 ward code width is read off this file, not
     assumed — the district-style "5→3" does NOT apply to wards) (expected to be
     `Ghi Chú` boilerplate, per the district case).

4. **Measure & characterize.** Per window, using the canonical parse (never
   ad-hoc scripts): total rows, changed rows, **distinct-code count**,
   **duplicate-row count**, presence of `Ghi Chú` composition prose, and whether
   `Ngày hiệu lực` carries per-event effective dates. This volume table sizes the
   build and is the primary spike output.

5. **Blind-spot cross-check + Lịch Sử retirement.**
   - **Confirm the crosswalk is net-only** across every sampled window (group by
     base unit; verify no base ward carries >1 distinct in-window effective date).
     Net-only is a *structural* property of a two-snapshot diff; the probe is
     sampled confirmation that the export behaves as a pure 2-point diff, not an
     exhaustive proof over all ward history. This establishes that
     same-unit-twice-in-year is invisible here — and therefore **record the
     per-event Nghị quyết UBTVQH magnitude check as the first build-time task
     rather than performing it in this spike.** Sizing how often
     same-unit-twice-in-year actually occurs (e.g. against `653/2019/UBTVQH14` for
     2019–21, `35/2023/UBTVQH15` for 2023–25) needs that external list, which is
     out of spike scope. **Sub-finding to record:** districts used the
     `NghiDinh.aspx` list (`crosscheck_decrees.py`, 544 recs); ward waves are
     Nghị quyết UBTVQH, which may live on a different GSO decree page — note the
     correct source, do not assume `NghiDinh.aspx` covers them (locating the
     correct page is itself part of that first build task).
   - Spend ~10 min opening **Lịch Sử at Cấp=Xã** to confirm it is still an
     inventory (not a timeline), then **update `DESIGN.md`** to retire the stale
     "hybrid: Lịch Sử events" assumption (decision 4) — recording that the
     crosswalk yearly-sweep + decree cross-check is the actual event-discovery
     mechanism.

## Deliverable

A dated probe journal `docs/journals/2026-07-20.NN.ward-crosswalk-spike.md`
containing:

- the **per-window volume table** (task 4);
- a **go/no-go** on "the crosswalk yearly-sweep suffices for wards" — expected to
  be **GO for the crosswalk as the net lineage backbone, pending a Nghị quyết-list
  magnitude check** (the net-only property means the blind-spot gap is real but
  unquantifiable from the crosswalk); not an unconditional GO;
- the recommended **full-window list** for the ward build: yearly EVENT windows
  starting at `2005→2006` (per the district precedent — `district_model.py`
  excludes `2004→2005` as a recode/alias source, not events) through `2024→2025`;
  plus the `2004→2005` recode boundary and the flat `2002→2025` code map (both
  CODE-MAP/recode, not event windows), and the `2025-06-30→2025-07-01` reform
  boundary;
- a recommended **build order** — chronological `2002→forward` vs `anchor-2025,
  chain back` — now decided against real volume data;
- any **new hazards** surfaced (đặc-khu count wobble, `Ghi Chú` template variants
  for city establishments / 3-way splits, ward-specific dedupe cases).

Plus two small committed tooling additions: **Xã tier support** in
`crosswalk_fetch.py`, and **`read_ward_crosswalk`** in `crosswalk.py` with tests.

## Non-goals (these are the *build*, gated on this spike's go/no-go)

- No ward entity/lineage assembly, no `local_id` minting, no name→code
  disambiguation implementation.
- No Wikidata reconciliation or emit; no QuickStatements batch.
- No full ~21-window yearly sweep (the spike pulls a handful of representative
  windows only).
- No Goal A / NA16 consumer export.
- No pre-2004 event recovery (below the crosswalk floor; a later concern).

## Sequencing

Spike (this doc) → probe journal + go/no-go → **`superpowers:writing-plans`**
produces `docs/plans/2026-07-20-phase3-ward-crosswalk-spike.md` for the tooling
work → run it → the journal's build-order recommendation feeds the *next*
Phase-3 slice (the actual ward build), which gets its own design + plan.

## References

- `DESIGN.md` — overarching design; decision 4 (change-discovery) to be updated.
- `DESIGN-phase3.md` — ward-phase design (stale internal numbering).
- `docs/journals/2026-07-13.01` — district Lịch Sử + crosswalk probe (Lịch Sử is
  an inventory).
- `docs/journals/2026-07-13.02` — district granular yearly-window method + the
  yearly-window blind spot flagged as first-class for wards; extraction mechanics.
- `docs/journals/2026-07-10.13` — ward change cadence (wave volumes).
- `docs/journals/2026-07-10.14` — day-precision + exact-duplicate ward rows.
- `src/vn_admin_units/crosswalk_fetch.py`, `crosswalk.py` — the tooling extended
  here.
