from vn_admin_units.reconcile import (match_districts, write_district_mapping,
                                       load_district_seed, load_district_mapping,
                                       load_acknowledged_gaps)
from vn_admin_units.district_model import District


def _d(code, name, prov):
    return District(code=code, valid_from=None, valid_to="2025-06-30", name_vi=name,
                    loai_hinh="Huyện",
                    parent_spans=[{"code": prov, "qid": None, "from": None, "to": "2025-06-30"}])


def test_match_by_folded_name_province_weak_tiebreak():
    ents = [_d("519", "Huyện Nông Sơn", "49"), _d("021", "Quận Bắc Từ Liêm", "01")]
    candidates = [{"qid": "Q2541962", "label": "Nông Sơn", "parent_code": "49"},
                  {"qid": "Q_WRONG", "label": "Nông Sơn", "parent_code": "99"}]  # stale parent
    out = match_districts(ents, candidates)
    d = {e.terminal_code: e for e in out}
    assert d["519"].wikidata_qid == "Q2541962" and d["519"].qid_status == "existing"  # province picks right one
    assert d["021"].wikidata_qid is None and d["021"].qid_status == "new"             # genuine gap


def test_name_match_survives_when_province_disagrees_entirely():
    ents = [_d("911", "Thành phố Phú Quốc", "91")]
    candidates = [{"qid": "Q42589", "label": "Phú Quốc", "parent_code": "00"}]        # only hit, stale parent
    out = match_districts(ents, candidates)
    assert out[0].wikidata_qid == "Q42589"                    # not discarded for P131 mismatch (§4)


def test_alias_only_item_matches_not_new():
    ents = [_d("456", "Huyện Mỏ Cày Nam", "83")]
    # the bulk item's LABEL is a stale/English form; the GSO name is only an ALIAS
    candidates = [{"qid": "Q123", "label": "Mo Cay Nam District",
                   "aliases": ["Huyện Mỏ Cày Nam"], "parent_code": "83"}]
    out = match_districts(ents, candidates)
    assert out[0].wikidata_qid == "Q123" and out[0].qid_status == "existing"   # matched via alias, not 'new'


def test_bulk_miss_uses_search_fallback_before_new():
    ents = [_d("021", "Quận Bắc Từ Liêm", "01")]              # absent from the bulk pull
    calls = []
    def fake_search(name):
        calls.append(name)                                   # invoked with the tier-stripped name
        return [{"id": "Q999", "label": "Bắc Từ Liêm", "description": "district"}]
    def fake_verify(ids):
        return {"Q999": ["Q881"]}                            # P17 = Vietnam
    out = match_districts(ents, [], search_fn=fake_search, verify_fn=fake_verify)
    assert out[0].wikidata_qid == "Q999" and out[0].qid_status == "existing"
    assert calls and "Từ Liêm" in calls[0] and "Quận" not in calls[0]


def test_verified_no_hit_is_new():
    ents = [_d("021", "Quận Bắc Từ Liêm", "01")]
    out = match_districts(ents, [], search_fn=lambda n: [], verify_fn=lambda ids: {})
    assert out[0].wikidata_qid is None and out[0].qid_status == "new"   # only a VERIFIED gap is 'new'


def test_district_seed_roundtrip_preserves_manual(tmp_path):
    p = tmp_path / "districts-qid.csv"
    write_district_mapping([_d("519", "Huyện Nông Sơn", "49")], str(p))
    p.write_text(p.read_text().replace("d-519-base,519,Huyện Nông Sơn,49,,,needs-lookup",
                                       "d-519-base,519,Huyện Nông Sơn,49,Q2541962,existing,verified"),
                 encoding="utf-8")
    seed = load_district_seed(str(p))
    assert seed["d-519-base"] == ("Q2541962", "existing")


def test_matched_rows_survive_offline_load_and_rewrite(tmp_path):
    # F1: a live auto-match (status 'matched') must be readable offline AND not be downgraded
    # to needs-lookup / lose its QID on the next rebuild.
    p = tmp_path / "districts-qid.csv"
    p.write_text("local_id,terminal_code,name_vi,parent_code,wikidata_qid,qid_status,match_status\n"
                 "d-519-base,519,Huyện Nông Sơn,49,Q2541962,existing,matched\n", encoding="utf-8")
    mapping = load_district_mapping(str(p))
    assert mapping["d-519-base"] == ("Q2541962", "existing")     # load_district_seed would MISS this
    assert load_district_seed(str(p)) == {}                      # (only verified/manual)
    ent = _d("519", "Huyện Nông Sơn", "49")
    ent.wikidata_qid, ent.qid_status = mapping["d-519-base"]
    write_district_mapping([ent], str(p))
    row = p.read_text().splitlines()[1]
    assert row.endswith("Q2541962,existing,matched")            # QID + 'matched' preserved, not downgraded


def test_acknowledged_gap_is_loaded_and_not_downgraded(tmp_path):
    # F1: a human-acknowledged create-later gap (no QID, match_status='gap') is recognized by the
    # completeness gate AND survives a rewrite instead of reverting to needs-lookup.
    p = tmp_path / "districts-qid.csv"
    p.write_text("local_id,terminal_code,name_vi,parent_code,wikidata_qid,qid_status,match_status\n"
                 "d-021-2013-12-28,021,Quận Bắc Từ Liêm,01,,new,gap\n"
                 "d-777-base,777,Huyện X,55,,,needs-lookup\n", encoding="utf-8")
    assert load_acknowledged_gaps(str(p)) == {"d-021-2013-12-28"}      # only the 'gap' row
    ent = District(code="021", valid_from="2013-12-28", valid_to="2025-06-30",
                   name_vi="Quận Bắc Từ Liêm", loai_hinh="Quận")       # local_id == d-021-2013-12-28
    write_district_mapping([ent], str(p))
    row = next(l for l in p.read_text().splitlines() if l.startswith("d-021-2013-12-28"))
    assert row.endswith("gap") and "needs-lookup" not in row          # gap preserved, not downgraded


def test_audit_reports_gap_separately_from_unresolved(tmp_path):
    # No QIDs in this mapping -> audit makes zero network calls (offline-safe). A 'gap' row is a
    # reviewed create-later gap, NOT an issue; an un-triaged QID-less row IS 'UNRESOLVED'.
    from vn_admin_units.reconcile import audit_district_qids
    p = tmp_path / "districts-qid.csv"
    p.write_text("local_id,terminal_code,name_vi,parent_code,wikidata_qid,qid_status,match_status\n"
                 "d-021-2013-12-28,021,Quận Bắc Từ Liêm,01,,new,gap\n"
                 "d-777-base,777,Huyện X,55,,,needs-lookup\n", encoding="utf-8")
    issues = audit_district_qids(str(p))
    assert any(i.startswith("UNRESOLVED") and "d-777-base" in i for i in issues)   # un-triaged -> issue
    assert not any("d-021-2013-12-28" in i for i in issues)                        # acknowledged gap -> not an issue
