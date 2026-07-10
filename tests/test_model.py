from vn_admin_units.model import Entity, LineageEdge, local_id


def test_local_id_is_code_era_stable():
    assert local_id("15", "post2025") == "p-15-post2025"
    # same code, different era -> distinct ids (code reuse safety)
    assert local_id("15", "pre2025") != local_id("15", "post2025")


def test_entity_roundtrip():
    e = Entity(local_id="p-15-post2025", gso_code="15", era="post2025",
               name_vi="Tỉnh Lào Cai", loai_hinh="Tỉnh",
               valid_from="2025-07-01", valid_to=None, wikidata_qid=None)
    assert e.to_dict()["local_id"] == "p-15-post2025"
