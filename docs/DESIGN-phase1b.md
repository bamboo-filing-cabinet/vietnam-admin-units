# vietnam-admin-units — Phase 1b Design (province history, 2002→2025)

Extends `DESIGN.md` (the overarching design + decisions log). Grounded in the
province-history probe [`2026-07-14.01`](journals/2026-07-14.01.province-history-doi-chieu-and-roster-probe.md)
and the 2004 code-scheme journal [`2026-07-10.15`](journals/2026-07-10.15.province-code-scheme-change-2004.md).

**Phase 1 is the province tier across the full GSO window (2002→2025).** Phase 1a
delivered the 2025-reform slice (uploaded, [batch #260741](https://quickstatements.toolforge.org/#/batch/260741)).
**Phase 1b** — this doc — extends the province tier *backward* to 2002: the 2004
code-scheme change, the 2004 carve-outs, and the 2008 Hà Tây merger, chained, and
reconciled to QIDs. It completes the province tier as a full **Goal-B** Wikidata
contribution **and** produces the historical province QIDs that **Phase 2 districts**
need for their pre-2008 `P131` spans (the `DESIGN-phase2.md` §"Dependencies" #1
prerequisite).

## Decisions (settled in the 2026-07-14 brainstorm)

1. **Deliverable = full Goal-B** (build → reconcile → emit → constraints/audit
   gates → **upload as a final manual reviewed step**, mirroring 1a).
2. **Reconcile all historical province entities**, including ended ones (Hà Tây)
   and the 2004 carve-out children — not just what districts strictly need.
3. **2004 splits = carve-outs, with real lineage** (chosen over create-only /
   exclude). All three are "parent persists, child separates": Điện Biên←Lai Châu,
   Đắk Nông←Đắk Lắk, Hậu Giang←Cần Thơ. The parent pairing is **not** in GSO Đối
   Chiếu (2004 floor), so it comes from the decree (NQ 22/2003/QH11, cached).
4. **Identity: one continuous entity across recode/retype**; a reform that *ends* a
   unit (2008 Hà Tây; the 2025 merges) ends the entity, and genuinely-new units
   (carve-out children) are new entities. Matches the taxonomy (`2026-07-10.10`):
   recode I3 / retype I2 = SAME; carve-out S1 = parent SAME + child NEW; absorption
   M1 = absorbed END + absorber SAME.
5. **Event discovery = yearly SOAP roster walk 2002→2025** (name/type-normalized
   diff) as the authoritative, Đối-Chiếu-independent backbone; Đối Chiếu windows
   supply lineage/prose/effective-dates from mid-2004 on. The walk is the *only*
   instrument that sees 2002→2004 (Đối Chiếu is floored there).
6. **Decree numbers sourced externally** by unit + date (the crosswalk's own decree
   column is unreliable — it shows a later "last-touching" decree).
7. **Code = Approach 1**: a new `province_history.py` alongside the untouched 1a
   `model.py`; extend `emit.py`. Factor a tier-neutral core at the *start of Phase 2*,
   once province-history and districts are both concrete.

## Events in scope (2002→2025)

Sparse and, except where noted, verified by the probe. Section is the event list the
**walk is expected to confirm** — the walk + cross-check is authoritative, so an
unanticipated event is caught, not assumed away.

| when | event | shape | source |
| --- | --- | --- | --- |
| 2002→2004 | **(none)** — 61 provinces stable | — | SOAP roster walk (confirmed eventless) |
| 30/06/2004¹ | **renumber** 3-digit→2-digit, ~61 provinces | recode (same entity; old code → alias) | Đối Chiếu remap window |
| 30/06/2004¹ | **3 carve-outs**: Điện Biên←Lai Châu, Đắk Nông←Đắk Lắk, Hậu Giang←Cần Thơ | carve-out (parent persists; child new) | Đối Chiếu (children as new) + **decree** (parentage) |
| 30/06/2004¹ | **Cần Thơ** Tỉnh→Thành phố TW | retype (same entity) | SOAP + Đối Chiếu |
| 01/08/2008 | **Hà Tây → Hà Nội** | absorption (Hà Tây ends; Hà Nội persists) | Đối Chiếu (with prose) |
| ~2025-01-01 | **Huế** Tỉnh→Thành phố TW | retype (same entity) | *to confirm in sweep* |
| 01/07/2025 | 2025 reform (63→34) | consolidation | **done in 1a**; 1b chains into it — **terminal boundary of 1b** |
| 30/04/2026 | Đồng Nai retype | retype | **out of scope** (post-reform freshness; see Out of scope + Emit) |

¹ GSO service-dates the 2004 change 30/06/2004; the **legal effective date is
2004-01-01** (NQ 22/2003/QH11). Use the **legal date** for `P571`/`P585`; keep the
decree as the reference.

## Data acquisition

- **Generalize `crosswalk_fetch.py` → `--tier {province,district}`**: Cấp=Tỉnh
  (value `1`), province cache path (`crosswalk/province_{base}_{compare}.xls`),
  province parser. Use the **Excel export** download (clean server-side file), never
  DOM scrape (stale-DOM contamination is severe — probe). Sweep Tỉnh windows: yearly
  2004→2024 + the 2002→2004 remap boundary + the 2024→2025 tail.
- **Yearly SOAP roster walk 2002→2025**: `fetch_provinces` supplies each snapshot,
  but `cli.cache_snapshots` currently **hardcodes only the two 2025-reform boundary
  dates** (`cli.py` `BOUNDARY_DATES` = {2025-06-30, 2026-07-10}) — **parameterize it**
  (or add a `cache_history_snapshots` command) to sweep the ~24 yearly 2002→2025
  dates. Cached with manifest, diffed for event discovery + cross-check. (The
  `2026-07-10` boundary is out of scope here — see Đồng Nai.)
- **New 9-column positional province reader** in `crosswalk.py`
  (`read_province_history_crosswalk`): the historical windows use the wider dual-side
  layout, not the 7-col named reform layout that `read_province_crosswalk` handles.
- **Decree** already cached: `data/raw/decrees/nq-22-2003-qh11.html` (+ manifest).
  A small derived `data/decrees/2004-splits.json` encodes the 3 carve-out pairings.

## Data model (`province_history.py`)

Generic-ish `Entity` / `LineageEdge`, district-shaped but **without** `parent_province`
(provinces have no parent). Kept separate from 1a `model.py` (which hardcodes the
2025 eras + a province-only 4-relation set); the shared shape is a Phase-2 refactor
target, not an import (see `DESIGN-phase2.md` §"Dependencies" #2).

**`Entity`** — continuous across recode/retype:

- `local_id` — scheme/era-aware, **not** `p-{code}-{era}` (codes reuse + the scheme
  changes at 2004, `.15`). Anchor on the entity, not a parsed code; disambiguate by
  `valid_from` where a code is reused. Collisions detected + logged.
- `gso_code` **history** (e.g. Lào Cai `205`→`10`) — former codes become aliases. The
  **reconciliation join key is `local_id`** (see Reconciliation), *not* `(gso_code,
  era)`: an entity has several codes across eras, and ended entities (Hà Tây) have no
  2025-era code at all.
- `name_vi`, `loai_hinh` **history** (retypes are attribute spans), `aliases`
  (former names + former codes), `valid_from`/`valid_to`, `wikidata_qid`, `qid_status`.
- **Name normalization** (NFC + consistent tone-mark placement, `Hoà`↔`Hòa`) applied
  before any comparison; variant list logged (probe caught a phantom `Hòa Bình` event).

**`LineageEdge`** — relation determines whether the predecessor ends:

- `carved_from` — predecessor **persists** (parent); a new child separates → **no
  `P576`** on the parent; child gets `P571` + `P807`→parent.
- `absorbed_into` — predecessor **ends**, absorbed into a persisting successor
  (Hà Tây→Hà Nội) → `P576` + `P7888`/`P1366`→successor; successor `P1365`→predecessor.
- **recode / retype = same-entity attribute changes, no edge** (old code/name → alias;
  retype → time-qualified `P31`).
- The 2025 consolidation is 1a's; 1b's chain connects its `pre2025` entities to their
  pre-2025 history rather than duplicating them.

**Chaining — enrich existing entities, mint only the genuinely-ended one.** 1b
extends 1a's `pre2025` province entities *backward*: attaches their pre-2025
code/name/type history + the 2004/2008 edges, so a province is traceable
2002→2004→2008→2025 as one spine. The carve-out children (Điện Biên, Đắk Nông, Hậu
Giang) **are** those existing `pre2025` entities — 1b does **not** create duplicates;
it fills in their `valid_from` (2004-01-01), `P571`, and the `P807`→parent edge. The
**only newly-minted** entity is **Hà Tây** (ended 2008, absent from the 2025 roster).
Old Cần Thơ *province* is not a separate entity — Cần Thơ persists as the city.

## Reconciliation (extends 1a `reconcile`)

- **Reuse existing 1a QIDs; reconcile fresh only what 1a never mapped.** The 2004
  carve-out children **are already in `mappings/provinces-qid.csv`** as `pre2025`
  survivors — Điện Biên `Q36955`, Đắk Nông `Q36723`, Hậu Giang `Q36320` — so they
  **reuse** those QIDs (a fresh lookup would risk a duplicate/mismatch manual
  decision). The only named historical entity **not** in the 2025-era mapping is
  **Hà Tây** (dissolved 2008), which reconciles fresh. All are existing WD items →
  **enrich, don't create**.
- **Mapping file (separate, `local_id`-keyed).** 1b writes a **new**
  `mappings/provinces-history-qid.csv` keyed by `local_id` — **not** by growing 1a's
  `mappings/provinces-qid.csv`. Reason: 1a's `reconcile._write_csv` (`reconcile.py:197`)
  rewrites the whole file with a fixed 6-column `HEADER` (`reconcile.py:13`), so an
  extra `local_id` column or a local-id-only row (Hà Tây) would be **clobbered** by the
  next `python -m vn_admin_units.reconcile` run. 1b **reads** 1a's csv read-only to
  reuse the survivor + carve-out-child QIDs, and writes the combined history mapping to
  its own file. 1a's file + writer stay untouched; the Phase-2 core refactor unifies
  them.
- Match on **normalized name + type** (province names are unique; no parent needed).
- **Audit gate — extend it to all historical entities.** 1a's `audit_province_qids`
  only type/name-checks `era == "pre2025"` rows (`reconcile.py`), so a `local_id`-only
  Hà Tây (or any non-`pre2025` historical) row gets **no** identity audit. Extend the
  audit to cover every 1b entity (name+type-aware instance-of) before upload; manual
  fixes → `match_status=manual`.
- **Verify WD's Lai Châu modeling** (continuation vs. new item). GSO records current
  Lai Châu as the continuation of old Lai Châu; if WD modeled it differently, flag it
  (`P1889 different from` where WD minted a distinct old-Lai-Châu item) rather than
  fight the community's choice (Goal B = feed WD).

## Emit (extends `emit.py`)

- **`P571` inception** on the 3 carve-out children (legal date **2004-01-01**),
  **gated on known `valid_from`, NOT on `qid_status`.** The children reuse *existing*
  WD items (Finding above) yet still lack a true inception, and the current
  `emit.py:32` emits `P571` only when `qid_status == "new"` — so it would **skip**
  them. Decouple "local entity founded in-era" from "WD item newly created", and
  **audit each item's existing claims first** to avoid a duplicate/conflicting `P571`
  (same rule as `DESIGN-phase2.md:178`).
- **`P807` separated-from** child→parent (fits the carve-out; subject/value-type
  constraints allow administrative territorial entity — verified for districts,
  `2026-07-13`).
- **`P31` retype**, **always date-qualified (`P580`/`P582`)** so city status is never
  backdated, for Cần Thơ (2004) and Huế (2025). **Đồng Nai's 2026-04-30 upgrade is out
  of scope** (post-reform), but the current `2026-07-10` snapshot already shows
  `Thành phố Đồng Nai`, so whenever it is emitted it must use a **dated** `P31` span
  (`P580 = 2026-04-30`), never an undated one.
- **`P576` + `P7888`/`P1366`/`P1365`** for Hà Tây→Hà Nội (`P585` = 2008-08-01).
- **Recode** → former code carried as an era attribute/alias, **no statement**.
- **Skip same-QID edges** (survivors edited in place).
- **References:** GSO source for the renumber/2008 rows; **NQ 22/2003/QH11** (cached)
  for the 3 carve-outs. Every statement referenced (`S248` → Nghị quyết item if it
  exists, else `S854` → the establishing resolution / NSO source; fixes the 1a
  site-root shortcut per `DESIGN-phase2.md` §"Dependencies" #3).
- **Extend the `constraints` gate — don't just re-run it.** The current tool checks
  allowed *qualifiers* for a single hard-coded qualifier (`P585`, `constraints.py`).
  Phase 1b needs it to check the **`P31`+`P580`/`P582`** qualifier combo **and
  value-type constraints for `P807`** (subject/value = administrative territorial
  entity). Extend, then gate, before upload. (`DESIGN-phase2.md` §Emit has the same
  gap — fold the extension in there too.)

## Pipeline & modules

`crosswalk_fetch` (extended: `--tier`, Excel export) + SOAP roster walk (existing) →
`crosswalk.read_province_history_crosswalk` (new 9-col reader) → **`province_history`**
(new: assemble entities + lineage; decrees from `data/decrees/2004-splits.json`) →
`reconcile` (extended) → `constraints` (gate) → `emit` (extended). Artifacts:
`data/provinces-history.json`, `data/province-history-lineage.json`,
`mappings/provinces-history-qid.csv` (new, `local_id`-keyed; 1a's `provinces-qid.csv`
read only), `statements/na-provinces-history.qs`.

## Testing (TDD, mirrors 1a)

- Unit: 9-col reader; name normalization (`Hoà`/`Hòa`); relation classification
  (recode vs retype vs carve-out vs absorption); scheme/era-aware `local_id` + reuse
  guard.
- **Ground-truth**: the 3 carve-outs (parent persists + child `P807` + `P571`
  2004-01-01), Cần Thơ + Huế retypes, 2008 Hà Tây (exactly 1 dissolution), 2004
  renumber (61 recodes, 0 dissolutions), chain-continuity into the 2025 reform.
- **Regression guards** for this review's findings: (a) `P571` **is** emitted for
  the carve-out children even though their `qid_status == existing` (guards the
  `emit.py:32` skip); (b) every retype `P31` carries a `P580` start date (guards
  backdating); (c) Điện Biên/Đắk Nông/Hậu Giang resolve to their **existing** csv
  QIDs, not fresh lookups; (d) an ended entity (Hà Tây) is keyed/reconciled by
  `local_id` with no 2025-era `(gso_code, era)`; (e) the extended audit flags a
  deliberately-broken Hà Tây mapping (audit covers non-`pre2025` rows); (f) 1b writes
  only `provinces-history-qid.csv` and never mutates 1a's `provinces-qid.csv`.
- **Roster-delta cross-validation** as a build assertion: every SOAP-diff event
  explained by an Đối Chiếu window or the decree; mismatches logged.
- `reconcile --audit` + `constraints` before any upload (manual gate, as 1a).

## Out of scope / residue

- **Pre-2002 history** (below the GSO floor) — Phase 4 / non-GSO.
- **Đồng Nai 2026-04-30 city upgrade** — post-reform, outside the 2002→2025 window;
  1b's terminal boundary is the 2025 reform. It's a freshness item (a later `DenNgay`
  diff); when emitted it needs a **dated** `P31` span so it doesn't backdate city
  status (see Emit). Flagged because 1a's `2026-07-10` snapshot already shows it.
- **District/ward-level** 2008 partial transfers (Hòa Bình/Vĩnh Phúc/Phú Thọ → Hà
  Nội) — those tiers' phases, not the province event.
- Name/type residue that normalization can't resolve → manual-curation file, logged.

## Open / to-confirm

- **Huế's exact 2025-01 decree + date** (the 2024→2025 sweep surfaces it).
- **WD's Lai Châu modeling** (reconcile-time check, above).
