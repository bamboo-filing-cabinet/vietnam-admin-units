import json
from pathlib import Path

from vn_admin_units.ward_audit_predecessor_gaps import (
    DECISIONS_PATH,
    EVIDENCE_PATH,
    audit_decisions,
    search_terms,
    select_sample,
)


def test_sample_is_deterministic_unique_and_order_independent():
    items = [{"local_id": f"w-{number}"} for number in range(20)]

    first = select_sample(items, "fixed-seed", 7)
    second = select_sample(list(reversed(items)), "fixed-seed", 7)

    assert first == second
    assert len({row["local_id"] for row in first}) == 7


def test_search_terms_include_full_short_and_parent_context():
    item = {
        "name_vi": "Xã Mỹ Tân",
        "parent_name_vi": "Thành phố Nam Định",
    }

    assert search_terms(item) == [
        "Xã Mỹ Tân", "Mỹ Tân", "Mỹ Tân Nam Định",
    ]


def test_decisions_must_cover_the_exact_saved_sample():
    evidence = {
        "sampling": {"sample_size": 2},
        "rows": [
            {
                "sample_number": 1,
                "local_id": "w-1",
                "wikidata_candidates": [{"qid": "Q1"}],
            },
            {
                "sample_number": 2,
                "local_id": "w-2",
                "wikidata_candidates": [],
            },
        ],
    }
    decisions = {
        "audit": {
            "reviewed_rows": 2,
            "existing_predecessor_items": 1,
            "current_mapping_swaps": 0,
            "no_distinct_item_found": 1,
            "sample_miss_rate": 0.5,
            "creation_batch_authorized": False,
        },
        "batches": [{"decisions": [
            {
                "sample_number": 1,
                "local_id": "w-1",
                "outcome": "existing-predecessor-item",
                "wikidata_qid": "Q1",
            },
            {
                "sample_number": 2,
                "local_id": "w-2",
                "outcome": "no-distinct-item-found",
            },
        ]}],
    }

    assert not audit_decisions(evidence, decisions)


def test_committed_random_audit_records_all_five_batches():
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    decisions = json.loads(DECISIONS_PATH.read_text(encoding="utf-8"))

    assert evidence["sampling"] == {
        "method": "lowest SHA-256(seed + NUL + local_id)",
        "seed": "2026-09-04-predecessor-gap-audit-v1",
        "population": 3879,
        "sample_size": 50,
        "batch_size": 10,
        "batches": 5,
    }
    assert [len(batch["decisions"]) for batch in decisions["batches"]] == [
        10, 10, 10, 10, 10,
    ]
    assert decisions["audit"]["existing_predecessor_items"] == 14
    assert decisions["audit"]["creation_batch_authorized"] is False
    assert not audit_decisions(evidence, decisions)

    selected = {
        row["local_id"]: row.get("wikidata_qid", "")
        for batch in decisions["batches"]
        for row in batch["decisions"]
        if row["outcome"].startswith("existing-predecessor-item")
    }
    assert selected["w-4012321-base"] == "Q10787225"
    assert Path("statements/na-wards-create-predecessors.qs").is_file()
