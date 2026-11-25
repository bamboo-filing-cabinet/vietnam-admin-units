import json
from datetime import datetime, timezone
from pathlib import Path

from vn_admin_units.ward_emit_predecessor_create import (
    MANIFEST_PATH,
    PREFLIGHT_PATH,
    REVIEW_PROGRESS_PATH,
    STATEMENTS_PATH,
    build_manifest,
    build_preflight,
    render_statements,
)


def _same_name_district_fixture():
    """Two wards whose districts share a name but sit in different provinces."""
    def ward(local_id, code, name, district_code):
        return {
            "local_id": local_id, "gso_codes": [code], "name_vi": name,
            "loai_hinh": "Thị trấn", "valid_from": None, "valid_to": "2025-06-30",
            "parent_spans": [{"code": district_code, "name_vi": "Huyện Châu Thành"}],
            # the echo carries the 2025 successor province code for both wards
            "province_echo_spans": [{"code": "80"}],
        }
    old_a = ward("w-a", "90001", "Thị trấn Châu Thành", "708")
    old_b = ward("w-b", "90002", "Thị trấn Châu Thành", "808")
    new = {
        "local_id": "w-new", "gso_codes": ["00001"], "name_vi": "Xã Mới",
        "loai_hinh": "Xã", "valid_from": "2025-07-01", "valid_to": None,
        "parent_spans": [{"code": "80"}], "province_echo_spans": [{"code": "80"}],
    }
    history = {
        "entities": [old_a, old_b, new],
        "lineage_edges": [
            {"predecessor": "w-a", "successor": "w-new",
             "effective_date": "2025-07-01",
             "reference_url": "https://example.test/resolution.pdf"},
            {"predecessor": "w-b", "successor": "w-new",
             "effective_date": "2025-07-01",
             "reference_url": "https://example.test/resolution.pdf"},
        ],
    }
    mapping = [
        {"local_id": "w-a", "terminal_code": "90001", "wikidata_qid": ""},
        {"local_id": "w-b", "terminal_code": "90002", "wikidata_qid": ""},
        {"local_id": "w-new", "terminal_code": "00001", "wikidata_qid": "Q2"},
    ]
    districts = [
        {"local_id": "d-708", "terminal_code": "708", "name_vi": "Huyện Châu Thành",
         "parent_code": "72", "wikidata_qid": "Q72"},
        {"local_id": "d-808", "terminal_code": "808", "name_vi": "Huyện Châu Thành",
         "parent_code": "80", "wikidata_qid": "Q80"},
    ]
    review = lambda key: {"review": [
        {"local_id": "w-a", "classification": "assigned-item-only",
         "candidate_qids": [], key: []},
        {"local_id": "w-b", "classification": "assigned-item-only",
         "candidate_qids": [], key: []},
    ]}
    return history, mapping, districts, review("current_qids_excluded"), review("assigned_qids_excluded")


def test_manifest_normalises_an_odd_tier_prefix_in_the_label():
    old = {
        "local_id": "w-old", "gso_codes": ["90001"],
        # a few source names carry the tier in an odd case
        "name_vi": "Thị Trấn Óc Eo", "loai_hinh": "Thị trấn",
        "valid_from": None, "valid_to": "2025-06-30",
        "parent_spans": [{"code": "447", "name_vi": "Huyện Kỳ Anh"}],
        "province_echo_spans": [{"code": "42"}],
    }
    new = {
        "local_id": "w-new", "gso_codes": ["00001"], "name_vi": "Xã Mới",
        "loai_hinh": "Xã", "valid_from": "2025-07-01", "valid_to": None,
        "parent_spans": [{"code": "42"}], "province_echo_spans": [{"code": "42"}],
    }
    history = {
        "entities": [old, new],
        "lineage_edges": [{
            "predecessor": "w-old", "successor": "w-new",
            "effective_date": "2025-07-01",
            "reference_url": "https://example.test/resolution.pdf",
        }],
    }
    mapping = [
        {"local_id": "w-old", "terminal_code": "90001", "wikidata_qid": ""},
        {"local_id": "w-new", "terminal_code": "00001", "wikidata_qid": "Q2"},
    ]
    districts = [{
        "local_id": "d-447", "terminal_code": "447", "name_vi": "Huyện Kỳ Anh",
        "parent_code": "42", "wikidata_qid": "Q1",
    }]
    primary = {"review": [{"local_id": "w-old", "classification": "assigned-item-only",
                           "candidate_qids": [], "current_qids_excluded": []}]}
    broad = {"review": [{"local_id": "w-old", "classification": "assigned-item-only",
                         "candidate_qids": [], "assigned_qids_excluded": []}]}

    manifest = build_manifest(history, mapping, districts, primary, broad)

    assert manifest["items"][0]["name_vi"] == "Óc Eo"
    assert manifest["items"][0]["description_vi"].startswith("thị trấn cũ thuộc ")
    assert manifest["items"][0]["description_en"].startswith("former township in ")


