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
| **raw cache** | committed SOAP snapshots + crosswalk Excel exports, verbatim | provenance |
| **observations** | per-`(code, era)` records: name, type, parent-at-time, dates, decree | time-qualified statements |
| **entities** | persistent `local_id`, existence span, current name/code, `wikidata_qid` | items |
| **lineage** | edges `replaces`/`merged_into`/`split_from` + whole/partial + decree + date | P571/P576/P7888/P1365/P1366 |
| **reconciliation** | `(code, era)` / entity ↔ Wikidata QID, with match status | — |
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
reforms), since ward-level changes occur between the big reforms too. See the
open question on change-discovery mechanism.

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

## Open decisions (not blocking Phase 1 start)

- Exact WD qualifier properties for partial/primary contributions (constraint-check).
- ~~`Ghi Chú` parsing approach~~ **Decided (`.09`):** rule-based template parser
  (a one-line regex already extracts the 12 province merge edges), validated to
  100% against the 34 known province outcomes in Phase 1, then reused for wards
  with snapshot-diff cross-check. Remaining sub-question: enumerating the handful
  of template variants (city establishments, 3-way merges) at ward scale.
- Reconcile-vs-create policy per unit (most new items exist; enrich by default).
- Whether to formally propose a GSO-code Wikidata property.
- Update cadence (scheduled `DenNgay=today` diff) — Phase 2.
- Raw-cache format to commit (CSV/parquet vs the `.xls` verbatim).

## References

Probe journals `docs/journals/2026-07-10.01`–`.08`; monorepo brainstorm spec
`docs/journals/2026-07-10.vietnam-admin-units-design.md` (superseded by this doc).
