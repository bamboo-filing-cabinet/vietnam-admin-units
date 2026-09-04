import csv
import json
from pathlib import Path

from vn_admin_units.ward_reconcile_predecessors import (
    apply_matches,
    apply_review_decisions,
    audit,
    evaluate,
    immediate_predecessor_ids,
    reduce_candidates,
    verify,
)


def _history():
    return {
        "entities": [
            {
                "local_id": "w-old-1",
                "gso_codes": ["00001"],
                "name_vi": "Xã Hòa Bình",
                "loai_hinh": "Xã",
                "valid_from": None,
                "valid_to": "2025-06-30",
                "parent_spans": [{"code": "001"}],
            },
            {
                "local_id": "w-old-2",
                "gso_codes": ["00002"],
                "name_vi": "Phường Tân Phú",
                "loai_hinh": "Phường",
                "valid_from": None,
                "valid_to": "2025-06-30",
                "parent_spans": [{"code": "002"}],
            },
            {
                "local_id": "w-new",
                "gso_codes": ["00003"],
                "name_vi": "Xã Mới",
                "loai_hinh": "Xã",
                "valid_from": "2025-07-01",
                "valid_to": None,
                "parent_spans": [{"code": "01"}],
            },
        ],
        "lineage_edges": [
            {
                "predecessor": "w-old-1",
                "successor": "w-new",
                "effective_date": "2025-07-01",
            },
            {
                "predecessor": "w-old-2",
                "successor": "w-new",
                "effective_date": "2025-07-01",
            },
        ],
    }


def _candidates():
    return {
        "scope": {"as_of": "2026-09-01"},
        "candidates": [
            {
                "qid": "Q1",
                "label_vi": "Hòa Bình",
                "label_en": "",
                "aliases": [],
                "types": ["Q2389082"],
                "parent_qids": ["QD1"],
            },
            {
                "qid": "Q2",
                "label_vi": "Xã Hòa Bình",
                "label_en": "",
                "aliases": [],
                "types": ["Q2389082"],
                "parent_qids": ["QD1"],
            },
            {
                "qid": "Q3",
                "label_vi": "Tân Phú",
                "label_en": "",
                "aliases": [],
                "types": ["Q687188"],
                "parent_qids": ["QD2"],
            },
        ],
    }


def _mapping():
    return [
        {
            "local_id": "w-old-1", "valid_to": "2025-06-30",
            "wikidata_qid": "", "qid_status": "", "match_status": "deferred-historical",
            "candidate_qids": "", "match_notes": "",
        },
        {
            "local_id": "w-old-2", "valid_to": "2025-06-30",
            "wikidata_qid": "", "qid_status": "", "match_status": "deferred-historical",
            "candidate_qids": "", "match_notes": "",
        },
        {
            "local_id": "w-new", "valid_to": "", "wikidata_qid": "Q3",
            "qid_status": "existing", "match_status": "manual",
            "candidate_qids": "Q3", "match_notes": "reviewed",
        },
    ]


def _verified(qid, name, parent, p31):
    return {
        "qid": qid,
        "missing": False,
        "labels": {"vi": name},
        "aliases": [],
        "p31": [p31],
        "p131": [parent],
    }


def test_predecessor_ids_are_limited_to_the_2025_reform():
    history = _history()
    history["lineage_edges"].append({
        "predecessor": "w-older",
        "successor": "w-old-1",
        "effective_date": "2024-01-01",
    })

    assert immediate_predecessor_ids(history) == ["w-old-1", "w-old-2"]


def test_reduction_excludes_current_qids_and_filters_by_terminal_district(tmp_path):
    history_path = tmp_path / "history.json"
    candidates_path = tmp_path / "candidates.json"
    districts_path = tmp_path / "districts.csv"
    history_path.write_text("history", encoding="utf-8")
    candidates_path.write_text("candidates", encoding="utf-8")
    districts_path.write_text("districts", encoding="utf-8")

    artifact = reduce_candidates(
        _history(), _candidates(), {"QD1": {"001"}, "QD2": {"002"}},
        _mapping(), history_path=history_path, candidate_path=candidates_path,
        district_mapping_path=districts_path,
    )
    by_id = {row["local_id"]: row for row in artifact["review"]}

    assert artifact["shortlisted_qids"] == ["Q1", "Q2"]
    assert by_id["w-old-1"]["district_candidate_qids"] == ["Q1", "Q2"]
    assert by_id["w-old-2"]["candidate_qids"] == []
    assert by_id["w-old-2"]["current_qids_excluded"] == ["Q3"]
    assert by_id["w-old-2"]["classification"] == "current-item-repurposed"


