# Statements

Emitted QuickStatements batches for Wikidata.

## Current status

`na-wards-create-current.qs` is empty. Batch #270342 created 151 items, its
Tam Nông error resolved to the pre-existing Q140391710, and batch #270387
created the remaining six without errors. All 3,321 current wards now have
QIDs; neither CREATE batch may be replayed.

The exact outcomes are in
`../data/ward-wikidata-create-batch-270342.json` and
`../data/ward-wikidata-create-batch-270387.json`. The regenerated empty
manifest and preflight are in `../data/ward-wikidata-create-current.json` and
`../data/ward-wikidata-create-preflight.json`. Full ward lineage remains
blocked until the 10,035 immediate pre-2025 predecessors are reconciled; see
`../data/ward-wikidata-emission-readiness.json`.

## Prepared, not uploaded

`na-wards-create-predecessors.qs` contains one consolidated draft for the 3,879
immediate pre-2025 ward predecessors for which the automated passes found no
acceptable distinct Wikidata item. That is not yet proof that every item is
absent. The
two-stage reconciliation assigned 6,154 predecessor QIDs automatically and two
manually; the CREATE manifest retains the candidate and current-QID exclusions
for every remaining row. Do not upload this draft yet.

The saved unrestricted QLever preflight leaves no unresolved machine candidate.
Five reproducible random batches of ten rows must also be reviewed and recorded
before upload authorization. After that audit, refresh the live evidence and
enforce the 24-hour gate immediately before any upload:

```sh
uv run python -m vn_admin_units.ward_reconcile_predecessors_broad \
  --fetch --verify --audit
uv run python -m vn_admin_units.ward_emit_predecessor_create --audit
uv run python -m vn_admin_units.ward_emit_predecessor_create \
  --check --audit --require-upload-ready --max-preflight-age-hours 24
```

After upload, ingest every returned QID into `mappings/wards-qid.csv` and
regenerate so this file becomes empty. Only then may the ward lineage package
be emitted. The manifest and preflight are
`../data/ward-wikidata-create-predecessors.json` and
`../data/ward-wikidata-create-predecessors-preflight.json`.

## Uploaded

| File | Uploaded | Batch | Ops | Errors | Description |
|------|----------|-------|-----|--------|-------------|
| `na-wards-create-current.qs` (six-item retry revision) | 2026-09-03 | [#270387](https://quickstatements.toolforge.org/#/batch/270387) | 6 | 0 | Created the six current wards that failed in batch #270342. |
| `na-wards-create-current.qs` (original 158-item revision) | 2026-09-03 | [#270342](https://quickstatements.toolforge.org/#/batch/270342) | 158 | 7 | Created 151 current wards; Tam Nông resolved to existing Q140391710; the other six were created by batch #270387. |
| `na-provinces-2025.qs` | 2026-07-12 | [#260741](https://quickstatements.toolforge.org/#/batch/260741) | 319 | 0 | 2025 province reform: P576 + P7888 + P1366/P1365 for 29 dissolutions → 23 survivors |
| `na-provinces-history.qs` | 2026-07-14 | [#260977](https://quickstatements.toolforge.org/#/batch/260977) | — | 0 | 2002→2025 province history: P571/P807/P31-retype/P576 + succession |
| `na-districts.qs` | 2026-07-20 | [#261331](https://quickstatements.toolforge.org/#/batch/261331) | 4001 | 0 | **Main district tier** — 718 districts, P571/P131/P31-retype/P576 + succession, 2004→2025 + 2025 abolition, all referenced. |
| `na-districts-create-former.qs` | 2026-07-20 | [#261329](https://quickstatements.toolforge.org/#/batch/261329) | 10 | 5 | CREATE the 5 Tier-C former districts WD lacked (huyện/thị xã that became a 2025 đặc-khu/phường). See note below. |
| `na-districts-create-former-2.qs` | 2026-07-20 | [#261330](https://quickstatements.toolforge.org/#/batch/261330) | 3 | 0 | CREATE 3 former districts split off a wrongly-shared QID by the collision audit: Ayun Pa (huyện) Q140626623, Duyên Hải (thị xã) Q140626624, Long Mỹ (thị xã) Q140626625. |

### Note — `na-districts-create-former.qs` (#261329)

Created 5 former-district items (Wikidata had no former item, only the 2025 successor — see
[`docs/journals/2026-07-19.02`](../docs/journals/2026-07-19.02.district-create-new-manual-instructions.md)):

| District | New QID | Successor (P1366) |
|---|---|---|
| Hoàng Sa (huyện) | [Q140626479](https://www.wikidata.org/wiki/Q140626479) | đặc khu Hoàng Sa Q5874429 |
| Lý Sơn (huyện) | [Q140626480](https://www.wikidata.org/wiki/Q140626480) | đặc khu Lý Sơn Q1320095 |
| Cát Hải (huyện) | [Q140626481](https://www.wikidata.org/wiki/Q140626481) | đặc khu Cát Hải Q5051032 |
| Quảng Trị (thị xã) | [Q140626482](https://www.wikidata.org/wiki/Q140626482) | phường Quảng Trị Q1320413 |
| Phú Quí (huyện) | [Q140626483](https://www.wikidata.org/wiki/Q140626483) | đặc khu Phú Quý Q32192913 |

**The 5 errors** were the 5 `<successor> P1365 LAST` back-links — QuickStatements cannot use `LAST`
as a *value* on a different item. All forward statements (labels, P31/P17/P131/P576/P1366) landed
cleanly. The back-links are re-emitted (with explicit QIDs) as part of the main `na-districts.qs`
batch via `data/district-create-new.json`, so no corrective batch is needed.

## Post-upload check

All three district batches uploaded 2026-07-20. When #261331 finishes processing, confirm **0 errors**
on the batch page, then re-run `reconcile.audit_district_qids` — expect only the 1 accepted Ninh Bình
successor-relabel (the 3 Tier-B TYPE flags clear once #261331 lands their P31=huyện).

## Rejected

See [`rejected/README.md`](rejected/README.md) — batches that were generated and reviewed but decided against uploading.
