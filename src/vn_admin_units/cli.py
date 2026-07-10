import json
from pathlib import Path

from vn_admin_units.soap import fetch_provinces_raw, parse_province_diffgram
from vn_admin_units.rawcache import save_raw

BOUNDARY_DATES = {"2025-06-30": "30/06/2025", "2026-07-10": "10/07/2026"}
SOAP_URL = "https://danhmuchanhchinh.nso.gov.vn/DMDVHC.asmx"
DATA = Path("data")


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


if __name__ == "__main__":
    cache_snapshots()
