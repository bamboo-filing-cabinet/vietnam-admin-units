"""Cross-check captured district crosswalk events against the official Nghị định list.

Validates that the yearly district crosswalk sweep (`docs/journals/2026-07-13.02`)
didn't miss district-*structural* events. It fetches the GSO Nghị định decree list,
keeps decrees where a district-level unit is the object of a structural change
(create / split / merge / dissolve / rename / reclassify / expand), and reports
which are (not) reflected in the cached crosswalk windows.

Interpreting misses: a "not captured" decree is usually **not** a real gap — it is
one of (a) the pre-2004 event floor (unit captured, ancestry not), (b) a
boundary-only adjustment that changes no district's identity (not a lineage event),
or (c) a decree-labeling mismatch — the event IS captured but the crosswalk row
carries a blank or later decree. See the journal for the verdict.

Usage (requests + lxml are core deps, so no extra group needed):
  uv run python -m vn_admin_units.crosscheck_decrees
"""
from __future__ import annotations

import argparse
import glob
import io
import json
import os
import re

import pandas as pd
import requests

from vn_admin_units.crosswalk import read_district_crosswalk
from vn_admin_units.names import fold_district_name

NGHIDINH_URL = "https://danhmuchanhchinh.nso.gov.vn/NghiDinh.aspx"

_DTYPE = r"(?:thành phố|thị xã|quận|huyện)"
# A district-level unit is the OBJECT of a structural verb (not "... thuộc huyện",
# which is a ward created within a district).
_STRUCT = re.compile(
    rf"(?:thành lập|chia tách|chia|nhập|sáp nhập|hợp nhất|giải thể|đổi tên|nâng cấp)\s+{_DTYPE}\b"
    rf"|mở rộng\s+(?:thành phố|thị xã)"
    rf"|điều chỉnh địa giới[^.]*?(?:mở rộng|thành lập|nâng cấp)\s+(?:thành phố|thị xã|quận)",
    re.I,
)


def decree_code(s: str) -> str:
    """Extract the canonical decree code (e.g. '132/NQ-CP') from a raw string."""
    m = re.search(r"(\d+[-/][A-Za-zĐ0-9/\-]+)", s or "")
    return m.group(1).upper().replace(" ", "") if m else ""


def is_district_structural(noi_dung: str) -> bool:
    """True if a district-level unit is the object of a structural change.

    Excludes ward/commune ops nested *within* a district and the province tier
    (central-government cities, 'trực thuộc trung ương')."""
    x = noi_dung or ""
    if "trực thuộc trung ương" in x.lower():
        return False
    return bool(_STRUCT.search(x))


def fetch_decrees(url: str = NGHIDINH_URL) -> pd.DataFrame:
    """Fetch the Nghị định list into a DataFrame (code, dates, content, flags)."""
    html = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60).text
    dec = next(
        t for t in pd.read_html(io.StringIO(html))
        if t.shape[1] == 4 and t.iloc[:, 0].astype(str).str.contains("NQ|NĐ|QH", na=False).any()
    )
    dec.columns = ["so", "ban_hanh", "hieu_luc", "noi_dung"]
    dec = dec.dropna(subset=["so"]).astype(str)
    dec["code"] = dec["so"].map(decree_code)
    dec["year"] = dec["hieu_luc"].map(
        lambda s: int(m.group(1)) if (m := re.search(r"(\d{4})", s)) else 0
    )
    dec["is_district"] = dec["noi_dung"].map(is_district_structural)
    return dec


def captured_decree_codes(pattern: str = "data/raw/crosswalk/district_20*.xls") -> set[str]:
    """All decree codes appearing on any row of the cached district windows."""
    codes: set[str] = set()
    for f in glob.glob(pattern):
        for r in read_district_crosswalk(f):
            for fld in (r["succ_nghi_dinh"], r["base_nghi_dinh"]):
                c = decree_code(fld)
                if c:
                    codes.add(c)
    return codes


