from vn_admin_units.reconcile import load_seed, apply_seed, _write_csv, _load_existing
from vn_admin_units.model import Entity


def test_apply_seed_sets_qid_and_status():
    seed = load_seed("mappings/provinces-qid.csv")
    e = Entity(local_id="p-15-pre2025", gso_codes=["15"], era="pre2025",
               name_vi="Tỉnh Yên Bái", loai_hinh="Tỉnh", valid_from=None,
               valid_to="2025-06-30", wikidata_qid=None)
    [e2] = apply_seed([e], seed)
    assert e2.wikidata_qid == "Q36349"
    assert e2.qid_status == "existing"


def test_csv_roundtrip_for_resume(tmp_path):
    p = str(tmp_path / "m.csv")
    rows = [["15", "pre2025", "Tỉnh Yên Bái", "Q36349", "existing", "verified"],
            ["10", "pre2025", "Tỉnh Lào Cai", "", "existing", "error"]]
    _write_csv(p, rows)
    ex = _load_existing(p)
    # verified row is reusable on resume; errored row is present but not trusted
    assert ex[("15", "pre2025")]["wikidata_qid"] == "Q36349"
    assert ex[("15", "pre2025")]["match_status"] == "verified"
    assert ex[("10", "pre2025")]["match_status"] == "error"
