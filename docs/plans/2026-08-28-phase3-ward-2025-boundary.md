# Phase 3 — 2025 ward boundary spine

Written 2026-08-28. This is the first implementation slice after the completed
204-date SOAP rescue (`docs/journals/2026-08-27.01`). It narrows the stale,
all-at-once Phase-3 design to one reproducible boundary before historical event
chaining or Wikidata reconciliation.

## Outcome

Build a source-backed, offline-regenerable representation of the
`2025-06-30 → 2025-07-01` ward boundary:

- normalized pre/post observations from the verified SOAP cache;
- every structured primary predecessor→successor link from the official NSO
  crosswalk;
- the five post-reform units with no commune-tier predecessor;
- the official post-reform composition note for every one of the 3,321
  successor units; and
- explicit residue for absorbed/partial constituents whose target is not yet
  resolved with sufficient confidence.

This slice does **not** emit Wikidata statements. The primary-link artifact is
deliberately named as partial evidence, not the finished ward lineage graph.

## Locked inputs

| Purpose | Raw artifact | Expected rows |
| --- | --- | ---: |
| pre-reform roster + district parent | `soap/DanhMucPhuongXa_2025-06-30.xml.gz` | 10,035 |
| post-reform roster + province parent | `soap/DanhMucPhuongXa_2025-07-01.xml.gz` | 3,321 |
| structured primary links | `crosswalk/ward_2025-06-30_2025-07-01.xls` | 10,040 |
| successor composition narratives | `crosswalk/ward_2025-07-01_2026-08-27.xls` | 3,321 |

The final file was acquired from the live NSO `Doi_Chieu_Moi.aspx` Excel export
on 2026-08-28. A post-reform base date is essential: unlike the old→new export,
this direction populates `Ghi Chú` for every current unit.

## Implementation sequence

1. Add one ward-focused module that reads only hash-verified raw-cache content.
2. Normalize Unicode to NFC and collapse embedded whitespace without modifying
   the preserved source. Collapse exact duplicate rows; reject conflicting rows
   for the same `(province, district, ward)` identity.
3. Validate the boundary invariants:
   - 10,035 unique pre codes and 3,321 unique post codes;
   - no missing pre-reform district codes;
   - post-reform SOAP's pseudo-district code equals its province code;
   - crosswalk coverage is 3,316 structured links + 5 blank-base creations;
   - every structured endpoint exists in the corresponding SOAP roster.
   The historical SOAP response's province fields are a current-record echo,
   not a date-correct parent: use the crosswalk's base province for the dated
   observation, retain SOAP's echoed values for provenance, and audit the delta.
4. Recover the one blank post-SOAP label (`00070`) only from the same official
   NSO composition export, and log that correction in the derived artifact.
5. Emit deterministic JSON observations and structured primary-link evidence.
6. Add fixture/unit coverage plus real-source ground-truth gates, then run the
   full suite.

## Composition-lineage gate

The new-direction export proves the composition source exists, but it is not
yet safe to call the result complete lineage:

- all 3,321 rows have notes;
- 20 notes hit the export's exact 255-character narrative limit and several end
  mid-name;
- list grammar frequently carries the tier only once (`các xã A, B, C`);
- the same ward name can occur in multiple former districts; and
- `một phần` contributions create genuine one-to-many predecessor edges.

The next slice parses names against the pre-reform SOAP roster using successor
province + former-district context, validates against the structured primary
edge, and writes a manual-curation residue. **No canonical `ward-lineage.json`
or Wikidata batch may be emitted until every predecessor is either resolved or
explicitly curated from the provincial resolution annexes.**

## Acceptance gates

- All four raw artifacts hash-verify through `rawcache`/manifest checks.
- Generated counts match the locked inputs and are stable across two builds.
- The 3,316 primary links have unique predecessor and successor codes.
- The 6,719 blank-successor predecessor rows remain explicitly counted as
  composition work; none is guessed from code or name alone.
- Tests cover normalization, exact duplicate collapse, conflict rejection,
  missing-label recovery, endpoint coverage, and real boundary counts.
- Documentation reports observations, primary links, creations, and unresolved
  composition as separate quantities.
