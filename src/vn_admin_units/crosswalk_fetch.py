"""Fetch Đối Chiếu crosswalk windows (province or district) from the GSO web UI.

DevExpress WebForms app; the Excel export is only reachable by driving the page.
Probe-confirmed Cấp combo values: Tỉnh=1, Huyện=2 (2026-07-13.02 / 2026-07-14.01).
Use the Excel download (clean server-side file) — DOM scraping suffers stale-row
contamination across tiers. See docs/journals/2026-07-14.01.

Usage (needs the `ingest` group + `playwright install chromium`):
  uv run --group ingest python -m vn_admin_units.crosswalk_fetch --tier province --sweep 2004 2024
  uv run --group ingest python -m vn_admin_units.crosswalk_fetch --tier province --window 01/01/2008 01/01/2009
  uv run --group ingest python -m vn_admin_units.crosswalk_fetch --sweep 2004 2024   # default tier=district
"""
from __future__ import annotations

import argparse
import io

from vn_admin_units.crosswalk import read_district_crosswalk, read_province_history_crosswalk
from vn_admin_units.rawcache import save_raw

URL = "https://danhmuchanhchinh.nso.gov.vn/Doi_Chieu_Moi.aspx"

# DevExpress control ids on the page
_CAP = "ctl00_PlaceHolderMain_cmbCap"          # Cấp combo
_BASE = "ctl00_PlaceHolderMain_txtNgay"        # Ngày gốc
_COMPARE = "ctl00_PlaceHolderMain_txtNgayDC"   # Ngày đối chiếu
_RUN = "ctl00_PlaceHolderMain_cmdThucHien"     # Thực Hiện
_EXCEL = "ctl00_PlaceHolderMain_cmdExcel"      # Excel export

TIER_CAP = {"province": "1", "district": "2", "ward": "3"}   # DevExpress cmbCap values (ward "3" to confirm live in Task 2)
TIER_VI = {"province": "Tỉnh", "district": "Huyện", "ward": "Xã"}    # manifest label
TIER_READER = {"province": read_province_history_crosswalk,
               "district": read_district_crosswalk}
               # ward reader wired in Task 3 (read_ward_crosswalk) once the schema is known


def _iso(ddmmyyyy: str) -> str:
    d, m, y = ddmmyyyy.split("/")
    return f"{y}-{m.zfill(2)}-{d.zfill(2)}"


def cache_relpath(tier: str, base: str, compare: str) -> str:
    """Deterministic raw-cache path for a window, namespaced by tier."""
    return f"crosswalk/{tier}_{_iso(base)}_{_iso(compare)}.xls"


def _set_date(page, control_id: str, ddmmyyyy: str) -> None:
    d, m, y = (int(x) for x in ddmmyyyy.split("/"))
    page.evaluate(
        "([id, y, m, d]) => ASPxClientControl.GetControlCollection().Get(id)"
        ".SetDate(new Date(y, m - 1, d))",
        [control_id, y, m, d],
    )


def _switch_cap(page, cap_value: str) -> None:
    """Set Cấp and fire its autopostback (server switches tier mode)."""
    with page.expect_navigation(wait_until="networkidle", timeout=60000):
        page.evaluate(
            "(v) => { ASPxClientControl.GetControlCollection().Get('%s').SetValue(v);"
            " __doPostBack('ctl00$PlaceHolderMain$cmbCap',''); }" % _CAP,
            cap_value,
        )


def _fetch_window_bytes(page, base: str, compare: str) -> bytes:
    _set_date(page, _BASE, base)
    _set_date(page, _COMPARE, compare)
    page.click(f"#{_RUN}")
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("tr[class*=dxgvDataRow]", timeout=30000)
    with page.expect_download(timeout=60000) as dl:
        page.click(f"#{_EXCEL}")
    with open(dl.value.path(), "rb") as f:
        return f.read()


def fetch_windows(tier: str, windows: list[tuple[str, str]], headless: bool = True) -> list[dict]:
    """Fetch + verbatim-cache each (base, compare) window for a tier."""
    from playwright.sync_api import sync_playwright

    reader = TIER_READER.get(tier)
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page(accept_downloads=True)
        page.goto(URL, wait_until="networkidle", timeout=60000)
        page.wait_for_function("() => typeof ASPxClientControl !== 'undefined'")
        _switch_cap(page, TIER_CAP[tier])
        for base, compare in windows:
            data = _fetch_window_bytes(page, base, compare)
            rows = reader(io.BytesIO(data)) if reader else []
            relpath = cache_relpath(tier, base, compare)
            save_raw(relpath, data, {
                "source_url": URL, "method": "Excel export (Playwright)",
                "params": {"Cap": TIER_VI[tier], "base": base, "compare": compare},
                "rows": len(rows)})
            print(f"  [{relpath}] {len(data)} bytes, {len(rows)} rows"
                  + ("" if reader else "  (unparsed — no ward reader yet)"))
            results.append({"path": relpath, "rows": len(rows), "bytes": len(data)})
        browser.close()
    return results


def yearly_windows(start_year: int, end_year: int) -> list[tuple[str, str]]:
    """01/01/YYYY → 01/01/(YYYY+1) for YYYY in [start_year, end_year]."""
    return [(f"01/01/{y}", f"01/01/{y + 1}") for y in range(start_year, end_year + 1)]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Fetch Đối Chiếu crosswalk windows.")
    ap.add_argument("--tier", choices=list(TIER_CAP), default="district",
                    help="province | district (default: district — preserves the "
                         "existing '--sweep …' district commands in journal 2026-07-13.02)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--window", nargs=2, metavar=("BASE", "COMPARE"),
                   help="one window, dd/mm/yyyy dd/mm/yyyy")
    g.add_argument("--sweep", nargs=2, type=int, metavar=("START_YEAR", "END_YEAR"),
                   help="yearly windows 01/01/Y → 01/01/Y+1 across the range")
    ap.add_argument("--headed", action="store_true", help="show the browser (debug)")
    a = ap.parse_args(argv)
    windows = [tuple(a.window)] if a.window else yearly_windows(*a.sweep)
    print(f"Fetching {len(windows)} {a.tier} window(s)...")
    fetch_windows(a.tier, windows, headless=not a.headed)
    print("Done.")


if __name__ == "__main__":
    main()
