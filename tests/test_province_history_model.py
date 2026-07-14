from vn_admin_units.province_history import Entity, LineageEdge, hist_local_id


def test_local_id_is_scheme_era_aware_not_bare_code():
    # entity anchored on first-known code + valid_from; NOT p-{code}
    assert hist_local_id("11", "2004-01-01") == "ph-11-2004-01-01"
    assert hist_local_id("28", None) == "ph-28-base"          # baseline (pre-2004) root
    # a reused code with a different valid_from → distinct id
    assert hist_local_id("11", "2004-01-01") != hist_local_id("11", None)


def test_entity_terminal_code_and_roundtrip():
    e = Entity(local_id="ph-10-base", gso_codes=["205", "10"], name_vi="Tỉnh Lào Cai",
               loai_hinh="Tỉnh", type_spans=[{"loai_hinh": "Tỉnh", "from": None, "to": "2025-06-30"}],
               aliases=["205"], valid_from=None, valid_to="2025-06-30",
               wikidata_qid=None, qid_status=None)
    assert e.terminal_code == "10"
    assert e.to_dict()["gso_codes"] == ["205", "10"]


def test_lineage_edge_has_reference_url():
    ed = LineageEdge("ph-12-base", "ph-11-2004-01-01", "carved_from",
                     "Số: 22/2003/QH11", "2004-01-01", "https://ref")
    assert ed.reference_url == "https://ref"
    assert ed.to_dict()["relation"] == "carved_from"
