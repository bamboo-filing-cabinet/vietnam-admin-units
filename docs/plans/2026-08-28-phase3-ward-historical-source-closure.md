# Phase 3 — historical ward source and provenance closure

Written 2026-08-28. This plan is the source-audit gate between the completed
ward SOAP rescue and the historical ward entity/lineage build. It records what
must be acquired, classified, and reconciled before the project may claim
complete ward change provenance from the NSO source floor to the present.

The 2025 boundary remains a closed, reusable slice. This plan does not reopen or
re-scrape it.

> **Task 1 complete (2026-08-28).** The 18 missing yearly exports are preserved.
> The cache now verifies 21/21 historical yearly windows and 24/24 ward
> crosswalk files overall. See journal `2026-08-28.03`.
>
> **Task 2 complete (2026-08-28).** The deterministic offline ledger inventories
> 204 SOAP artifacts, 24 crosswalks, and 449 unique legal instruments. It reuses
> 34 verified 2025 source pairs and exposes 415 unclassified/source-open
> instruments. See journal `2026-08-28.04`.
>
> **Task 3 complete (2026-08-28).** The deterministic observed-change artifact
> covers all 203 adjacent SOAP intervals: 179 change-bearing and 24 no-change.
> It preserves conflicts as anomalies and makes no same-code identity claim.
> See journal `2026-08-28.05`.
>
> **Task 4 complete (2026-08-28).** Annual, boundary, and post-reform evidence
> supports 35,342/35,350 observed components after 15 targeted exports and a
> long-range fallback. The eight remaining components are four paired 2004
> code-transition omissions, retained as explicit residue. See journal
> `2026-08-28.06`. **Resume at Task 5: preserve the historical legal corpus.**

## Outcome

Produce an offline-regenerable coverage ledger for the ward tier from
`2002-01-01` through the pinned current snapshot `2026-08-27`, proving that:

- every planned SOAP observation is present and hash-verified;
- every observed roster change is linked to old→new evidence and a legal
  instrument, or is explicitly classified as a non-lineage data correction;
- every ward-relevant legal-index record is classified, including instruments
  that produce only a parent/boundary change or no observable identity change;
- every change-bearing event has an archived primary-government source with
  stable provenance metadata; and
- all remaining gaps are machine-counted residue rather than implicit absence.

Only after this gate closes should the historical canonical ward graph be
built. Wikidata reconciliation, statement emission, and upload are separate
later phases.

## What “complete” means

These are separate gates and must not be collapsed into one claim:

1. **Observation complete:** the reviewed 204-date SOAP plan is fully present,
   byte/hash verified, and parseable.
2. **Event complete:** each normalized change between retained observations is
   explained by a crosswalk row, legal event, source correction, or an explicit
   reviewed exception.
3. **Lineage complete:** each creation, dissolution, merge, split, rename,
   retype, code change, and whole/partial transfer has resolved predecessor and
   successor endpoints where the source permits them.
4. **Legal provenance complete:** every change-bearing event identifies its
   instrument, effective date, primary source URL, archived artifact, content
   hash, and the article/clause or source passage used when available.

A third-party legal database page may aid discovery, transcription checking,
or disaster recovery. It does not satisfy the primary-source gate by itself.

## Locked baseline

The acquisition preflight must reproduce these counts before network access:

| Source | Preserved baseline |
| --- | ---: |
| ward SOAP plan | 204/204 snapshots |
| unique decoded SOAP payloads | 180 |
| rows across all SOAP snapshots | 2,202,543 |
| legal-index records | 544 |
| high-recall ward-relevant legal records | 453 |
| distinct ward-relevant effective dates | 179 |
| preserved ward crosswalk exports | 6 |
| complete 2025 resolution pairs | 34 signed PDFs + 34 official HTML pages |

The six current ward crosswalk exports are:

- the flat `2002-01-01 → 2025-06-30` net comparison;
- yearly samples `2017→2018`, `2019→2020`, and `2024→2025`;
- the `2025-06-30 → 2025-07-01` reform boundary; and
- the `2025-07-01 → 2026-08-27` post-reform comparison.

The flat 2002→2025 comparison is not a substitute for an event sequence. The
yearly historical sweep contains 21 windows (`2004→2005` through `2024→2025`),
of which three are already preserved; the initial acquisition residue is
therefore 18 yearly exports.

## Source hierarchy

Use sources in this order and record the source class in the ledger:

1. signed instrument from an issuing-authority or Government host;
2. official full-text Government/issuing-authority publication;
3. official legal metadata page that unambiguously identifies the instrument;
4. Thư Viện Pháp Luật or another legal database as a secondary discovery and
   transcription-check source; and
