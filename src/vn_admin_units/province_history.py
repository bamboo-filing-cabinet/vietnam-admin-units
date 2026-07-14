"""Phase 1b — province-tier history 2002→2025 (entity + lineage assembly).

Continuous-entity model: one Entity per province across recode/retype; carve-out
children and the ended Hà Tây are their own entities. Kept separate from the 1a
`model.py` (which hardcodes the 2025 eras); the shared shape is a Phase-2 refactor
target, not an import. See docs/DESIGN-phase1b.md.
"""
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from vn_admin_units.names import fold_name


def diff_roster(before: list, after: list) -> dict:
    """Code-keyed diff of two ADJACENT-year province snapshots (same code-era, so
    codes are stable). Same code + changed type = retype; same code + changed folded
    name = rename — both SAME entity (catches Huế: Thừa Thiên Huế→Huế, code 46), NOT
    dissolve+create. 'Hoà'/'Hòa' orthography folds equal → no event. NOT valid across
    the 2004 renumber (codes change there — that boundary is handled by the Đối Chiếu
    remap window + carve-out decree, not this diff)."""
    b = {r["ma"]: r for r in before}
    a = {r["ma"]: r for r in after}
    created = sorted(a[k]["ten"] for k in a.keys() - b.keys())
    dissolved = sorted(b[k]["ten"] for k in b.keys() - a.keys())
    retyped, renamed = [], []
    for k in a.keys() & b.keys():
        if b[k]["loai_hinh"] != a[k]["loai_hinh"]:
            retyped.append({"from": b[k]["ten"], "to": a[k]["ten"],
                            "loai_hinh_from": b[k]["loai_hinh"], "loai_hinh_to": a[k]["loai_hinh"]})
        elif fold_name(b[k]["ten"]) != fold_name(a[k]["ten"]):
            renamed.append({"from": b[k]["ten"], "to": a[k]["ten"]})
    return {"created": created, "dissolved": dissolved, "retyped": retyped, "renamed": renamed}


def load_carve_outs(path: str = "data/decrees/2004-splits.json") -> dict:
    """The curated 2004 carve-out pairings + decree/reference (parentage the GSO
    Đối Chiếu omits below the 2004 floor)."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def hist_local_id(first_code: str, valid_from: Optional[str]) -> str:
    """Entity-anchored id: first-known code + inception ('base' if pre-2004 root).
    Codes reuse across reforms and the scheme changes at 2004 (journal .15), so the
    bare code is never a key; valid_from disambiguates reused codes."""
    return f"ph-{first_code}-{valid_from or 'base'}"


@dataclass
class Entity:
    local_id: str
    gso_codes: list                      # chronological; [-1] = terminal/reconcile code
    name_vi: str                         # terminal name
    loai_hinh: str                       # terminal type
    type_spans: list                     # [{loai_hinh, from, to, decree?, reference_url?}]
    aliases: list                        # former names + former codes
    valid_from: Optional[str]
    valid_to: Optional[str]
    wikidata_qid: Optional[str]
    qid_status: Optional[str] = None     # "existing" | "new"

    @property
    def terminal_code(self) -> str:
        return self.gso_codes[-1] if self.gso_codes else ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LineageEdge:
    predecessor: str                     # local_id
    successor: str                       # local_id
    relation: str                        # "carved_from" | "absorbed_into"
    decree: str
    effective_date: str
    reference_url: str = ""              # event-specific source (per-edge, not per-batch)

    def to_dict(self) -> dict:
        return asdict(self)
