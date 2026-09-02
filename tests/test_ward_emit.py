import csv
import json
from pathlib import Path

import pytest

from vn_admin_units.ward_emit import (
    build_current_creation_manifest,
    build_emission_readiness,
    emit_creation_item,
    emit_ward_lineage_quickstatements,
    render_creation_statements,
)


def _entity(local_id, name, code, parent, *, valid_to=None):
    return {
        "local_id": local_id,
        "name_vi": name,
        "loai_hinh": "Xã",
        "gso_codes": [code],
        "valid_from": "2025-07-01" if valid_to is None else None,
        "valid_to": valid_to,
        "parent_spans": [{"code": parent, "name_vi": "Tỉnh Mẫu", "qid": None}],
        "creation_evidence": {
            "instrument_ids": ["999/NQ-UBTVQH15@2025-07-01"],
        },
    }


def _mapping(entity, qid="", status="reviewed-unresolved"):
    return {
        "local_id": entity["local_id"],
        "terminal_code": entity["gso_codes"][-1],
        "name_vi": entity["name_vi"],
        "loai_hinh": entity["loai_hinh"],
        "parent_code": entity["parent_spans"][-1]["code"],
        "valid_from": entity["valid_from"] or "",
        "valid_to": entity["valid_to"] or "",
        "wikidata_qid": qid,
        "qid_status": "existing" if qid else "",
        "match_status": status,
        "candidate_qids": "Q123",
        "match_notes": "reviewed",
    }


def test_current_creation_manifest_is_reviewed_referenced_and_grouped():
    first = _entity("w-00001-2025-07-01", "Xã Một", "00001", "01")
    second = _entity("w-00002-2025-07-01", "Xã Hai", "00002", "01")
    history = {"entities": [first, second], "lineage_edges": []}
    mapping = [_mapping(first), _mapping(second)]
    provinces = [{
        "gso_code": "01", "era": "post2025", "name_vi": "Tỉnh Mẫu",
        "wikidata_qid": "Q999",
    }]
    sources = {"instruments": [{
        "instrument_id": "999/NQ-UBTVQH15@2025-07-01",
        "attachments": [{"media_type": "pdf", "url": "https://example.test/999.pdf"}],
    }]}
    decisions = {"batches": [{"decisions": [
        {
            "local_id": entity["local_id"],
            "outcome": "retain-unresolved",
            "wikidata_qid": "",
            "candidate_qids_checked": ["Q123"],
            "mapping_note": "no current item",
            "rationale": "checked",
        }
        for entity in (first, second)
    ]}]}

    manifest = build_current_creation_manifest(
        history, mapping, provinces, sources, decisions, review_group_size=1,
    )

    assert manifest["audit"]["items"] == 2
    assert manifest["audit"]["statement_files"] == 1
    assert manifest["audit"]["review_groups"] == 2
    assert [row["review_group"] for row in manifest["items"]] == [1, 2]
    assert manifest["items"][0]["description_vi"] == (
        "xã thuộc tỉnh Mẫu, Việt Nam, thành lập năm 2025"
    )
    rendered = render_creation_statements(manifest)
    assert rendered.count("CREATE\n") == 2
    assert "LAST\tP31\tQ2389082" in rendered
    assert "LAST\tP131\tQ999" in rendered
    assert 'S854\t"https://example.test/999.pdf"' in rendered


def test_creation_renderer_escapes_wikidata_strings():
    item = {
        "name_vi": 'Xã "Mẫu"',
        "description_vi": "xã \\ mẫu",
        "type_qid": "Q2389082",
        "country_qid": "Q881",
        "parent_qid": "Q999",
        "valid_from": "2025-07-01",
        "reference_url": "https://example.test/ref",
    }

    rendered = emit_creation_item(item)

    assert 'LAST\tLvi\t"Xã \\"Mẫu\\""' in rendered
    assert 'LAST\tDvi\t"xã \\\\ mẫu"' in rendered


def test_lineage_emitter_fails_closed_when_any_endpoint_lacks_qid():
    old = _entity("w-old", "Xã Cũ", "90001", "001", valid_to="2025-06-30")
    new = _entity("w-new", "Xã Mới", "00001", "01")
    history = {
        "entities": [old, new],
        "lineage_edges": [{
            "predecessor": "w-old",
            "successor": "w-new",
            "relation": "merged_into",
            "effective_date": "2025-07-01",
            "reference_url": "https://example.test/ref",
        }],
    }
    mapping = [
        _mapping(old, status="deferred-historical"),
        _mapping(new, qid="Q2", status="matched"),
    ]

    readiness = build_emission_readiness(history, mapping)

    assert readiness["audit"]["reform_edges_with_both_qids"] == 0
    assert readiness["gates"]["ward_lineage_emit_ready"] is False
    with pytest.raises(ValueError, match="historical_predecessor_qids=1"):
        emit_ward_lineage_quickstatements(history, mapping)


def test_lineage_emitter_renders_complete_referenced_bidirectional_edge():
    old = _entity("w-old", "Xã Cũ", "90001", "001", valid_to="2025-06-30")
    new = _entity("w-new", "Xã Mới", "00001", "01")
    history = {
        "entities": [old, new],
        "lineage_edges": [{
            "predecessor": "w-old",
            "successor": "w-new",
            "relation": "merged_into",
            "effective_date": "2025-07-01",
            "reference_url": "https://example.test/ref",
        }],
    }
    mapping = [
        _mapping(old, qid="Q1", status="matched"),
        _mapping(new, qid="Q2", status="matched"),
    ]

    rendered = emit_ward_lineage_quickstatements(history, mapping)

    assert "Q1\tP576\t+2025-07-01T00:00:00Z/11" in rendered
    assert "Q1\tP7888\tQ2\tP585\t+2025-07-01T00:00:00Z/11" in rendered
    assert "Q1\tP1366\tQ2\tP585\t+2025-07-01T00:00:00Z/11" in rendered
    assert "Q2\tP1365\tQ1\tP585\t+2025-07-01T00:00:00Z/11" in rendered
    assert rendered.count('S854\t"https://example.test/ref"') == 4


def test_committed_graph_produces_158_creation_items_in_one_file():
    history = json.loads(Path("data/ward-history.json").read_text(encoding="utf-8"))
    mapping = list(csv.DictReader(
        Path("mappings/wards-qid.csv").read_text(encoding="utf-8").splitlines()
    ))
    provinces = list(csv.DictReader(
        Path("mappings/provinces-qid.csv").read_text(encoding="utf-8").splitlines()
    ))
    sources = json.loads(Path("data/ward-legal-sources.json").read_text(encoding="utf-8"))
    decisions = json.loads(
        Path("data/ward-wikidata-review-decisions.json").read_text(encoding="utf-8")
    )

    manifest = build_current_creation_manifest(
        history, mapping, provinces, sources, decisions,
    )
    readiness = build_emission_readiness(history, mapping)

    assert manifest["audit"] == {
        "items": 158,
        "statement_files": 1,
        "review_groups": 16,
        "type_counts": {"Phường": 25, "Xã": 133},
        "province_count": 15,
        "official_reference_urls": 15,
    }
    assert readiness["audit"]["distinct_reform_predecessors"] == 10_035
    assert readiness["audit"]["reform_edges"] == 10_586
    assert readiness["audit"]["reform_edges_with_both_qids"] == 0
