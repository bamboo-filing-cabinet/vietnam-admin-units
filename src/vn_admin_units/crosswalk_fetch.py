"""Fetch district (Huyện) Đối Chiếu crosswalk windows from the GSO web UI.

The GSO Đối Chiếu page (`Doi_Chieu_Moi.aspx`) is a DevExpress WebForms app whose
Excel export is only reachable by driving the page: pick Cấp=Huyện, set the
base/compare dates, run "Thực Hiện", then click "Excel". A plain HTTP replay
fails (AJAX callbacks + client-populated state), so we drive it with Playwright
and capture the `.xls` download, caching it verbatim. See
`docs/journals/2026-07-13.02`.

Yearly windows within a single code-era isolate each year's district changes with
precise effective dates and real `Ghi Chú` prose — unlike the flat 2002→2025
export (whose `Ghi Chú` is code-conversion boilerplate).

Usage (needs the `ingest` dependency group + `playwright install chromium`):
  uv run --group ingest python -m vn_admin_units.crosswalk_fetch --sweep 2004 2024
  uv run --group ingest python -m vn_admin_units.crosswalk_fetch --window 01/01/2013 01/01/2014
"""
from __future__ import annotations

import argparse
import io

from vn_admin_units.crosswalk import read_district_crosswalk
from vn_admin_units.rawcache import save_raw

URL = "https://danhmuchanhchinh.nso.gov.vn/Doi_Chieu_Moi.aspx"

# DevExpress control ids on the page
_CAP = "ctl00_PlaceHolderMain_cmbCap"          # Cấp combo (value 2 = Huyện)
_BASE = "ctl00_PlaceHolderMain_txtNgay"        # Ngày gốc
_COMPARE = "ctl00_PlaceHolderMain_txtNgayDC"   # Ngày đối chiếu
_RUN = "ctl00_PlaceHolderMain_cmdThucHien"     # Thực Hiện
_EXCEL = "ctl00_PlaceHolderMain_cmdExcel"      # Excel export


def _iso(ddmmyyyy: str) -> str:
    d, m, y = ddmmyyyy.split("/")
    return f"{y}-{m.zfill(2)}-{d.zfill(2)}"


def cache_relpath(base: str, compare: str) -> str:
    """Deterministic raw-cache path for a district window."""
    return f"crosswalk/district_{_iso(base)}_{_iso(compare)}.xls"


def _set_date(page, control_id: str, ddmmyyyy: str) -> None:
    d, m, y = (int(x) for x in ddmmyyyy.split("/"))
    page.evaluate(
        "([id, y, m, d]) => ASPxClientControl.GetControlCollection().Get(id)"
        ".SetDate(new Date(y, m - 1, d))",
        [control_id, y, m, d],
    )


def _switch_to_huyen(page) -> None:
    """Set Cấp=Huyện and fire its autopostback (server switches to district mode)."""
    with page.expect_navigation(wait_until="networkidle", timeout=60000):
        page.evaluate(
            "() => { ASPxClientControl.GetControlCollection().Get('%s').SetValue('2');"
            " __doPostBack('ctl00$PlaceHolderMain$cmbCap',''); }" % _CAP
        )


def _fetch_window_bytes(page, base: str, compare: str) -> bytes:
    """Fetch one district window's Excel export (page must be in Huyện mode)."""
    _set_date(page, _BASE, base)
    _set_date(page, _COMPARE, compare)
    page.click(f"#{_RUN}")
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("tr[class*=dxgvDataRow]", timeout=30000)
    with page.expect_download(timeout=60000) as dl:
        page.click(f"#{_EXCEL}")
    with open(dl.value.path(), "rb") as f:
        return f.read()


def fetch_district_windows(windows: list[tuple[str, str]], headless: bool = True) -> list[dict]:
    """Fetch + verbatim-cache each (base, compare) window. Returns manifest-ish info."""
    from playwright.sync_api import sync_playwright

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page(accept_downloads=True)
        page.goto(URL, wait_until="networkidle", timeout=60000)
        page.wait_for_function("() => typeof ASPxClientControl !== 'undefined'")
        _switch_to_huyen(page)
        for base, compare in windows:
            data = _fetch_window_bytes(page, base, compare)
            rows = read_district_crosswalk(io.BytesIO(data))
            relpath = cache_relpath(base, compare)
            save_raw(relpath, data, {
                "source_url": URL,
                "method": "Excel export (Playwright)",
                "params": {"Cap": "Huyện", "base": base, "compare": compare},
                "rows": len(rows),
            })
            print(f"  [{relpath}] {len(data)} bytes, {len(rows)} rows")
            results.append({"path": relpath, "rows": len(rows), "bytes": len(data)})
        browser.close()
    return results


def yearly_windows(start_year: int, end_year: int) -> list[tuple[str, str]]:
    """01/01/YYYY → 01/01/(YYYY+1) for YYYY in [start_year, end_year]."""
    return [(f"01/01/{y}", f"01/01/{y + 1}") for y in range(start_year, end_year + 1)]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Fetch district Đối Chiếu crosswalk windows.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--window", nargs=2, metavar=("BASE", "COMPARE"),
                   help="one window, dd/mm/yyyy dd/mm/yyyy")
    g.add_argument("--sweep", nargs=2, type=int, metavar=("START_YEAR", "END_YEAR"),
                   help="yearly windows 01/01/Y → 01/01/Y+1 across the range")
    ap.add_argument("--headed", action="store_true", help="show the browser (debug)")
    a = ap.parse_args(argv)
    windows = [tuple(a.window)] if a.window else yearly_windows(*a.sweep)
    print(f"Fetching {len(windows)} district window(s)...")
    fetch_district_windows(windows, headless=not a.headed)
    print("Done.")


if __name__ == "__main__":
    main()
