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
