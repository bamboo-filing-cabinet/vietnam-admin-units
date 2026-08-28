# vietnam-admin-units — Design (overarching)

**This is the overarching, cross-phase design + decisions log.** Per-phase detail
lives in separate docs (see Document map). Supersedes the initial brainstorm spec
(`../../docs/journals/2026-07-10.vietnam-admin-units-design-SUPERSEDED.md`,
monorepo), which predated the source reconnaissance. Grounded in probe journals
`2026-07-10.01`–`.15`.

## Document map

| Doc | Role |
| --- | --- |
| `docs/DESIGN.md` (this) | Overarching design: purpose, data model, identity, decisions log, phasing |
| `docs/DESIGN-phase1b.md` | Phase-1b design: **province history** (2002→2025) — 2004 renumber + carve-outs, 2008 Hà Tây, chained; completes the province tier + unblocks Phase 2 |
| `docs/DESIGN-phase2.md` | Phase-2 design: **district tier** (2004→2025), Goal B Wikidata lineage + 2025 abolition; feeds NA11–NA15 |
| `docs/DESIGN-phase3.md` | Phase-3 design: ward tier + province chaining (2002→2025), Goal A for NA16. **Internal numbering is stale** (predates the district-first renumber); to be revised when reached |
| `docs/DESIGN-phase4.md` (future) | Phase-4 design: **pre-2002 history** (NA1–NA10) via non-GSO sources. Not yet written |
| `docs/plans/2026-07-10-phase1-province-wikidata.md` | Phase-1 **implementation plan** (province tier, done) |
| `docs/journals/2026-07-10.NN.*.md` | Dated decision/probe log (`.01`–`.15`): source recon, taxonomy, findings |
| `../../docs/journals/2026-07-10.vietnam-admin-units-design-SUPERSEDED.md` | Original brainstorm spec (monorepo), **superseded by this doc** |

## Purpose

A time-versioned, Wikidata-reconciled dataset of Vietnam's administrative units
(province / district / commune-ward), 2002→present. It is the **foundation layer**
beneath the election projects and the source that **drives corrections to
Wikidata's out-of-date VN admin items**. Facts only — no election concepts, no
government photos (see licensing, `.07`).

Two goals, one shared core (**reconciliation**):

- **Goal A — feed the election repos.** Point-in-time lookup: "units of province
  P at date D, with QIDs" + the old↔new crosswalk. Served by snapshots +
  reconciliation.
- **Goal B — fix Wikidata.** The identity + lineage graph that turns WD's
  mid-migration state into a correct one.

**First deliverable: Goal B — the 2025-reform Wikidata correction.** (Decided
2026-07-10.) Rationale: it directly attacks the `vietnam-elections-wikidata`
lao-cai pain, and recon showed it's tractable — the new WD items largely already
exist; only the **graph structure connecting them is missing** (`.08`).

## The product is a dataset, not a pipeline

The raw data is handed to us by GSO/NSO; the value-add is identity, lineage, and
reconciliation. Artifacts (each mirrors a Wikidata concept):

| Artifact | What it is | WD analog |
| --- | --- | --- |
| **raw cache** | `data/raw/` — **exact source bytes** (SOAP responses as `.xml`, crosswalk as `.xls`) + a **provenance manifest** (`manifest.jsonl`: source URL, params/`DenNgay`, retrieved-at, sha256, rows) | provenance |
| **observations** | per-`(code, era)` records: name, type, parent-at-time, dates, decree | time-qualified statements |
| **entities** | persistent `local_id`, existence span, current name/code, `wikidata_qid` | items |
| **lineage** | edges `replaces`/`merged_into`/`split_from` + whole/partial + decree + date | P571/P576/P7888/P1365/P1366 |
| **reconciliation** | `(code, era)` / entity ↔ Wikidata QID, with match status — **incremental edge-closure** (per phase, only entities on the edges being built; enrich existing items, create gaps) | — |
| **exports** | WD correction batches (Goal B); consumer JSON (Goal A) | outputs |

## Identity model (decided 2026-07-10)

