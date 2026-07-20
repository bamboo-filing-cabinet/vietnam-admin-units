from vn_admin_units.district_model import District
from vn_admin_units.core import LineageEdge
from vn_admin_units.emit import emit_district_quickstatements, ABOLITION_DATE


def _d(code, name, qid, vf=None, vto="2025-06-30", loai="Huyện", parent=None):
    d = District(code=code, valid_from=vf, valid_to=vto, name_vi=name, loai_hinh=loai,
                 parent_spans=parent or [{"code": "01", "qid": "Q1858", "from": vf, "to": vto}],
                 wikidata_qid=qid, qid_status="existing")
    return d


def test_universal_abolition_p576_on_survivor_no_successor():
    d = _d("271", "Huyện Ba Vì", "Q1234")
    qs = emit_district_quickstatements([d], [], default_ref_url="https://nso", abolition_ref="https://reform")
    p576 = next(l for l in qs.splitlines() if l.startswith("Q1234\tP576"))
    assert f"+{ABOLITION_DATE}T00:00:00Z/11" in p576 and '"https://reform"' in p576
    assert "P7888" not in qs and "P1366" not in qs                 # abolition has no successor


def test_dated_p131_per_parent_span():
    d = _d("271", "Huyện Ba Vì", "Q1234",
           parent=[{"code": "28", "qid": "Q1077294", "from": None, "to": "2008-07-31"},
                   {"code": "01", "qid": "Q1858", "from": "2008-08-01", "to": "2025-06-30"}])
    qs = emit_district_quickstatements([d], [], default_ref_url="https://nso", abolition_ref="https://reform")
    p131 = [l for l in qs.splitlines() if l.startswith("Q1234\tP131")]
    assert any("Q1077294" in l and "P582\t+2008-07-31" in l for l in p131)   # old parent end-dated
    assert any("Q1858" in l and "P580\t+2008-08-01" in l for l in p131)      # new parent start-dated


def test_carve_out_child_p807_and_p571_parent_persists():
    parent = _d("458", "Huyện Quảng Trạch", "Qpar")
    child = _d("454", "Huyện Quảng Trạch", "Qchild", vf="2013-12-21")   # Ba Đồn/Quảng Trạch carve
    edges = [LineageEdge(parent.local_id, child.local_id, "carved_from",
                         decree="Số: 125/NQ-CP", effective_date="2013-12-21", reference_url="https://d")]
    qs = emit_district_quickstatements([parent, child], edges, default_ref_url="https://nso", abolition_ref="https://reform")
    assert "Qchild\tP807\tQpar" in qs and "Qchild\tP571\t+2013-12-21" in qs
    assert not any(l.startswith("Qpar\tP576\t+2013-12-21") for l in qs.splitlines())  # parent NOT dissolved at carve


def test_split_predecessor_dissolved_products_succeed():
    old = _d("019", "Huyện Từ Liêm", "Qold", vto="2013-12-27")
    nam = _d("019", "Quận Nam Từ Liêm", "Qnam", vf="2013-12-28", loai="Quận")
    edges = [LineageEdge(old.local_id, nam.local_id, "split", share="partial",
                         decree="Số: 132/NQ-CP", effective_date="2013-12-28")]
    qs = emit_district_quickstatements([old, nam], edges, default_ref_url="https://nso", abolition_ref="https://reform")
    assert "Qold\tP576\t+2013-12-28" in qs                          # predecessor ends at split date
    assert "Qnam\tP1365\tQold" in qs and "Qnam\tP571\t+2013-12-28" in qs
    assert not any(l.startswith("Qold\tP576\t+2025-07-01") for l in qs.splitlines())  # not double-dissolved by abolition


