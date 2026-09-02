from vn_admin_units.core import (wd_date, ref_s854, p31_target, predecessor_ends,
                                 P31_TARGETS, REFERENCE_URL)

def test_wd_date_is_day_precision_and_defensive():
    assert wd_date("2025-07-01") == "+2025-07-01T00:00:00Z/11"
    assert wd_date("2013-12-28 00:00:00") == "+2013-12-28T00:00:00Z/11"   # datetime tail stripped

def test_ref_is_s854():
    assert ref_s854("https://x") == 'S854\t"https://x"'

def test_p31_target_maps_by_loai_hinh():
    assert p31_target("Tỉnh") == P31_TARGETS["Tỉnh"]
    assert p31_target("Thành phố Trung ương") == P31_TARGETS["Thành phố Trung ương"]
    assert p31_target("Xã") == "Q2389082"
    assert p31_target("Phường") == "Q687188"
    assert p31_target("Đặc khu") == "Q134999516"

def test_predecessor_ends_only_for_ending_relations():
    assert predecessor_ends("merged_into") and predecessor_ends("split")
    assert predecessor_ends("absorbed_into") and predecessor_ends("replaces")
    assert not predecessor_ends("carved_from")      # parent persists
    assert not predecessor_ends("renamed_to") and not predecessor_ends("retyped")

from vn_admin_units.core import Entity, LineageEdge

def test_entity_terminal_and_gso_code_accessors():
    e = Entity("d-019-base", ["019"], "Huyện Từ Liêm", "Huyện", [], [], None, "2013-12-27")
    assert e.terminal_code == "019" and e.gso_code == "019"
    assert e.era is None and e.type_spans == [] and e.parent_spans == []

def test_entity_1a_style_via_kwargs_and_1b_style_positional():
    prov = Entity(local_id="p-15-post2025", gso_codes=["15"], name_vi="Tỉnh Lào Cai",
                  loai_hinh="Tỉnh", valid_from="2025-07-01", valid_to=None,
                  wikidata_qid="Q36446", qid_status="existing", era="post2025")
    assert prov.gso_code == "15" and prov.era == "post2025"
    hist = Entity("ph-28-base", ["28"], "Tỉnh Hà Tây", "Tỉnh",
                  [{"loai_hinh": "Tỉnh", "from": None, "to": "2008-07-31"}], [],
                  None, "2008-07-31", None, None)   # 1b positional order preserved
    assert hist.terminal_code == "28" and hist.type_spans[0]["to"] == "2008-07-31"

def test_lineage_edge_1a_positional_preserved():
    ed = LineageEdge("p-10-pre2025", "p-15-post2025", "replaces", "whole", True,
                     "Số: 1685", "2025-07-01")
    assert ed.share == "whole" and ed.primary is True and ed.effective_date == "2025-07-01"
    d = LineageEdge("a", "b", "carved_from", decree="Số: 22", effective_date="2004-01-01",
                    reference_url="https://x")
    assert d.reference_url == "https://x" and d.share == "whole"
