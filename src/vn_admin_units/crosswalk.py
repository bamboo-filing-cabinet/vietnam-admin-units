import re
from datetime import datetime, timedelta

import pandas as pd

_COLS = {
    "Tỉnh": "base_ma", "Tên Tỉnh": "base_ten",
    "Nghị định": "nghi_dinh", "Ngày hiệu lực": "hieu_luc",
    "Tên Tỉnh ĐC": "succ_ten", "Tỉnh ĐC": "succ_ma",
    "Ghi Chú": "ghi_chu",
}


def _code(v: str) -> str:
    """Normalize a province code to 2-digit zero-padded (guards Excel numeric coercion)."""
    v = str(v).strip()
    if v.endswith(".0"):        # numeric cell coerced to "1.0"
        v = v[:-2]
    return v.zfill(2) if v.isdigit() else v


def _clean(v: str) -> str:
    """Strip whitespace and Excel's numeric ".0" coercion; keep codes verbatim."""
    v = str(v).strip()
    return v[:-2] if v.endswith(".0") else v


_EXCEL_EPOCH = datetime(1899, 12, 30)  # Excel's day-0 (accounts for the 1900 leap bug)


def _excel_date(v: str) -> str:
    """Normalize an effective-date cell to ISO 'YYYY-MM-DD'; pass through blanks.

    pandas+xlrd may yield either a raw Excel serial ('37257.0') or an already
    parsed timestamp string ('2013-12-28 00:00:00'), so handle both."""
    v = str(v).strip()
    if not v:
        return ""
    if "-" in v:                       # already a (timestamp) date string
        return v.split(" ", 1)[0]
    try:
        return (_EXCEL_EPOCH + timedelta(days=int(float(v)))).strftime("%Y-%m-%d")
    except ValueError:
        return v  # non-numeric, non-date — leave as-is


# District crosswalk (Đối Chiếu, Cấp=Huyện) has 13 positional columns with two
# duplicate "Nghị định"/"Ngày hiệu lực" headers (base side + compare side), so we
# read by index rather than by name.
_DISTRICT_COLS = [
    "base_tinh", "base_tinh_ten", "base_ma", "base_ten", "base_nghi_dinh", "base_hieu_luc",
    "succ_ten", "succ_ma", "succ_nghi_dinh", "succ_hieu_luc", "succ_tinh_ten", "succ_tinh",
    "ghi_chu",
]


def read_district_crosswalk(path: str) -> list[dict]:
    """Read a Đối Chiếu district (Huyện) .xls export into normalized rows.

    Works for both the flat 2002→2025 export and narrow year-windows (same
    schema). Effective dates are converted from Excel serials to ISO."""
    df = pd.read_excel(path, engine="xlrd", dtype=str, header=0).fillna("")
    out = []
    for _, r in df.iterrows():
        row = {name: _clean(r.iloc[i]) for i, name in enumerate(_DISTRICT_COLS)}
        row["base_hieu_luc"] = _excel_date(row["base_hieu_luc"])
        row["succ_hieu_luc"] = _excel_date(row["succ_hieu_luc"])
        out.append(row)
    return out


# Ward crosswalk (Đối Chiếu, Cấp=Xã): 13 positional columns, base side then compare
# side. Same fixed shape as _DISTRICT_COLS (journal 2026-07-10.06) — province-parented,
# the district (QH) columns are DROPPED from the export. The pre-2025 ward's district
# code (the disambiguation key) is NOT here; it comes from SOAP (DanhMucQuanHuyen) at
# build time. Confirmed against the cached ward_2019-01-01_2020-01-01.xls (Task 2 Step 3).
_WARD_COLS = [
    "base_tinh", "base_tinh_ten",           # province code + name, base side
    "base_ma", "base_ten",                  # ward code + name, base side
    "base_nghi_dinh", "base_hieu_luc",
    "succ_ten", "succ_ma",                  # ward name + code, compare side
    "succ_nghi_dinh", "succ_hieu_luc",      # decree + effective date, compare side
    "succ_tinh_ten", "succ_tinh",           # province name + code, compare side
    "ghi_chu",
]

