# vietnam-admin-units — Phase 3 Design (wards + province chaining)

> **Stale internal numbering.** This doc was written when wards were "Phase 2" and
> districts "Phase 3". The roadmap in `DESIGN.md` has since put **districts first
> (Phase 2)** and **wards second (Phase 3)**. The file has been renamed to
> `DESIGN-phase3.md` to match, but the body below still says "Phase 2" / "P2a–P2d"
> and treats districts as a later phase — read those as the **ward** phase. The
> body will be revised when this phase is reached.
>
> **Update (2026-07-14): "province historical chaining" (P2b below) has moved to
> Phase 1b.** It completes the province tier (2002→2025) and is a prerequisite for
> Phase 2 districts, not ward-phase work. Disregard **P2b** here — see `DESIGN.md`
> roadmap + decision 9.
>
> **Update (2026-07-20): Lịch Sử retired as an event source.** Everywhere this doc
> lists **"Lịch Sử events"** or a **Lịch Sử scrape** as the change/event mechanism,
> disregard it: `Lich_Su_Moi.aspx` is a point-in-time *inventory*, not a change
> timeline (verified districts `2026-07-13.01`, wards `2026-07-20.01`). The actual
> mechanism is the **Đối Chiếu crosswalk yearly-sweep + Nghị định/Nghị quyết UBTVQH
> cross-check** (the crosswalk is net-only; the decree list bounds the yearly-window
> blind spot). See `DESIGN.md` decision 4 + spike journal `2026-07-20.01`.
>
> **Update (2026-08-31): Phase 3 is active; the 2025 source/topology gate is
> complete.** The complete
> 204-date SOAP archive supplies inventory and former-district parentage. The
> boundary observation + structured primary-link spine is documented in
> `docs/plans/2026-08-28-phase3-ward-2025-boundary.md`. The composition follow-up
> preserves 34 signed provincial resolutions plus official full-text HTML and
> closes every predecessor: 10,586 edges, 459 split predecessors, zero residue
> (`docs/journals/2026-08-28.02.ward-2025-composition-lineage.md`). Historical
> source Tasks 1–6 are also complete: the 204 SOAP snapshots and 39 crosswalks
> verify; all 453 candidate legal rows and 449 unique instruments are classified
> and linked; and 416/449 instruments now have 825 archived official artifacts.
> Resume at source-closure Task 7 with 31 primary-source-open instruments, all
> change-bearing. Resolution `469/NQ-UBTVQH15@2022-04-10` and Decrees 84,
> 85, 97, and 98 of 2005 now have exact official attachment recovery paths, but
> their bytes remain unavailable from the live legacy endpoints; see journals
> `2026-08-30.02`–`.06`. Decree `28/2006/NDD-CP@2006-04-06` is now closed with
> archived Government metadata and its original Word attachment; the
> raw/official code and observation/effective-date differences are preserved in
> `2026-08-30.07`. Decree `29/2006/NĐ-CP@2006-04-07` now has complete secondary
> text, contemporaneous Government press corroboration, and an indexed official
> VBPL lead, but remains open because official retrieval is blocked
> (`2026-08-31.01`). Decree `34/2006/NĐ-CP@2006-04-15` now has complete
> secondary text, an indexed official lead, and a reconciled whole-unit Cát
> Thành retype, but the official bytes remain blocked (`2026-08-31.02`).
> Decree `39/2006/NĐ-CP@2006-05-06` now has reviewed topology for seven
> commune creations and two boundary transfers, Government press
> corroboration, and an indexed official lead, but the official bytes remain
> blocked (`2026-08-31.03`). Decree `60/2006/NĐ-CP@2006-07-04` now has
> complete parallel secondary texts, Government press corroboration, an
> indexed official lead, and reconciled topology for three Tân An ward
> establishments, but the official bytes remain blocked (`2026-08-31.04`).
> Decree `64/2006/NĐ-CP@2006-07-08` now has complete parallel secondary texts,
> an indexed official lead, and reconciled topology for five whole-commune
> parent changes plus a roster-invisible boundary transfer, but the official
> bytes remain blocked (`2026-08-31.05`). Decree
> `137/2007N@2007-09-11` is now closed with archived Government metadata and
> its original Word attachment; five commune creations and seven continuing
> Cư Kuin parent changes are reconciled separately from eleven concurrent Vĩnh
> Long changes (`2026-08-31.06`). The actual Government decree and
> original Word attachment prove that both July/August NSO rows are invalid
> code-title identities; Resolution `14/2008/QH12` remains the canonical Tân
> Đức authority (`2026-08-31.07`). Decree `07/NĐ-CP@2009-01-07` now has a
> complete Buôn Hồ secondary transcription, an exact official VBPL record,
> an indexed original ZIP lead, and 23 reconciled topology components, but
> remains open because the official bytes are blocked. The supplied
> LuatVietnam page is the later Nghệ An Decree 07 and is excluded from this
> row; date-qualified secondary mapping prevents that same-code contamination
> (`2026-08-31.08`). Decree `08/NĐ-CP@2009-01-07` now has a complete Hồng Ngự
> secondary transcription, exact official VBPL full-text and original ZIP
> leads, contemporaneous provincial implementation corroboration, later
> Ministry classification evidence, and seven reconciled topology components.
> It remains open because the official bytes are blocked; date-qualified
> provenance also removes the Hồng Ngự URL from the later Bến Tre Decree 08
> (`2026-08-31.09`). Continue with Decree `10/NĐ-CP@2009-01-07`. Only
> after the source audit closes should historical records be promoted into canonical
> entities/`LineageEdge` objects. Wikidata emission remains gated.

