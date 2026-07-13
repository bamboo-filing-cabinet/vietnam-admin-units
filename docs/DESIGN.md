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
| `docs/DESIGN-phase2.md` | Phase-2 design: ward tier + province chaining (2002→2025), Goal A for NA16 |
| `docs/DESIGN-phase3.md` (future) | Phase-3 design: **district tier** (2002→2025) → NA11–NA15 units. Not yet written |
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
real only at ward scale — budget it as its own Phase-1b sub-step with validation.

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

**Change-discovery mechanism (decided 2026-07-10): hybrid.** The **Lịch Sử**
change-log page is the authoritative event list (decree + effective date per
change); the **Đối Chiếu crosswalk** supplies the old↔new lineage; **SOAP
`DenNgay`** supplies membership snapshots. Each source does what it's best at.
Open task: browser-scrape Lịch Sử (DevExpress + Excel export, like the crosswalk
— mechanics still to verify).

## Phase roadmap

Phases are ordered by **tier + time-depth**, which map onto **which National
Assembly era's electoral units they can feed** (Goal A). The hard boundary: the
**GSO source floors at 2002-01-01** (`.02`), covering NA11→NA16; earlier
assemblies need non-GSO sources.

| Phase | Scope | Feeds (Goal A) | Source |
| --- | --- | --- | --- |
| **1** ✅ | 2025 reform, **province** tier | — | GSO |
| **2** | **district** tier (huyện/quận, 2002→2025 — abolished in 2025) | **NA11–NA15 (2002–2021)** units (district-composed) | GSO |
| **3** | **ward** tier + province historical chaining (2002→2025) + freshness | **NA16 (2026)** units (ward-composed) | GSO |
| **4** (aspirational) | **pre-2002 history** (NA1 1946 → NA10 1997), all tiers | earliest assemblies | **non-GSO** (decrees, archives, Wikipedia, gazetteers) |

- **Phase 1** built the entire pipeline on the easy tier: identity + lineage +
  `Ghi Chú` parser + qualifier encoding + WD batch, validated 100% on 34 known
  province outcomes; the parser is reused downstream. **Uploaded 2026-07-12**
  ([batch #260741](https://quickstatements.toolforge.org/#/batch/260741), 0 errors).
- **Phase 2 (districts)** — the district tier is purely historical (all
  dissolved in 2025) and establishes the parent layer that wards need for P131
  lineage. Districts are simpler (~700 entities vs ~10k wards) and feed the
  district-composed NA11–NA15 electoral units. Challenges: the 2004 code-scheme
  change (`.15`) and 2002–2025 churn. Districts before wards so that ward P131
  history can reference proper district QIDs.
- **Phase 3 (wards)** — ward tier (10k→3.3k in 2025 reform), name→code
  disambiguation (the core difficulty), province historical chaining, Goal A
  exports for NA16 (ward-composed). Formerly `DESIGN-phase2.md` sub-projects
  P2a–P2d; to be revised when reached.
- **Phase 4** is the "back to NA1 (1946)" ambition. It is genuinely different: no
  GSO data below 2002, so it's a distinct sourcing/provenance project, not more
  of the same pipeline. Captured here so the ambition isn't lost.

## Decisions log (all foundational forks now settled)

1. First deliverable = **Goal B**, 2025 reform, **province tier first**.
2. Identity = **new-entity-per-reform + lineage**; NSO continuity via
   qualifiers/aliases (`.08`).
3. Temporal scope = **all reforms 2002→present, chained** multi-hop.
4. Change-discovery = **hybrid** (Lịch Sử events + crosswalk lineage + SOAP
   snapshots).
5. Lineage resolution = **combination** (anchor primary → resolve prose via
   snapshot context → validate → manual residue).
6. Reconciliation = **incremental edge-closure** (per phase; enrich, create gaps).
   **Always audit before upload** — `reconcile --audit` (name-aware instance-of)
   is a required gate; it caught Cà Mau province mis-matched to the city
   (`2026-07-11.02`). Manual fixes → `match_status=manual`.
7. Ghi Chú parsing = **rule-based template parser**, validated on provinces (`.09`).
8. Licensing = **clear** for facts (`.07`).

## Remaining items — execution tasks, not decisions (fold into the plan)

- ~~**Verify WD qualifier constraints** for `P1365`/`P7888`~~ **DONE (`2026-07-11.01`):**
  province batch is constraint-clean (P585 fine on P7888/P1366/P1365; P576 date-as-value).
  Tool: `vn_admin_units.constraints`. Phase-2 note: `P571` rejects `P585` (keep
  inception as value). Re-run the tool for new props (`P518`/`P1107`) in Phase 2.
- **Browser-scrape Lịch Sử** mechanics (Excel export like the crosswalk).
- **Data-quality normalization** pass (Ghi Chú typos/newlines; đặc-khu 12-vs-13;
  **exact-duplicate rows in historical ward snapshots** — 17 in 2019, 19 in 2020,
  0 in 2025 per `.14`; dedupe on `(MaTinh, MaQuanHuyen, MaPhuongXa)` within a
  snapshot), with a logged correction list. Always fetch via `vn_admin_units.fetch`
  (canonical, DocumentElement-scoped), never ad-hoc scripts.
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
