import csv
import json
from pathlib import Path

from vn_admin_units.ward_reconcile_predecessors_article import (
    ARTIFACT_PATH,
    audit,
    build_review,
    evaluate,
)


def _history(successor_name="Xã Mới"):
    return {
        "entities": [
            {"local_id": "w-old", "name_vi": "Xã Hòa Bình"},
            {"local_id": "w-new", "name_vi": successor_name},
        ],
        "lineage_edges": [{
            "predecessor": "w-old",
            "successor": "w-new",
            "effective_date": "2025-07-01",
        }],
    }


def _candidates(*qids):
    return {"candidates": [
        {"qid": qid, "types": ["Q2389082"]} for qid in qids
    ]}


def _primary(*qids):
    return {"review": [{
        "local_id": "w-old",
        "terminal_code": "00001",
        "name_vi": "Xã Hòa Bình",
        "loai_hinh": "Xã",
        "parent_code": "001",
        "parent_codes": ["000", "001"],
        "classification": "no-district-candidate",
        "candidate_qids": list(qids),
        "auto_candidate_qids": [],
    }]}


def _broad():
    return {"review": [{"local_id": "w-old", "auto_candidate_qids": []}]}


def _mapping():
    return [
        {"local_id": "w-old", "valid_to": "2025-06-30", "wikidata_qid": ""},
        {"local_id": "w-new", "valid_to": "", "wikidata_qid": "Q9"},
    ]


def _verified(qid, *, title="Hòa Bình"):
    return {
        "qid": qid,
        "missing": False,
        "labels": {"vi": "Hòa Bình"},
        "aliases": [],
        "p31": ["Q2389082"],
        "sitelinks": {"viwiki": title} if title else {},
    }


def test_unique_matching_article_recovers_a_different_name_predecessor():
    artifact = build_review(
        _history(), _candidates("Q1"), _primary("Q1"), _broad(), _mapping(),
    )
    artifact["action_api_verification"]["entities"] = [_verified("Q1")]

    row = evaluate(artifact, _mapping())["review"][0]

    assert row["article_candidate_qids"] == ["Q1"]
    assert row["auto_candidate_qids"] == ["Q1"]
    assert row["classification"] == "verified-unique"


def test_same_name_successor_blocks_article_only_assignment():
    artifact = build_review(
        _history("Xã Hòa Bình"), _candidates("Q1"), _primary("Q1"),
        _broad(), _mapping(),
    )
    artifact["action_api_verification"]["entities"] = [_verified("Q1")]

    row = evaluate(artifact, _mapping())["review"][0]

    assert row["same_name_successor"] is True
    assert row["auto_candidate_qids"] == []
    assert row["classification"] == "same-name-successor-risk"


def test_multiple_matching_articles_remain_ambiguous():
    artifact = build_review(
        _history(), _candidates("Q1", "Q2"), _primary("Q1", "Q2"),
        _broad(), _mapping(),
    )
    artifact["action_api_verification"]["entities"] = [
        _verified("Q1"), _verified("Q2", title="Hòa Bình, huyện cũ"),
    ]

    row = evaluate(artifact, _mapping())["review"][0]

    assert row["article_candidate_qids"] == ["Q1", "Q2"]
    assert row["auto_candidate_qids"] == []
    assert row["classification"] == "ambiguous-viwiki-articles"


def test_committed_article_artifact_is_complete_and_collision_free():
    if not ARTIFACT_PATH.is_file():
        return
    artifact = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
    mapping = list(csv.DictReader(
        Path("mappings/wards-qid.csv").read_text(encoding="utf-8").splitlines()
    ))

    assert artifact["audit"]["unresolved_input_rows"] > 0
    assert not audit(artifact, mapping)
