import json
from pathlib import Path
from vn_admin_units.cli import build_all


def test_build_all_produces_artifacts():
    """Integration test: runs the full build against the committed data/ and
    data/raw/ inputs, writing the real data/ + statements/ artifacts. Requires
    Task 2/3 inputs to exist. (No tmp isolation — build_all uses repo-relative
    paths; this is an end-to-end check, not a unit test.)"""
    build_all()
    ents = json.loads(Path("data/entities.json").read_text(encoding="utf-8"))
    assert len([e for e in ents if e["era"] == "post2025"]) == 34
    qs = Path("statements/na-provinces-2025.qs").read_text(encoding="utf-8")
    assert "P576" in qs and "P1365" in qs
    # end-to-end safety net (guards review findings #1/#2 against regression):
    for line in qs.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[1] in {"P7888", "P1366", "P1365"}:
            assert parts[0] != parts[2], f"self-referential statement leaked: {line}"
    assert "P571" not in qs, "no province item should get a (false) 2025 inception"
    assert "S854" in qs, "every statement must be referenced"
    assert "+2025-07-01T00:00:00Z/11" in qs, "reform date must be present"
    assert " 00:00:00T" not in qs and "2004" not in qs, "no malformed/base-history dates"


def test_build_province_history_all_artifacts():
    """Phase-1b integration test over the committed data/ + data/raw/ inputs."""
    from vn_admin_units.cli import build_province_history_all
    build_province_history_all()
    ents = json.loads(Path("data/provinces-history.json").read_text(encoding="utf-8"))
    codes = {e["gso_codes"][-1] for e in ents}
    assert {"11", "67", "93", "28", "01"} <= codes            # carve-out children + Hà Tây + Hà Nội
    qs = Path("statements/na-provinces-history.qs").read_text(encoding="utf-8")
    for line in qs.splitlines():
        p = line.split("\t")
        if len(p) >= 3 and p[1] in {"P7888", "P1366", "P1365", "P807"}:
            assert p[0] != p[2], f"self-referential statement: {line}"
    assert "P807" in qs and "P571" in qs and "S854" in qs     # carve-outs always emit (reuse 1a QIDs)
    # The 2008 absorption (P576) emits once Hà Tây's QID is hand-verified.
    ha_tay = next((e for e in ents if e["gso_codes"][-1] == "28"), None)
    if ha_tay and ha_tay["wikidata_qid"]:
        assert "P576" in qs


def test_district_pipeline_offline_guards():
    # OFFLINE: build the graph + emit directly (no network). Synthetic QIDs make the emit
    # deterministic without touching Wikidata; the live path (reconcile_districts_live) is
    # exercised manually, never in the suite.
    from vn_admin_units.district_model import build_districts
    from vn_admin_units.emit import emit_district_quickstatements
    ents, edges = build_districts("data/raw/crosswalk")
    _res = getattr(build_districts, "residue", [])
    assert not [r for r in _res if r[0] == "dissolve-date-unrecovered"], \
        "unrecovered dissolve dates — cache data/raw/nghidinh.json (D6.5) before this test"
    assert not [r for r in _res if r[0] == "merge-target-unresolved"], \
        "unresolved merge successors — curate data/district-merge-targets.json"
    assert 690 <= len([e for e in ents if e.valid_to == "2025-06-30"]) <= 700     # count guard
    for i, e in enumerate(ents):                                                  # deterministic QIDs
        e.wikidata_qid, e.qid_status = f"Q{1000 + i}", "existing"
        for sp in e.parent_spans:                                                 # synthetic province QIDs so
            sp["qid"] = f"QP{sp['code']}"                                         # P131 is EMITTED (else skipped)
    qs = emit_district_quickstatements(ents, edges, default_ref_url="https://nso.example/",
                                       abolition_ref="https://reform.example/resolution")
    lines = qs.splitlines()
    assert lines, "no statements emitted"
    assert any("\tP576\t+2025-07-01T00:00:00Z/11" in l for l in lines)            # universal abolition
    for line in lines:
        p = line.split("\t")
        if len(p) >= 3 and p[1] in {"P7888", "P1366", "P1365", "P807"}:
            assert p[0] != p[2], f"self-referential: {line}"                      # no self-edges
        assert ("S854" in line or "S248" in line), f"unreferenced statement: {line}"
    from vn_admin_units.cli import event_statements_missing_reference
    assert event_statements_missing_reference(qs, "https://nso.example/") == [], \
        "event statements missing a real decree reference — curate data/decree-urls.json"


def test_event_ref_gate_requires_url_for_all_events_exempts_only_baseline_p131():
    from vn_admin_units.cli import event_statements_missing_reference
    root = "https://nso/"
    qs = "\n".join([
        f'Q1\tP1365\tQ2\tP585\t+2013-12-28T00:00:00Z/11\tS854\t"{root}"',        # succession on root -> BAD
        'Q1\tP571\t+2013-12-28T00:00:00Z/11\tS854\t"nan"',                        # inception, 'nan' ref -> BAD
        'Q7\tP807\tQ8\tS854\t""',                                                 # carve, empty ref -> BAD
        f'Q1\tP131\tQ9\tP580\t+2008-08-01T00:00:00Z/11\tS854\t"{root}"',          # dated (re-parent) P131 -> BAD
        f'Q2\tP576\t+2025-07-01T00:00:00Z/11\tS854\t"{root}"',                    # abolition on ROOT -> BAD (F2)
        'Q6\tP576\t+2025-07-01T00:00:00Z/11\tS854\t"https://reform/nq"',          # abolition w/ reform URL -> OK
        f'Q5\tP131\tQ9\tS854\t"{root}"',                                          # bare baseline P131 -> exempt
        'Q3\tP807\tQ4\tS854\t"https://vb/125"',                                   # carve w/ decree -> OK
    ])
    bad = event_statements_missing_reference(qs, root)
    assert len(bad) == 5
    assert any(b.startswith("Q2\t") and "\tP576\t+2025-07-01" in b for b in bad)  # root-referenced abolition flagged
    assert 'S854\t"https://reform/nq"' not in "\n".join(bad)         # abolition w/ real reform URL passes
    assert 'S854\t"https://vb/125"' not in "\n".join(bad)            # a real decree URL passes
    assert not any(b.startswith("Q5\t") for b in bad)                # bare baseline P131 exempt