**New entity + lineage, Wikidata-aligned.** A reform / merger / split produces a
**new entity** (new `local_id`, matching WD's freshly-created items like
`Q135651473`); predecessors dissolve and are linked by lineage. A **pure rename
or minor boundary tweak within a stable period keeps the same entity** (relabel;
old name as alias). This matches (a) what the WD community actually did for the
2025 reform (`.08`) and (b) the `vietnam-elections-wikidata` electoral-unit
"new item on namespace redraw" precedent, one tier down.

**NSO continuity is preserved via qualifiers/references/aliases, not by merging
nodes.** So the new-entity choice loses no information:

- New entity: `P571 inception`; `P1365 replaces` → each predecessor, **referenced**
  to the decree (`P248` → the Nghị quyết) and **qualified** for partial
  contributors ("1 phần …") with a proportion/part qualifier (`P1107`/`P518`);
  the renamed-from primary's name kept as an **alias**; the inherited GSO code
  carried as its era attribute.
- Old entities: `P576 dissolved`; `P7888 merged into` (+ `P1366 replaced by`) →
  the new entity; `P131` kept as historical (optionally end-dated).

Identity keys: repo-owned **`local_id`** is the spine; GSO `code` is a per-era
attribute keyed **`(code, era)`** — codes are reused across reforms at both
province (`.02` A1) and ward (`.03`) level, so code is never a cross-era key.

**Local entities vs Wikidata items are two layers (critical).** The local model
is *always* new-entity-per-reform. **Reconciliation** then maps each local entity
to the WD item that represents it — and this is **many-local-to-one-QID** where
WD edited a survivor **in place**:

- **Provinces:** WD kept one item per surviving province and edited it (e.g. old
  Lào Cai *and* merged Lào Cai are both `Q36446`); the absorbed province (Yên
  Bái `Q36349`) is a distinct item. So the pre and post local entities of a
  survivor reconcile to the **same QID**.
- **Wards:** WD minted **new** items even for the renamed-from primary (Ba Đình
  `Q135651473` ≠ Trúc Bạch `Q10828647`).

So each entity carries a reconciliation **`qid_status`**: `existing` (item
pre-dates the reform — enrich only) vs `new` (freshly minted). This drives emit:

