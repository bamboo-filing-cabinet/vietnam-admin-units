import hashlib
import json

from vn_admin_units import rawcache
from vn_admin_units.ward_reconcile import (
    CANDIDATE_CACHE,
    build_parent_qid_index,
    serialize_json,
)
from vn_admin_units.ward_reconcile_broad import (
    CACHE_PATH,
    QUERY_PATH,
    RAW_RESULT,
    _base_mapping_rows,
    audit,
    evaluate,
    parse_candidates,
    query_terms,
    render_query,
)


def _mapping_row(status="needs-lookup"):
    return {
        "local_id": "w-1-2025-07-01",
        "name_vi": "Phường Hòa Bình",
        "loai_hinh": "Phường",
        "parent_code": "75",
        "valid_to": "",
        "match_status": status,
    }


def test_query_terms_include_tierless_vietnamese_and_ascii_forms():
    assert query_terms("Phường Hòa Bình") == {
        ("Phường Hòa Bình", "vi"),
        ("Hòa Bình", "vi"),
        ("Hoa Binh", "vi"),
        ("Hoa Binh", "en"),
    }


def test_render_query_is_broad_and_limited_to_unresolved_names():
    query = render_query([
        _mapping_row(),
        {**_mapping_row("matched"), "name_vi": "Xã Không Đưa Vào"},
    ])

    assert '"Hòa Bình"@vi' in query
    assert '"Hoa Binh"@en' in query
    assert "Không Đưa Vào" not in query
    assert "wdt:P31" not in query
    assert "SERVICE wikibase:label" not in query
    assert query.count("VALUES ?matchedTerm") == 2


def test_parse_candidates_compacts_item_term_and_match_kind():
    payload = {"results": {"bindings": [
        {
            "item": {
                "type": "uri",
                "value": "http://www.wikidata.org/entity/Q20",
            },
            "matchedTerm": {
                "type": "literal",
                "value": "Hòa Bình",
                "xml:lang": "vi",
            },
            "matchKind": {"type": "literal", "value": "label"},
        },
        {
            "item": {
                "type": "uri",
                "value": "http://www.wikidata.org/entity/Q20",
            },
            "matchedTerm": {
                "type": "literal",
                "value": "Hòa Bình",
                "xml:lang": "vi",
            },
            "matchKind": {"type": "literal", "value": "alias"},
        },
    ]}}

    assert parse_candidates(payload) == [{
        "qid": "Q20",
        "matches": [{
            "value": "Hòa Bình",
            "language": "vi",
            "kinds": ["alias", "label"],
        }],
    }]


def test_evaluate_separates_new_nonward_current_province_candidate():
    artifact = {
        "audit": {},
        "candidates": [{
            "qid": "Q2",
            "matches": [{
                "value": "Hòa Bình",
                "language": "vi",
                "kinds": ["label"],
            }],
        }],
        "action_api_verification": {
            "entities": [{
                "qid": "Q2",
                "missing": False,
                "p31": ["Q999"],
                "p131": ["Q900"],
            }],
        },
    }
    primary = {"candidates": [{"qid": "Q1"}]}

    result = evaluate(artifact, [_mapping_row()], primary, {"Q900": {"75"}})

    assert result["review"] == [{
        "local_id": "w-1-2025-07-01",
        "name_vi": "Phường Hòa Bình",
        "loai_hinh": "Phường",
        "parent_code": "75",
        "prior_status": "needs-lookup",
        "classification": "current-province-nonward-candidate",
        "candidate_qids": ["Q2"],
        "new_candidate_qids": ["Q2"],
        "current_province_qids": ["Q2"],
        "current_province_ward_qids": [],
        "current_province_nonward_qids": ["Q2"],
        "exact_active_ward_qids": [],
        "auto_candidate_qids": [],
    }]


def test_evaluate_uses_exact_current_tier_to_break_broad_ambiguity():
    matches = [{
        "value": "Hòa Bình",
        "language": "vi",
        "kinds": ["label"],
    }]
    artifact = {
        "audit": {},
        "candidates": [
            {"qid": "Q1", "matches": matches},
            {"qid": "Q2", "matches": matches},
        ],
        "action_api_verification": {"entities": [
            {
                "qid": "Q1", "missing": False, "p31": ["Q2389082"],
                "p131": ["Q900"], "p576": [],
            },
            {
                "qid": "Q2", "missing": False, "p31": ["Q687188"],
                "p131": ["Q900"], "p576": [],
            },
        ]},
    }

    result = evaluate(artifact, [_mapping_row()], {"candidates": []}, {
        "Q900": {"75"},
    })

    assert result["review"][0]["exact_active_ward_qids"] == ["Q1", "Q2"]
    assert result["review"][0]["auto_candidate_qids"] == ["Q2"]


def test_saved_broad_query_result_and_cache_are_reproducible():
    assert rawcache.raw_is_verified(RAW_RESULT)
    primary = json.loads(CANDIDATE_CACHE.read_text(encoding="utf-8"))
    parent_index = build_parent_qid_index()
    rows = _base_mapping_rows(primary, parent_index)
    artifact = json.loads(CACHE_PATH.read_text(encoding="utf-8"))

    assert QUERY_PATH.read_text(encoding="utf-8") == render_query(rows)
    assert artifact["source"]["query_sha256"] == hashlib.sha256(
        QUERY_PATH.read_bytes()
    ).hexdigest()
    assert artifact["audit"] == {
        "api_verified_candidates": 3319,
        "candidate_items": 3319,
        "classification_counts": {
            "current-province-nonward-candidate": 212,
            "current-province-ward-candidate": 168,
            "name-candidate-other-or-missing-parent": 321,
            "no-broad-name-candidate": 111,
        },
        "query_result_rows": 4964,
        "query_terms": 2948,
        "review_rows": 812,
        "rows_with_any_candidate": 701,
        "rows_with_current_province_candidate": 380,
        "rows_with_current_province_nonward_candidate": 212,
        "rows_with_new_candidate": 631,
        "rows_with_one_auto_candidate": 162,
        "unresolved_current_rows": 812,
    }
    assert not audit(artifact, rows)
    rebuilt = evaluate(artifact, rows, primary, parent_index)
    assert CACHE_PATH.read_text(encoding="utf-8") == serialize_json(rebuilt)
