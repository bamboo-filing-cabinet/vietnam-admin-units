import json
from pathlib import Path
from vn_admin_units.model import build_entities, build_lineage
from vn_admin_units.crosswalk import read_province_crosswalk

# Verified predecessor(pre code) -> successor(post code) from the 63->34 reform.
# Guards result-NAME correctness (a wrong result that still resolves to *some*
# post entity would pass coverage but be wrong).
KNOWN_EDGES = {
    "15": "15",  # Yên Bái  -> merged Lào Cai (post code 15)
    "10": "15",  # old Lào Cai -> merged Lào Cai (survivor, code 10->15)
    "06": "19",  # Bắc Kạn  -> Thái Nguyên
    "02": "08",  # Hà Giang -> Tuyên Quang
    "01": "01",  # Hà Nội   -> unchanged
}


def _load():
    pre = json.loads(Path("data/provinces-2025-06-30.json").read_text(encoding="utf-8"))
    post = json.loads(Path("data/provinces-2026-07-10.json").read_text(encoding="utf-8"))
    ents = build_entities(pre, post)
    edges = build_lineage(ents, read_province_crosswalk("data/raw/crosswalk/DoiChieu_Tinh_2025.xls"))
    return ents, edges


def test_every_post_province_has_predecessor():
    ents, edges = _load()
    post_ids = {e.local_id for e in ents if e.era == "post2025"}
    covered = {e.successor for e in edges}
    missing = post_ids - covered
    assert not missing, f"post-reform provinces with no predecessor edge: {missing}"
    assert len(post_ids) == 34
    assert len([e for e in ents if e.era == "pre2025"]) == 63


def test_known_edges_resolve_to_correct_successor():
    _, edges = _load()
    by_pred = {e.predecessor: e.successor for e in edges}
    for pre_code, post_code in KNOWN_EDGES.items():
        assert by_pred.get(f"p-{pre_code}-pre2025") == f"p-{post_code}-post2025", \
            f"pre {pre_code} should map to post {post_code}"


def test_edge_effective_date_is_reform_date_not_base_history():
    """Regression: effective_date must be the successor's inception (reform date),
    not the predecessor's own last-change date from the crosswalk (e.g. 2004)."""
    _, edges = _load()
    for e in edges:
        assert e.effective_date == "2025-07-01", \
            f"{e.predecessor}->{e.successor} has effective_date {e.effective_date}"
