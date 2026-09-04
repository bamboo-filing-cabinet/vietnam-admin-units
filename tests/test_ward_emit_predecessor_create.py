import json
from datetime import datetime, timezone
from pathlib import Path

from vn_admin_units.ward_emit_predecessor_create import (
    MANIFEST_PATH,
    PREFLIGHT_PATH,
    STATEMENTS_PATH,
    build_manifest,
    build_preflight,
    render_statements,
)


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


def test_committed_predecessor_creation_package_is_complete_and_unique():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    preflight = json.loads(PREFLIGHT_PATH.read_text(encoding="utf-8"))
    statements = STATEMENTS_PATH.read_text(encoding="utf-8")

    assert manifest["audit"]["items"] == 3879
    assert manifest["audit"]["type_counts"] == {
        "Phường": 738, "Thị trấn": 408, "Xã": 2733,
    }
    assert len({
        (row["name_vi"], row["parent_qid"], row["type_qid"])
        for row in manifest["items"]
    }) == 3879
    assert preflight["audit"] == {
        "items": 3879,
        "clear_items": 3879,
        "needs_review_items": 0,
        "fresh": True,
        "upload_ready": True,
    }
    assert statements.count("CREATE\n") == 3879
    assert "\tP576\t" not in statements
