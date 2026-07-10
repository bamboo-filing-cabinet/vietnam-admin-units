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


if __name__ == "__main__":
    cache_snapshots()
