from dataclasses import dataclass, asdict
from typing import Optional


def local_id(gso_code: str, era: str) -> str:
    """Stable repo-owned id, keyed on (code, era) since codes are reused."""
    return f"p-{gso_code}-{era}"


@dataclass
class Entity:
    local_id: str
    gso_code: str
    era: str            # "pre2025" | "post2025"
    name_vi: str
    loai_hinh: str
    valid_from: Optional[str]
    valid_to: Optional[str]
    wikidata_qid: Optional[str]
    qid_status: Optional[str] = None   # "existing" | "new" — set during reconcile; gates P571

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LineageEdge:
    predecessor: str    # local_id
    successor: str      # local_id
    relation: str       # "merged_into" | "replaces" | "renamed_to" | "split_from"
    share: str          # "whole" | "partial"
    primary: bool       # True if predecessor is the code-inheriting/renamed-from primary
    decree: str
    effective_date: str

    def to_dict(self) -> dict:
        return asdict(self)


def build_entities(pre_rows: list[dict], post_rows: list[dict]) -> list["Entity"]:
    """One entity per (code, era). Pre-reform entities end at the reform date.

    Phase-1 debt: the reform date + era labels are hard-coded here; parameterize
    before Phase 1b (see DESIGN §Temporal scope)."""
    ents = []
    for r in pre_rows:
        ents.append(Entity(
            local_id=local_id(r["ma"], "pre2025"), gso_code=r["ma"], era="pre2025",
            name_vi=r["ten"], loai_hinh=r["loai_hinh"],
            valid_from=None, valid_to="2025-06-30", wikidata_qid=None))
    for r in post_rows:
        ents.append(Entity(
            local_id=local_id(r["ma"], "post2025"), gso_code=r["ma"], era="post2025",
            name_vi=r["ten"], loai_hinh=r["loai_hinh"],
            valid_from="2025-07-01", valid_to=None, wikidata_qid=None))
    return ents
