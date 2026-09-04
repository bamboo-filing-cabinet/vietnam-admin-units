import csv
import json
from pathlib import Path

from vn_admin_units import rawcache
from vn_admin_units.ward_reconcile_predecessors import ARTIFACT_PATH
from vn_admin_units.ward_reconcile_predecessors_broad import (
    CACHE_PATH,
    QUERY_PATH,
    RAW_RESULT,
    audit,
    build_review,
    evaluate,
    parse_candidates,
    render_query,
    unresolved_rows,
)


def _row():
    return {
        "local_id": "w-old",
        "terminal_code": "00001",
        "name_vi": "Phường Hòa Bình",
        "loai_hinh": "Phường",
        "parent_code": "001",
        "classification": "no-name-candidate",
        "auto_candidate_qids": [],
    }


def _base_artifact(candidates):
    return {
        "audit": {"query_terms": 4, "query_result_rows": 1, "candidate_items": len(candidates)},
        "candidates": candidates,
        "shortlisted_qids": [],
        "action_api_verification": {"entities": []},
        "review": [],
    }


def test_query_is_unrestricted_and_collects_parent_and_type_evidence():
    query = render_query([_row()])

    assert '"Hòa Bình"@vi' in query
    assert '"Hoa Binh"@en' in query
    assert "wdt:P31 ?type" in query
    assert "wdt:P131 ?parent" in query
    assert "VALUES ?type" not in query
    assert 'FILTER(REGEX(STR(?item), "/Q[1-9][0-9]*$"))' in query


def test_parse_candidates_merges_terms_types_and_parents():
    payload = {"results": {"bindings": [{
        "item": {"value": "http://www.wikidata.org/entity/Q2"},
        "matchedTerm": {"value": "Hòa Bình", "xml:lang": "vi"},
        "matchKind": {"value": "label"},
        "types": {"value": "http://www.wikidata.org/entity/Q687188"},
        "parents": {"value": "http://www.wikidata.org/entity/QD1"},
    }]}}

    assert parse_candidates(payload) == [{
        "qid": "Q2",
        "types": ["Q687188"],
        "parent_qids": [],
        "matches": [{
            "value": "Hòa Bình", "language": "vi", "kinds": ["label"],
        }],
    }]


def test_review_and_evaluation_require_exact_vi_ward_and_district_evidence():
    candidates = [{
        "qid": "Q2",
        "types": ["Q687188"],
        "parent_qids": ["Q10"],
        "matches": [{
            "value": "Hòa Bình", "language": "vi", "kinds": ["label"],
        }],
    }]
    predecessor = {"review": [_row()]}
    mapping = [{"local_id": "w-new", "valid_to": "", "wikidata_qid": "Q9"}]
    district_index = {"Q10": {"001"}}
    artifact = build_review(
        _base_artifact(candidates), predecessor, mapping, district_index,
    )
    artifact["action_api_verification"]["entities"] = [{
        "qid": "Q2",
        "missing": False,
        "labels": {"vi": "Hòa Bình"},
        "aliases": [],
        "p31": ["Q687188"],
        "p131": ["Q10"],
    }]

    result = evaluate(artifact, mapping, district_index)

    assert result["review"][0]["auto_candidate_qids"] == ["Q2"]
    assert result["review"][0]["classification"] == "verified-unique"

    committed = [
        *mapping,
        {"local_id": "w-old", "valid_to": "2025-06-30", "wikidata_qid": "Q2"},
    ]
    rebuilt = build_review(
        _base_artifact(candidates), predecessor, committed, district_index,
    )
    assert rebuilt["review"][0]["district_candidate_qids"] == ["Q2"]


def test_evaluation_prefers_the_only_viwiki_candidate():
    candidates = [
        {
            "qid": qid,
            "types": ["Q687188"],
            "parent_qids": ["Q10"],
            "matches": [{
                "value": "Hòa Bình", "language": "vi", "kinds": ["label"],
            }],
        }
        for qid in ("Q2", "Q3")
    ]
    predecessor = {"review": [_row()]}
    mapping = [{"local_id": "w-new", "valid_to": "", "wikidata_qid": "Q9"}]
    district_index = {"Q10": {"001"}}
    artifact = build_review(
        _base_artifact(candidates), predecessor, mapping, district_index,
    )
    artifact["action_api_verification"]["entities"] = [
        {
            "qid": qid,
            "missing": False,
            "labels": {"vi": "Hòa Bình"},
            "aliases": [],
            "p31": ["Q687188"],
            "p131": ["Q10"],
            "sitelinks": {"viwiki": "Hòa Bình"} if qid == "Q3" else {},
        }
        for qid in ("Q2", "Q3")
    ]

    result = evaluate(artifact, mapping, district_index)

    assert result["review"][0]["auto_candidate_qids"] == ["Q3"]


def test_committed_broad_artifact_and_query_are_reproducible():
    predecessor = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
    artifact = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    mapping = list(csv.DictReader(
        Path("mappings/wards-qid.csv").read_text(encoding="utf-8").splitlines()
    ))

    assert rawcache.raw_is_verified(RAW_RESULT)
    assert QUERY_PATH.read_text(encoding="utf-8") == render_query(
        unresolved_rows(predecessor)
    )
    assert artifact["audit"] == {
        "api_verified_candidates": 75,
        "auto_matched_rows": 54,
        "candidate_items": 10924,
        "classification_counts": {
            "ambiguous-verified-candidates": 2,
            "assigned-item-only": 840,
            "no-broad-candidate": 192,
            "no-broad-district-candidate": 2836,
            "verification-rejected": 10,
            "verified-unique": 54,
        },
        "query_result_rows": 16663,
        "query_terms": 11849,
        "rows_with_any_candidate": 2902,
        "rows_with_district_candidate": 66,
        "rows_with_verified_candidate": 56,
        "shortlisted_qids": 75,
        "unresolved_predecessor_rows": 3934,
        "unresolved_rows": 3880,
    }
    assert not audit(artifact, predecessor, mapping)
