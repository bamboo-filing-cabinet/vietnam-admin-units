# vietnam-admin-units — Phase 2 Design (district tier, 2004→2025)

Extends `DESIGN.md` (the overarching design + decisions log). Grounded in the
district probe journals [`2026-07-13.01`](journals/2026-07-13.01.district-lich-su-and-crosswalk-probe.md)
(source scouting) and [`2026-07-13.02`](journals/2026-07-13.02.district-granular-crosswalk-probe.md)
(granular-window validation, extraction mechanism, decree cross-check).

The district tier (huyện / quận / thị xã / thành phố thuộc tỉnh) is **purely
historical**: it existed 2002→2025 and was **abolished 2025-07-01** by the two-tier
reform. Phase 2 builds the district entity + lineage graph 2004→2025 and drives
**Goal B** — Wikidata corrections. It also establishes the parent layer that Phase 3
wards need for historical `P131`.

## Decisions (settled in the 2026-07-13 brainstorm)

1. **First deliverable = Goal B** (Wikidata district lineage), mirroring Phase 1.
   WD already has the district items but lacks their lineage and 2025 dissolution.
2. **Time depth = full 2004→2025 chained history + the 2025 abolition.** All
   structural events the crosswalk exposes (create / dissolve / merge / split /
   rename / type-upgrade / re-parent), not just a single boundary.
3. **2025 abolition = `P576` dissolved only**, no successor link. The tier was
   eliminated and the province already contained the district; there is no
   same-tier successor. (Not "merged into province"; not linked to successor wards.)
4. **Identity = one continuous entity per district** (differs from Phase-1
   province "new entity per reform"): rename, type-upgrade, and **re-parenting** are
   **relabels/attribute-changes of the same entity** (WD edits in place → same QID;
   old name → alias). A **new entity is minted only for a genuinely new unit** (a
   split's products, a carve-out's child); any **persisting** side (a carve-out's
   shrunk parent, an absorption's grown absorber) **keeps its entity**. Lineage
   edges connect them.
5. **Event floor at 2004.** The Đối Chiếu tool cannot diff two pre-2004 dates
   (returns the code-conversion mapping — `2026-07-13.02`), so districts present at
   the 2004 baseline are roots (`valid_from = None`); pre-2004 ancestry is out of
   scope (Phase 4 / non-GSO).
6. **Decree numbers come from the Nghị định list**, matched by unit + effective
   date — *not* the crosswalk's own decree column, which is unreliable (blank or a
   later "last-touching" decree; `2026-07-13.02` cross-check).

## Sources (all cached / reachable)

- **23 district windows** `data/raw/crosswalk/district_*.xls` — yearly 2004→2024,
  the 2002→2004 code-remap boundary, and the 2025-01→06 pre-abolition tail.
- **Nghị định list** (`NghiDinh.aspx`) — authoritative decree numbers + dates;
  fetched/parsed by the existing `crosscheck_decrees` module.
- Reused: `crosswalk.read_district_crosswalk` (parser, done), the Phase-1
  `reconcile` / `emit` / `constraints` scaffolding.

## Data model

District assembly lives in a **new `district_model.py`**. Phase-1 `model.py`
hardcodes province eras/dates, a province-only `relation` set, and `p-{code}-{era}`
— so these are **district-shaped `Entity` / `LineageEdge` dataclasses, not a thin
reuse** of the Phase-1 ones (treat the shared shape as a refactor target, not an
import — see Dependencies & risks §2).

**`Entity`** (district), extended with two fields beyond the Phase-1 shape:

- `local_id = d-{code}-{gen}` — the 3-digit code alone is **not** a unique key:
  split/merge mint new entities that can **inherit** a predecessor's code across an
  event boundary (Từ Liêm `019` → new Nam Từ Liêm `019`), and a code can also be
  dissolved then reassigned. `gen` disambiguates entities sharing a code — the
  entity's `valid_from` (or `base` for the pre-2004 baseline). So old Từ Liêm =
  `d-019-base`, new Nam Từ Liêm = `d-019-2013-12-28`. Collisions detected + logged.
- `gso_code`, `name_vi`, `loai_hinh` (Huyện/Quận/Thị xã/Thành phố),
  `valid_from` / `valid_to`, `wikidata_qid`, `qid_status`.