Extends `DESIGN.md` (the overarching design + decisions log). **Phase 1**
delivered the *2025-reform province slice* (`docs/plans/2026-07-10-phase1-
province-wikidata.md`). **Phase 2** is everything needed to reach the full
promise: a **time-versioned, all-tier, all-reform** gazetteer that (a) drives
*complete* Wikidata corrections and (b) feeds the election repos (Goal A).

This is a consolidation of constraints already established across the probe
journals (cited inline), not a fresh brainstorm. Genuine open decisions are
called out at the end for a short brainstorm before any plan.

**Phase boundary (see the roadmap in `DESIGN.md`).** Phase 2 is **province + ward
only, within the GSO window**. Two things are explicitly *out* and become later
phases:
- **Districts → Phase 3.** The district tier existed only pre-2025 (abolished by
  the reform), so it's purely historical, and it's what feeds the
  **district-composed NA11–NA15 electoral units**. Clean split: **post-2025 wards
  attach directly to the province (no district)**, so Phase 2 needs no district
  entities; **pre-2025 wards were parented to districts**, so historical ward
  chaining rides along with districts in Phase 3.
- **Pre-2002 history (NA1–NA10) → Phase 4** — below the GSO floor; different
  sources.

## From the Phase-1 slice to the full gazetteer

Phase 1 proved the pipeline shape on the easy tier (63↔34 provinces, unique
names, one reform, all items pre-existing). Phase 2 adds every dimension Phase 1
deliberately deferred:

| dimension | Phase 1 | Phase 2 |
| --- | --- | --- |
| tiers | provinces | + **wards** (current, 10k→3.3k) — *districts = Phase 3* |
| reforms | 2025 only | province chaining **2002→2025** (2004 renumber, 2008 merger) + the 2025 ward reform |
| lineage source | structured crosswalk + trivial Ghi Chú | Ghi Chú **name→code disambiguation** + ~~**Lịch Sử** events~~ **crosswalk yearly-sweep + Nghị quyết/Nghị định cross-check** (Lịch Sử retired — see banner + `2026-07-20.01`) |
| dates | one boundary | **event-level** effective dates per decree |
| WD items | all pre-existing (enrich) | + **create** gaps (đặc khu, new wards) |
| consumers | none | **Goal A** exports for **NA16 (2026)** (ward-composed) |

## Sub-projects (each gets its own plan)

### P2a — Complete the 2025 reform (all provinces, all tiers)
Finish what Phase 1 started, so the 2025 reform is fully on Wikidata.
- **Province reconciliation**: fill all ~97 QIDs (`mappings/provinces-qid.csv`);
  the batch grows from 1 edge to the full ~29 mergers.
- **Ward tier** (10,040→3,321): reuse the `Ghi Chú` parser, but build the
  **name→code disambiguation** step (`.11`) — the core new difficulty, invisible
  at province level — plus **dedupe exact-duplicate rows** (`.14`) and the
  **đặc khu** type (`.03`).
- **`P31`/`P131` fixes**: type changes (Xã→Phường, Tỉnh→Thành phố) and the
  2-level re-parent; the taxonomy (`.10`) enumerates these.
- **Pre-upload gate**: verify `P1365`/`P7888` qualifier constraints on live WD;
  then upload (reviewed step, personal WD account).

### P2b — Province historical chaining (2002 → 2025)
Make the **province** timeline actually span time (the "chained" decision) —
province-level only; ward/district history is Phase 2-ward / Phase 3.
- **Ingest** province snapshots at each boundary + **Lịch Sử** for event-level
  dates + decrees (hybrid, `.13`/`.14`).
- **Discontinuities to handle**: the **2004 code-scheme change** (3-digit→2-digit,
  `.15`) and the **2008 Hà Tây merger**; both need name/territory matching, not
  code equality.
- **Chained multi-hop lineage**: a province traceable across every reform;
  **scheme/era-aware `local_id`** (not naive `p-{code}-{era}`, `.15`).
