import json

from vn_admin_units import ward_review_predecessor_gaps as review_module
from vn_admin_units.ward_review_predecessor_gaps import (
    audit_batch_evidence,
    build_batch_evidence,
    build_review_progress,
    build_review_queue,
    main,
)


def _decisions(*rows):
    return {"batches": [{"batch_number": 1, "decisions": list(rows)}]}


def test_review_queue_contains_each_never_reviewed_row_once():
    manifest = {
        "items": [
            {"local_id": "w-1"},
            {"local_id": "w-2"},
            {"local_id": "w-3"},
            {"local_id": "w-4"},
            {"local_id": "w-5"},
        ],
    }
    prior = [_decisions(
        {"local_id": "w-1", "outcome": "no-distinct-item-found"},
        {"local_id": "w-3", "outcome": "existing-predecessor-item"},
    )]

    queue = build_review_queue(
        manifest,
        prior,
        seed="fixed-exhaustive-seed",
        batch_size=2,
        first_round=53,
    )
    reversed_queue = build_review_queue(
        {"items": list(reversed(manifest["items"]))},
        prior,
        seed="fixed-exhaustive-seed",
        batch_size=2,
        first_round=53,
    )

    assert queue == reversed_queue
    assert queue["audit"] == {
        "baseline_population": 5,
        "previously_reviewed_rows": 2,
        "queued_rows": 3,
        "batch_size": 2,
        "batches": 2,
        "first_round": 53,
        "last_round": 54,
    }
    assert [batch["round"] for batch in queue["batches"]] == [53, 54]
    assert [len(batch["items"]) for batch in queue["batches"]] == [2, 1]
    queued_ids = [
        item["local_id"]
        for batch in queue["batches"]
        for item in batch["items"]
    ]
    assert set(queued_ids) == {"w-2", "w-4", "w-5"}
    assert len(queued_ids) == len(set(queued_ids))


def test_review_progress_requires_queue_and_current_manifest_coverage():
    manifest = {"items": [
        {"local_id": "w-1"},
        {"local_id": "w-2"},
        {"local_id": "w-3"},
    ]}
    queue = {
        "audit": {"queued_rows": 2},
        "batches": [{
            "round": 53,
            "items": [{"local_id": "w-2"}, {"local_id": "w-3"}],
        }],
    }
    baseline = _decisions(
        {"local_id": "w-1", "outcome": "no-distinct-item-found"},
    )
    first_batch = _decisions(
        {"local_id": "w-2", "outcome": "no-distinct-item-found"},
    )

    pending = build_review_progress(
        manifest, queue, [baseline, first_batch],
    )

    assert pending["audit"] == {
        "queued_rows": 2,
        "reviewed_queue_rows": 1,
        "pending_queue_rows": 1,
        "current_manifest_rows": 3,
        "reviewed_current_rows": 2,
        "unreviewed_current_rows": 1,
        "unapplied_existing_rows": 0,
        "review_complete": False,
        "creation_batch_authorized": False,
    }
    assert pending["pending_local_ids"] == ["w-3"]

    final_batch = _decisions(
        {
            "local_id": "w-3",
            "outcome": "existing-predecessor-item",
            "wikidata_qid": "Q3",
        },
    )
    unapplied = build_review_progress(
        manifest, queue, [baseline, first_batch, final_batch],
    )

    assert unapplied["audit"]["pending_queue_rows"] == 0
    assert unapplied["audit"]["unreviewed_current_rows"] == 1
    assert unapplied["audit"]["unapplied_existing_rows"] == 1
    assert unapplied["audit"]["creation_batch_authorized"] is False

    corrected = build_review_progress(
        {"items": manifest["items"][:2]},
        queue,
        [baseline, first_batch, final_batch],
    )

    assert corrected["audit"] == {
        "queued_rows": 2,
        "reviewed_queue_rows": 2,
        "pending_queue_rows": 0,
        "current_manifest_rows": 2,
        "reviewed_current_rows": 2,
        "unreviewed_current_rows": 0,
        "unapplied_existing_rows": 0,
        "review_complete": True,
        "creation_batch_authorized": True,
    }
    assert corrected["pending_local_ids"] == []


