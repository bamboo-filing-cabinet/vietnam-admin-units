from vn_admin_units.province_history import Entity, LineageEdge
from vn_admin_units.emit import emit_history_quickstatements


def _e(code, name, qid, vf=None, status="existing", vto="2025-06-30", spans=None):
    return Entity(f"ph-{code}-x", [code], name, "Tỉnh",
                  spans or [{"loai_hinh": "Tỉnh", "from": vf, "to": vto}], [], vf, vto, qid, status)


def test_carve_out_emits_p571_despite_existing_item_and_p807_referenced_to_decree():
    parent = _e("12", "Tỉnh Lai Châu", "Q19608")
    child = _e("11", "Tỉnh Điện Biên", "Q36955", vf="2004-01-01", status="existing")
    edges = [LineageEdge(parent.local_id, child.local_id, "carved_from",
                         decree="Số: 22/2003/QH11", effective_date="2004-01-01",
                         reference_url="https://decree/22-2003")]
    qs = emit_history_quickstatements([parent, child], edges, default_ref_url="https://nso")
    p571 = next(l for l in qs.splitlines() if l.startswith("Q36955\tP571"))
    assert "+2004-01-01T00:00:00Z/11" in p571                    # inception even though existing
    assert '"https://decree/22-2003"' in p571                    # referenced to the carve-out decree
    assert "Q36955\tP807\tQ19608" in qs                          # separated from parent
    assert "Q19608\tP576" not in qs                              # parent persists
    assert "\tP31\t" not in qs                                   # single-span entities: no restated P31


def test_absorption_emits_dissolution_and_succession_referenced_to_2008():
    ha_tay = _e("28", "Tỉnh Hà Tây", "Q158668", vto="2008-07-31")
    ha_noi = _e("01", "Thành phố Hà Nội", "Q1858")
    edges = [LineageEdge(ha_tay.local_id, ha_noi.local_id, "absorbed_into",
                         decree="Số: 15/2008/QH12", effective_date="2008-08-01",
                         reference_url="https://decree/15-2008")]
    qs = emit_history_quickstatements([ha_tay, ha_noi], edges, default_ref_url="https://nso")
    p576 = next(l for l in qs.splitlines() if l.startswith("Q158668\tP576"))
    assert "+2008-08-01T00:00:00Z/11" in p576 and '"https://decree/15-2008"' in p576
    assert "Q158668\tP7888\tQ1858\tP585\t+2008-08-01T00:00:00Z/11" in qs
    assert "Q1858\tP1365\tQ158668" in qs
    assert "Q1858\tP576" not in qs                               # absorber persists


def test_retype_emits_bounded_p31_old_ended_new_started():
    ct = _e("92", "Thành phố Cần Thơ", "Q1552", vf=None, status="existing",
            spans=[{"loai_hinh": "Tỉnh", "from": None, "to": "2004-01-01",
                    "reference_url": "https://decree/22-2003"},
                   {"loai_hinh": "Thành phố Trung ương", "from": "2004-01-01", "to": "2025-06-30",
                    "reference_url": "https://decree/22-2003"}])
    qs = emit_history_quickstatements([ct], [], default_ref_url="https://nso")
    p31 = [l for l in qs.splitlines() if l.startswith("Q1552\tP31")]
    assert any("P582\t+2004-01-01T00:00:00Z/11" in l for l in p31)   # old province type end-dated
    assert any("P580\t+2004-01-01T00:00:00Z/11" in l for l in p31)   # new city type start-dated
    assert all('"https://decree/22-2003"' in l for l in p31)         # both referenced to the decree