- (The **2019–24 ward-merger waves** — thousands of events, `.13` — are
  *historical ward* work; they ride with districts in **Phase 3**, since
  pre-2025 wards are parented to the district tier.)

### P2c — Goal A: consumer exports for NA16 (the original motivation)
Feed the election repos so electoral units → NA members can be built.
- Slice the entity graph at the **NA16 (2026)** date → clean JSON with QIDs:
  electoral-unit `P527` parts (**wards/communes**), `P768`, old↔new crosswalk.
- **NA16 only in Phase 2** — its units are ward-composed. **NA11–NA15 units are
  district-composed**, so exporting those waits on the **Phase 3** district tier.

### P2d — Freshness
- Scheduled `DenNgay=today` diff to catch future changes (e.g. the next Đồng
  Nai-style upgrade). Low effort; ongoing.

## Data-model extensions (beyond Phase 1's schema)

- **`local_id` must be scheme/era-aware** — pre-2004 3-digit codes must not
  collide with 2-digit ones, and codes reuse across reforms (`.02` A1, `.15`).
  Anchor on name/territory, not parsed codes.
- **Event-sourced dating** — effective dates from Lịch Sử decrees, not SOAP
  bisection (the source is stable but dating via decrees is authoritative, `.14`).
- **Many-to-many partial lineage** — splits + `một phần` shares, with `P518`/
  `P1107` qualifiers (`.06`, `.11`); Phase 1 only handled whole merges.
- **Normalization pass** — dedupe exact-duplicate rows (`.14`), Ghi Chú typos/
  newlines (`.11`), đặc-khu count wobble (`.03`); always log what's changed.
- **District tier is NOT modeled in Phase 2** — it's Phase 3 (first-class
  historical former entities, `.03`). Note: Phase 2 ward disambiguation still
  *uses the district code* carried in each pre-2025 ward row (`MaQuanHuyen`) as a
  disambiguation key — that needs the code, not a district entity.

## Hard problems (the real Phase-2 work, with pointers)

1. **Ward name→code disambiguation** (`.11`) — Ghi Chú names constituents
   ambiguously; resolving to codes uses the province + the old ward's district
   *code* (`MaQuanHuyen`, present in the row — no district entity needed) +
   manual residue. The core difficulty; provinces never expose it.
2. **2004 code-scheme discontinuity** (`.15`) — cross-era matching by name/
   territory across the 3-digit→2-digit boundary.
3. **Lịch Sử scrape** — DevExpress WebForms (like the crosswalk); needs
   browser automation or the Excel export. Not yet exercised.
4. **WD long-tail** (`.05`, `.08`) — ~11.6k existing VN items (mostly stale old
   structure) to enrich + gaps to create; batch size, bot approval, community
   modeling conventions.
5. **Event volume** (`.13`) — the thousands of ward events across the 2019–24
   waves are mostly **Phase 3** (historical wards + districts); Phase 2's ward
   work is the single 2025 reform boundary. Ingest must still be event-driven.

## Sequencing & dependencies

- **P2a** closes out the 2025 reform (natural completion of Phase 1's output);
  its ward tier is the prerequisite for **P2c (NA16)**.
- **P2c (NA16)** needs only P2a (current wards) — not the province history.
- **P2b** (province chaining) is independent and underpins the "chained" vision.
- **P2d** is ongoing, low effort, any time after P2a.
- **Cross-phase:** feeding **NA11–NA15** electoral units needs the district tier
  → **Phase 3**; **NA1–NA10** → **Phase 4**. Phase 2 gets you NA16 only.

## Open decisions — resolve in a short Phase-2 brainstorm before planning

1. **Priority order:** finish-the-current-reform (P2a) vs feed-the-elections
   (P2c, the original goal) vs backfill-history (P2b) first? These optimize
   different things (complete WD contribution vs unblock electoral units vs the
   full timeline).
2. **Lịch Sử access:** browser-automation scrape vs driving the Excel export vs
   replaying DevExpress callbacks.
3. **WD creation policy:** create missing items (đặc khu, new wards) via
   QuickStatements vs a bot; batch sizes; community coordination.
4. **Goal A export contract:** exact JSON shape the election repos want (confirm
   with `vietnam-elections` / `vietnam-elections-wikidata`).
5. **Province chaining depth:** every recorded province event 2002→now, or just
   the boundaries needed (2004, 2008, 2025)? (Fine-grained *ward* history is a
   Phase-3 question, not here.)

## Next step

Pick a first slice (decision #1), run `superpowers:brainstorming` on just that
slice to settle its open decisions, then `superpowers:writing-plans` to produce
`docs/plans/2026-07-…-phase2X-….md` — mirroring the Phase-1 flow.
