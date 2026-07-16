"""District tier (huyện / quận / thị xã / thành phố thuộc tỉnh) assembly, 2004→2025.

Purely historical: the tier existed 2002→2025 and was abolished 2025-07-01 by the
two-tier reform. Builds one continuous Entity per district (rename/retype/re-parent
are same-entity relabels) + the lineage edges the yearly Đối Chiếu windows expose,
then applies the universal 2025 abolition. See docs/DESIGN-phase2.md."""
from __future__ import annotations

import logging

from vn_admin_units.core import Entity, LineageEdge

log = logging.getLogger("vn_admin_units.district_model")

ABOLITION_DATE = "2025-07-01"       # two-tier reform; districts' event date
ABOLITION_VALID_TO = "2025-06-30"   # last in-force day (inclusive)
DISTRICT_TYPES = {"Huyện", "Quận", "Thị xã", "Thành phố"}


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
