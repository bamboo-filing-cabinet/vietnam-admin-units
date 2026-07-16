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


# ── District templates (Phase 2). Sibling to parse_ghichu; shares only _norm. ──
_DTYPE = r"(?:huyện|quận|thị xã|thành phố)"
_D_MERGE_TARGET = re.compile(rf"\bvào\s+{_DTYPE}\s+(?P<target>[^,.;]+)", re.IGNORECASE)
_D_MERGE_SOURCE = re.compile(rf"\bcủa\s+{_DTYPE}\s+(?P<source>.+?)\s+vào\b", re.IGNORECASE)
_D_CARVE = re.compile(rf"chia tách từ\s+{_DTYPE}\s+(?P<source>.+?)\s*\(?\s*cũ", re.IGNORECASE)
_D_RENAME = re.compile(
    rf"đổi tên\s+{_DTYPE}\s+(?P<old>.+?)\s+thành\s+{_DTYPE}\s+(?P<new>[^,.;]+)", re.IGNORECASE)


def parse_district_ghichu(text: str) -> dict:
    """Classify a district Ghi Chú and extract the merge/carve/rename constituents.

    Returns {event, source, target}. event in
    {none, merge, carve, establish, rename, retype, other}. `source`/`target` are
    bare unit names (no tier prefix) when the prose names them, else None. Never
    required — the structured-column classifier (district_model) is primary; this
    confirms/overrides when prose is present (design §Lineage resolution)."""
    t = _norm(text)
    if not t:
        return {"event": "none", "source": None, "target": None}
    low = t.lower()
    if low.startswith("đổi tên"):
        m = _D_RENAME.search(t)
        return {"event": "rename",
                "source": m.group("old").strip() if m else None,
                "target": m.group("new").strip() if m else None}
    if "loại hình" in low or low.startswith("chuyển"):
        return {"event": "retype", "source": None, "target": None}
    if low.startswith("chia tách từ"):
        m = _D_CARVE.search(t)
        return {"event": "carve", "source": m.group("source").strip() if m else None, "target": None}
    if low.startswith("thành lập"):
        return {"event": "establish", "source": None, "target": None}
    if any(k in low for k in ("nhập", "sáp nhập", "sát nhập")):
        ms, mt = _D_MERGE_SOURCE.search(t), _D_MERGE_TARGET.search(t)
        return {"event": "merge",
                "source": ms.group("source").strip() if ms else None,
                "target": mt.group("target").strip() if mt else None}
    return {"event": "other", "source": None, "target": None}
