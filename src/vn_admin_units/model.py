import re

from vn_admin_units.core import Entity, LineageEdge
from vn_admin_units.ghichu import parse_ghichu, _norm


def local_id(gso_code: str, era: str) -> str:
    """Stable repo-owned id, keyed on (code, era) since codes are reused."""
    return f"p-{gso_code}-{era}"


def build_entities(pre_rows: list[dict], post_rows: list[dict]) -> list["Entity"]:
    """One entity per (code, era). Pre-reform entities end at the reform date.

    Phase-1 debt: the reform date + era labels are hard-coded here; parameterize
    before Phase 1b (see DESIGN §Temporal scope)."""
    ents = []
    for r in pre_rows:
        ents.append(Entity(
            local_id=local_id(r["ma"], "pre2025"), gso_codes=[r["ma"]], era="pre2025",
            name_vi=r["ten"], loai_hinh=r["loai_hinh"],
            valid_from=None, valid_to="2025-06-30", wikidata_qid=None))
    for r in post_rows:
        ents.append(Entity(
            local_id=local_id(r["ma"], "post2025"), gso_codes=[r["ma"]], era="post2025",
            name_vi=r["ten"], loai_hinh=r["loai_hinh"],
            valid_from="2025-07-01", valid_to=None, wikidata_qid=None))
    return ents


def _strip_prefix(name: str) -> str:
    return _norm(re.sub(r"^(tỉnh|thành phố)\s+", "", name, flags=re.IGNORECASE)).lower()


def build_lineage(entities: list["Entity"], crosswalk: list[dict]) -> list["LineageEdge"]:
    """Predecessor->successor edges. (a) structured succ_ma = primary/renamed-from
    (replaces); (b) blank succ_ma + Ghi Chú merge result = absorbed (merged_into)."""
    post_by_code = {e.gso_code: e for e in entities if e.era == "post2025"}
    post_by_name = {_strip_prefix(e.name_vi): e for e in entities if e.era == "post2025"}
    pre_by_code = {e.gso_code: e for e in entities if e.era == "pre2025"}
    edges: list[LineageEdge] = []
    for row in crosswalk:
        pre = pre_by_code.get(row["base_ma"])
        if pre is None:
            continue
        decree = row["nghi_dinh"]
        # The merge/succession takes effect when the SUCCESSOR comes into being
        # (its valid_from = the reform date). The crosswalk base-side `hieu_luc`
        # is the predecessor's own last-change date (e.g. 2004) — NOT this event.
        if row["succ_ma"]:                                   # (a) structured primary
            succ = post_by_code.get(row["succ_ma"])
            if succ:
                edges.append(LineageEdge(pre.local_id, succ.local_id, "replaces",
                                         "whole", True, decree, succ.valid_from))
            continue
        parsed = parse_ghichu(row["ghi_chu"])               # (b) absorbed via prose
        if parsed["event"] == "merge" and parsed["result"]:
            succ = post_by_name.get(_strip_prefix(parsed["result"]))
            if succ:
                edges.append(LineageEdge(pre.local_id, succ.local_id, "merged_into",
                                         "whole", False, decree, succ.valid_from))
    return edges
