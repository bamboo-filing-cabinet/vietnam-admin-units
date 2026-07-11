# vietnam-admin-units — Phase 2 Design

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
| lineage source | structured crosswalk + trivial Ghi Chú | Ghi Chú **name→code disambiguation** + **Lịch Sử** events |
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