- **`parent_province`** — a list of dated **parent-at-time spans**
  `{province_code, province_qid, from, to}`, **not a scalar**, because re-parenting
  keeps the same entity (Hà Tây→Hà Nội 2008 = one district, two parent spans).
  Drives date-qualified `P131`; the current span is the reconciliation key.
- **`aliases`** — former names from renames/upgrades (→ WD aliases).

**Date convention (consistent).** `valid_from`/`valid_to` are the **in-force span,
inclusive** (last in-force day). The **Wikidata event date** (`P571`/`P576`/`P585`)
is the **effective date**, equal to the successor's `valid_from` and the
predecessor's `valid_to` + 1 day. E.g. the abolition: `valid_to = 2025-06-30`,
event date `2025-07-01`; Từ Liêm's dissolution: `valid_to = 2013-12-27`, event date
`2013-12-28`. Baseline districts have `valid_from = None` (inception pre-2004,
unknown). The 2004 5-digit→3-digit remap is a recode of the same entity (old code →
alias via the 2002→2004 flat map), not a separate entity.

**`LineageEdge`**: `predecessor`, `successor`, `relation`, `share`
(`whole`/`partial`), `primary`, `decree`, `effective_date`. The `relation`
distinguishes **whether the predecessor ends** — because only ended entities get
`P576` (see Emit):

- `consolidated` / `merged_into` — predecessor **ends**, folded into successor.
- `split` — predecessor **ends**, replaced by two+ all-new successors
  (Từ Liêm → Nam + Bắc Từ Liêm).
- `carved_from` — predecessor **persists** (shrinks); a new successor is separated
  from part of it → **no `P576` on the predecessor** (emit: child `P807`→parent).
- `absorbed_into` — predecessor **ends**, absorbed into a **persisting** successor
  (successor is not new, just grows).
- `renamed_to` / `retyped` — same entity relabel (no edge; recorded as alias +
  optional `P31`/label update).

The 2025 abolition is an entity `valid_to` + flag (emit → `P576`, no successor),
not an edge. (Taxonomy per journal `2026-07-10.10`.)

## Graph assembly (event-log chaining)

For each yearly window in chronological order, harvest the **changed rows** (new /
dissolved / renamed / type-changed / **re-parented**) as dated events carrying the
crosswalk fields + `Ghi Chú`. Seed entities from the 2004 baseline roster, apply
events chronologically — chaining by district code — to build each entity's
timeline and the lineage edges, then apply the universal 2025 abolition.

**Cross-validation (built in):** the events harvested for year Y must exactly
explain the roster delta between the Y and Y+1 window snapshots; any mismatch is
logged (catches parser/chaining gaps).

## Lineage resolution — layered by signal, `Ghi Chú` supplementary

`Ghi Chú` is **often absent on changed rows** (e.g. the Từ Liêm split rows are
blank), so it is never required:

1. **Structured columns (always present)** classify the event type: name-diff +
   same code = rename; `loai_hinh` prefix change = type-upgrade; blank base =
   creation; blank succ = dissolution; **base-province ≠ compare-province =
   re-parenting** (a `P131` change, same entity — e.g. Hà Tây→Hà Nội 2008; added
   to change-detection since name-diff alone misses it).
2. **Same-`(effective_date, province, decree)` grouping** buckets related rows, but
   is only a *candidate* set — **one decree can cover several independent operations
   in one province** (verified: 2020 Cao Bằng `897/NQ-UBTVQH14` = three distinct
   mergers → Hà Quảng, Trùng Khánh, Quảng Hòa). Pairing each predecessor with its
   correct successor inside a multi-operation bucket needs the **parsed target name**
   (`Ghi Chú` "… vào huyện Y") or a structured primary link. A single-operation
   bucket resolves without prose (Từ Liêm→Nam+Bắc, 2013-12-28, `132/NQ-CP`); a
   multi-operation bucket that neither prose nor structure disambiguates goes to the
   manual-curation file.
3. **Roster-delta cross-check** confirms the grouping.
4. **`Ghi Chú` prose**, when present, names exact constituents and
   confirms/overrides the inference (parsed by the extended `ghichu.py`).
