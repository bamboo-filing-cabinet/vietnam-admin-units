from vn_admin_units.reconcile import reuse_1a_qids
from vn_admin_units.province_history import Entity


def _ent(code, name, valid_from=None):
    return Entity(f"ph-{code}-x", [code], name, "Tỉnh",
                  [{"loai_hinh": "Tỉnh", "from": valid_from, "to": "2025-06-30"}], [],
                  valid_from, "2025-06-30", None, None)


def test_reuse_1a_qids_by_terminal_code_and_era():
    ents = [_ent("11", "Tỉnh Điện Biên", "2004-01-01"), _ent("28", "Tỉnh Hà Tây")]
    out = reuse_1a_qids(ents, "mappings/provinces-qid.csv")
    d = {e.terminal_code: e for e in out}
    assert d["11"].wikidata_qid == "Q36955" and d["11"].qid_status == "existing"  # from 1a pre2025
    assert d["28"].wikidata_qid is None                                           # Hà Tây not in 1a -> fresh


def test_prefilled_ha_tay_qid_survives_rebuild(tmp_path):
    from vn_admin_units.reconcile import load_history_seed, apply_history_seed, write_history_mapping
    csv_path = tmp_path / "provinces-history-qid.csv"
    csv_path.write_text(
        "local_id,terminal_code,name_vi,wikidata_qid,qid_status,match_status\n"
        "ph-28-base,28,Tỉnh Hà Tây,Q158668,existing,verified\n", encoding="utf-8")
    seed = load_history_seed(str(csv_path))
    assert seed["ph-28-base"] == ("Q158668", "existing")
    ents = [Entity("ph-28-base", ["28"], "Tỉnh Hà Tây", "Tỉnh",
                   [{"loai_hinh": "Tỉnh", "from": None, "to": "2008-07-31"}], [], None, "2008-07-31", None, None)]
    ents[0].wikidata_qid = "Q_REUSED_WRONG"                    # simulate a reused-but-wrong 1a QID
    apply_history_seed(ents, seed)
    assert ents[0].wikidata_qid == "Q158668"                   # manual seed OVERRIDES the reused QID
    write_history_mapping(ents, str(csv_path))                 # rebuild must not clobber
    txt = csv_path.read_text(encoding="utf-8")
    assert "Q158668" in txt and "verified" in txt
