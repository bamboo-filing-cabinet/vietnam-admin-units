# vietnam-admin-units — Design

Living design doc. Supersedes the initial brainstorm spec
(`../../docs/journals/2026-07-10.vietnam-admin-units-design.md`, monorepo), which
predated the source reconnaissance. Grounded in probe journals `2026-07-10.01`–`.08`.

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

## Phasing

- **Phase 1 (now): Goal B, 2025 reform — province tier first** (63↔34). This
  builds the *entire* stack end-to-end on a small, fully-known set: identity +
  lineage + **`Ghi Chú` parser** + qualifier encoding + WD batch. Provinces need
  `Ghi Chú` parsing too (absorbed provinces' destinations are prose-only, `.09`)
  — and are the ideal validation set (34 known outcomes → verify the parser to
  100%). The parser is then reused for the ward tier.
- **Phase 1b: ward tier** (10,040↔3,321) — same parser, no full ground-truth,
  cross-checked against snapshot diffs.
- **Phase 2: Goal A** — consumer exports + historical eras (2002–2021) for the
  election repos; and the abolished-district / old-item dissolution backfill.

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
7. Ghi Chú parsing = **rule-based template parser**, validated on provinces (`.09`).
8. Licensing = **clear** for facts (`.07`).

## Remaining items — execution tasks, not decisions (fold into the plan)

- **Verify WD qualifier constraints** for `P1365`/`P7888` (partial/primary/date
  qualifiers) — do before the emit step (WDQS was under outage).
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
spec `docs/journals/2026-07-10.vietnam-admin-units-design.md` (superseded by this
doc).