5. news or community material only as a lead, never as event authority.

For Thư Viện Pháp Luật, preserve the stable URL and matched instrument metadata
in the ledger. Do not silently promote its English translation, transliteration,
or membership-gated omissions to source-of-record text.

## Derived coverage artifact

Add `data/ward-source-coverage.json` as deterministic derived data. It should
contain:

- source-floor/current dates and hashes of all planning inputs;
- one record per legal instrument, keyed by normalized code + effective date;
- one record per normalized ward event or observed-delta group;
- links from events to SOAP before/after snapshots and crosswalk rows;
- links from events to primary and secondary legal sources;
- an explicit classification and review status; and
- summary counts and unresolved-residue lists.

Legal-record classifications must include at least:

- `lineage` — creates, dissolves, merges, splits, or transfers whole/partial
  predecessor territory;
- `rename_or_retype`;
- `code_only`;
- `parent_or_boundary_only` — a material administrative change without a ward
  identity transition;
- `no_observable_roster_change`;
- `duplicate_or_superseded`;
- `out_of_scope_false_positive`; and
- `unresolved`.

Source status must distinguish `verified_official_artifact`,
`official_metadata_only`, `secondary_only`, and `missing`. Only
`verified_official_artifact` closes a change-bearing event's primary-source
gate; other statuses remain visible residue until reviewed and resolved.

## Implementation sequence

### Task 1 — close the yearly ward-crosswalk inventory

**Status: DONE (`2026-08-28.03`).** The preflight reproduced the six-file
starting inventory and 18-file residue. The resumable fetcher then preserved all
18 files, recovering from a canceled download by restarting Chromium and
skipping verified work. A fresh offline audit verifies 21/21 yearly windows,
24/24 total ward crosswalk artifacts, 256,149 parsed rows, and zero manifest-row
or hash mismatches.

Use the existing `crosswalk_fetch --tier ward` path. First make acquisition
resumable: verified files are skipped by default, `--force` is explicit, and a
failed window does not invalidate already verified downloads.

Before opening the browser, run an offline preflight that verifies the six
starting crosswalk files, derives the fixed 21-window historical plan, and
prints exactly 18 missing yearly paths. Stop if those counts differ.

Then fetch the 18 missing yearly windows from the live NSO Excel export. For
every file:

- retain the exact `.xls` bytes;
- record base/compare dates, tier, URL, byte count, row count, and SHA-256 in
  `data/raw/manifest.jsonl`;
- require the known 13-column ward schema and a non-empty parsed result; and
- verify the cached artifact again in a fresh offline process.

Do not fetch `2002→2025` repeatedly and do not use a yearly window that crosses
the `2025-07-01` code-era boundary in place of the already preserved boundary
exports.

This task comes first because the external NSO endpoint is the only
availability-sensitive dependency. All later inventory, parsing, and review can
run from the committed raw cache while the source is offline.

### Task 2 — build the offline baseline ledger

**Status: DONE (`2026-08-28.04`).** `ward_source_coverage.py` verifies the locked
offline inputs, collapses 453 legal-index rows to 449 unique instrument keys
without losing four duplicate-key variants, reuses the 34 closed 2025 official
source pairs, and writes a deterministic 552,506-byte
`data/ward-source-coverage.json`. A fresh `--check` build is byte-identical. The
empty event list and 415 unclassified/source-open instruments are explicit Task
3/Task 5 residue, not a completeness claim.

Add `ward_source_coverage.py` and fixture-focused tests. Without using the
network, it must:

1. verify all 204 SOAP files and all existing crosswalk/resolution artifacts
   through `rawcache`;
2. require 21 verified historical yearly ward crosswalks plus the long-range
   and two special boundary exports (24 ward crosswalk files total);
3. re-run the ward legal classifier over the pinned legal index;
4. inventory annual, boundary, long-range, PDF, and HTML artifacts;
5. emit the deterministic skeleton coverage JSON; and
6. fail if the locked SOAP/legal/resolution counts or post-acquisition
   crosswalk counts drift without a reviewed update to this plan or a dated
   journal.

This task establishes the complete offline denominator before event matching.

### Task 3 — enumerate observed ward changes

Build a normalized diff over the chronological 204-date SOAP archive. Preserve
raw source values while deriving stable comparison fields for Unicode,
whitespace, tier labels, and names.

The diff must separately count:

- additions and removals;
- same-code name or tier changes;
- district/province-parent changes;
- exact duplicate source rows;
- conflicting identity rows; and
- byte-identical/no-change observation intervals.

Historical SOAP province fields can echo the current province rather than the
date-correct parent. Never infer lineage from that echo. Resolve historical
parent context through the date-correct province/district graphs and retain the
SOAP value only as observed provenance.

