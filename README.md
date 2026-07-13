# vietnam-admin-units

A time-versioned gazetteer of Vietnam's administrative units — provinces,
districts, and communes/wards — modeling how they change across reform eras,
reconciled to Wikidata.

This is the **foundation layer** beneath the Bamboo Filing Cabinet election
projects. Both
[`vietnam-elections`](https://github.com/bamboo-filing-cabinet/vietnam-elections)
and
[`vietnam-elections-wikidata`](https://github.com/bamboo-filing-cabinet/vietnam-elections-wikidata)
consume it; it holds **zero** election concepts of its own.

```
vietnam-admin-units  (layer 1: the gazetteer)
        ▲                    ▲
        │                    │
vietnam-elections     vietnam-elections-wikidata
```

## ▶ Start here (resume on any machine)

1. **Clone with submodules** (this repo lives inside the `monorepo`):
   ```sh
   git clone --recurse-submodules git@github.com:bamboo-filing-cabinet/monorepo.git
   cd monorepo/vietnam-admin-units          # (or: git submodule update --init)
   ```
2. **Set up + verify:**
   ```sh
   uv sync
   uv run pytest -q                          # 27 tests should pass
   ```
3. **Read the design — the single entry point:** [`docs/DESIGN.md`](docs/DESIGN.md).
   Its **Document map**, **decisions log**, and **phase roadmap** index everything
   else (per-phase designs, the plan, and the dated decision journals `.01`–`.15`,
   `2026-07-11.*`). Phase-2 design: [`docs/DESIGN-phase2.md`](docs/DESIGN-phase2.md).

## Status

**Phase 1 complete and uploaded** (2025-reform, province tier). The full
pipeline runs end-to-end (SOAP ingest → verbatim raw cache → crosswalk → `Ghi
Chú` parser → entities → lineage `34/34` gate → reconcile → emit), 27 tests
pass, and the Wikidata batch is **live**: `statements/na-provinces-2025.qs` (116
statements, 29 dissolutions → 23 survivors; all referenced; constraint-clean;
reconciliation audited via `reconcile --audit`). Uploaded 2026-07-12 via
QuickStatements ([batch #260741](https://quickstatements.toolforge.org/#/batch/260741),
319 ops, 0 errors).

**Next phases:** wards (NA16), districts (NA11–NA15), pre-2002 history — see the
roadmap in `docs/DESIGN.md` and `docs/DESIGN-phase2.md`.

## The model

One record per real-world admin unit, per era of existence, carrying an
existence span (`valid_from`/`valid_to`), parent-at-time hierarchy, lineage
edges across reforms (`merged_into`/`split_from`/`replaces`), the official GSO
code (`mã ĐVHC`), and a reconciled Wikidata QID. Snapshots and the official
change-history are *inputs*; this entity graph is the source of truth, and it
maps almost one-to-one onto Wikidata (`P571`/`P576`/`P7888`/`P1365`/`P1366`/
`P131`), which lets it also drive Wikidata corrections upstream.

## Layout

- `src/vn_admin_units/` — the package: `soap` (canonical GSO fetch, all tiers) ·
  `fetch` (CLI diagnostics) · `crosswalk` · `ghichu` (parser) · `model`
  (entities + lineage) · `reconcile` (Wikidata QIDs + `--audit`) · `constraints`
  (pre-upload gate) · `emit` (QuickStatements) · `cli` (`cache_snapshots`, `build_all`).
- `data/raw/` — verbatim source bytes + `manifest.jsonl` (provenance). `data/` —
  derived JSON (snapshots, `entities.json`, `lineage.json`).
- `mappings/provinces-qid.csv` — reconciled `(code, era) → QID`.
- `statements/` — emitted Wikidata batches.
- `docs/DESIGN*.md` — design; `docs/plans/` — implementation plans;
  `docs/journals/` — dated decision/probe log.

## Common commands

```sh
uv run python -m vn_admin_units.cli                 # refresh raw cache + snapshots
uv run python -c "from vn_admin_units.cli import build_all; build_all()"   # rebuild batch
uv run python -m vn_admin_units.reconcile           # (re)reconcile provinces -> QIDs (resumable)
uv run python -m vn_admin_units.reconcile --audit   # correctness gate (required before upload)
uv run python -m vn_admin_units.constraints         # check WD property constraints
uv run python -m vn_admin_units.fetch --tier ward --date 01/01/2019 --dups   # ad-hoc source query
```

## Sources

Authoritative upstream is the GSO/NSO *danh mục hành chính* service
(`nso.gov.vn`): `DMDVHC.asmx` SOAP (point-in-time via `DenNgay`, all tiers) +
`Doi_Chieu_Moi.aspx` crosswalk + `Lich_Su_Moi.aspx` change-log. Data is 2002→
present. See `docs/journals/2026-07-10.01`–`.02` for the verified inventory.

## Development

Python + [uv](https://docs.astral.sh/uv/) (matching `vietnam-elections-wikidata`).
TDD; small commits; `uv run pytest`.
