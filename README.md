# vietnam-admin-units

A time-versioned gazetteer of Vietnam's administrative units — provinces,
districts, and communes/wards — modeling how they change across reform eras,
reconciled to Wikidata.

This is the **foundation layer** beneath the Bamboo Filing Cabinet election
projects. Both
[`vietnam-elections`](https://github.com/bamboo-filing-cabinet/vietnam-elections)
and
[`vietnam-elections-wikidata`](https://github.com/bamboo-filing-cabinet/vietnam-elections-wikidata)
consume it; it holds **zero** election concepts of its own.

```
vietnam-admin-units  (layer 1: the gazetteer)
        ▲                    ▲
        │                    │
vietnam-elections     vietnam-elections-wikidata
```

## ▶ Start here (resume on any machine)

1. **Clone with submodules** (this repo lives inside the `monorepo`):
   ```sh
   git clone --recurse-submodules git@github.com:bamboo-filing-cabinet/monorepo.git
   cd monorepo/vietnam-admin-units          # (or: git submodule update --init)
   ```
2. **Set up + verify:**
   ```sh
   uv sync
   uv run pytest -q                          # 91 tests pass (Phase 2 in progress)
   ```

   **If you're resuming Phase 2 (districts), read the "Phase 2" block under [Status](#status) below — it is the authoritative resume point** (state, execution corrections, the open decision, and the exact next step), and it points you to the plan.
3. **Read the design — the single entry point:** [`docs/DESIGN.md`](docs/DESIGN.md).
   Its **Document map**, **decisions log**, and **phase roadmap** index everything
   else (per-phase designs, the plan, and the dated decision journals `.01`–`.15`,
   `2026-07-11.*`, `2026-07-13.*`). Ward/province design (Phase 3, to be revised):
   [`docs/DESIGN-phase3.md`](docs/DESIGN-phase3.md).

## Status

**Phase 1a complete and uploaded** (2025-reform slice, province tier). The full
pipeline runs end-to-end (SOAP ingest → verbatim raw cache → crosswalk → `Ghi
Chú` parser → entities → lineage `34/34` gate → reconcile → emit), 27 tests
pass, and the Wikidata batch is **live**: `statements/na-provinces-2025.qs` (116
statements, 29 dissolutions → 23 survivors; all referenced; constraint-clean;
reconciliation audited via `reconcile --audit`). Uploaded 2026-07-12 via
QuickStatements ([batch #260741](https://quickstatements.toolforge.org/#/batch/260741),
319 ops, 0 errors).

**Phase 1b complete and uploaded** — the province tier now spans the full
**2002→2025 history**: the 2004 code-scheme renumber (3-digit→2-digit), the three
2004 carve-outs (Điện Biên←Lai Châu, Đắk Nông←Đắk Lắk, Hậu Giang←Cần Thơ, from NQ
22/2003/QH11), the 2008 Hà Tây→Hà Nội merger, and the Cần Thơ/Huế type upgrades,
chained and reconciled to QIDs. `statements/na-provinces-history.qs` (14 statements;
`P571`/`P807`/`P31`-retype/`P576`+succession; audit 0 issues; constraints-clean).
Uploaded 2026-07-14 via QuickStatements ([batch #260977](https://quickstatements.toolforge.org/#/batch/260977)).
This completes the **province tier** and unblocks Phase 2 districts (their pre-2008
`P131` spans need these historical province QIDs).

**Phase 2 (districts) — IN PROGRESS (last worked 2026-07-17). ◀ RESUME HERE.**

Building the district tier (huyện / quận / thị xã / thành phố thuộc tỉnh) as a
continuous-entity lineage graph **2004→2025 + the universal 2025-07-01 abolition**,
reconciled to Wikidata (Goal B). Execution is **task-by-task per the plan**:
[`docs/plans/2026-07-14-phase2-districts.md`](docs/plans/2026-07-14-phase2-districts.md)
— **read it, ESPECIALLY the "Execution corrections (2026-07-17)" section near the top**,
which supersedes the as-written D4/D6.5/D7 mechanism. Tasks: R1–R4 ("Movement A" =
tier-neutral `core.py` refactor) then D1–D11 (district build). Everything is committed on
`main` (solo repo — commit directly on `main`, no branch).

**Done & pushed** — suite **91 passed**, tree clean, HEAD `9615ad0`:
- **R1–R4:** extracted `src/vn_admin_units/core.py` (shared `Entity`/`LineageEdge` +
  emit primitives + relation vocabulary); migrated 1a (`model.py`) and 1b
  (`province_history.py`) onto it — **1a `mappings/` proven byte-identical**.
- **D1–D6.5:** `parse_district_ghichu` (`ghichu.py`); `fold_district_name` (`names.py`);
  `district_model.py` types + `unit_tier`/`classify_change`/`window_events` +
  `group_by_event`/`source_survives`/`resolve_merge_target`; `decree_index`/`decree_for`/
  `decrees_naming`/`cache_decrees` (`crosscheck_decrees.py`). Cached Nghị định list →
  `data/raw/nghidinh.json` (544 recs). Reference URLs: `data/decree-urls.json` = **63**
  thuvienphapluat `van-ban` URLs.

**Execution corrections (the plan's section is authoritative — do NOT follow the old D6.5/D7 date path):**
1. **Dissolve/merge DATE + decree come from the crosswalk SURVIVOR row**
   (`succ_hieu_luc` + `succ_nghi_dinh`), NOT `decrees_naming` — the Nghị định list titles
   name the *province*, not the district, so name-matching finds nothing. Reach the survivor
   via the dissolved row's Ghi Chú "vào Y" target, else `data/district-merge-targets.json`.
2. **Reference URLs = WebSearch `<code>` on `thuvienphapluat.vn`** → `data/decree-urls.json`
   (direct fetch is Cloudflare-403; the NSO list has no per-row URL).
3. **Corrected ground-truth dates** (real, per-unit): Thông Nông→Hà Quảng **2020-02-01**
   (decree `864`, NOT 2020-03-01); Trà Lĩnh/Phục Hoà 2020-03-01 (`897`); Nông Sơn→Quế Sơn
   **2025-01-01** (`1241`, needs a `district-merge-targets.json` entry — no Ghi Chú target);
   Từ Liêm split 2013-12-28 (`132/NQ-CP`). The D7 ground-truth test already asserts these.

**⚠ OPEN DECISION (blocks D11's reference gate — resolve this):** 93 of 156 decree
reference URLs are unresolved (44 old `NĐ-CP` 2004–08, 31 `NQ-CP` 2009–13, 18 `NQ-UBTVQH`);
WebSearch tops out ~40% (US-indexed, recency-biased). Options weighed with the maintainer,
not yet chosen: **(a)** locality-keyed retry + authoritative fallback URL (`vbpl.vn` national
gov DB or the NSO `NghiDinh.aspx` list) for the stubborn tail; **(b)** maintainer
browser-resolves the residue (has Cloudflare access); **(c)** fallback URLs now, upgrade later.
The 63 resolved are in `data/decree-urls.json`; the residue list regenerates from the
crosswalk changed-rows (`decree_code(succ_nghi_dinh)` minus the resolved keys). *(An API
session limit was hit mid-batch on 2026-07-17.)*

**NEXT, in order:**
1. **D7 (in progress)** — implement `build_districts` in `district_model.py` on the
   **survivor-row** date mechanism: seed roots from the 2005-01-01 roster, walk the yearly
   windows applying reparent/rename/retype/create/dissolve, resolve split/carve/merge buckets
   (D6 discriminator), curate `data/district-merge-targets.json` (incl. `Nông Sơn 519 → Quế Sơn 509`),
   apply the universal 2025 abolition (~696 districts). Gate: `tests/test_district_groundtruth.py`
   (corrected dates) + `test_no_blocking_residue`. Full code scaffold + the corrections are in plan Task D7.
2. **D8** reconciliation (bulk SPARQL — live Wikidata) · **D9** emitter · **D10** constraints
   (+ live-confirm the 4 district `P31` target QIDs) · **D11** wire pipeline (5 hard gates,
   offline test; live build; source the 2025 reform-resolution URL for the abolition reference).

**Human touchpoints (don't auto-do these):** the reference-residue decision above; confirming
the district `P31` QIDs (D10); confirming the 2025 reform-resolution URL (D11); reviewing and
performing the **Wikidata upload** (always manual, maintainer's account).

**Next phases after 2:** wards (NA16, Phase 3), pre-2002 history — see the roadmap in `docs/DESIGN.md`.

## The model

One record per real-world admin unit, per era of existence, carrying an
existence span (`valid_from`/`valid_to`), parent-at-time hierarchy, lineage
edges across reforms (`merged_into`/`split_from`/`replaces`), the official GSO
code (`mã ĐVHC`), and a reconciled Wikidata QID. Snapshots and the official
change-history are *inputs*; this entity graph is the source of truth, and it
maps almost one-to-one onto Wikidata (`P571`/`P576`/`P7888`/`P1365`/`P1366`/
`P131`), which lets it also drive Wikidata corrections upstream.

## Layout

- `src/vn_admin_units/` — the package: `soap` (canonical GSO fetch, all tiers) ·
  `fetch` (CLI diagnostics) · `crosswalk` · `ghichu` (province + district `Ghi Chú`
  parsers) · `names` (name folding) · `core` (tier-neutral `Entity`/`LineageEdge` +
  emit primitives + relation vocab — **shared by all tiers**) · `model` (province 1a) ·
  `province_history` (province 1b) · `district_model` (district assembly, Phase 2) ·
  `crosscheck_decrees` (Nghị định list fetch/cache + decree lookup) · `reconcile`
  (Wikidata QIDs + `--audit`) · `constraints` (pre-upload gate) · `emit`
  (QuickStatements) · `cli` (`cache_snapshots`, `build_all`).
- `data/raw/` — verbatim source bytes + `manifest.jsonl` (provenance); `crosswalk/`
  (23 district windows); `nghidinh.json` (cached Nghị định list, 544 recs). `data/` —
  derived JSON (snapshots, `entities.json`, `lineage.json`); Phase-2 curated inputs:
  `decree-urls.json` (decree → thuvienphapluat URL), `district-merge-targets.json`
  (`{dissolved_local_id: successor_local_id}` overrides, created in D7).
- `mappings/provinces-qid.csv` + `provinces-history-qid.csv` — reconciled province QIDs;
  `districts-qid.csv` (Phase 2, D8).
- `statements/` — emitted Wikidata batches.
- `docs/DESIGN*.md` — design; `docs/plans/` — implementation plans;
  `docs/journals/` — dated decision/probe log.

## Common commands

```sh
uv run python -m vn_admin_units.cli                 # refresh raw cache + snapshots
uv run python -c "from vn_admin_units.cli import build_all; build_all()"   # rebuild batch
uv run python -m vn_admin_units.reconcile           # (re)reconcile provinces -> QIDs (resumable)
uv run python -m vn_admin_units.reconcile --audit   # correctness gate (required before upload)
uv run python -m vn_admin_units.constraints         # check WD property constraints
uv run python -m vn_admin_units.fetch --tier ward --date 01/01/2019 --dups   # ad-hoc source query
```

## Sources

Authoritative upstream is the GSO/NSO *danh mục hành chính* service
(`nso.gov.vn`): `DMDVHC.asmx` SOAP (point-in-time via `DenNgay`, all tiers) +
`Doi_Chieu_Moi.aspx` crosswalk + `Lich_Su_Moi.aspx` change-log. Data is 2002→
present. See `docs/journals/2026-07-10.01`–`.02` for the verified inventory.

## Development

Python + [uv](https://docs.astral.sh/uv/) (matching `vietnam-elections-wikidata`).
TDD; small commits; `uv run pytest`.
