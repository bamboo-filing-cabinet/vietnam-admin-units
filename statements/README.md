# Statements

Emitted QuickStatements batches for Wikidata.

## Uploaded

| File | Uploaded | Batch | Ops | Errors | Description |
|------|----------|-------|-----|--------|-------------|
| `na-provinces-2025.qs` | 2026-07-12 | [#260741](https://quickstatements.toolforge.org/#/batch/260741) | 319 | 0 | 2025 province reform: P576 + P7888 + P1366/P1365 for 29 dissolutions → 23 survivors |
| `na-provinces-history.qs` | 2026-07-14 | [#260977](https://quickstatements.toolforge.org/#/batch/260977) | — | 0 | 2002→2025 province history: P571/P807/P31-retype/P576 + succession |
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

## Pending upload

- `na-districts.qs` — full district tier (718 districts, 2004→2025 + abolition), incl. the 5+3
  create-former succession statements above. **All 13 former-district items now created; 0 gaps.**
  Not yet uploaded — the final step.

## Rejected

See [`rejected/README.md`](rejected/README.md) — batches that were generated and reviewed but decided against uploading.