def _iso_from_dmy(s: str) -> str:
    """'28/12/2013' -> '2013-12-28'; pass through anything already ISO or unparseable."""
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})", s or "")
    return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}" if m else (s or "")


def _clean_url(v) -> str:
    """Normalize a URL cell to "" for the empties pandas leaves behind — a missing cell that
    `fetch_decrees().astype(str)` stringified to the literal 'nan'/'none', or blanks. Without
    this a 'nan' url is truthy: it blocks the curated-override merge AND ships as S854 "nan"."""
    s = str(v or "").strip()
    return "" if s.lower() in ("", "nan", "none", "<na>") else s


def decree_index(records) -> dict:
    """{iso_effective_date: [{code, url, noi_dung}]} from Nghị định records
    (each {code, hieu_luc, noi_dung, url?}). Accepts the fetch_decrees DataFrame rows
    or plain dicts. `url` is the decree's per-row source link when the list exposes one
    (see fetch_decrees extension below), else "" (via _clean_url) — a curated override fills the rest."""
    idx: dict[str, list] = {}
    for r in records:
        iso = _iso_from_dmy(str(r["hieu_luc"]))
        idx.setdefault(iso, []).append(
            {"code": r["code"], "url": _clean_url(r.get("url")), "noi_dung": str(r["noi_dung"])})
    return idx


def index_from_df(dec) -> dict:
    """decree_index over a fetch_decrees() DataFrame."""
    return decree_index(dec.to_dict("records"))


def load_decree_urls(path: str = "data/decree-urls.json") -> dict:
    """Curated {decree_code: source_url} overrides for decrees whose per-row link the
    Nghị định list doesn't expose (same discipline as 1b's cached Hà Tây/Huế decrees).
    Merged over any url fetch_decrees scraped; the emit gate (D11) lists any structural
    decree still lacking a url so the residue is never silent."""
    return json.loads(open(path, encoding="utf-8").read()) if os.path.exists(path) else {}


def decree_for(idx: dict, unit_name: str, effective_date: str, aliases=()) -> tuple:
    """Authoritative (decree code, source url) for a (unit, effective-date) change.

    Matches the decree whose noi_dung names the unit BY ANY OF ITS NAMES — the current
    name AND its former names/aliases — because a split product (`Quận Nam Từ Liêm`) is
    named in the decree only as its source (`huyện Từ Liêm`). Matching the successor
    label alone misses it whenever the date carries >1 decree. If no name/alias hits and
    exactly ONE decree bears the date, fall back to it; otherwise ("", "") — ambiguous
    (caller keeps the crosswalk value or routes to residue)."""
    cands = idx.get(effective_date, [])
    if not cands:
        return ("", "")
    folds = [f for f in (fold_district_name(n) for n in (unit_name, *aliases) if n) if f]
    for c in cands:
        prose = fold_district_name(c["noi_dung"])
        if any(fn in prose for fn in folds):
            return (c["code"], c["url"])
    return (cands[0]["code"], cands[0]["url"]) if len(cands) == 1 else ("", "")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Cross-check district captures vs the Nghị định list.")
    ap.add_argument("--start", type=int, default=2004, help="first effective year (district event floor)")
    ap.add_argument("--end", type=int, default=2025)
    a = ap.parse_args(argv)

    dec = fetch_decrees()
    captured = captured_decree_codes()
    era = dec[(dec.year >= a.start) & (dec.year <= a.end) & dec.is_district]
    missed = era[~era.code.isin(captured)]
    print(f"district-structural decrees {a.start}-{a.end}: {len(era)}")
    print(f"  matched by decree code in windows: {len(era) - len(missed)}")
    print(f"  not matched (inspect: pre-floor / boundary-only / label mismatch): {len(missed)}\n")
    for _, r in missed.sort_values("year").iterrows():
        print(f"  {r.year} {r.code:<20} {r.noi_dung[:76]}")


if __name__ == "__main__":
    main()
