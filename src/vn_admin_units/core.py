"""Tier-neutral core shared by the province (1a/1b), district (Phase 2), and
future ward (Phase 3) pipelines. Two concerns live here: the Wikidata emit
primitives (date literal, reference, P31 type-target resolution) and the lineage
relation vocabulary (which relations END the predecessor -> P576). The Entity /
LineageEdge dataclasses (added in R2) are supersets every tier constructs."""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Optional

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
    # provincial-city "Thành phố" here). CONFIRMED live via SPARQL 2026-07-19 (D10) — the earlier
    # placeholders were random junk items (would have emitted wrong P31, as bit Phase 1b).
    "Huyện": "Q2582669",                      # rural district of Vietnam (579 VN items)
    "Quận": "Q6644510",                       # urban district of Vietnam (52)
    "Thị xã": "Q2112349",                     # District-level town of Vietnam / thị xã (64)
    "Thành phố": "Q3249005",                  # provincial city of Vietnam / thành phố thuộc tỉnh (86)
    # Ward tier. These are the same class IDs used by the read-only ward
    # reconciler when it verifies a candidate's P31.
    "Xã": "Q2389082",                            # commune of Vietnam
    "Phường": "Q687188",                         # ward of Vietnam
    "Thị trấn": "Q1070942",                       # township of Vietnam
    "Đặc khu": "Q134999516",                    # special administrative zone of Vietnam
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


@dataclass
class Entity:
    """Tier-neutral admin-unit entity. Field ORDER matches 1b's province_history
    (gso_codes list, type_spans, aliases) so 1b constructions stay positional; the
    trailing era/parent_spans are defaulted so 1a/2 add them by keyword.

    - gso_codes: chronological codes; [-1] = terminal/reconcile code.
    - type_spans: [{loai_hinh, from, to, decree?, reference_url?}] — >1 span => retype.
    - aliases: former names + former codes (-> WD aliases).
    - era: 1a's "pre2025"/"post2025" label (None for history/districts).
    - parent_spans: [{code, qid, from, to}] dated P131 parent-province spans (districts/wards).
    """
    local_id: str
    gso_codes: list
    name_vi: str
    loai_hinh: str
    type_spans: list = field(default_factory=list)
    aliases: list = field(default_factory=list)
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    wikidata_qid: Optional[str] = None
    qid_status: Optional[str] = None
    era: Optional[str] = None
    parent_spans: list = field(default_factory=list)

    @property
    def terminal_code(self) -> str:
        return self.gso_codes[-1] if self.gso_codes else ""

    @property
    def gso_code(self) -> str:          # 1a back-compat accessor
        return self.gso_codes[-1] if self.gso_codes else ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LineageEdge:
    """Tier-neutral lineage edge. Field ORDER matches 1a's model.LineageEdge
    (share, primary before decree) so 1a edges stay positional; 1b/2 use keywords
    for decree/effective_date/reference_url."""
    predecessor: str
    successor: str
    relation: str
    share: str = "whole"
    primary: bool = False
    decree: str = ""
    effective_date: str = ""
    reference_url: str = ""

    def to_dict(self) -> dict:
        return asdict(self)
