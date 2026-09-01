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
   uv run pytest -q                          # 230 tests pass
   ```

   **Phases 1 and 2 are complete and uploaded to Wikidata (provinces + districts).** The next work is **Phase 3 (wards)** — read the "Phase 2" block under [Status](#status) for the post-upload verification step and the roadmap pointer.
3. **Read the design — the single entry point:** [`docs/DESIGN.md`](docs/DESIGN.md).
   Its **Document map**, **decisions log**, and **phase roadmap** index everything
   else (per-phase designs, execution plans, and dated decision journals).
   Ward/province design (Phase 3, to be revised):
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

**Phase 2 (districts) — COMPLETE and uploaded (2026-07-20).** The district tier (huyện / quận /
thị xã / thành phố thuộc tỉnh) is built as a continuous-entity lineage graph **2004→2025 + the
universal 2025-07-01 abolition**, reconciled to Wikidata. **718 districts, 0 gaps, 0 collisions;
suite 127.** Three QuickStatements batches (personal account, 2026-07-20):

- `statements/na-districts.qs` — the main tier: `P571`/`P131`/`P31`-retype/`P576` + succession, all
  referenced. Uploaded [batch #261331](https://quickstatements.toolforge.org/#/batch/261331)
  (4,001 ops, **0 errors**).
- `statements/na-districts-create-former.qs` — CREATE the 5 Tier-C former districts WD lacked
  (island huyện→đặc khu, thị xã→ward): Hoàng Sa Q140626479, Lý Sơn Q140626480, Cát Hải Q140626481,
  Quảng Trị Q140626482, Phú Quí Q140626483. [batch #261329](https://quickstatements.toolforge.org/#/batch/261329).
- `statements/na-districts-create-former-2.qs` — CREATE 3 more former districts split off a
  wrongly-shared QID by the collision audit: Ayun Pa Q140626623, Duyên Hải Q140626624, Long Mỹ
  Q140626625. [batch #261330](https://quickstatements.toolforge.org/#/batch/261330).

The 11-district "became-a-ward/đặc-khu" tail, 2 name-collisions (Thanh Sơn/Tân Sơn, Thanh Khê/Cẩm Lệ),
and 8 same-name/different-tier QID collisions were all resolved — see journals
[`2026-07-19.01`](docs/journals/2026-07-19.01.district-reconciliation-successor-tail.md) /
[`.02`](docs/journals/2026-07-19.02.district-create-new-manual-instructions.md) /
[`.03`](docs/journals/2026-07-19.03.district-qid-collision-audit.md). Reconcile + audit were hardened
(fold-normalization, label-over-alias, tier-check, distinctness) so the class can't recur; an
independent geo cross-check (P625 kNN) confirmed **0 wrong-place matches**. Build followed
[`docs/plans/2026-07-14-phase2-districts.md`](docs/plans/2026-07-14-phase2-districts.md) (R1–R4 refactor
+ D1–D11), committed on `main` (solo repo — no branch).

**Post-upload verification (2026-07-20, DONE):** `reconcile.audit_district_qids` → **1 issue**, the
*accepted* Ninh Bình → Hoa Lư successor-relabel; the 3 Tier-B TYPE flags cleared (batch #261331 stamped
`P31`=huyện). Independent geo cross-check (P625 kNN): **0 wrong-place matches**. **Phase 2 fully verified.**

**◀◀ RESUME HERE — Phase 3: ward Wikidata mapping review.** Provinces
(Phase 1) and districts (Phase 2) are complete + live on Wikidata with **no open
work**. The 2025 ward boundary and full predecessor→successor topology are
complete offline. Historical source-closure Tasks 1–6 are also complete: all
204 SOAP snapshots, 39 crosswalks, 179 observed-change events, 453 candidate
legal rows, and 449 unique instruments are deterministically inventoried,
classified, and linked with zero unclassified instruments or legally unlinked
observed events. Tasks 7 and 8 are complete with the 29 reviewed
primary-source-open instruments accepted as bounded graph-construction residue.

The read-only Wikidata discovery snapshot is also complete: one saved QLever
query produced 11,838 candidates in 739 ms, local parent prefiltering reduced
Action API verification to 2,878 items in 58 batches, and two additional saved
evidence passes raise coverage to 2,670 of 3,321 current wards with zero
structural issues. **Resume with review of the 651 unassigned current rows**
(47 ambiguous, 324 needs review, 280 needs lookup). No Wikidata statements have
been emitted. See the initial [reconciliation journal](docs/journals/2026-09-01.05.ward-wikidata-reconciliation.md),
the [review-reduction journal](docs/journals/2026-09-01.06.ward-wikidata-review-reduction.md),
and run:

```sh
uv run python -m vn_admin_units.ward_reconcile_broad --check --audit
uv run python -m vn_admin_units.ward_reconcile --check --audit
```

**Task 7 review log (historical):** At its final strict-primary checkpoint the
audit was **418/449 official**, with **29
primary-source-open instruments**: 4 `missing` and 25 `secondary_only`; **all
29 are change-bearing**. The registry preserves 411 official attachments and 829
official artifacts. Decree `84/2005-NĐ-CP@2005-07-22` (Thuận Bắc, Ninh Thuận)
now has a complete indexed official VBPL print view and exact DOC attachment
URL, but live retrieval still times out. Preserve its official 2005-07-07 issue
and 2005-07-30 effective dates alongside the earlier NSO registry date; archive
the official bytes before closing it. Resolution
`469/NQ-UBTVQH15@2022-04-10` likewise has an exact official registry and PDF
lead whose legacy file server resets live retrieval attempts. Decree
`85/2005/NĐ-CP@2005-07-22` now has the same exact VBPL print/DOC recovery path,
a preserved date discrepancy, and complete secondary topology. Decree
`97/2005/NĐ-CP@2005-08-10` now has a complete indexed official print view,
history record, and exact DOC recovery path; its 2005-08-17 legal effective
date differs from the earlier registry date. Decree
`98/2005/NĐ-CP@2005-08-10` now has the same complete indexed print/DOC recovery
path and preserved date discrepancy, plus a reconciled Tân Hiệp → Ngã Bảy name
chain. Decree `28/2006/NDD-CP@2006-04-06` is now closed with archived
Government metadata and its original Word attachment; the registry preserves
the raw `NDD-CP` code and 2006-04-06 observation date beside official
`NĐ-CP` and 2006-04-13 legal effectiveness. Decree
`29/2006/NĐ-CP@2006-04-07` now has complete parallel secondary texts,
contemporaneous Government press corroboration, and an indexed official VBPL
lead, but remains open because the official bytes are blocked by HTTP 403. The
complete parallel transcriptions of Decree `34/2006/NĐ-CP@2006-04-15` confirm
the whole-unit Cát Thành retype, while the indexed official page remains
blocked by HTTP 403. Its 2006-04-25 legal effective date remains distinct from
the 2006-04-15 NSO observation date. Decree
`39/2006/NĐ-CP@2006-05-06` now has reviewed secondary topology for seven Gia
Lai commune creations, two boundary transfers, contemporaneous Government
press corroboration, and an indexed official lead. The official bytes remain
blocked by HTTP 403, and the registry's 2006-05-06 date remains distinct from
the 2006-05-15 legal effective date. Decree
`60/2006/NĐ-CP@2006-07-04` now has complete parallel secondary texts,
contemporaneous Government press corroboration, an indexed official lead, and
reconciled topology for three Tân An ward establishments. The official bytes
remain blocked by HTTP 403; the registry's 2006-07-04 observation date remains
distinct from the 2006-07-13 legal effective date, and its later `Thành phố
Tân An` parent-label echo is not projected backward. Decree
`64/2006/NĐ-CP@2006-07-08` now has complete parallel secondary texts, an
indexed official lead, and reconciled topology for five
whole-commune parent changes plus a roster-invisible boundary transfer. Its
official bytes remain blocked by HTTP 403; the 2006-07-08 observation date
remains distinct from the 2006-07-16 legal effective date, and SOAP's later
`Thành phố Hà Giang` label is not projected backward. Decree
`137/2007N@2007-09-11` is now closed with archived
Government metadata and the original Word attachment for formal Decree
`137/2007/NĐ-CP`. The official issue date is 2007-08-27 and legal effective
date is 2007-09-18, while 2007-09-11 remains the NSO observation key. The
document reconciles five commune creations and the seven continuing communes
re-parented into newly created Cư Kuin; eleven concurrent Vĩnh Long parent
changes in the same SOAP interval belong to Decree 125/2007/NĐ-CP. The supplied
Government page and original Word file prove that the actual decree was issued
on 2008-02-04, effective 2008-02-25, and concerns district-level specialized
agencies—not Tân Đức. Both July/August NSO rows are now closed as verified
invalid index identities; the already archived Resolution `14/2008/QH12` is
the canonical authority for the Tân Đức transfer. Decree
`07/NĐ-CP@2009-01-07` now has a complete Buôn Hồ secondary transcription, an
exact official VBPL record, and an indexed original ZIP lead. Its 23 linked
topology components are reconciled, but the official bytes remain blocked by
HTTP 403. The supplied LuatVietnam URL belongs to the later Nghệ An Decree 07,
so date-qualified secondary mappings now prevent same-code contamination.
Decree `08/NĐ-CP@2009-01-07` now has a complete Hồng Ngự secondary
transcription, an exact official VBPL full-text and original ZIP lead,
contemporaneous provincial implementation corroboration, and later Ministry
classification evidence. Its seven linked topology components are reconciled,
but the official bytes remain blocked by HTTP 403. Date-qualified provenance
also removes this Hồng Ngự source from the later Bến Tre Decree 08.
Decree `10/NĐ-CP@2009-01-07` now has a complete Ba Tơ–Sơn Tây secondary
transcription, contemporaneous Government Office corroboration, and exact
official VBPL full-text and original ZIP leads. Its four commune-creation
components are reconciled, but the official bytes remain blocked. The decree
was issued in 2008; `2009-01-07` remains the NSO observation key rather than
the legal date. Decree `11/NĐ-CP@2009-01-07` now has a complete Mường
Lát–Quan Sơn secondary transcription and an exact official VBPL full-text
lead. It creates Nhi Sơn and Trung Tiến; the crosswalk's Lãng Công attribution
is an isolated Decree 11/09 code error and remains a derived-topology
correction target. The official bytes remain blocked. All five supplied links
belong to the later Hà Giang Decree 11, already closed with official metadata
and its original Word file; date-qualified mappings prevent contamination.
Decree `12/NĐ-CP@2009-01-07` now has an exact official VBPL full-text and
original ZIP lead, a complete Cần Thơ secondary transcription, and reviewed
press corroboration. Its topology now links all 30 proved components,
including Phường Thạnh Hòa, whose crosswalk row carries a later 2025 citation.
The official bytes remain blocked; the 2008 legal dates stay distinct from the
2009 NSO observation key. The supplied Hưng Yên report is a false hit for
Decree `14/NĐ-CP@2009-04-11`: Hưng Yên city was established by Decree
04/NĐ-CP, while the queue target is the 2009-04-10 Bình Phước instrument.
No primary bytes were recovered, so that target remains `secondary_only`.
Resolution `26/NQ-CP@2009-06-11` is now closed with archived Government
metadata and original Word attachment. The legal issue/effective date is
2009-06-10; the NSO date remains an observation key. Its two commune creations
and six Thuận Nam parent changes are fully linked. Resolution
`28/NQ-CP@2009-06-30` is now closed with an archived official Tiền Giang
Gazette record and enacted PDF. Its legal issue/effective date is 2009-06-29;
the NSO date remains an observation key. The two observed whole-commune parent
changes are linked, while the resolution's other partial-area transfers remain
roster-invisible boundary changes. Resolution `29/NQ-CP@2009-06-30` now has a
complete secondary review, contemporaneous Government and implementation press
corroboration, and an exact official VBPL full-text/original-ZIP lead. Its three
commune creations and five Giang Thành parent changes are fully linked, while
the partial Phú Mỹ→Đông Hồ transfer is roster-invisible. The official bytes
remain blocked by HTTP 403, so it remains `secondary_only`. Resolution
`889/NQ-UBTVQH13@2015-03-12` now has a complete signed secondary-hosted scan,
expanded contemporaneous and retrospective press review, and all seven
same-code ward retypes reconciled. Its legal issue/effective date is
2015-03-11; the NSO date remains the observation key. No official-hosted
enacted copy was recovered, so it remains `secondary_only`. All 29 primary-
source-open instruments have received bounded reviews and are now explicitly
accepted as bounded source residue for historical graph construction. They
remain primary-source-open; none was promoted to official evidence. Task 8 is
complete in `data/ward-history.json`. Continue official-artifact recovery only
when a concrete lead is available, and keep Wikidata reconciliation and
emission separately gated.

Read the current [graph handoff](docs/journals/2026-09-01.03.ward-history-graph.md),
the generated [open-instrument checklist](docs/ward-source-open-instruments.md),
and the source-closure
[`plan`](docs/plans/2026-08-28-phase3-ward-historical-source-closure.md).
Resolution 460's official Vietlaw recovery and Resolution 820's bounded
secondary review are recorded in journals
[`2026-08-29.16`](docs/journals/2026-08-29.16.ward-source-460-nq-ubtvqh14.md)
and
[`2026-08-29.17`](docs/journals/2026-08-29.17.ward-secondary-provenance-820.md).
Resolution 469's official PDF lead and supplied-source review are recorded in
[`2026-08-30.02`](docs/journals/2026-08-30.02.ward-secondary-provenance-469.md).
Decree 84's official print/DOC leads, date discrepancy, and supplied-source
review are recorded in
[`2026-08-30.03`](docs/journals/2026-08-30.03.ward-secondary-provenance-84.md).
Decree 85's official recovery path, secondary topology, and local-press
corroboration are recorded in
[`2026-08-30.04`](docs/journals/2026-08-30.04.ward-secondary-provenance-85.md).
Decree 97's official recovery path, five commune creations, date discrepancy,
and supplied-source review are recorded in
[`2026-08-30.05`](docs/journals/2026-08-30.05.ward-secondary-provenance-97.md).
Decree 98's official recovery path, Tân Hiệp topology and date discrepancy,
and supplied-source review are recorded in
[`2026-08-30.06`](docs/journals/2026-08-30.06.ward-secondary-provenance-98.md).
Decree 28's archived Government artifacts, code/date correction, and Hơ Moong
topology are recorded in
[`2026-08-30.07`](docs/journals/2026-08-30.07.ward-source-28-2006-nd-cp.md).
Decree 29's official lead, two whole-commune retypes, date discrepancy, and
supplied-source review are recorded in
[`2026-08-31.01`](docs/journals/2026-08-31.01.ward-secondary-provenance-29.md).
Decree 34's official lead, whole-commune retype, date discrepancy, and
supplied-source review are recorded in
[`2026-08-31.02`](docs/journals/2026-08-31.02.ward-secondary-provenance-34.md).
Decree 39's official lead, seven commune creations, boundary transfers,
transcription discrepancy, and supplied-source review are recorded in
[`2026-08-31.03`](docs/journals/2026-08-31.03.ward-secondary-provenance-39.md).
Decree 60's official lead, three ward establishments, parent-label echo, and
supplied-source review are recorded in
[`2026-08-31.04`](docs/journals/2026-08-31.04.ward-secondary-provenance-60.md).
Decree 64's official lead, five parent changes, boundary transfer, and
supplied-source review are recorded in
[`2026-08-31.05`](docs/journals/2026-08-31.05.ward-secondary-provenance-64.md).
Decree 137's official Government recovery, code/date discrepancies, Cư Kuin
topology, and concurrent-event disambiguation are recorded in
[`2026-08-31.06`](docs/journals/2026-08-31.06.ward-source-137-2007-nd-cp.md).
The two malformed Decree 14 index rows, the archived actual decree, and their
canonical Resolution 14 correction are recorded in
[`2026-08-31.07`](docs/journals/2026-08-31.07.ward-index-correction-14-2008.md).
Decree 07's exact official ZIP lead, Buôn Hồ topology, transcription anomaly,
and same-code Nghệ An disambiguation are recorded in
[`2026-08-31.08`](docs/journals/2026-08-31.08.ward-secondary-provenance-07-buon-ho.md).
Decree 08's official full-text/ZIP lead, Hồng Ngự topology, implementation and
classification evidence, and same-code Bến Tre disambiguation are recorded in
[`2026-08-31.09`](docs/journals/2026-08-31.09.ward-secondary-provenance-08-hong-ngu.md).
Decree 10's exact official full-text/ZIP lead, Ba Tơ–Sơn Tây topology,
date discrepancy, and same-code Lâm Đồng disambiguation are recorded in
[`2026-08-31.10`](docs/journals/2026-08-31.10.ward-secondary-provenance-10-ba-to-son-tay.md).
The two date-distinct Decree 11 records, the supplied Hà Giang bundle, the
correct Thanh Hóa full-text lead, and the Lãng Công crosswalk anomaly are
recorded in
[`2026-08-31.11`](docs/journals/2026-08-31.11.ward-secondary-provenance-11-number-collision.md).
Decree 12's complete official full-text/ZIP lead, 30 Cần Thơ topology
components, Thạnh Hòa correction, date discrepancy, and supplied-source
review are recorded in
[`2026-08-31.12`](docs/journals/2026-08-31.12.ward-secondary-provenance-12-can-tho.md).
Resolution 26's archived Government artifacts, Thuận Nam topology, date
distinction, secondary-source defects, and preceding Decree 14 false hit are
recorded in
[`2026-08-31.13`](docs/journals/2026-08-31.13.ward-source-26-nq-cp.md).
Resolution 28's archived official Gazette record and enacted PDF, Mỹ Tho
topology, legal/observation date distinction, and supplied-source review are
recorded in
[`2026-08-31.14`](docs/journals/2026-08-31.14.ward-source-28-nq-cp.md).
Resolution 29's official ZIP lead, Giang Thành topology, legal/observation date
distinction, and supplied-source review are recorded in
[`2026-09-01.01`](docs/journals/2026-09-01.01.ward-secondary-provenance-29-nq-cp.md).
Resolution 889's signed secondary scan, seven whole-unit ward retypes,
legal/observation date distinction, and expanded supplied-source review are
recorded in
[`2026-09-01.02`](docs/journals/2026-09-01.02.ward-secondary-provenance-889-dien-ban.md).
The later graph-building slice remains gated: only after Task 7 passes should
the observations and resolved events be promoted into canonical ward entities
and `LineageEdge` records. Do not emit or upload ward Wikidata statements yet.

**Phase-3 source recovery (2026-08-27/28): the ward SOAP archive is complete.** The
NSO hostname recovered after a DNS `SERVFAIL`, and `vn_admin_units.ward_rescue` cached + hash-verified
the 2025 reform boundaries, 2026 Đồng Nai boundaries, and current roster. The pre-reform source has
**10,035 wards, 691 province/district parent pairs, and complete `MaQuanHuyen` coverage**; the
post-reform/current source has **3,321 wards**. This unblocks the 2025 ward slice. The full historical
Phase-3 build uses a reviewed 204-date crawl, pinned as of 2026-08-27, with deterministic gzip storage;
**all 204 dates are verified**. The archive contains 180 unique decoded payloads and no missing
district parent codes across 2,202,543 snapshot rows. The historical archive remains the input for
the later 2002→2025 chain.
See [Emergency ward-source
rescue](#emergency-ward-source-rescue) and journal
[`2026-08-27.01`](docs/journals/2026-08-27.01.ward-soap-source-rescue.md) for the audit, recovery,
storage contract, and next work. The first build slice is now locked in
[`docs/plans/2026-08-28-phase3-ward-2025-boundary.md`](docs/plans/2026-08-28-phase3-ward-2025-boundary.md):
normalize the 2025 boundary and preserve all 3,316 structured primary links and
five creations. The boundary spine now builds as `data/ward-2025-boundary.json`; its audit also
records the historical SOAP province-echo behavior (999 code differences) and
the one source-backed blank-label repair. See journal
[`2026-08-28.01`](docs/journals/2026-08-28.01.ward-2025-boundary-spine.md).

**Phase-3 composition gate (2026-08-28, DONE).** All 34 provincial instruments
(`1654`–`1687/NQ-UBTVQH15`) are preserved as signed PDFs plus official full-text
HTML. Their 3,194 arrangement clauses, together with 127 unchanged-unit rows,
resolve all 10,035 pre-reform wards into 10,586 edges. The graph has 459 split
predecessors, five predecessorless special-unit creations, zero unresolved
predecessors, and all 3,316 primary links. The parser deliberately excludes
successor result names from constituent evidence; 192 parser-resistant
predecessor identities/splits are explicit, resolution-backed curation. See
`data/ward-2025-composition.json` and journal
[`2026-08-28.02`](docs/journals/2026-08-28.02.ward-2025-composition-lineage.md).

<details><summary><b>Phase 2 build log (historical — complete + uploaded 2026-07-20)</b></summary>

**R1–D11 all complete:**
- **D7** `build_districts` — 718 entities, 25 lineage edges, 0 residue (survivor-row
  dissolve mechanism; division-via-dissolve for Ayun Pa; curated
  `data/district-merge-targets.json`). 8-test ground-truth gate.
- **D8** reconciliation — bulk SPARQL + alias-aware match + audit; **live-reconciled
  718/718** (the SPARQL class `Q13221722` was wrong → the four real district classes).
- **D9** relation-aware emitter (P576-on-end, P807 carve, dated P131/P31, abolition).
- **D10** constraints gate (P131+P580/P582) + **live-confirmed the 4 district `P31`
  targets** (the placeholders were junk items — corrected in `core.py`).
- **D11** pipeline (`build_districts_all`, 4 hard gates) + `event-decree overrides`
  (`data/district-decree-overrides.json`) that cleared the whole-graph reference gate.
  `ABOLITION_REF` = Luật 72/2025/QH15 (Điều 51 khoản 3). Emitted **1778 referenced
  statements** — 0 self-edges, 0 reference-gate offenders.
- Earlier, R1–R4 + D1–D6.5 (below) + the decree reference URLs (63→**156**).

<details><summary>R1–D6.5 (earlier)</summary>

- **R1–R4:** extracted `src/vn_admin_units/core.py` (shared `Entity`/`LineageEdge` +
  emit primitives + relation vocabulary); migrated 1a (`model.py`) and 1b
  (`province_history.py`) onto it — **1a `mappings/` proven byte-identical**.
- **D1–D6.5:** `parse_district_ghichu` (`ghichu.py`); `fold_district_name` (`names.py`);
  `district_model.py` types + `unit_tier`/`classify_change`/`window_events` +
  `group_by_event`/`source_survives`/`resolve_merge_target`; `decree_index`/`decree_for`/
  `decrees_naming`/`cache_decrees` (`crosscheck_decrees.py`). Cached Nghị định list →
  `data/raw/nghidinh.json` (544 recs).
- **Reference URLs — RESOLVED (2026-07-18):** `data/decree-urls.json` = **155** URLs
  (was 63); the entire residue is cleared. See journal
  [`docs/journals/2026-07-18.01`](docs/journals/2026-07-18.01.district-decree-reference-residue.md)
  for the worklist and the two follow-ups it hands to the D7 build (plan Execution
  corrections 4–5): exclude `621/TCTK-PPCĐ` (a code-only re-code, not an event) and key
  the 5 genuinely-ambiguous bare codes by `(code, effective_date)` — their 10 per-event
  URLs sit in `data/decree-urls-residue-2026-07-18.json → residue_c_date_qualified`.

</details>

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

**✅ RESOLVED (was the reference-residue OPEN DECISION):** the decree reference URLs are
fully sourced (`data/decree-urls.json` 63→155). Two automated fan-out passes
(thuvienphapluat, then authoritative-gov fallback) plus a maintainer browser-resolve of the
unfindable tail closed it. **Also authoritative in the plan now (Execution corrections 4–5):**
`621/TCTK-PPCĐ` is excluded as a code-only re-code (not a lineage event), and the 5
genuinely-ambiguous bare codes (`04/11/19/33/34 NQ-CP`) are keyed by `(code, effective_date)`
— both are D7-build code changes, not data. Full worklist: journal `2026-07-18.01`.

**NEXT, in order (pre-upload) — see journal [`2026-07-19.01`](docs/journals/2026-07-19.01.district-reconciliation-successor-tail.md):**
1. **Decide the 11 "became-a-ward/đặc-khu" districts one-by-one** (the journal lists each
   with Wikidata URLs). Three groups: island huyện → 1 đặc khu (successor-match, = Phú Quý);
   thị xã → ward (swap in the correct successor); mainland huyện → many wards (1:many — no
   single successor → create-new or leave `gap`). Then update `mappings/districts-qid.csv`.
2. **Land the reconciliation-fallback tier-check** (systemic): `_district_search_fallback`
   must verify the candidate is district-tier (`P31 ∈ the 4 classes`), not just `P17=Vietnam`
   — that P17-only check is what accepted the wrong same-named items (a province, a Thanh Hóa
   commune). Do before the next `reconcile_districts_live`.
3. *(only if any create-new)* add QuickStatements `CREATE` support to `emit_district_quickstatements`.
4. Re-run `build_districts_all` → regenerate `statements/na-districts.qs`; re-run the pre-upload
   **audit** (`reconcile.audit_district_qids` — clean except the accepted cross-tier `TYPE`
   flags like Phú Quí) + the **D10 constraints gate**.

**Human touchpoints (were manual):** the 11-district decisions; the Wikidata uploads (maintainer's
account — QuickStatements batches #261329/#261330/#261331).

</details>

**Future phases:** Phase 3 wards (NA16) — the resume target above; then pre-2002 history. See the
roadmap in [`docs/DESIGN.md`](docs/DESIGN.md).

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
  (QuickStatements) · `ward_rescue` (resumable raw ward SOAP preservation) ·
  `ward_model` (verified 2025 boundary observations + primary-link evidence) ·
  `ward_history` (canonical 2002-present ward graph) · `cli`
  (`cache_snapshots`, `build_all`, `build_wards_2025_boundary_all`,
  `build_ward_history_all`).
- `data/raw/` — exact source content, stored verbatim or in deterministic lossless
  gzip, + `manifest.jsonl` (artifact and decoded-content hashes); `crosswalk/`
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
uv run python -c "from vn_admin_units.cli import build_wards_2025_boundary_all; build_wards_2025_boundary_all()"
uv run python -m vn_admin_units.ward_history --check --audit
uv run python -m vn_admin_units.reconcile           # (re)reconcile provinces -> QIDs (resumable)
uv run python -m vn_admin_units.reconcile --audit   # correctness gate (required before upload)
uv run python -m vn_admin_units.constraints         # check WD property constraints
uv run python -m vn_admin_units.fetch --tier ward --date 01/01/2019 --dups   # ad-hoc source query
```

