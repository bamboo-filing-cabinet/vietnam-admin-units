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

Design spec: `../docs/journals/2026-07-10.vietnam-admin-units-design.md` (monorepo).

## The model

One record per real-world admin unit, per era of existence, carrying an
existence span (`valid_from`/`valid_to`), parent-at-time hierarchy, lineage
edges across reforms (`merged_into`/`split_from`/`replaces`), the official GSO
code (`mã ĐVHC`), and a reconciled Wikidata QID. Snapshots and the official
change-history are *inputs*; this entity graph is the source of truth, and it
maps almost one-to-one onto Wikidata (`P571`/`P576`/`P7888`/`P1365`/`P1366`/
`P131`), which lets it also drive Wikidata corrections upstream.

## Sources

Authoritative upstream is the GSO/NSO *danh mục hành chính* service. See
`docs/journals/2026-07-10.01.gso-source-reconnaissance.md` for the verified
endpoint inventory. In brief:

- **Current snapshot** — `DMDVHC.asmx` SOAP service (`DanhMucTinh`,
  `DanhMucQuanHuyen`, `DanhMucPhuongXa`).
- **Change history + point-in-time** — `Lich_Su_Moi.aspx` (Nghị quyết
  references + effective dates; date picker; Excel export).
- Prior art / cross-checks: `VietThan/DanhMucHanhChinh`,
  `sunshine-tech/VietnamProvinces`, `tranngocminhhieu/vietnamadminunits`.

## Status

Bootstrapping. First milestone: repo scaffold + GSO source reconnaissance
(this README, `docs/journals/`, and the recon journal). The ingest → graph →
reconcile → emit pipeline is designed but not yet built; see the design spec.

## Development

Python project managed with [uv](https://docs.astral.sh/uv/) (matching
`vietnam-elections-wikidata`). Tooling is added in a later milestone.
