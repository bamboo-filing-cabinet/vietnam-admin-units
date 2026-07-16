import re
import unicodedata


def fold_name(s: str) -> str:
    """Fold a VN admin-unit name for comparison: strip tier prefix, lowercase,
    collapse whitespace, and normalize tone-mark placement by dropping combining
    marks (NFD) so 'Hoà'=='Hòa'; đ→d. Keeps distinct names distinct."""
    s = re.sub(r"^(tỉnh|thành phố)\s+", "", s.strip(), flags=re.IGNORECASE).lower()
    s = re.sub(r"\s+", " ", s)
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").strip()


def fold_district_name(s: str) -> str:
    """Fold a district name for comparison: strip any of the four tier prefixes
    (huyện/quận/thị xã/thành phố), lowercase, collapse whitespace, drop combining
    tone marks (NFD) so 'Hoà'=='Hòa'; đ→d. Wider prefix set than fold_name (which
    is province-only)."""
    s = re.sub(r"^(huyện|quận|thị xã|thành phố)\s+", "", s.strip(), flags=re.IGNORECASE).lower()
    s = re.sub(r"\s+", " ", s)
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").strip()
