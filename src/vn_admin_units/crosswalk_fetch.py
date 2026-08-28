"""Fetch Đối Chiếu crosswalk windows from the GSO/NSO web UI.

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
import time

from vn_admin_units.crosswalk import (
    read_district_crosswalk, read_province_history_crosswalk, read_ward_crosswalk,
)
from vn_admin_units import rawcache

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
               "district": read_district_crosswalk,
               "ward": read_ward_crosswalk}


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


def preflight(tier: str, windows: list[tuple[str, str]]) -> dict:
    """Inspect a fetch plan and the tier's raw cache without using the network."""
    planned = []
    missing_windows = []
    for base, compare in windows:
        relpath = cache_relpath(tier, base, compare)
        verified = rawcache.raw_is_verified(relpath)
        planned.append({
            "base": base,
            "compare": compare,
            "path": relpath,
            "verified": verified,
        })
        if not verified:
            missing_windows.append((base, compare))

    cache_dir = rawcache.RAW / "crosswalk"
    tier_paths = sorted(
        path.relative_to(rawcache.RAW).as_posix()
        for path in cache_dir.glob(f"{tier}_*.xls")
    ) if cache_dir.is_dir() else []
    verified_tier_paths = [
        path for path in tier_paths if rawcache.raw_is_verified(path)
    ]
    invalid_tier_paths = [
        path for path in tier_paths if not rawcache.raw_is_verified(path)
    ]
    return {
        "tier": tier,
        "planned_count": len(planned),
        "verified_planned_count": len(planned) - len(missing_windows),
        "missing_count": len(missing_windows),
        "missing_windows": missing_windows,
        "planned": planned,
        "verified_tier_count": len(verified_tier_paths),
        "verified_tier_paths": verified_tier_paths,
        "invalid_tier_paths": invalid_tier_paths,
    }


def print_preflight(report: dict) -> None:
    """Print the cache-only fetch checklist in a stable, reviewable form."""
    print(
        f"{report['tier']} crosswalk preflight: "
        f"{report['verified_planned_count']}/{report['planned_count']} planned verified; "
        f"{report['missing_count']} missing; "
        f"{report['verified_tier_count']} total tier files verified"
    )
    for item in report["planned"]:
        status = "VERIFIED" if item["verified"] else "MISSING"
        print(f"  {status:8} {item['path']}")
    for path in report["invalid_tier_paths"]:
        print(f"  INVALID  {path}")


def _cached_result(relpath: str) -> dict:
    entry = rawcache.manifest_entry(relpath) or {}
    return {
        "path": relpath,
        "rows": entry.get("rows"),
        "bytes": entry.get("bytes"),
        "status": "cached",
    }


def fetch_windows(tier: str, windows: list[tuple[str, str]], headless: bool = True,
                  force: bool = False) -> list[dict]:
    """Fetch missing windows and preserve verified cache entries by default."""
    results_by_path = {}
    pending = []
    for base, compare in windows:
        relpath = cache_relpath(tier, base, compare)
        if not force and rawcache.raw_is_verified(relpath):
            results_by_path[relpath] = _cached_result(relpath)
            print(f"  [{relpath}] verified cache — skipped")
        else:
            pending.append((base, compare))

    if not pending:
        return [
            results_by_path[cache_relpath(tier, base, compare)]
            for base, compare in windows
        ]

    from playwright.sync_api import sync_playwright

    reader = TIER_READER.get(tier)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page(accept_downloads=True)
        page.goto(URL, wait_until="networkidle", timeout=60000)
        page.wait_for_function("() => typeof ASPxClientControl !== 'undefined'")
        _switch_cap(page, TIER_CAP[tier])
        for base, compare in pending:
            data = _fetch_window_bytes(page, base, compare)
            rows = reader(io.BytesIO(data)) if reader else []
            relpath = cache_relpath(tier, base, compare)
            rawcache.save_raw(relpath, data, {
                "source_url": URL, "method": "Excel export (Playwright)",
                "params": {"Cap": TIER_VI[tier], "base": base, "compare": compare},
                "rows": len(rows)})
            print(f"  [{relpath}] {len(data)} bytes, {len(rows)} rows"
                  + ("" if reader else "  (unparsed — no ward reader yet)"))
            results_by_path[relpath] = {
                "path": relpath,
                "rows": len(rows),
                "bytes": len(data),
                "status": "fetched",
            }
        browser.close()
    return [
        results_by_path[cache_relpath(tier, base, compare)]
        for base, compare in windows
    ]


def fetch_with_retries(tier: str, windows: list[tuple[str, str]], *,
                       headless: bool = True, force: bool = False,
                       max_attempts: int = 5, base_delay: float = 2.0,
                       sleeper=time.sleep) -> list[dict]:
    """Restart the browser and resume verified windows after transient failures."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fetch_windows(tier, windows, headless=headless, force=force)
        except Exception as exc:
            last_error = exc
            if attempt == max_attempts:
                break
            delay = base_delay * (2 ** (attempt - 1))
            print(
                f"  browser attempt {attempt}/{max_attempts} failed: {exc}; "
                f"restarting in {delay:g}s"
            )
            sleeper(delay)
    raise RuntimeError(
        f"crosswalk fetch failed after {max_attempts} browser attempt(s): {last_error}"
    ) from last_error


def yearly_windows(start_year: int, end_year: int) -> list[tuple[str, str]]:
    """01/01/YYYY → 01/01/(YYYY+1) for YYYY in [start_year, end_year]."""
    return [(f"01/01/{y}", f"01/01/{y + 1}") for y in range(start_year, end_year + 1)]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Fetch Đối Chiếu crosswalk windows.")
    ap.add_argument("--tier", choices=list(TIER_CAP), default="district",
                    help="province | district | ward (default: district — preserves the "
                         "existing '--sweep …' district commands in journal 2026-07-13.02)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--window", nargs=2, metavar=("BASE", "COMPARE"),
                   help="one window, dd/mm/yyyy dd/mm/yyyy")
    g.add_argument("--sweep", nargs=2, type=int, metavar=("START_YEAR", "END_YEAR"),
                   help="yearly windows 01/01/Y → 01/01/Y+1 across the range")
    ap.add_argument("--headed", action="store_true", help="show the browser (debug)")
    ap.add_argument("--preflight", action="store_true",
                    help="print the cache-only checklist without opening a browser")
    ap.add_argument("--force", action="store_true",
                    help="re-fetch windows even when their cached artifacts verify")
    ap.add_argument("--max-attempts", type=int, default=5,
                    help="browser-session attempts after transient failures (default: 5)")
    ap.add_argument("--base-delay", type=float, default=2.0,
                    help="initial retry delay in seconds (default: 2)")
    a = ap.parse_args(argv)
    if a.max_attempts < 1:
        ap.error("--max-attempts must be at least 1")
    if a.base_delay < 0:
        ap.error("--base-delay cannot be negative")
    windows = [tuple(a.window)] if a.window else yearly_windows(*a.sweep)
    report = preflight(a.tier, windows)
    print_preflight(report)
    if a.preflight:
        return
    print(f"Fetching {len(windows)} {a.tier} window(s)...")
    fetch_with_retries(
        a.tier,
        windows,
        headless=not a.headed,
        force=a.force,
        max_attempts=a.max_attempts,
        base_delay=a.base_delay,
    )
    print("Done.")


if __name__ == "__main__":
    main()