def test_review_progress_uses_the_latest_superseding_decision():
    manifest = {"items": [{"local_id": "w-1"}]}
    queue = {"audit": {"queued_rows": 0}, "batches": []}
    incorrect = _decisions({
        "local_id": "w-1",
        "outcome": "existing-predecessor-item",
        "wikidata_qid": "Q1",
    })
    correction = _decisions({
        "local_id": "w-1",
        "outcome": "no-distinct-item-found",
        "supersedes": "incorrect earlier same-name/different-district decision",
    })

    progress = build_review_progress(
        manifest, queue, [incorrect, correction],
    )

    assert progress["audit"]["reviewed_current_rows"] == 1
    assert progress["audit"]["unreviewed_current_rows"] == 0
    assert progress["audit"]["unapplied_existing_rows"] == 0
    assert progress["audit"]["creation_batch_authorized"] is True


def test_batch_evidence_covers_the_exact_frozen_round():
    items = [
        {
            "local_id": f"w-{number}",
            "name_vi": f"Xã {number}",
            "parent_name_vi": "Huyện Mẫu",
            "parent_qid": "Q10",
            "loai_hinh": "Xã",
            "gso_code": f"0000{number}",
            "valid_from": None,
            "valid_to": "2025-06-30",
            "successor_qids": [],
            "broad_classification": "no-broad-candidate",
            "candidate_qids_checked": [],
        }
        for number in (2, 4)
    ]
    queue = {
        "seed": "frozen-seed",
        "audit": {
            "baseline_population": 5,
            "queued_rows": 3,
        },
        "batches": [{"round": 53, "items": items}],
    }

    evidence = build_batch_evidence(
        queue,
        53,
        [],
        wikidata_search_fn=lambda item: [],
        viwiki_search_fn=lambda item: [],
        entity_fetch_fn=lambda qids: [],
    )

    assert evidence["scope"]["purpose"] == (
        "exhaustive manual review of previously unreviewed predecessor gaps"
    )
    assert evidence["sampling"] == {
        "method": "frozen exhaustive review queue batch",
        "seed": "frozen-seed-v53",
        "population": 5,
        "eligible_population": 3,
        "review_round": 53,
        "sample_size": 2,
        "batch_size": 10,
        "batches": 1,
    }
    assert {row["local_id"] for row in evidence["rows"]} == {"w-2", "w-4"}
    assert audit_batch_evidence(evidence, queue, [], 53) == []

    evidence["rows"][0]["local_id"] = "w-wrong"
    assert audit_batch_evidence(evidence, queue, [], 53) == [
        "QUEUE-BATCH-DRIFT",
    ]


def test_cli_initializes_frozen_queue_and_progress(tmp_path, monkeypatch):
    manifest_path = tmp_path / "manifest.json"
    queue_path = tmp_path / "queue.json"
    progress_path = tmp_path / "progress.json"
    decisions_path = tmp_path / "ward-wikidata-predecessor-gap-sample-decisions.json"
    manifest_path.write_text(json.dumps({"items": [
        {"local_id": "w-1"},
        {"local_id": "w-2"},
        {"local_id": "w-3"},
    ]}))
    decisions_path.write_text(json.dumps(_decisions(
        {"local_id": "w-1", "outcome": "no-distinct-item-found"},
    )))
    monkeypatch.setattr(review_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(review_module, "MANIFEST_PATH", manifest_path)

    main([
        "--init-queue",
        "--queue-path", str(queue_path),
        "--seed", "fixed-seed",
        "--batch-size", "1",
        "--first-round", "53",
    ])
    main([
        "--rebuild-progress",
        "--queue-path", str(queue_path),
        "--progress-path", str(progress_path),
    ])

    queue = json.loads(queue_path.read_text())
    progress = json.loads(progress_path.read_text())
    assert queue["audit"]["queued_rows"] == 2
    assert queue["input_fingerprints"] == {
        str(manifest_path): review_module._sha256(manifest_path),
        str(decisions_path): review_module._sha256(decisions_path),
    }
    assert progress["audit"]["pending_queue_rows"] == 2
    assert progress["audit"]["creation_batch_authorized"] is False
    assert progress["pending_local_ids"] == [
        item["local_id"]
        for batch in queue["batches"]
        for item in batch["items"]
    ]


def test_decision_discovery_applies_corrections_after_numbered_rounds(
    tmp_path, monkeypatch,
):
    first = tmp_path / "ward-wikidata-predecessor-gap-sample-decisions.json"
    second = tmp_path / "ward-wikidata-predecessor-gap-sample-v2-decisions.json"
    corrections = tmp_path / "ward-wikidata-predecessor-gap-review-corrections.json"
    for path in (second, corrections, first):
        path.write_text("{}")
    monkeypatch.setattr(review_module, "DATA_DIR", tmp_path)

    assert review_module._decision_paths() == [first, second, corrections]