def test_retype_p31_both_spans_cite_the_decree():
    # F1: a genuine retype emits TWO dated P31 (old P582 + new P580); BOTH must cite the retype
    # decree — the closed span too, else its dated P31 lands on the NSO root and the gate blocks.
    d = District(code="116", valid_from=None, valid_to="2025-06-30",
                 name_vi="Thành phố Sơn La", loai_hinh="Thành phố",
                 type_spans=[{"loai_hinh": "Thị xã", "from": None, "to": "2008-10-02",
                              "reference_url": "https://vb/retype"},
                             {"loai_hinh": "Thành phố", "from": "2008-10-03", "to": "2025-06-30",
                              "reference_url": "https://vb/retype"}],
                 parent_spans=[{"code": "14", "qid": "Q1", "from": None, "to": "2025-06-30"}],
                 wikidata_qid="Qsl", qid_status="existing")
    qs = emit_district_quickstatements([d], [], default_ref_url="https://nso", abolition_ref="https://reform")
    p31 = [l for l in qs.splitlines() if l.startswith("Qsl\tP31")]
    assert len(p31) == 2 and all('"https://vb/retype"' in l for l in p31)     # neither on the NSO root
    assert any("P582\t+2008-10-02" in l for l in p31) and any("P580\t+2008-10-03" in l for l in p31)


def test_create_new_wires_two_way_succession_to_successor():
    # Tier C: WD had no former-district item, only the 2025 successor (đặc khu / phường), so the
    # former item was hand-created (manual CREATE batch) and its QID is now in the mapping. WD holds
    # no lineage edge to the commune-tier successor, so the succession is wired from a curated
    # {local_id: {successor, reference_url}} map — BOTH directions, referenced to the province
    # arrangement resolution, P585 = the abolition date. (The manual batch's `<successor> P1365 LAST`
    # back-link errored — LAST-as-value — so na-districts.qs must carry it.)
    d = _d("602", "Huyện Phú Quí", "Qnew")
    create_new = {d.local_id: {"successor": "Qsucc", "reference_url": "https://vb/1671"}}
    qs = emit_district_quickstatements([d], [], default_ref_url="https://nso",
                                       abolition_ref="https://reform", create_new=create_new)
    lines = qs.splitlines()
    fwd = next(l for l in lines if l.startswith("Qnew\tP1366\tQsucc"))
    back = next(l for l in lines if l.startswith("Qsucc\tP1365\tQnew"))
    assert f"P585\t+{ABOLITION_DATE}T00:00:00Z/11" in fwd and '"https://vb/1671"' in fwd
    assert f"P585\t+{ABOLITION_DATE}T00:00:00Z/11" in back and '"https://vb/1671"' in back
    assert any(l.startswith("Qnew\tP576") for l in lines)              # still carries the abolition
    assert "P7888" not in qs                                          # replacement, not a merger


def test_create_new_skips_entities_without_qid_or_not_listed():
    d_gap = _d("602", "Huyện Phú Quí", None)                          # still a gap: no QID yet
    d_gap.qid_status = None
    other = _d("271", "Huyện Ba Vì", "Q1234")                         # has QID but not in create_new
    create_new = {d_gap.local_id: {"successor": "Qsucc", "reference_url": "https://vb/1671"}}
    qs = emit_district_quickstatements([d_gap, other], [], default_ref_url="https://nso",
                                       abolition_ref="https://reform", create_new=create_new)
    assert "P1365" not in qs and "Qsucc" not in qs                    # gap emits no succession
    assert "Q1234\tP1365" not in qs                                   # non-listed item untouched


def test_merge_target_unresolved_still_emits_dissolution_p576():
    # F2: a dissolve whose successor couldn't be resolved still emitted its P576 (we know it
    # dissolved on the recovered date). The missing succession link is manual-curation residue.
    e = _d("044", "Huyện Thông Nông", "Qtn", vto="2020-02-29")
    e.dissolution = ("2020-03-01", "https://vb/897")        # stamped by _apply_dissolve (no edge)
    qs = emit_district_quickstatements([e], [], default_ref_url="https://nso", abolition_ref="https://reform")
    p576 = next(l for l in qs.splitlines() if l.startswith("Qtn\tP576"))
    assert "+2020-03-01T00:00:00Z/11" in p576 and '"https://vb/897"' in p576     # dissolution NOT dropped
    assert not any(l.startswith("Qtn\tP576\t+2025-07-01") for l in qs.splitlines())  # not an abolition
