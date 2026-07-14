import json
from pathlib import Path

from vn_admin_units.soap import fetch_provinces_raw, parse_province_diffgram
from vn_admin_units.rawcache import save_raw
from vn_admin_units.crosswalk import read_province_crosswalk
from vn_admin_units.model import build_entities, build_lineage
from vn_admin_units.reconcile import load_seed, apply_seed
from vn_admin_units.emit import emit_quickstatements

BOUNDARY_DATES = {"2025-06-30": "30/06/2025", "2026-07-10": "10/07/2026"}
SOAP_URL = "https://danhmuchanhchinh.nso.gov.vn/DMDVHC.asmx"
DATA = Path("data")
CROSSWALK = "data/raw/crosswalk/DoiChieu_Tinh_2025.xls"


def cache_snapshots() -> None:
    DATA.mkdir(exist_ok=True)
    for iso, ddmmyyyy in BOUNDARY_DATES.items():
        xml = fetch_provinces_raw(ddmmyyyy)
        rows = parse_province_diffgram(xml)
        save_raw(f"soap/DanhMucTinh_{iso}.xml", xml.encode("utf-8"),
                 {"source_url": SOAP_URL, "method": "DanhMucTinh",
                  "params": {"DenNgay": ddmmyyyy}, "rows": len(rows)})
        (DATA / f"provinces-{iso}.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"cached {len(rows)} provinces @ {iso}")


def history_snapshot_dates() -> list[tuple[str, str]]:
    """(iso, dd/mm/yyyy) yearly 01/01 snapshots 2002..2025 + the event boundaries
    that a 01/01 grid would straddle (2004 renumber service-date, 2008 Hà Tây,
    2025 pre-reform). Terminal boundary = the 2025 reform; 2026 is out of scope."""
    pairs = [(f"{y}-01-01", f"01/01/{y}") for y in range(2002, 2026)]
    pairs += [("2004-07-01", "01/07/2004"),   # just after the 30/06/2004 renumber+carve-outs
              ("2008-09-01", "01/09/2008"),   # just after 2008-08-01 Hà Tây
              ("2025-06-30", "30/06/2025")]   # 1a pre-reform boundary (already cached by 1a)
    seen, out = set(), []
    for iso, ddmm in pairs:
        if iso not in seen:
            seen.add(iso)
            out.append((iso, ddmm))
    return sorted(out)


def cache_history_snapshots() -> None:
    """Yearly SOAP DanhMucTinh walk 2002→2025 (event-discovery backbone). Reuses
    fetch_provinces_raw; caches verbatim + manifest + derived JSON, like
    cache_snapshots but over the historical date set (cache_snapshots hardcodes only
    the two 2025-reform boundary dates)."""
    DATA.mkdir(exist_ok=True)
    for iso, ddmmyyyy in history_snapshot_dates():
        xml = fetch_provinces_raw(ddmmyyyy)
        rows = parse_province_diffgram(xml)
        save_raw(f"soap/DanhMucTinh_{iso}.xml", xml.encode("utf-8"),
                 {"source_url": SOAP_URL, "method": "DanhMucTinh",
                  "params": {"DenNgay": ddmmyyyy}, "rows": len(rows)})
        (DATA / f"provinces-{iso}.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"cached {len(rows)} provinces @ {iso}")


def _load(iso):
    return json.loads((DATA / f"provinces-{iso}.json").read_text(encoding="utf-8"))


def build_all() -> None:
    pre, post = _load("2025-06-30"), _load("2026-07-10")
    ents = apply_seed(build_entities(pre, post), load_seed("mappings/provinces-qid.csv"))
    edges = build_lineage(ents, read_province_crosswalk(CROSSWALK))
    DATA.mkdir(exist_ok=True)
    (DATA / "entities.json").write_text(
        json.dumps([e.to_dict() for e in ents], ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA / "lineage.json").write_text(
        json.dumps([e.to_dict() for e in edges], ensure_ascii=False, indent=2), encoding="utf-8")
    Path("statements").mkdir(exist_ok=True)
    Path("statements/na-provinces-2025.qs").write_text(
        emit_quickstatements(ents, edges), encoding="utf-8")
    print(f"built {len(ents)} entities, {len(edges)} lineage edges")


def build_province_history_all() -> None:
    from vn_admin_units.province_history import build_province_history
    from vn_admin_units.reconcile import (reuse_1a_qids, load_history_seed,
                                          apply_history_seed, write_history_mapping)
    from vn_admin_units.emit import emit_history_quickstatements, NSO_SOURCE_URL
    ents, edges = build_province_history("data", "data/raw/crosswalk",
                                         "data/decrees/2004-splits.json",
                                         "mappings/provinces-qid.csv")
    ents = reuse_1a_qids(ents, "mappings/provinces-qid.csv")
    # Preserve the hand-verified Hà Tây QID (manual step) across rebuilds BEFORE emit,
    # so the 2008 absorption edge isn't skipped for a missing QID.
    ents = apply_history_seed(ents, load_history_seed())
    write_history_mapping(ents)
    DATA.mkdir(exist_ok=True)
    (DATA / "provinces-history.json").write_text(
        json.dumps([e.to_dict() for e in ents], ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA / "province-history-lineage.json").write_text(
        json.dumps([e.to_dict() for e in edges], ensure_ascii=False, indent=2), encoding="utf-8")
    Path("statements").mkdir(exist_ok=True)
    # Per-statement references come from each edge/span/decree; NSO is the fallback.
    Path("statements/na-provinces-history.qs").write_text(
        emit_history_quickstatements(ents, edges, default_ref_url=NSO_SOURCE_URL), encoding="utf-8")
    print(f"built {len(ents)} entities, {len(edges)} lineage edges")


if __name__ == "__main__":
    cache_snapshots()