def test_manifest_prefers_the_ward_district_code_over_a_same_named_district():
    history, mapping, districts, primary, broad = _same_name_district_fixture()
    provinces = [
        {"gso_code": "72", "era": "pre2025", "name_vi": "Tỉnh Tây Ninh"},
        {"gso_code": "80", "era": "pre2025", "name_vi": "Tỉnh Long An"},
    ]

    manifest = build_manifest(
        history, mapping, districts, primary, broad, province_rows=provinces,
    )
    by_id = {row["local_id"]: row for row in manifest["items"]}

    # the province echo names 80 for both wards; the district code must win
    assert by_id["w-a"]["parent_qid"] == "Q72"
    assert by_id["w-b"]["parent_qid"] == "Q80"


def test_manifest_disambiguates_descriptions_for_a_repeated_district_name():
    history, mapping, districts, primary, broad = _same_name_district_fixture()
    provinces = [
        {"gso_code": "72", "era": "pre2025", "name_vi": "Tỉnh Tây Ninh"},
        {"gso_code": "80", "era": "pre2025", "name_vi": "Tỉnh Long An"},
    ]

    manifest = build_manifest(
        history, mapping, districts, primary, broad, province_rows=provinces,
    )
    by_id = {row["local_id"]: row for row in manifest["items"]}

    # Wikidata forbids two items sharing a label and a description
    assert by_id["w-a"]["description_vi"] != by_id["w-b"]["description_vi"]
    assert "tỉnh Tây Ninh" in by_id["w-a"]["description_vi"]
    assert "tỉnh Long An" in by_id["w-b"]["description_vi"]
    assert by_id["w-a"]["description_en"] != by_id["w-b"]["description_en"]
    assert "Tây Ninh province" in by_id["w-a"]["description_en"]
    assert "Long An province" in by_id["w-b"]["description_en"]


def test_manifest_refuses_to_emit_a_repeated_label_and_description():
    history, mapping, districts, primary, broad = _same_name_district_fixture()

    try:
        build_manifest(history, mapping, districts, primary, broad)
    except ValueError as error:
        assert "province name to disambiguate" in str(error)
    else:
        raise AssertionError("expected a ValueError without province rows")


def test_manifest_resolves_district_by_name_and_emits_referenced_base_item():
    old = {
        "local_id": "w-old",
        "gso_codes": ["90001"],
        "name_vi": "Xã Cũ",
        "loai_hinh": "Xã",
        "valid_from": None,
        "valid_to": "2025-06-30",
        "parent_spans": [{"code": "449", "name_vi": "Thị xã Kỳ Anh"}],
        "province_echo_spans": [{"code": "42"}],
    }
    new = {
        "local_id": "w-new",
        "gso_codes": ["00001"],
        "name_vi": "Xã Mới",
        "loai_hinh": "Xã",
        "valid_from": "2025-07-01",
        "valid_to": None,
        "parent_spans": [{"code": "42"}],
        "province_echo_spans": [{"code": "42"}],
    }
    history = {
        "entities": [old, new],
        "lineage_edges": [{
            "predecessor": "w-old",
            "successor": "w-new",
            "effective_date": "2025-07-01",
            "reference_url": "https://example.test/resolution.pdf",
        }],
    }
    mapping = [
        {"local_id": "w-old", "terminal_code": "90001", "wikidata_qid": ""},
        {"local_id": "w-new", "terminal_code": "00001", "wikidata_qid": "Q2"},
    ]
    districts = [{
        "local_id": "d-town", "terminal_code": "447",
        "name_vi": "Thị xã Kỳ Anh", "parent_code": "42",
        "wikidata_qid": "Q1",
    }]
    primary = {"review": [{
        "local_id": "w-old", "classification": "current-item-repurposed",
        "candidate_qids": [], "current_qids_excluded": ["Q9"],
    }]}
    broad = {"review": [{
        "local_id": "w-old", "classification": "assigned-item-only",
        "candidate_qids": [], "assigned_qids_excluded": ["Q9"],
    }]}

    manifest = build_manifest(history, mapping, districts, primary, broad)
    rendered = render_statements(manifest)

    assert manifest["audit"]["items"] == 1
    assert manifest["items"][0]["parent_code"] == "449"
    assert manifest["items"][0]["parent_qid"] == "Q1"
    assert manifest["items"][0]["current_or_assigned_qids_excluded"] == ["Q9"]
    assert "CREATE\n" in rendered
    assert "LAST\tLen\t" in rendered
    assert "LAST\tDen\t" in rendered
    assert "LAST\tP131\tQ1" in rendered
    assert 'S854\t"https://example.test/resolution.pdf"' in rendered
    assert "\tP576\t" not in rendered