5. **Manual-curation file** for the unresolvable residue — logged, never silent.

`Ghi Chú` district templates (extend `ghichu.py`):

| pattern | event | edge |
| --- | --- | --- |
| `nhập (toàn bộ) … huyện X vào huyện Y` | merge | X `merged_into` Y |
| `chia tách từ huyện X (cũ)` / `thành lập … trên cơ sở … X` | split | new `split_from` X |
| `thành lập (huyện/quận/thị xã/thành phố) X` | creation | new entity |
| `đổi tên … thành …` | rename | relabel (same entity) |
| `thay đổi loại hình` | type-upgrade | relabel (same entity) |

## Reconciliation (~700 districts — all, since the 2025 abolition is universal)

District names repeat across provinces, so match on **(folded name + parent
province)**, not name alone.

- **Bulk SPARQL** pulls all VN districts (incl. abolished/historical) with QID,
  label, aliases, parent province, `P31` in one query; match locally. Scales far
  better than ~700 per-item searches. Fallback: per-item `wbsearchentities` +
  province-verify for misses.
- `qid_status` = `existing` (enrich) vs `new` (gap to create); most exist, but
  existing VN district items are typically **near-empty** (e.g. Nông Sơn
  `Q2541962` has only `P31`/`P131` — no inception or origin; verified 2026-07-13),
  so most edits are **additive** (`P571`/`P807`/`P576`/`P131`), and some units are
  genuine gaps (e.g. Bắc Từ Liêm has no `vi` item).
- **Audit gate** (extends Phase-1 `--audit`): name- *and* province-aware
  instance-of check; flagged rows fixed manually (`match_status = manual`).
  Required before any upload.

## Emit (extends `emit.py`)

- **`P576` (dissolved) only on entities that actually END** — whose `valid_to`
  equals this event's date. A `carved_from` or `absorbed_into` predecessor that
  **persists** gets **no `P576`**. (Key fix: never dissolve a survivor of a
  carve-out/absorption.)
- **Succession by relation:** an **ended** predecessor → `P7888`/`P1366` →
  successor, and successor → `P1365` → predecessor, `P585` = event date. A
  **`carved_from`** child (parent persists) instead uses **`P807` (separated from) →
  parent** + its own `P571`: `P807` fits by definition ("subject was founded or
  started by separating from identified object"), and its subject/value-type
  constraints both allow *administrative territorial entity* — VN districts qualify
  (verified 2026-07-13) — whereas `P1365`/`P576` would wrongly imply the parent was
  replaced/dissolved.
- **Skip same-QID edges** (rename/type-upgrade survivors edited in place).
- **`P571` inception when `valid_from` is known** (created within 2004→2025) —
  **not** gated on `qid_status`: a genuinely-new-in-era district usually already has
  a WD item that still lacks/misstates its inception. **Audit the item's existing
  claims first** to avoid a duplicate/conflicting `P571`. Baseline districts
  (`valid_from = None`) never get `P571`.
- **`P131`** → parent province, one date-qualified statement **per parent span**
  (`P580`/`P582`) — Hà Tây→Hà Nội 2008 emits two `P131` statements.
- **2025 abolition:** `P576 = 2025-07-01` on every district, referenced to the
  reform resolution; no successor.
- Every statement **referenced** (`S248` → the Nghị quyết item if it exists, else
  `S854` URL). **Extend then re-run the `constraints` gate**: it currently checks
  allowed qualifiers for a single hard-coded qualifier (`P585`, `constraints.py`), so
  the new combos (`P131`+`P580`/`P582`; `P807` value-type) need a tool extension, not
  just a re-run, before upload.

## Dependencies, risks & known gaps

Surfaced in the 2026-07-14 design review; fold into the plan.

1. **Prerequisite — Phase 1b (province history) lands first.** Historical `P131`
   spans (e.g. Hà Tây districts before the 2008-08-01 merger) emit a province
   **QID**, but Phase 1a reconciled **2025-era provinces only**. The Hà Tây /
   pre-2004 province QIDs come from **Phase 1b** (province chaining 2002→2025 — now
   a Phase-1 task, `DESIGN.md` roadmap + decision 9). **Sequencing: 1b before Phase
   2.** If 1b is not yet done when districts are built, emit only the **final-era**
   `P131` span and defer + log the earlier spans — **never emit a `P131` with an
   unreconciled province value.**

2. **"Extend/reuse" = substantial rewrite, not a thin extension.** Budget for it:
   - `emit.py` currently emits `P576 + P7888 + P1366 + P1365` for *every* edge with
     **no relation awareness**; every Phase-2 rule (`P576` only on ended entities,
     `P807` for carve-outs, no-successor abolition, per-span `P131`) is net-new.
     This is the largest single piece of Phase-2 code.
   - `ghichu.py` is one hardcoded **province** regex; the district templates share
     none of it — a sibling parser, not an extension.
   - `model.py` hardcodes `p-{code}-{era}` and a 4-value province `relation` set;
     hence the separate `district_model.py` + the new fields above.
   - **Recommendation:** factor a tier-neutral core out of `model.py` / `emit.py`
     *first*, rather than special-casing provinces a second time.

3. **Reference quality — fix the Phase-1a shortcut.** The shipped emitter references
   every statement with a single site-root URL (`emit.py` `REFERENCE_URL`), below
   this design's own standard (`S248` → the Nghị quyết item, else `S854` → the
   *establishing resolution*). Phase 2 already sources authoritative decrees from
   the Nghị định list — use them for **per-statement decree references**, and
   backfill Phase 1a.

