# Repository Guidelines

## Project Structure & Module Organization

This repo is the time-versioned administrative-unit gazetteer (layer 1) beneath
the election projects. It contains reference data and the tooling to produce it;
no election, candidate, or electoral-unit concepts belong here.

- `docs/journals/` — dated decision journals (`YYYY-MM-DD.NN.topic.md`),
  mirroring `vietnam-elections-wikidata`. Design/source decisions live here.
- Planned (added in later milestones): `src/` (ingest → build-graph →
  reconcile → emit pipeline), `data/raw/` (committed GSO snapshot + history
  cache), `data/` (the entity graph — the source of truth), `mappings/`
  (`mã ĐVHC` ↔ Wikidata QID).

The overarching design spec lives in the monorepo:
`../docs/journals/2026-07-10.vietnam-admin-units-design.md`.

## Build, Test, and Development Commands

Python project managed with [uv](https://docs.astral.sh/uv/), matching
`vietnam-elections-wikidata`. Once tooling lands:

- `uv sync` — install dependencies.
- `uv run python -m src.<stage>` — run a pipeline stage (ingest/build/reconcile/emit).

Until then this repo is docs + data only.

## Coding Style & Naming Conventions

- Python, 4-space indent; keep modules small and single-purpose (one pipeline
  stage per module).
- Data files: UTF-8 JSON, stable key ordering, Vietnamese text kept in original
  diacritics (`name_vi`) plus a folded key where matching needs it.
- Repo-owned `local_id` is the stable spine for units; the GSO `mã ĐVHC` is a
  time-scoped attribute (codes are reused across reforms — never a cross-era key).

## Testing Guidelines

- No runner configured yet. When the pipeline lands, add fixture-based tests for
  snapshot-diffing and lineage derivation, and a validation pass over the graph
  (no dangling parents, spans consistent with lineage edges).

## Commit & Pull Request Guidelines

- Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`), short imperative.
- Record source-of-record decisions as a `docs/journals/` entry in the same PR.
- Cite the GSO artifact (snapshot date or Nghị quyết) that backs any data change.

## Configuration & Security Notes

- No secrets. All sources are public government endpoints and open datasets.
- Commit the raw GSO cache so ingest is reproducible and the government endpoint
  is not hit repeatedly.
