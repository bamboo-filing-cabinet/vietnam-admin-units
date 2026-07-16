"""Tier-neutral core shared by the province (1a/1b), district (Phase 2), and
future ward (Phase 3) pipelines. Two concerns live here: the Wikidata emit
primitives (date literal, reference, P31 type-target resolution) and the lineage
relation vocabulary (which relations END the predecessor -> P576). The Entity /
LineageEdge dataclasses (added in R2) are supersets every tier constructs."""
from __future__ import annotations

REFERENCE_URL = "https://danhmuchanhchinh.nso.gov.vn/"

# Wikidata item QIDs for admin-unit types (P31 targets). Province types were confirmed via
# constraints.describe_items 2026-07-14. The four district types are registered here as
# PLACEHOLDERS so the district emitter (D9) resolves a target in its shape tests; their QIDs are
# CONFIRMED/corrected via constraints.describe_items in Task D10 before any real district emit —
# a wrong QID passes shape tests but emits a wrong P31 (this bit Phase 1b).
P31_TARGETS = {
    "Tỉnh": "Q2824648",                       # province of Vietnam
    "Thành phố Trung ương": "Q1381899",       # centrally-controlled city of Vietnam
    # District tier (longest-key-first resolution: "Thành phố Trung ương" above wins over the
    # provincial-city "Thành phố" here). PLACEHOLDERS — CONFIRM in D10.
    "Huyện": "Q5057368",                      # rural district of Vietnam — CONFIRM (D10)
    "Quận": "Q5124547",                       # urban district of Vietnam — CONFIRM (D10)
    "Thị xã": "Q7973736",                     # district-level town (thị xã) — CONFIRM (D10)
    "Thành phố": "Q20124469",                 # provincial city (thành phố thuộc tỉnh) — CONFIRM (D10)
}


def wd_date(d: str) -> str:
    """Wikidata date literal (day precision). Defensively takes the date part in
    case a source passes a datetime string like '2025-07-01 00:00:00'."""
    d = str(d).strip().split(" ")[0].split("T")[0]
    return f"+{d}T00:00:00Z/11"


def ref_s854(url: str) -> str:
    return f'S854\t"{url}"'


def p31_target(loai_hinh: str) -> str:
    """QID for a unit type's P31 target. Longest-key-first so 'Thành phố Trung
    ương' wins over a bare 'Thành phố' prefix match."""
    for key in sorted(P31_TARGETS, key=len, reverse=True):
        if loai_hinh.startswith(key):
            return P31_TARGETS[key]
    return ""


# Relations where the predecessor ENDS (gets P576). Everything else persists.
PREDECESSOR_ENDS = {"consolidated", "merged_into", "split", "absorbed_into", "replaces"}


def predecessor_ends(relation: str) -> bool:
    return relation in PREDECESSOR_ENDS