# Expected raw header (before pandas dedupes the duplicate base/compare names),
# in file order — the schema guard in read_ward_crosswalk compares against this so
# ANY column reorder raises instead of silently mislabeling. Locked to the exact
# header observed in the cached ward_2019-01-01_2020-01-01.xls (Task 2 Step 3):
# note "DC" (not the province reader's "ĐC") and the "Nghị định"/"Ngày hiệu lực"
# capitalization.
_WARD_HEADER = [
    "Tỉnh", "Tên Tỉnh", "Xã", "Tên Xã", "Nghị định", "Ngày hiệu lực",
    "Tên Xã DC", "Xã DC", "Nghị định", "Ngày hiệu lực",
    "Tên Tỉnh DC", "Tỉnh DC", "Ghi Chú",
]


def read_ward_crosswalk(path) -> list[dict]:
    """Read a Đối Chiếu ward (Xã) .xls export into normalized rows.

    Same positional-index approach as read_district_crosswalk (duplicate base/
    compare Nghị định/Ngày hiệu lực headers). Effective dates → ISO; codes kept
    verbatim (no zero-padding — ward codes and district codes vary in width).
    Accepts a path or a file-like object."""
    df = pd.read_excel(path, engine="xlrd", dtype=str, header=0).fillna("")
    # Schema guard — the reader is POSITIONAL, so any column reorder (not just a
    # count change) shifts every field and mislabels SILENTLY. Compare the FULL
    # header against the locked _WARD_HEADER (count + order, including the middle
    # columns) so a deviating window RAISES. pandas suffixes the duplicate base/
    # compare headers (".1"); strip that before comparing. This is what lets Task 4
    # Step 4's parse loop certify every window's schema, not just column count.
    got = [re.sub(r"\.\d+$", "", str(c)).strip() for c in df.columns]
    if got != _WARD_HEADER:
        raise ValueError(
            f"ward crosswalk header does not match the locked schema; the positional "
            f"reader would mislabel. Got {got}, expected {_WARD_HEADER}")
    out = []
    for _, r in df.iterrows():
        row = {name: _clean(r.iloc[i]) for i, name in enumerate(_WARD_COLS)}
        row["base_hieu_luc"] = _excel_date(row["base_hieu_luc"])
        row["succ_hieu_luc"] = _excel_date(row["succ_hieu_luc"])
        out.append(row)
    return out


# Province HISTORY crosswalk (Đối Chiếu, Cấp=Tỉnh, base pre-reform) has 9 positional
# columns with duplicate base/compare "Nghị định"/"Ngày hiệu lực" — read by index,
# like the district reader. Distinct from read_province_crosswalk (7-col reform export).
_PROVINCE_HISTORY_COLS = [
    "base_ma", "base_ten", "base_nghi_dinh", "base_hieu_luc",
    "succ_ten", "succ_ma", "succ_nghi_dinh", "succ_hieu_luc", "ghi_chu",
]


def read_province_history_crosswalk(path) -> list[dict]:
    """Read a 9-col Đối Chiếu province-history window (.xls or file-like) into rows.

    Province codes are NOT zero-padded to 2 digits here: pre-2004 codes are 3-digit
    (e.g. '301') and post-2004 are 2-digit (e.g. '12'); keep both verbatim via _clean."""
    df = pd.read_excel(path, engine="xlrd", dtype=str, header=0).fillna("")
    out = []
    for _, r in df.iterrows():
        row = {name: _clean(r.iloc[i]) for i, name in enumerate(_PROVINCE_HISTORY_COLS)}
        row["base_hieu_luc"] = _excel_date(row["base_hieu_luc"])
        row["succ_hieu_luc"] = _excel_date(row["succ_hieu_luc"])
        out.append(row)
    return out


def read_province_crosswalk(path: str) -> list[dict]:
    """Read the Đối Chiếu province .xls export into normalized rows."""
    df = pd.read_excel(path, engine="xlrd", dtype=str).fillna("")
    out = []
    for _, r in df.iterrows():
        row = {dest: str(r.get(src, "")).strip() for src, dest in _COLS.items()}
        row["base_ma"] = _code(row["base_ma"])
        row["succ_ma"] = _code(row["succ_ma"]) if row["succ_ma"] else ""
        out.append(row)
    return out