def test_preflight_requires_safe_classification_and_fresh_live_evidence():
    manifest = {"items": [{
        "local_id": "w-old", "name_vi": "Xã Cũ", "parent_qid": "Q1",
    }]}
    broad = {
        "source": {"retrieved_at": "2026-09-04T12:00:00Z"},
        "action_api_verification": {"retrieved_at": "2026-09-04T12:01:00Z"},
        "review": [{
            "local_id": "w-old", "classification": "no-broad-district-candidate",
        }],
    }

    status = build_preflight(
        manifest, broad, max_age_hours=24,
        now=datetime(2026, 9, 4, 13, tzinfo=timezone.utc),
    )
    stale = build_preflight(
        manifest, broad, max_age_hours=0.5,
        now=datetime(2026, 9, 4, 13, tzinfo=timezone.utc),
    )

    assert status["audit"]["upload_ready"] is True
    assert stale["audit"]["upload_ready"] is False
    assert stale["issues"][0].startswith("STALE-PREFLIGHT")


def test_preflight_blocks_until_exhaustive_review_is_complete():
    manifest = {"items": [{
        "local_id": "w-old", "name_vi": "Xã Cũ", "parent_qid": "Q1",
    }]}
    broad = {
        "source": {"retrieved_at": "2026-09-04T12:00:00Z"},
        "action_api_verification": {"retrieved_at": "2026-09-04T12:01:00Z"},
        "review": [{
            "local_id": "w-old", "classification": "no-broad-district-candidate",
        }],
    }
    pending = {"audit": {
        "queued_rows": 2,
        "reviewed_queue_rows": 1,
        "pending_queue_rows": 1,
        "unreviewed_current_rows": 1,
        "review_complete": False,
        "creation_batch_authorized": False,
    }}

    status = build_preflight(
        manifest,
        broad,
        review_progress=pending,
        now=datetime(2026, 9, 4, 13, tzinfo=timezone.utc),
    )

    assert status["audit"]["reviewed_queue_rows"] == 1
    assert status["audit"]["pending_queue_rows"] == 1
    assert status["audit"]["review_creation_authorized"] is False
    assert status["audit"]["upload_ready"] is False
    assert status["issues"] == [
        "EXHAUSTIVE-REVIEW-INCOMPLETE 1/2 queue rows pending; "
        "1 current rows unreviewed",
    ]


def test_committed_predecessor_creation_package_is_complete_and_unique():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    preflight = json.loads(PREFLIGHT_PATH.read_text(encoding="utf-8"))
    statements = STATEMENTS_PATH.read_text(encoding="utf-8")

    assert REVIEW_PROGRESS_PATH == Path(
        "data/ward-wikidata-predecessor-gap-review-progress.json"
    )
    assert REVIEW_PROGRESS_PATH.as_posix() in preflight["input_fingerprints"]
    assert manifest["audit"]["items"] == 748
    assert manifest["audit"]["type_counts"] == {
        "Phường": 74, "Thị trấn": 117, "Xã": 557,
    }
    assert len({
        (row["name_vi"], row["parent_qid"], row["type_qid"])
        for row in manifest["items"]
    }) == 748
    assert preflight["audit"] == {
        "items": 748,
        "clear_items": 748,
        "needs_review_items": 0,
        "fresh": True,
        "reviewed_queue_rows": 1394,
        "pending_queue_rows": 0,
        "unreviewed_current_rows": 0,
        "review_complete": True,
        "review_creation_authorized": True,
        "upload_ready": True,
    }
    assert preflight["issues"] == []
    assert statements.count("CREATE\n") == 748
    assert "\tP576\t" not in statements
