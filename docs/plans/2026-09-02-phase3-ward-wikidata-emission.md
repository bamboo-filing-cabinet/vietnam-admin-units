# Phase 3 ward Wikidata emission plan

**Date:** 2026-09-02

**Scope:** local preparation and reviewed Wikidata handoff; no automatic upload

## Starting point

The canonical ward graph is complete: 14,544 entities and 10,603 lineage edges.
The 2025 reform slice contains 10,586 edges from 10,035 distinct predecessors to
3,316 successors. Every reform edge has an official establishing-resolution URL.

Current-unit reconciliation is also review-complete:

- 3,163 of 3,321 current units have distinct QIDs;
- 158 rows are reviewed item-creation gaps;
- no `ambiguous`, `needs-review`, or `needs-lookup` rows remain.

The mapping is not yet lineage-complete. Its 11,223 historical rows were
deliberately marked `deferred-historical`, so none of the 10,035 immediate
pre-2025 predecessors has a QID. A lineage emitter that silently skipped those
endpoints would produce an empty or materially incomplete result.

## Safety boundary

Keep all generation offline. Wikidata writes remain a human-reviewed step on
the maintainer's account. In particular:

1. Run a fresh duplicate check immediately before the CREATE upload. The saved
   discovery data proves the 158 gaps as of the review, not forever.
2. Record every returned QID after the upload. Never replay a successful CREATE
   file.
3. Do not emit lineage until every endpoint in the selected slice has a QID and
   every event has an official reference URL.
4. Re-run live property-constraint checks immediately before a lineage upload.

## Work packages

### W1 — current item creation package (complete)

`vn_admin_units.ward_emit` builds a deterministic manifest and one consolidated
QuickStatements file containing all 158 items. The manifest retains logical
review groups of at most ten items. Every item has:

- Vietnamese label and province-specific description;
- ward-tier `P31` (`Xã` or `Phường` for the present gaps);
- `P17 = Q881` and current province `P131`;
- `P571 = 2025-07-01`;
- `S854` pointing to its province's signed 2025 resolution on every statement;
- the checked candidate QIDs and the durable review rationale in the manifest.

The live preflight now resolves exactly one current Vietnamese Wikipedia page
for each of the 158 rows. All 158 pages have no Wikibase item. It also verifies
574 unique live Wikidata candidates, records 582 per-row candidate
associations, and rejects every association with a structured reason; zero
duplicates and zero review rows remain. See
`data/ward-wikidata-create-preflight.json` and journal `2026-09-02.68`.
The emitter consequently adds the one verified `Sviwiki` title to each CREATE
block. If that evidence is missing or stale, it writes no CREATE statements and
fails the upload gate.

After the successful upload, write the new QIDs to `mappings/wards-qid.csv` as
`qid_status=new`, `match_status=manual`, and retain a creation-batch note.
Regenerate the package so completed rows disappear from subsequent work.

Batch #270342 ran on 2026-09-03: 151 commands created new items and seven
reported errors. The 151 title-linked QIDs exactly match the batch-tagged
Wikidata creation log. Tam Nông, Phú Thọ had become linked to existing
Q140391710, leaving six genuine failures. All 152 resolved rows are now in the
mapping, and the regenerated six-item retry passes a fresh live preflight.
See `data/ward-wikidata-create-batch-270342.json` and journal `2026-09-03.01`.

Batch #270387 then created all six retry items without errors. Their QIDs are
recorded as `new`, the mapping resolves all 3,321 current wards, and the
regenerated CREATE package is empty. See
`data/ward-wikidata-create-batch-270387.json` and journal `2026-09-03.02`.

### W2 — immediate predecessor reconciliation (review complete; CREATE pending)

Reconcile the 10,035 distinct predecessors used by the 2025 reform edges before
attempting the broader 11,223-row historical backlog. This is the minimum
endpoint closure needed for the 2025 Goal-B batch.

Use the saved QLever candidate corpus and index it once by folded name. Match
within the predecessor's terminal district (`parent_spans[-1].code`) using the
already reconciled district-QID map. Verify only the shortlisted QIDs through
batched `wbgetentities`; do not issue one network query per entity.

Exclude QIDs already assigned to current wards. Some current articles/items
were repurposed in place in 2025. Under the repository's new-entity-per-reform
identity model, such a QID represents the current unit; assigning it again to a
historical predecessor would erase the boundary and create a QID collision.
Those predecessors become reviewed former-item creation gaps unless a distinct
historical item exists.

Persist automatic confidence, candidate evidence, and manual decisions exactly
as the current reconciliation did. The hard gates are zero unknown candidates,
zero QID collisions, and zero unresolved predecessor endpoints.

Implemented 2026-09-04. The ward-class pass reduced 10,035 predecessors to
6,171 shortlisted QIDs and verified them in bounded Action API batches, yielding
6,100 automatic matches. A saved unrestricted QLever query evaluated 11,853
exact terms in 5.5 seconds, returned 10,926 items, reduced them to 75 live
checks, and added 54 automatic matches. Manual review assigned Nam Du to
Q10830340 and Glar to Q16480277. No assigned current QID was reused and no
mapping collision remains.

The remaining 3,879 rows are provisional distinct former-item gaps: no
acceptable item survived the automated candidate passes, but absence is not
yet proved. Their one-file draft and machine preflight are
`statements/na-wards-create-predecessors.qs` and
`data/ward-wikidata-create-predecessors-preflight.json`. Five reproducible
random samples of ten rows must be reviewed before upload authorization. W2
becomes endpoint-complete only after that review, upload, QID ingestion, and an
empty regeneration.

### W3 — current enrichment delta

Once all 3,321 current QIDs exist, fetch a fresh compact claim snapshot for
`P31`, `P17`, `P131`, and `P571`. Generate only missing or incorrect desired
claims; do not restate the entire current tier blindly. Each event-driven claim
uses the signed province resolution as its reference.

### W4 — 2025 lineage batch

The fail-closed renderer produces, for every ending predecessor→successor edge:

- predecessor `P576`;
- predecessor `P7888` and `P1366`, qualified by `P585`;
- successor `P1365`, qualified by `P585`;
- the edge's signed-resolution `S854` reference.

Exact duplicate lines are removed, but a predecessor that splits into multiple
successors retains one relationship to each successor. Rendering is forbidden
while even one selected edge lacks either endpoint QID.

### W5 — validation and upload handoff

Before any upload:

```sh
uv run pytest -q
uv run python -m vn_admin_units.ward_reconcile_broad --check --audit
uv run python -m vn_admin_units.ward_reconcile --check --audit
uv run python -m vn_admin_units.ward_create_preflight --fetch --audit
uv run python -m vn_admin_units.ward_create_preflight --check --require-upload-ready --max-age-hours 24
uv run python -m vn_admin_units.ward_emit --check --audit
uv run python -m vn_admin_units.ward_emit --check --require-current-create-ready --max-preflight-age-hours 24
uv run python -m vn_admin_units.ward_emit --check --require-lineage-ready
uv run python -m vn_admin_units.constraints
```

The two preflight checks must pass immediately before the CREATE upload. The
lineage-ready command must still fail until both current creation and historical
predecessor reconciliation are complete; it becomes the final endpoint gate.

Upload CREATE, current-enrichment, and lineage batches separately. Record batch
URLs, operation/error counts, and post-upload audits in `statements/README.md`
and a dated journal.

## Immediate next action

Review and record five reproducible random samples of ten provisional creation
gaps. If the sample exposes missed duplicates, improve the reconciliation and
rerun it before considering any upload. If it clears, refresh the 24-hour live
gate and seek explicit upload authorization.
