from vn_admin_units.model import Entity, LineageEdge
from vn_admin_units.emit import emit_quickstatements


def test_emit_absorbed_merge_is_referenced_no_p571():
    ents = [
        Entity("p-15-post2025", "15", "post2025", "Tỉnh Lào Cai", "Tỉnh", "2025-07-01", None, "Q36446", "existing"),
        Entity("p-15-pre2025", "15", "pre2025", "Tỉnh Yên Bái", "Tỉnh", None, "2025-06-30", "Q36349", "existing"),
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
        Entity("p-10-pre2025", "10", "pre2025", "Tỉnh Lào Cai", "Tỉnh", None, "2025-06-30", "Q36446", "existing"),
        Entity("p-15-post2025", "15", "post2025", "Tỉnh Lào Cai", "Tỉnh", "2025-07-01", None, "Q36446", "existing"),
    ]
    edges = [LineageEdge("p-10-pre2025", "p-15-post2025", "replaces", "whole", True,
                         "Số: 202/2025/QH15", "2025-07-01")]
    assert emit_quickstatements(ents, edges) == ""


def test_emit_p571_only_for_new_items():
    ents = [
        Entity("w-x-post", "x", "post2025", "Phường Ba Đình", "Phường", "2025-07-01", None, "Q135651473", "new"),
        Entity("w-y-pre", "y", "pre2025", "Phường Trúc Bạch", "Phường", None, "2025-06-30", "Q10828647", "existing"),
    ]
    edges = [LineageEdge("w-y-pre", "w-x-post", "merged_into", "whole", True, "Số: 1656", "2025-07-01")]
    qs = emit_quickstatements(ents, edges)
    assert "Q135651473\tP571\t+2025-07-01T00:00:00Z/11\tS854" in qs