### Emergency ward-source rescue

The ward crosswalk omits the former district code (`MaQuanHuyen`), so exact
`DanhMucPhuongXa` SOAP snapshots are required before the Phase-3 ward build.
The rescue command verifies cached hashes, skips completed dates, retries
transient failures with exponential backoff, and writes exact response content
in deterministic gzip + provenance to `data/raw/`:

```sh
# Five highest-priority 2025/2026 dates (preview, then fetch)
uv run python -m vn_admin_units.ward_rescue --dry-run
uv run python -m vn_admin_units.ward_rescue

# Reviewed history: source/annual anchors + each ward-event effective date.
# Consecutive event observations supply the prior state for the next event.
uv run python -m vn_admin_units.ward_rescue --scope history --plan-as-of 2026-08-27 --dry-run
uv run python -m vn_admin_units.ward_rescue --scope history --plan-as-of 2026-08-27

# Emergency ceiling for suspected legal-index gaps: also request every day-before.
uv run python -m vn_admin_units.ward_rescue --scope history-bracketed --plan-as-of 2026-08-27 --dry-run

# A short recovery window or an explicit date
uv run python -m vn_admin_units.ward_rescue --scope history --plan-as-of 2026-08-27 --limit 20
uv run python -m vn_admin_units.ward_rescue --date 30/06/2025
```

Keep `--plan-as-of` unchanged and rerun the same command after any interruption;
otherwise the rolling current-roster request changes with the calendar date.
Verified payloads are not fetched
again unless `--force` is supplied. The rescue stops after the first date that
exhausts its retries so it does not hammer an unavailable source; use
`--continue-on-error` only to probe past a date-specific failure.

## Sources

Authoritative upstream is the GSO/NSO *danh mục hành chính* service
(`nso.gov.vn`): `DMDVHC.asmx` SOAP (point-in-time via `DenNgay`, all tiers) +
`Doi_Chieu_Moi.aspx` crosswalk + `NghiDinh.aspx` legal-document index.
`Lich_Su_Moi.aspx` is an inventory, not an event source. Data is 2002→present.
See `docs/DESIGN.md` and `docs/journals/2026-07-20.01` for the current source model.

## Development

Python + [uv](https://docs.astral.sh/uv/) (matching `vietnam-elections-wikidata`).
TDD; small commits; `uv run pytest`.
