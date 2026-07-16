from vn_admin_units.district_model import dist_local_id, District, detect_collisions
from vn_admin_units.core import Entity

def test_local_id_gen_disambiguates_inherited_code():
    assert dist_local_id("019", None) == "d-019-base"                 # baseline root
    assert dist_local_id("019", "2013-12-28") == "d-019-2013-12-28"   # new Nam Từ Liêm
    assert dist_local_id("019", None) != dist_local_id("019", "2013-12-28")

def test_district_is_core_entity_with_parent_spans():
    d = District(code="271", valid_from=None, valid_to="2025-06-30",
                 name_vi="Huyện Ba Vì", loai_hinh="Huyện",
                 parent_spans=[{"code": "28", "qid": None, "from": None, "to": "2008-07-31"},
                               {"code": "01", "qid": None, "from": "2008-08-01", "to": "2025-06-30"}])
    assert isinstance(d, Entity)
    assert d.local_id == "d-271-base" and d.terminal_code == "271"
    assert len(d.parent_spans) == 2 and d.parent_spans[-1]["code"] == "01"

def test_detect_collisions_flags_dup_local_id():
    a = District(code="019", valid_from=None, valid_to="2013-12-27", name_vi="Huyện Từ Liêm", loai_hinh="Huyện")
    b = District(code="019", valid_from=None, valid_to=None, name_vi="X", loai_hinh="Huyện")  # same id
    c = District(code="019", valid_from="2013-12-28", valid_to="2025-06-30", name_vi="Quận Nam Từ Liêm", loai_hinh="Quận")
    assert detect_collisions([a, b, c]) == ["d-019-base"]
