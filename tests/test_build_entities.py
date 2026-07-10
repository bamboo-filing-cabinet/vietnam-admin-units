from vn_admin_units.model import build_entities


def test_build_entities_counts():
    pre = [{"ma": "15", "ten": "Tỉnh Yên Bái", "loai_hinh": "Tỉnh"}]
    post = [{"ma": "15", "ten": "Tỉnh Lào Cai", "loai_hinh": "Tỉnh"}]
    ents = build_entities(pre, post)
    ids = {e.local_id for e in ents}
    assert ids == {"p-15-pre2025", "p-15-post2025"}
    post_e = next(e for e in ents if e.era == "post2025")
    assert post_e.name_vi == "Tỉnh Lào Cai"
    assert post_e.valid_from == "2025-07-01"
    pre_e = next(e for e in ents if e.era == "pre2025")
    assert pre_e.valid_to == "2025-06-30"
