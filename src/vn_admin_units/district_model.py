"""District tier (huyện / quận / thị xã / thành phố thuộc tỉnh) assembly, 2004→2025.

Purely historical: the tier existed 2002→2025 and was abolished 2025-07-01 by the
two-tier reform. Builds one continuous Entity per district (rename/retype/re-parent
are same-entity relabels) + the lineage edges the yearly Đối Chiếu windows expose,
then applies the universal 2025 abolition. See docs/DESIGN-phase2.md."""
from __future__ import annotations

import logging

from vn_admin_units.core import Entity, LineageEdge
from vn_admin_units.names import fold_district_name

log = logging.getLogger("vn_admin_units.district_model")

ABOLITION_DATE = "2025-07-01"       # two-tier reform; districts' event date
ABOLITION_VALID_TO = "2025-06-30"   # last in-force day (inclusive)
DISTRICT_TYPES = {"Huyện", "Quận", "Thị xã", "Thành phố"}

_TIERS = ("Thành phố", "Thị xã", "Huyện", "Quận")   # longest-first so "Thị xã" wins


def unit_tier(name: str) -> str:
    for t in _TIERS:
        if name.startswith(t):
            return t
    return ""


def classify_change(row: dict) -> str:
    """Candidate event kind from structured columns. 'reparent' is checked before
    name/tier diffs because a Hà Tây→Hà Nội row keeps the same code+name and only
    the province differs. 'retype_rename' (tier AND name changed) is a candidate the
    D6 resolver may promote to a split (Từ Liêm)."""
    b, s = row["base_ma"], row["succ_ma"]
    if not b and s:
        return "create"
    if b and not s:
        return "dissolve"
    if row["base_tinh"] != row["succ_tinh"]:
        return "reparent"
    tier_diff = unit_tier(row["base_ten"]) != unit_tier(row["succ_ten"])
    name_diff = fold_district_name(row["base_ten"]) != fold_district_name(row["succ_ten"])
    if tier_diff and name_diff:
        return "retype_rename"
    if tier_diff:
        return "retype"
    if name_diff:
        return "rename"
    return "unchanged"


def window_events(rows: list) -> list:
    """Changed rows of one yearly window as classified event dicts (kind !=
    unchanged). Carries both codes/names/provinces, the compare-side effective date
    + decree, and Ghi Chú for the D6 resolver."""
    out = []
    for r in rows:
        kind = classify_change(r)
        if kind == "unchanged":
            continue
        out.append({
            "kind": kind,
            "code_from": r["base_ma"], "code_to": r["succ_ma"],
            "name_from": r["base_ten"], "name_to": r["succ_ten"],
            "tinh_from": r["base_tinh"], "tinh_to": r["succ_tinh"],
            "eff_date": r["succ_hieu_luc"] or r["base_hieu_luc"],
            "decree_raw": r["succ_nghi_dinh"] or r["base_nghi_dinh"],
            "ghi_chu": r["ghi_chu"],
        })
    return out


def dist_local_id(code: str, valid_from) -> str:
    """Entity-anchored id: code + generation. `gen` = valid_from ('base' for the
    2004 baseline root). The bare code is never a key — codes are inherited across
    splits (Từ Liêm 019 → Nam Từ Liêm 019) and reassigned (Đạ Tẻh→Đạ Huoai 682)."""
    return f"d-{code}-{valid_from or 'base'}"


def District(code: str, valid_from, valid_to, name_vi: str, loai_hinh: str,
             parent_spans=None, aliases=None, gso_codes=None,
             wikidata_qid=None, qid_status=None, type_spans=None) -> Entity:
    """Construct a district as a core.Entity (era stays None; districts use
    parent_spans for dated P131). gso_codes defaults to [code]; type_spans defaults
    to a single span so a genuine retype (>1 span) is distinguishable."""
    return Entity(
        local_id=dist_local_id(code, valid_from),
        gso_codes=gso_codes or [code],
        name_vi=name_vi, loai_hinh=loai_hinh,
        type_spans=type_spans or [{"loai_hinh": loai_hinh, "from": valid_from, "to": valid_to}],
        aliases=aliases or [],
        valid_from=valid_from, valid_to=valid_to,
        wikidata_qid=wikidata_qid, qid_status=qid_status,
        parent_spans=parent_spans or [])


def detect_collisions(entities: list) -> list:
    """local_ids appearing more than once (a code+gen clash the assembly must
    disambiguate). Logged, returned sorted; never silent."""
    from collections import Counter
    dups = sorted(k for k, n in Counter(e.local_id for e in entities).items() if n > 1)
    for d in dups:
        log.warning("local_id collision: %s", d)
    return dups
