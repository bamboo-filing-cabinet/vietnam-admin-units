from vn_admin_units.province_history import build_province_history


def _build():
    return build_province_history(
        snapshot_dir="data",
        window_dir="data/raw/crosswalk",
        carve_outs_path="data/decrees/2004-splits.json",
        seed_1a="mappings/provinces-qid.csv")


def test_2004_carve_outs_are_edges_children_have_inception():
    ents, edges = _build()
    by_code = {e.terminal_code: e for e in ents}
    for child, parent in [("11", "12"), ("67", "66"), ("93", "92")]:
        ce = by_code[child]
        assert ce.valid_from == "2004-01-01"                       # inception filled in
        ed = [x for x in edges if x.successor == ce.local_id and x.relation == "carved_from"]
        assert len(ed) == 1 and by_code[parent].local_id == ed[0].predecessor
        assert by_code[parent].valid_to in (None, "2025-06-30")    # parent persists


def test_carve_out_children_are_not_duplicated():
    ents, _ = _build()
    for code in ("11", "67", "93"):
        assert len([e for e in ents if e.terminal_code == code]) == 1


def test_2004_renumber_is_alias_not_new_entity():
    ents, _ = _build()
    lao_cai = next(e for e in ents if e.terminal_code == "10")     # survivor to 2025-reform era
    assert "205" in lao_cai.aliases and lao_cai.gso_codes[0] == "205"
    assert lao_cai.valid_to == "2025-06-30" and lao_cai.valid_from is None


def test_2008_ha_tay_absorbed_into_ha_noi():
    ents, edges = _build()
    ha_tay = next(e for e in ents if e.terminal_code == "28")
    assert ha_tay.valid_to == "2008-07-31"
    ed = [x for x in edges if x.predecessor == ha_tay.local_id]
    assert len(ed) == 1 and ed[0].relation == "absorbed_into" and ed[0].effective_date == "2008-08-01"
    ha_noi = next(e for e in ents if e.terminal_code == "01")
    assert ed[0].successor == ha_noi.local_id and ha_noi.valid_to in (None, "2025-06-30")


def test_cantho_retype_span_is_dated():
    ents, _ = _build()
    ct = next(e for e in ents if e.terminal_code == "92")
    types = {s["loai_hinh"] for s in ct.type_spans}
    assert "Tỉnh" in types and any("Thành phố" in t for t in types)
    assert ct.type_spans[-1]["from"] == "2004-01-01"          # NQ22 legal date; dated -> P31 emits
    assert ct.type_spans[0]["to"] == "2004-01-01"             # old province span end-dated (P582)
    assert "Tỉnh Cần Thơ" in ct.aliases                       # former name kept (folds equal, differs literally)


def test_hue_rename_and_retype_same_entity():
    ents, _ = _build()
    hue = next(e for e in ents if e.terminal_code == "46")
    assert "Tỉnh Thừa Thiên Huế" in hue.aliases               # old name kept as alias (same entity)
    city_span = hue.type_spans[-1]
    assert city_span["from"] == "2025-01-01" and "Thành phố" in city_span["loai_hinh"]
    assert hue.valid_from is None                             # existed pre-2004; retype != inception
    assert hue.gso_codes[0] == "411" and "411" in hue.aliases
    assert hue.local_id == "ph-411-base"                     # local_id consistent with gso_codes[0]
