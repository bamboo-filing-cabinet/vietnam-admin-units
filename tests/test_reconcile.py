from vn_admin_units.reconcile import load_seed, apply_seed
from vn_admin_units.model import Entity


def test_apply_seed_sets_qid_and_status():
    seed = load_seed("mappings/provinces-qid.csv")
    e = Entity("p-15-pre2025", "15", "pre2025", "Tỉnh Yên Bái", "Tỉnh", None, "2025-06-30", None)
    [e2] = apply_seed([e], seed)
    assert e2.wikidata_qid == "Q36349"
    assert e2.qid_status == "existing"
