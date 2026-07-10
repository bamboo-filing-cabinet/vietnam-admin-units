import re
import unicodedata

_MERGE = re.compile(
    r"của\s+(?P<parts>.+?)\s+thành\s+(?:tỉnh|thành phố)\s+mới\s+có tên gọi là\s+(?P<result>.+)",
    re.IGNORECASE,
)
_SPLIT_PARTS = re.compile(r",\s*|\s+và\s+")


def _norm(s: str) -> str:
    """Normalize whitespace/newlines; keep diacritics (NFC)."""
    return unicodedata.normalize("NFC", re.sub(r"\s+", " ", s)).strip()


def parse_ghichu(text: str) -> dict:
    """Classify a Ghi Chú string and extract merge constituents + result."""
    t = _norm(text)
    if not t:
        return {"event": "none", "constituents": [], "result": None}
    if "giữ nguyên" in t.lower():
        return {"event": "unchanged", "constituents": [], "result": None}
    m = _MERGE.search(t)
    if m and ("sắp xếp" in t.lower() or "hợp nhất" in t.lower()):
        parts = [p.strip().rstrip(".") for p in _SPLIT_PARTS.split(m.group("parts")) if p.strip()]
        return {"event": "merge", "constituents": parts, "result": m.group("result").strip().rstrip(".")}
    if t.lower().startswith("thành lập"):
        return {"event": "establish", "constituents": [], "result": None}
    return {"event": "other", "constituents": [], "result": None}