### Task 4 — reconcile annual crosswalk events

Match the normalized SOAP changes to the yearly crosswalk rows using codes,
names, province/district context, effective dates, and `Ghi Chú`. Keep the
crosswalk as net-lineage evidence, not the sole event-discovery source.

Generate targeted event windows only when the annual comparison cannot expose:

- a unit changed more than once in the same year;
- an ephemeral unit appears and disappears inside one annual window;
- multiple same-date instruments make the target ambiguous;
- a partial transfer needs narrower composition evidence; or
- SOAP and the annual export disagree.

Targeted windows must be derived from retained observation dates and legal
effective dates. Do not blanket-download all 369 emergency-bracketed dates
unless the ledger demonstrates that the reviewed 204-date plan is insufficient.

### Task 5 — preserve the historical legal corpus

Add a generic ward legal-source fetcher rather than extending the 2025-only
resolution-number assumptions. For each confirmed or still-plausible
change-bearing instrument:

1. discover and validate the best official URL;
2. cache the best available official PDF and/or full-text HTML;
3. validate instrument code, date, title, content type, and non-empty legal
   body before accepting the download;
4. write the source URL, source class, retrieval time, exact hashes, and related
   artifact paths to the raw manifest; and
5. record secondary TVPL URLs separately for cross-checking.

Use deterministic paths based on normalized instrument code and date. An
existing verified artifact must make the fetcher offline and idempotent.

The 34 verified 2025 resolution pairs are consumed as already complete. The
2026 Đồng Nai instrument `237/NQ-UBTVQH16` is the first non-2025 acceptance
case for the generic path.

### Task 6 — link instruments, events, and source clauses

For each event, record the legal instrument and the specific evidence used for
its effective date and topology. One instrument may create many events; one
event may require more than one instrument or source passage.

Then review all 453 high-recall legal records, including those with no SOAP
identity delta. The result must explain whether each record is a lineage event,
rename/retype, code-only change, parent/boundary-only event, false positive,
duplicate/superseded instrument, or unresolved.

No matching may rely on legal code alone: duplicated short resolution numbers,
missing crosswalk decree cells, and same-date instruments require date,
territory, title, and named-unit checks.

### Task 7 — close the source audit

Add a command that regenerates the coverage JSON and prints a concise audit.
Write a dated completion journal containing final counts, reviewed exceptions,
source outages, and any corrections made only in derived data.

The source-closure gate passes only when:

- 204/204 SOAP artifacts verify;
- all 21 historical yearly crosswalk windows and the special boundary windows
  verify;
- every normalized SOAP delta is linked or explicitly classified;
- every crosswalk event is linked to observed state or explained as net-only,
  partial, or source-only evidence;
- all 453 candidate legal records are classified;
- every change-bearing event has verified official source provenance;
- `secondary_only`, `missing`, and `unresolved` counts are zero for
  change-bearing events; and
- the 2002→2004 interval has an explicit evidence verdict rather than an
  assumption derived from identical snapshots.

If an official artifact genuinely cannot be recovered, keep the gate open and
record a bounded residue. Do not redefine a secondary page as primary merely to
reach zero.

### Task 8 — build the historical ward graph

After Task 7 passes, promote the observations and resolved events into
era-scoped canonical ward entities and `core.LineageEdge` records. Reuse the
completed 2025 topology rather than parsing it again.

Graph gates must cover date spans, date-correct parents, dangling endpoints,
duplicate/self edges, code reuse across eras, whole/partial topology, and exact
source-provenance preservation. Reconciliation and Wikidata output remain
separate reviewed steps after the graph audit.

## Test and review strategy

- Unit-test classification, date normalization, ledger determinism, source
  precedence, artifact validation, and event-link matching with small fixtures.
- Add real-source ground-truth tests for one early event, one same-year chained
  event, one partial transfer, the 2025 reform, and the 2026 Đồng Nai event.
- Run the complete test suite after every task that changes shared parsing or
  raw-cache behavior.
- Regenerate `data/ward-source-coverage.json` twice and require byte-identical
  output.
- Review unresolved rows directly; never patch derived output by hand.

## Commit boundaries

Keep acquisition and interpretation reviewable:

1. resumable crosswalk sweep plus raw artifacts;
2. baseline ledger schema/tool/tests;
3. SOAP change inventory;
4. crosswalk/event reconciliation and targeted windows;
5. legal-source fetcher plus official raw artifacts;
6. instrument/event linkage and complete classification;
7. source-closure journal and acceptance audit; and
8. historical canonical graph in a later implementation series.
