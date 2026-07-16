from vn_admin_units.model import Entity, LineageEdge
from vn_admin_units.emit import emit_quickstatements


def test_emit_absorbed_merge_is_referenced_no_p571():
    ents = [
        Entity(local_id="p-15-post2025", gso_codes=["15"], era="post2025",
               name_vi="Tỉnh Lào Cai", loai_hinh="Tỉnh", valid_from="2025-07-01",
               valid_to=None, wikidata_qid="Q36446", qid_status="existing"),
        Entity(local_id="p-15-pre2025", gso_codes=["15"], era="pre2025",
               name_vi="Tỉnh Yên Bái", loai_hinh="Tỉnh", valid_from=None,
               valid_to="2025-06-30", wikidata_qid="Q36349", qid_status="existing"),
    ]
    edges = [LineageEdge("p-15-pre2025", "p-15-post2025", "merged_into", "whole", False,
                         "Số: 202/2025/QH15", "2025-07-01")]
    qs = emit_quickstatements(ents, edges)
    assert "Q36349\tP576\t+2025-07-01T00:00:00Z/11\tS854" in qs
    assert "Q36349\tP7888\tQ36446\tP585\t+2025-07-01T00:00:00Z/11\tS854" in qs
    assert "Q36446\tP1365\tQ36349" in qs
    assert 'S854\t"https://danhmuchanhchinh.nso.gov.vn/"' in qs
    assert "P571" not in qs


def test_emit_survivor_same_qid_emits_nothing():
    ents = [
        Entity(local_id="p-10-pre2025", gso_codes=["10"], era="pre2025",
               name_vi="Tỉnh Lào Cai", loai_hinh="Tỉnh", valid_from=None,
               valid_to="2025-06-30", wikidata_qid="Q36446", qid_status="existing"),
        Entity(local_id="p-15-post2025", gso_codes=["15"], era="post2025",
               name_vi="Tỉnh Lào Cai", loai_hinh="Tỉnh", valid_from="2025-07-01",
               valid_to=None, wikidata_qid="Q36446", qid_status="existing"),
    ]
    edges = [LineageEdge("p-10-pre2025", "p-15-post2025", "replaces", "whole", True,
                         "Số: 202/2025/QH15", "2025-07-01")]
    assert emit_quickstatements(ents, edges) == ""


def test_emit_p571_only_for_new_items():
    ents = [
        Entity(local_id="w-x-post", gso_codes=["x"], era="post2025",
               name_vi="Phường Ba Đình", loai_hinh="Phường", valid_from="2025-07-01",
               valid_to=None, wikidata_qid="Q135651473", qid_status="new"),
        Entity(local_id="w-y-pre", gso_codes=["y"], era="pre2025",
               name_vi="Phường Trúc Bạch", loai_hinh="Phường", valid_from=None,
               valid_to="2025-06-30", wikidata_qid="Q10828647", qid_status="existing"),
    ]
    edges = [LineageEdge("w-y-pre", "w-x-post", "merged_into", "whole", True, "Số: 1656", "2025-07-01")]
    qs = emit_quickstatements(ents, edges)
    assert "Q135651473\tP571\t+2025-07-01T00:00:00Z/11\tS854" in qs
