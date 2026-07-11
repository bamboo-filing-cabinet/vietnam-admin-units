# vietnam-admin-units — Phase 2 Design

Extends `DESIGN.md` (the overarching design + decisions log). **Phase 1**
delivered the *2025-reform province slice* (`docs/plans/2026-07-10-phase1-
province-wikidata.md`). **Phase 2** is everything needed to reach the full
promise: a **time-versioned, all-tier, all-reform** gazetteer that (a) drives
*complete* Wikidata corrections and (b) feeds the election repos (Goal A).

This is a consolidation of constraints already established across the probe
journals (cited inline), not a fresh brainstorm. Genuine open decisions are
called out at the end for a short brainstorm before any plan.

## From the Phase-1 slice to the full gazetteer

Phase 1 proved the pipeline shape on the easy tier (63↔34 provinces, unique
names, one reform, all items pre-existing). Phase 2 adds every dimension Phase 1
deliberately deferred:

| dimension | Phase 1 | Phase 2 |
| --- | --- | --- |
| tiers | provinces | + districts (historical) + **wards** (10k+) |
| reforms | 2025 only | **all: 2002 floor → 2004 → 2008 → 2019–24 → 2025 → 2026**, chained |
| lineage source | structured crosswalk + trivial Ghi Chú | Ghi Chú **name→code disambiguation** + **Lịch Sử** events |
| dates | one boundary | **event-level** effective dates per decree |
| WD items | all pre-existing (enrich) | + **create** gaps (đặc khu, new wards) |
| consumers | none | **Goal A** exports for vietnam-elections(-wikidata) |

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

### P2b — Historical eras + chaining (2002 → 2025)
Make the model actually span time (the "all reforms, chained" decision).
- **Ingest** snapshots at each boundary + **Lịch Sử** for event-level dates +
  decrees (hybrid, `.13`/`.14`).
- **Discontinuities to handle**: the **2004 code-scheme change** (3-digit→2-digit,
  `.15`) and the **2008 Hà Tây merger**; both need name/territory matching, not
  code equality.
- **Volume**: the **2019–24 ward-merger waves** (thousands of events, `.13`).
- **Chained multi-hop lineage**: a place traceable across every reform;
  **scheme/era-aware `local_id`** (not naive `p-{code}-{era}`, `.15`).

### P2c — Goal A: consumer exports (the original motivation)
Feed the election repos so electoral units → NA members can be built.
- Slice the entity graph at each **election date** → clean JSON with QIDs:
  electoral-unit `P527` parts, `P768` districts, old↔new crosswalk.
- **Can start early for a single era** (e.g. NA15 2021) without full history —
  arguably the highest *user* value, since it's why the project exists.

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
- **District tier** — first-class historical former entities (`.03`), needed for
  pre-2025 electoral units.

## Hard problems (the real Phase-2 work, with pointers)

1. **Ward name→code disambiguation** (`.11`) — Ghi Chú names constituents
   ambiguously; resolving to codes needs province+district context + manual
   residue. The core difficulty; provinces never expose it.
2. **2004 code-scheme discontinuity** (`.15`) — cross-era matching by name/
   territory across the 3-digit→2-digit boundary.
3. **Lịch Sử scrape** — DevExpress WebForms (like the crosswalk); needs
   browser automation or the Excel export. Not yet exercised.
4. **WD long-tail** (`.05`, `.08`) — ~11.6k existing VN items (mostly stale old
   structure) to enrich + gaps to create; batch size, bot approval, community
   modeling conventions.
5. **Event volume** (`.13`) — thousands of ward events across the waves; ingest
   must be event-driven, not annual.

## Sequencing & dependencies

- **P2a** closes out the 2025 reform (natural completion of Phase 1's output).
- **P2c** can run independently for a chosen era once that era's snapshots + QIDs
  exist — it does *not* require full history.
- **P2b** is the largest; it underpins complete P2c (all eras) and the "chained"
  vision, but isn't required to feed a single election.
- **P2d** is ongoing, low effort, any time after P2a.

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
5. **How far to chain:** every ward event 2002→now, or key eras only (per NA
   term) first?

## Next step

Pick a first slice (decision #1), run `superpowers:brainstorming` on just that
slice to settle its open decisions, then `superpowers:writing-plans` to produce
`docs/plans/2026-07-…-phase2X-….md` — mirroring the Phase-1 flow.
