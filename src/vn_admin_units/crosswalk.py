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