- **`P571 inception` only when `qid_status == new`.** Never stamp an inception on
  a pre-existing item (that would falsify a decades-old province's history).
- **Emit skips any lineage edge where `pre.qid == post.qid`** (survivor edited in
  place = one continuing item; emit no dissolved/merged/replaces self-references).
- **Every statement is referenced** (`S248` → the Nghị quyết item if it exists,
  else `S854` reference URL to the establishing resolution / NSO source) and
  lineage statements carry `P585` = effective date. Non-negotiable (`.07`).

> Constraint check required before any batch: `P1365`/`P1366`/`P7888` allowed-
> qualifier and value-type constraints (we hit this class of issue with `P1107`
> on `P39`). Verify against live property constraints.

## How the data is sourced (recon-confirmed)

- **Snapshots (membership, any date, all tiers):** SOAP `DMDVHC.asmx` with the
  `DenNgay` as-of-date param; empty `Tinh` returns a whole tier in one call
  (`.02`, `.03`). Floor = 2002-01-01 (`.02`). Era detection via the province-echo
  quirk, not a hard-coded date.
- **Lineage (old↔new + decree + effective date + composition):** the
  `Doi_Chieu_Moi.aspx` crosswalk, Excel export (`.04`, `.06`). Structured `Xã DC`
  gives only the **primary 1:1 successor** (code-inheriting); the full merge/split
  membership ("hợp nhất …, một phần …") is **only in the `Ghi Chú` prose** — so
  building complete edges requires **parsing `Ghi Chú`** (or cross-checking with
  SOAP snapshot diffs). Effective dates are reliable for mergers (2025-07-01,
  2008-08-01); anchor others to the decree.
- **Reconciliation:** no GSO-code property exists on WD (`.05`); match by
  `name-fold + province` (unique for current wards; add district for pre-reform).
  WD holds ~11.6k items reflecting the **old** structure; new reform items exist
  but lack lineage (`.05`, `.08`).

## Lineage resolution (decided 2026-07-10)

Complete the many-to-many lineage by a **combination**, since `Ghi Chú` names
constituents ambiguously (`.11`):

1. **Anchor** code-level edges on the structured primary link (`Xã ĐC`/`Tỉnh ĐC`
   — unambiguous, code-to-code).
2. **Resolve** the absorbed/partial `hợp nhất` / `một phần` constituents by
   matching each parsed name against the **pre-reform SOAP snapshot** within the
   new unit's province + old-district context.
3. **Validate** against `tranngocminhhieu/vietnamadminunits` (63→34 crosswalk +
   split flag).
4. **Manual curation file** for the unresolvable residue (logged, never silent).

Provinces (unique names) exercise steps 1–3 trivially; the disambiguation work is
real only at ward scale — budget it as its own **Phase-3** (ward) sub-step with
validation.

## Pipeline (regeneration tooling — secondary to the data)

`ingest` (SOAP snapshots + crosswalk export → raw cache) → `build` (normalize →
observations; parse crosswalk primary-links + `Ghi Chú` → lineage; assign
`local_id` entities) → `reconcile` (entities ↔ QID) → `emit` (Goal B: WD
QuickStatements batch; later Goal A: consumer JSON). Python + `uv`, mirroring
`vietnam-elections-wikidata`.

## What Goal B concretely delivers (first build)

From the lineage graph, generate a referenced Wikidata correction batch that:

1. **New units** — enrich existing items (or create if absent): `P571`, `P1365`
   → predecessors (qualified/referenced), fix `P131` (2-level → province) / `P31`.
2. **Dissolved units** — `P576`, `P7888`/`P1366` → successor; keep historical
   `P131`.
3. Everything referenced to the establishing Nghị quyết (satisfies the Statistics
   Law citation duty, `.07`).

## Temporal scope (decided 2026-07-10)

**The model spans all reforms in the GSO window (2002→present) with multi-hop
chained lineage** — a place is traceable across 2004 splits → 2008 (Hà Tây→Hà
Nội) → 2025 reform → 2026 (Đồng Nai). This is the "complete gazetteer over the
years" vision. It does **not** change the first *build* (Goal B, 2025 reform,
province tier) — but it means the schema must be generic dated records (no
event hard-coded to 2025), and it adds a **change-discovery** workstream:
enumerating *every* change event + date across the span (not just the headline
reforms), since ward-level changes occur between the big reforms too.

