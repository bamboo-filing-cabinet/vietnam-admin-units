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
    """Fold a district name to a comparison KEY (not a display form): strip a leading
    tier prefix (huyện/quận/thị xã/thành phố) AND a trailing disambiguation parenthetical
    ('Đức Phổ (thị xã)', 'Tam Nông (Phú Thọ)' — how Wikidata labels near-duplicates),
    lowercase, drop tone marks (NFD) so 'Hoà'=='Hòa', đ→d, then reduce to alphanumerics so
    spacing/apostrophe/hyphen variants unify ('Đa Krông'=='Đakrông', "K'Bang"=='KBang',
    'Phan Rang-Tháp Chàm'=='Phan Rang - Tháp Chàm'). Wider prefix set than fold_name
    (province-only)."""
    s = re.sub(r"^(huyện|quận|thị xã|thành phố)\s+", "", s.strip(), flags=re.IGNORECASE)
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s).lower()          # drop a trailing (disambiguator)
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", s.replace("đ", "d"))    # alnum key: no spaces/apostrophes/hyphens


def fold_ward_name(s: str) -> str:
    """Fold a ward-tier name while preserving the identity-bearing place name.

    Wikidata labels frequently omit ``Xã``/``Phường``/``Thị trấn``/``Đặc khu``
    or add a parenthetical disambiguator. Type and parent are checked as
    separate reconciliation evidence, so neither belongs in the name key.
    """
    s = re.sub(
        r"^(xã|phường|thị trấn|đặc khu)\s+", "", s.strip(),
        flags=re.IGNORECASE,
    )
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s).lower()
    s = "".join(
        char for char in unicodedata.normalize("NFD", s)
        if unicodedata.category(char) != "Mn"
    )
    return re.sub(r"[^a-z0-9]", "", s.replace("đ", "d"))