4. **Reconciliation match key leans on WD's stalest field.** Matching on `(folded
   name + parent province)` trusts WD `P131`, which `2026-07-10.08` shows is
   frequently stale (items still pointing at abolished parents). Treat the province
   half as a *weak* disambiguator: prefer name + the per-item `wbsearchentities`
   fallback, and don't discard a name match solely because WD's `P131` disagrees.

5. **Carve-out vs. division discriminator — state the algorithm.** `carved_from`
   (parent persists) vs. `split` (parent ends) for a new unit is decided by
   **whether the named source district survives into the next window's roster**
   (survives → carve-out + `P807`; gone → division + `P576`/`P1365`). Derivable but
   non-obvious; make it explicit in the assembly step.

6. **Yearly-window blind spot — an accepted risk, not a solved one.** Same-unit-
   twice-in-a-year and create-and-dissolve-in-a-year collapse in snapshot diffs
   (`2026-07-13.02`). For districts the **decree cross-check** (147 structural
   decrees, no real miss) is the compensating control — record it as such. The
   event-driven mitigation stays deferred to Phase 3.

## Pipeline & modules

`crosswalk` (parser, done) → **`district_model`** (new: assemble entities +
lineage; **district-template `ghichu`** — a sibling parser, §2; decree source =
`crosscheck_decrees`) → `reconcile` (province-aware, bulk SPARQL, audit) →
`constraints` (gate) → `emit` (**relation-aware rewrite**, §2). Artifacts:
`data/districts.json`, `data/district-lineage.json`, `mappings/districts-qid.csv`,
`statements/*.qs`.

## Testing (TDD)

- Unit: each `Ghi Chú` district template; structural classification incl. no-prose
  and re-parenting cases; `local_id` + reuse guard; assembly on a small synthetic
  window set.
- **Ground-truth** (like `test_lineage_groundtruth`): Từ Liêm split, Nông Sơn
  create→dissolve, 2020 Cao Bằng mergers, 2008 Hà Tây re-parenting, ~696-district
  2025 abolition count.
- Roster-delta cross-validation as a build assertion.
- `reconcile --audit` + `constraints` before any upload (manual gate, as Phase 1).

## Out of scope / residue

- **Pre-2004 ancestry** (event floor) — Phase 4 / non-GSO sources.
- **Boundary-only adjustments** ("điều chỉnh địa giới … để mở rộng …" with no
  identity change) — real but not lineage events; the cross-check confirmed they
  legitimately don't appear in the diff.
- **Goal A** (district-composed NA11–NA15 electoral-unit exports) — a later build
  on the same graph.
- **Ward re-parenting** at the 2025 abolition — Phase 3.
- Name-disambiguation residue → the manual-curation file.