def test_evaluation_uses_exact_tier_to_break_ambiguity_and_applies_match(tmp_path):
    history_path = tmp_path / "history.json"
    candidates_path = tmp_path / "candidates.json"
    districts_path = tmp_path / "districts.csv"
    for path in (history_path, candidates_path, districts_path):
        path.write_text(path.name, encoding="utf-8")
    mapping = _mapping()
    artifact = reduce_candidates(
        _history(), _candidates(), {"QD1": {"001"}, "QD2": {"002"}},
        mapping, history_path=history_path, candidate_path=candidates_path,
        district_mapping_path=districts_path,
    )
    artifact["action_api_verification"]["entities"] = [
        _verified("Q1", "Hòa Bình", "QD1", "Q2389082"),
        _verified("Q2", "Hòa Bình", "QD1", "Q687188"),
    ]

    artifact = evaluate(artifact, {"QD1": {"001"}, "QD2": {"002"}}, mapping)
    rows = apply_matches(mapping, artifact)
    by_id = {row["local_id"]: row for row in rows}

    assert artifact["review"][0]["auto_candidate_qids"] == ["Q1"]
    assert by_id["w-old-1"]["wikidata_qid"] == "Q1"
    assert by_id["w-old-1"]["match_status"] == "verified"
    assert by_id["w-new"]["wikidata_qid"] == "Q3"


def test_evaluation_rejects_qid_collisions(tmp_path):
    history = _history()
    history["entities"][1]["name_vi"] = "Phường Hòa Bình"
    history["entities"][1]["parent_spans"] = [{"code": "001"}]
    history_path = tmp_path / "history.json"
    candidates_path = tmp_path / "candidates.json"
    districts_path = tmp_path / "districts.csv"
    for path in (history_path, candidates_path, districts_path):
        path.write_text(path.name, encoding="utf-8")
    candidates = _candidates()
    candidates["candidates"] = candidates["candidates"][:1]
    mapping = _mapping()
    mapping[-1]["wikidata_qid"] = "Q9"
    artifact = reduce_candidates(
        history, candidates, {"QD1": {"001"}}, mapping,
        history_path=history_path, candidate_path=candidates_path,
        district_mapping_path=districts_path,
    )
    artifact["action_api_verification"]["entities"] = [
        _verified("Q1", "Hòa Bình", "QD1", "Q2389082"),
    ]

    artifact = evaluate(artifact, {"QD1": {"001"}}, mapping)

    assert {row["classification"] for row in artifact["review"]} == {
        "qid-collision"
    }
    assert not any(row["auto_candidate_qids"] for row in artifact["review"])


def test_manual_predecessor_decision_assigns_checked_unique_qid():
    mapping = _mapping()
    decisions = {"batches": [{
        "batch_id": "review-1",
        "decisions": [{
            "local_id": "w-old-1",
            "outcome": "assign",
            "wikidata_qid": "Q8",
            "candidate_qids_checked": ["Q7", "Q8"],
            "mapping_note": "distinct former commune",
        }],
    }]}

    rows = apply_review_decisions(mapping, decisions)
    row = {item["local_id"]: item for item in rows}["w-old-1"]

    assert row["wikidata_qid"] == "Q8"
    assert row["match_status"] == "manual"
    assert row["candidate_qids"] == "Q7|Q8"


def test_verification_fetches_only_qids_missing_from_saved_api_evidence(tmp_path):
    history_path = tmp_path / "history.json"
    candidates_path = tmp_path / "candidates.json"
    districts_path = tmp_path / "districts.csv"
    for path in (history_path, candidates_path, districts_path):
        path.write_text(path.name, encoding="utf-8")
    mapping = _mapping()
    artifact = reduce_candidates(
        _history(), _candidates(), {"QD1": {"001"}, "QD2": {"002"}},
        mapping, history_path=history_path, candidate_path=candidates_path,
        district_mapping_path=districts_path,
    )
    artifact["action_api_verification"] = {
        "retrieved_at": "earlier",
        "entities": [_verified("Q1", "Hòa Bình", "QD1", "Q2389082")],
    }
    requested = []

    result = verify(
        artifact, {"QD1": {"001"}, "QD2": {"002"}}, mapping,
        fetch_fn=lambda qids: requested.extend(qids) or [
            _verified("Q2", "Hòa Bình", "QD1", "Q687188")
        ],
    )

    assert requested == ["Q2"]
    assert result["action_api_verification"]["reused_candidates"] == 1
    assert result["action_api_verification"]["fetched_candidates"] == 1


def test_committed_predecessor_artifact_is_complete_and_collision_free():
    artifact = json.loads(Path(
        "data/ward-wikidata-predecessor-candidates.json"
    ).read_text(encoding="utf-8"))
    mapping = list(csv.DictReader(
        Path("mappings/wards-qid.csv").read_text(encoding="utf-8").splitlines()
    ))

    assert artifact["audit"] == {
        "predecessor_rows": 10035,
        "current_assigned_qids": 3321,
        "rows_with_current_qid_excluded": 4730,
        "rows_with_name_candidate": 8527,
        "rows_with_district_candidate": 6182,
        "shortlisted_qids": 6171,
        "api_verified_candidates": 6171,
        "rows_with_verified_candidate": 6180,
        "auto_matched_rows": 6100,
        "unresolved_rows": 3935,
        "classification_counts": {
            "ambiguous-verified-candidates": 32,
            "current-item-repurposed": 1262,
            "no-district-candidate": 2345,
            "no-name-candidate": 246,
            "qid-collision": 48,
            "verification-rejected": 2,
            "verified-unique": 6100,
        },
    }
    assert not audit(artifact, mapping)