**Change-discovery mechanism (decided 2026-07-10; revised 2026-07-20).** The
mechanism is the **Đối Chiếu crosswalk yearly-sweep** (`01/01/Y → 01/01/(Y+1)`,
each window inside one code-era) for old↔new lineage + effective dates +
composition prose, **cross-checked against the Nghị định / Nghị quyết UBTVQH decree
lists** to catch same-unit-twice-in-year and ephemeral units the net-only crosswalk
misses; **SOAP `DenNgay`** supplies membership snapshots (and, for wards, the
district code the crosswalk export drops). **Superseded: Lịch Sử is NOT an event
source.** `Lich_Su_Moi.aspx` is a point-in-time *inventory* (code/name/level/decree
+ parent hierarchy), not an old→new change timeline — verified for districts
(`2026-07-13.01`) and wards (`2026-07-20.01`); its Excel export is non-functional at
sub-province level. Ward waves are **Nghị quyết UBTVQH**, and they are **already on
the existing `NghiDinh.aspx` list** — a mixed legal-document list, not Nghị-định-only
(202 UBTVQH resolutions, 177 ward-level, 2015→2026, per-resolution effective dates
matching the crosswalk's; probe `2026-07-20.01` §Follow-up). So `crosscheck_decrees.py`
extends to wards — no new source. The criteria-framework resolutions
(`653/2019/UBTVQH14`, `35/2023/UBTVQH15`) are NOT in that list, but the per-province
arrangement resolutions with effective dates are.

## Phase roadmap

Phases are ordered by **tier + time-depth**, which map onto **which National
Assembly era's electoral units they can feed** (Goal A). The hard boundary: the
**GSO source floors at 2002-01-01** (`.02`), covering NA11→NA16; earlier
assemblies need non-GSO sources.

| Phase | Scope | Feeds (Goal A) | Source |
| --- | --- | --- | --- |
| **1** ✅ | **province** tier, full **2002→2025** history — **1a** ✅ 2025-reform slice ([batch #260741](https://quickstatements.toolforge.org/#/batch/260741)); **1b** ✅ historical chaining (2004 renumber + carve-outs, 2008 Hà Tây, Cần Thơ/Huế retypes; [batch #260977](https://quickstatements.toolforge.org/#/batch/260977)) | — (province parent layer) | GSO |
| **2** | **district** tier (huyện/quận, 2002→2025 — abolished in 2025) | **NA11–NA15 (2002–2021)** units (district-composed) | GSO |
| **3** | **ward** tier + freshness | **NA16 (2026)** units (ward-composed) | GSO |
| **4** (aspirational) | **pre-2002 history** (NA1 1946 → NA10 1997), all tiers | earliest assemblies | **non-GSO** (decrees, archives, Wikipedia, gazetteers) |

- **Phase 1 (province tier, 2002→2025)** is *not* finished until the province tier
  spans the full GSO window. It has two parts:
  - **1a — 2025-reform slice ✅ uploaded.** Built the entire pipeline on the easy
    tier: identity + lineage + `Ghi Chú` parser + qualifier encoding + WD batch,
    validated 100% on 34 known province outcomes; the parser is reused downstream.
    **Uploaded 2026-07-12** ([batch #260741](https://quickstatements.toolforge.org/#/batch/260741),
    0 errors).
  - **1b — historical chaining 2002→2025 ✅ uploaded 2026-07-14 ([batch #260977](https://quickstatements.toolforge.org/#/batch/260977); design: `DESIGN-phase1b.md`, plan: `docs/plans/2026-07-14-phase1b-province-history.md`).** The **2004 code-scheme change**
    (3-digit→2-digit, `.15`) + the three 2004 carve-outs (NQ 22/2003/QH11), the **2008
    Hà Tây→Hà Nội** merger, and Cần Thơ/Huế retypes — chained, with the historical
    province entities **reconciled to QIDs** (14 statements; audit 0 issues).
    Previously slotted under Phase 3 ("province historical chaining"); **moved here**
    because it completes the province tier and because **Phase 2 districts depend on
    it** — a district's pre-2008 `P131` span emits the Hà Tây (etc.) province QID,
    which only 1b produces (1a reconciled 2025-era provinces only). **Sequencing: 1b
    before Phase 2.**
- **Phase 2 (districts)** — the district tier is purely historical (all
  dissolved in 2025) and establishes the parent layer that wards need for P131
  lineage. Districts are simpler (~700 entities vs ~10k wards) and feed the
  district-composed NA11–NA15 electoral units. Challenges: the 2004 code-scheme
  change (`.15`) and 2002–2025 churn. Districts before wards so that ward P131
  history can reference proper district QIDs.
- **Phase 3 (wards)** — ward tier (10k→3.3k in 2025 reform), name→code
  disambiguation (the core difficulty), Goal A exports for NA16 (ward-composed).
  (**Province historical chaining moved to Phase 1b** — see above.) Documented in
  `DESIGN-phase3.md` (sub-projects P2a–P2d; that doc's internal numbering predates
  the district-first renumber and still houses province chaining under P2b — to be
  revised when reached).
- **Phase 4** is the "back to NA1 (1946)" ambition. It is genuinely different: no
  GSO data below 2002, so it's a distinct sourcing/provenance project, not more
  of the same pipeline. Captured here so the ambition isn't lost.

## Decisions log (all foundational forks now settled)

1. First deliverable = **Goal B**, 2025 reform, **province tier first**.
2. Identity = **new-entity-per-reform + lineage**; NSO continuity via
   qualifiers/aliases (`.08`).
3. Temporal scope = **all reforms 2002→present, chained** multi-hop.
4. Change-discovery = **Đối Chiếu crosswalk yearly-sweep + Nghị định/Nghị quyết
   cross-check + SOAP snapshots** (revised 2026-07-20). **Lịch Sử retired as an
   event source** — it is an inventory, not a change timeline (`2026-07-13.01`
   districts, `2026-07-20.01` wards). The crosswalk is net-only, so the decree/Nghị
   quyết cross-check is required to bound the yearly-window blind spot.
5. Lineage resolution = **combination** (anchor primary → resolve prose via
   snapshot context → validate → manual residue).
6. Reconciliation = **incremental edge-closure** (per phase; enrich, create gaps).
   **Always audit before upload** — `reconcile --audit` (name-aware instance-of)
   is a required gate; it caught Cà Mau province mis-matched to the city
   (`2026-07-11.02`). Manual fixes → `match_status=manual`.
7. Ghi Chú parsing = **rule-based template parser**, validated on provinces (`.09`).
8. Licensing = **clear** for facts (`.07`).
9. **Province tier = full 2002→2025** (Phase 1) — **1a** 2025-reform slice ✅ +
   **1b** historical chaining (2004 renumber, 2008 Hà Tây), reconciled to QIDs —
   completed **before** districts. Phase 2's historical `P131` depends on the
   historical province QIDs that 1b reconciles (2026-07-14; supersedes the earlier
   placement of province chaining under Phase 3).

## Remaining items — execution tasks, not decisions (fold into the plan)

- **Ward SOAP raw-cache recovery (2026-08-27): critical slice DONE; history
  pending.** The initial audit found no real `DanhMucPhuongXa` response in the
  repository or its Git history. After the NSO hostname recovered, the rescue
  workflow preserved all five critical 2025/2026 dates: 10,035 pre-reform wards
  with complete `MaQuanHuyen`, then 3,321 post-reform/current wards, all unique.
  This unblocks the 2025 ward slice. Before the generated 371-date historical
  crawl, record the storage decision: the critical sample is 6.5 MiB raw but
  only ~398 KiB under deterministic gzip, projecting roughly 1.1 GiB raw versus
  60–70 MiB compressed for the full high-recall inventory. Operational record:
  journal `2026-08-27.01`.
- ~~**Verify WD qualifier constraints** for `P1365`/`P7888`~~ **DONE (`2026-07-11.01`):**
  province batch is constraint-clean (P585 fine on P7888/P1366/P1365; P576 date-as-value).
  Tool: `vn_admin_units.constraints`. Phase-2 note: `P571` rejects `P585` (keep
  inception as value). Re-run the tool for new props (`P518`/`P1107`) in Phase 2.
- ~~**Browser-scrape Lịch Sử** mechanics~~ **Dropped (2026-07-20):** Lịch Sử is an
  inventory, not an event source (`2026-07-13.01`, `2026-07-20.01`); no scrape
  needed. The ward net-only cross-check source is the **existing `NghiDinh.aspx`**
  (it already lists the ward-arrangement Nghị quyết UBTVQH — probe `2026-07-20.01`
  §Follow-up); extend `crosscheck_decrees.py` to wards.
- **Data-quality normalization** pass (Ghi Chú typos/newlines; đặc-khu 12-vs-13;
  **exact-duplicate rows in historical ward snapshots** — 17 in 2019, 19 in 2020,
  0 in 2025 per `.14`; dedupe on `(MaTinh, MaQuanHuyen, MaPhuongXa)` within a
  snapshot), with a logged correction list. Preserve build inputs via
  `vn_admin_units.ward_rescue` (exact bytes + manifest); use
  `vn_admin_units.fetch` only for ad-hoc diagnostics. Both use the canonical,
  DocumentElement-scoped parser — never use ad-hoc source scripts.
- **Ward `Ghi Chú` template variants** enumeration (city establishments, 3-way).
- ~~Raw-cache format~~ **Decided (2026-07-10):** verbatim raw + manifest +
  derived. `data/raw/` = exact source bytes (`soap/*.xml`, `crosswalk/*.xls`) +
  `manifest.jsonl` provenance; `data/` = normalized/derived (parsed JSON, built
  entities/lineage). Best provenance + reproducibility; accepts binary `.xls` in
  the raw layer.
- Optional/later: propose a GSO-code WD property; update cadence (`DenNgay=today`
  diff, Phase 2).

## References

Probe/decision journals `docs/journals/2026-07-10.01`–`.11`; monorepo brainstorm
spec `docs/journals/2026-07-10.vietnam-admin-units-design-SUPERSEDED.md` (superseded by this
doc).
