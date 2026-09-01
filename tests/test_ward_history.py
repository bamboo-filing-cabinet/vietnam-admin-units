from collections import Counter
from datetime import date, timedelta

import pytest

from vn_admin_units.ward_history import build_ward_history


@pytest.fixture(scope="module")
def artifact():
    return build_ward_history()


def test_real_historical_graph_counts_are_locked(artifact):
    assert artifact["scope"] == {
        "tier": "ward",
        "source_floor": "2002-01-01",
        "as_of": "2026-08-27",
        "status": (
            "canonical_observation_graph_complete_with_explicit_topology_residue"
        ),
        "source_gate_status": "accepted_bounded_residue",
        "wikidata_status": "not_reconciled_or_emitted",
    }
    assert artifact["audit"] == {
        "entities": 14_544,
        "baseline_entities": 10_538,
        "current_entities": 3_321,
        "pre_reform_entities": 10_035,
        "post_reform_entities": 3_321,
        "lineage_edges": 10_603,
        "relation_counts": {
            "merged_into": 9_445,
            "replaces": 148,
            "split": 1_010,
        },
        "share_counts": {"partial": 1_010, "whole": 9_593},
        "composition_edges_2025": 10_586,
        "code_reuse_breaks": 17,
        "code_transition_overrides": 4,
        "code_transition_unmapped_predecessors": 1,
        "transition_additions": 214,
        "predecessorless_historical_additions": 454,
        "successorless_historical_removals": 1_153,
        "source_anomaly_codes_at_floor": 1,
        "dangling_edges": 0,
        "duplicate_edges": 0,
        "self_edges": 0,
    }


def test_entity_ids_and_spans_are_consistent(artifact):
    entities = artifact["entities"]
    assert len({entity["local_id"] for entity in entities}) == len(entities)

    for entity in entities:
        if entity["valid_from"] and entity["valid_to"]:
            assert entity["valid_from"] <= entity["valid_to"]
        for spans in (
            entity["name_spans"],
            entity["type_spans"],
            entity["parent_spans"],
            entity["province_echo_spans"],
        ):
            assert spans[0]["from"] == entity["valid_from"]
            assert spans[-1]["to"] == entity["valid_to"]
            for previous, following in zip(spans, spans[1:]):
                assert previous["to"] is not None
                expected = date.fromisoformat(previous["to"]) + timedelta(days=1)
                assert following["from"] == expected.isoformat()


def test_lineage_endpoints_dates_and_topology_are_consistent(artifact):
    entities = {entity["local_id"]: entity for entity in artifact["entities"]}
    edges = artifact["lineage_edges"]
    keys = [
        (edge["predecessor"], edge["successor"], edge["effective_date"])
        for edge in edges
    ]
    assert len(keys) == len(set(keys))
    assert all(edge["predecessor"] != edge["successor"] for edge in edges)
    for edge in edges:
        expected_end = date.fromisoformat(edge["effective_date"]) - timedelta(days=1)
        assert entities[edge["predecessor"]]["valid_to"] == expected_end.isoformat()
        assert edge["share"] in {"whole", "partial"}
        if edge["share"] == "partial":
            assert edge["relation"] == "split"

    reform_edges = [
        edge for edge in edges if edge["effective_date"] == "2025-07-01"
    ]
    assert len(reform_edges) == 10_586
    assert Counter(edge["share"] for edge in reform_edges) == {
        "whole": 9_576,
        "partial": 1_010,
    }
    assert all(
        edge["provenance"]["event_id"] == "soap:2025-06-30->2025-07-01"
        and edge["provenance"]["composition_evidence"]
        for edge in reform_edges
    )


def test_code_transition_and_reuse_do_not_collapse_entities(artifact):
    entities = {entity["local_id"]: entity for entity in artifact["entities"]}

    ngan_chien = entities["w-2011711-base"]
    assert ngan_chien["gso_codes"] == ["2011711", "01117"]
    assert ngan_chien["valid_to"] == "2019-12-31"
    reused = entities["w-01117-2020-01-01"]
    assert reused["gso_codes"] == ["01117"]
    assert reused["valid_from"] == "2020-01-01"

    quang_truong = entities["w-4070733-base"]
    assert quang_truong["gso_codes"] == ["4070733", "19054"]
    assert artifact["residue"]["transition_unmapped_predecessors"][0][
        "entity_id"
    ] == "w-2011715-base"


def test_current_parent_tier_and_source_residue_policy_are_preserved(artifact):
    current = [
        entity for entity in artifact["entities"] if entity["valid_to"] is None
    ]
    assert len(current) == 3_321
    assert all(entity["parent_spans"][-1]["tier"] == "province" for entity in current)
    assert all(entity["parent_spans"][-1]["code"] for entity in current)

    provenance = artifact["provenance"]
    assert len(provenance["accepted_source_residue_instrument_ids"]) == 29
    instruments = {
        item["instrument_id"]: item for item in provenance["legal_instruments"]
    }
    for instrument_id in provenance["accepted_source_residue_instrument_ids"]:
        assert instruments[instrument_id]["source_status"] in {
            "missing", "secondary_only",
        }
        assert instruments[instrument_id]["primary_sources"] == []
