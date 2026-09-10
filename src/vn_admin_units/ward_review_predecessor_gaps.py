"""Drive exhaustive manual review of predecessor creation candidates.

This module freezes rows that were never covered by the random audit rounds and
tracks whether every queued row and every current CREATE candidate has a manual
decision. It performs no Wikidata writes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Iterable
from pathlib import Path

from vn_admin_units.ward_audit_predecessor_gaps import (
    _read_csv,
    _serialize_json,
    _sha256,
    _utc_now,
    _write,
    audit_decisions,
    build_evidence,
)
from vn_admin_units.ward_reconcile import MAPPING


DATA_DIR = Path("data")
MANIFEST_PATH = DATA_DIR / "ward-wikidata-create-predecessors.json"
QUEUE_PATH = DATA_DIR / "ward-wikidata-predecessor-gap-review-queue.json"
PROGRESS_PATH = DATA_DIR / "ward-wikidata-predecessor-gap-review-progress.json"
DECISIONS_GLOB = "ward-wikidata-predecessor-gap-sample*-decisions.json"
CORRECTIONS_NAME = "ward-wikidata-predecessor-gap-review-corrections.json"
DEFAULT_SEED = "2026-09-10-predecessor-gap-exhaustive-review"


ALLOWED_OUTCOMES = {
    "existing-predecessor-item",
    "existing-predecessor-item-after-current-swap",
    "no-distinct-item-found",
}


def decision_rows(document: dict) -> list[dict]:
    return [
        row
        for batch in document.get("batches", [])
        for row in batch.get("decisions", [])
    ]


def _ordered_items(items: Iterable[dict], seed: str) -> list[dict]:
    def priority(item: dict) -> tuple[str, str]:
        digest = hashlib.sha256(
            f"{seed}\0{item['local_id']}".encode("utf-8")
        ).hexdigest()
        return digest, item["local_id"]

    return sorted(items, key=priority)


def build_review_queue(
    manifest: dict,
    decision_documents: Iterable[dict],
    *,
    seed: str,
    batch_size: int = 50,
    first_round: int = 53,
) -> dict:
    if batch_size < 1:
        raise ValueError("batch size must be positive")
    reviewed = {
        row["local_id"]
        for document in decision_documents
        for row in decision_rows(document)
    }
    ordered = _ordered_items(
        (
            item for item in manifest["items"]
            if item["local_id"] not in reviewed
        ),
        seed,
    )
    batches = [
        {
            "round": first_round + offset // batch_size,
            "items": ordered[offset:offset + batch_size],
        }
        for offset in range(0, len(ordered), batch_size)
    ]
    return {
        "schema_version": 1,
        "scope": {
            "tier": "ward",
            "purpose": "exhaustive review queue for predecessor creation gaps",
            "wikidata_write_performed": False,
        },
        "seed": seed,
        "audit": {
            "baseline_population": len(manifest["items"]),
            "previously_reviewed_rows": len(manifest["items"]) - len(ordered),
            "queued_rows": len(ordered),
            "batch_size": batch_size,
            "batches": len(batches),
            "first_round": first_round,
            "last_round": batches[-1]["round"] if batches else first_round - 1,
        },
        "batches": batches,
    }


def build_review_progress(
    manifest: dict,
    queue: dict,
    decision_documents: Iterable[dict],
) -> dict:
    rows = [
        row
        for document in decision_documents
        for row in decision_rows(document)
        if row.get("outcome") in ALLOWED_OUTCOMES
    ]
    outcomes = {}
    for row in rows:
        outcomes[row["local_id"]] = row["outcome"]

    queue_ids = [
        item["local_id"]
        for batch in queue["batches"]
        for item in batch["items"]
    ]
    reviewed_queue = {local_id for local_id in queue_ids if local_id in outcomes}
    pending = [local_id for local_id in queue_ids if local_id not in outcomes]
    no_item_ids = {
        local_id for local_id, outcome in outcomes.items()
        if outcome == "no-distinct-item-found"
    }
    existing_ids = {
        local_id for local_id, outcome in outcomes.items()
        if outcome.startswith("existing-predecessor-item")
    }
    current_ids = {item["local_id"] for item in manifest["items"]}
    reviewed_current = current_ids & no_item_ids
    unreviewed_current = current_ids - no_item_ids
    unapplied_existing = current_ids & existing_ids
    review_complete = not pending and not unreviewed_current
    authorized = review_complete and not unapplied_existing

    return {
        "audit": {
            "queued_rows": len(queue_ids),
            "reviewed_queue_rows": len(reviewed_queue),
            "pending_queue_rows": len(pending),
            "current_manifest_rows": len(current_ids),
            "reviewed_current_rows": len(reviewed_current),
            "unreviewed_current_rows": len(unreviewed_current),
            "unapplied_existing_rows": len(unapplied_existing),
            "review_complete": review_complete,
            "creation_batch_authorized": authorized,
        },
        "pending_local_ids": pending,
    }


def _queue_batch(queue: dict, round_number: int) -> dict:
    matches = [
        batch for batch in queue["batches"]
        if batch["round"] == round_number
    ]
    if len(matches) != 1:
        raise ValueError(f"review round {round_number} is not in the queue")
    return matches[0]


def build_batch_evidence(
    queue: dict,
    round_number: int,
    mapping_rows: list[dict],
    *,
    workers: int = 8,
    wikidata_search_fn=None,
    viwiki_search_fn=None,
    entity_fetch_fn=None,
) -> dict:
    batch = _queue_batch(queue, round_number)
    items = batch["items"]
    seed = f"{queue['seed']}-v{round_number}"
    kwargs = {
        "seed": seed,
        "sample_size": len(items),
        "batch_size": 10,
        "workers": workers,
    }
    if wikidata_search_fn is not None:
        kwargs["wikidata_search_fn"] = wikidata_search_fn
    if viwiki_search_fn is not None:
        kwargs["viwiki_search_fn"] = viwiki_search_fn
    if entity_fetch_fn is not None:
        kwargs["entity_fetch_fn"] = entity_fetch_fn
    evidence = build_evidence({"items": items}, mapping_rows, **kwargs)
    evidence["scope"]["purpose"] = (
        "exhaustive manual review of previously unreviewed predecessor gaps"
    )
    evidence["sampling"] = {
        "method": "frozen exhaustive review queue batch",
        "seed": seed,
        "population": queue["audit"]["baseline_population"],
        "eligible_population": queue["audit"]["queued_rows"],
        "review_round": round_number,
        "sample_size": len(items),
        "batch_size": 10,
        "batches": (len(items) + 9) // 10,
    }
    return evidence


def audit_batch_evidence(
    evidence: dict,
    queue: dict,
    mapping_rows: list[dict],
    round_number: int,
    decisions: dict | None = None,
) -> list[str]:
    del mapping_rows
    issues = []
    batch = _queue_batch(queue, round_number)
    expected_ids = {item["local_id"] for item in batch["items"]}
    actual_ids = [row["local_id"] for row in evidence["rows"]]
    if len(actual_ids) != len(expected_ids) or set(actual_ids) != expected_ids:
        issues.append("QUEUE-BATCH-DRIFT")
    if decisions is not None:
        issues.extend(audit_decisions(evidence, decisions))
    return issues


def _decision_paths() -> list[Path]:
    def version(path: Path) -> int:
        match = re.search(r"-v([0-9]+)-decisions\.json$", path.name)
        return int(match.group(1)) if match else 1

    paths = sorted(DATA_DIR.glob(DECISIONS_GLOB), key=version)
    corrections = DATA_DIR / CORRECTIONS_NAME
    return [*paths, *([corrections] if corrections.is_file() else [])]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_new(path: Path, payload: dict, *, force: bool) -> None:
    if path.exists() and not force:
        raise SystemExit(f"refusing to overwrite existing artifact: {path}")
    _write(path, _serialize_json(payload))


def _round_paths(round_number: int) -> tuple[Path, Path]:
    stem = f"ward-wikidata-predecessor-gap-sample-v{round_number}"
    return DATA_DIR / f"{stem}.json", DATA_DIR / f"{stem}-decisions.json"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Exhaustively review unreviewed predecessor creation gaps",
    )
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--init-queue", action="store_true")
    actions.add_argument("--rebuild-progress", action="store_true")
    actions.add_argument("--fetch", action="store_true")
    actions.add_argument("--check", action="store_true")
    parser.add_argument("--round", type=int)
    parser.add_argument("--seed", default=DEFAULT_SEED)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--first-round", type=int, default=53)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--queue-path", type=Path, default=QUEUE_PATH)
    parser.add_argument("--progress-path", type=Path, default=PROGRESS_PATH)
    parser.add_argument("--evidence-path", type=Path)
    parser.add_argument("--decisions-path", type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--audit", action="store_true")
    args = parser.parse_args(argv)

    manifest = _load_json(MANIFEST_PATH)
    decision_paths = _decision_paths()
    decision_documents = [_load_json(path) for path in decision_paths]

    if args.init_queue:
        queue = build_review_queue(
            manifest,
            decision_documents,
            seed=args.seed,
            batch_size=args.batch_size,
            first_round=args.first_round,
        )
        queue["created_at"] = _utc_now()
        queue["input_fingerprints"] = {
            path.as_posix(): _sha256(path)
            for path in (MANIFEST_PATH, *decision_paths)
        }
        _write_new(args.queue_path, queue, force=args.force)
        if args.audit:
            print(json.dumps(queue["audit"], ensure_ascii=False, indent=2))
        return

    queue = _load_json(args.queue_path)
    if args.rebuild_progress:
        progress = build_review_progress(manifest, queue, decision_documents)
        progress.update({
            "schema_version": 1,
            "scope": {
                "tier": "ward",
                "purpose": "exhaustive predecessor-gap review progress",
                "wikidata_write_performed": False,
            },
            "generated_at": _utc_now(),
            "input_fingerprints": {
                args.queue_path.as_posix(): _sha256(args.queue_path),
                **{
                    path.as_posix(): _sha256(path)
                    for path in decision_paths
                },
            },
        })
        _write(args.progress_path, _serialize_json(progress))
        if args.audit:
            print(json.dumps(progress["audit"], ensure_ascii=False, indent=2))
        return

    if args.round is None:
        raise SystemExit("--round is required with --fetch or --check")
    default_evidence, default_decisions = _round_paths(args.round)
    evidence_path = args.evidence_path or default_evidence
    decisions_path = args.decisions_path or default_decisions
    mapping_rows = _read_csv(MAPPING)

    if args.fetch:
        evidence = build_batch_evidence(
            queue,
            args.round,
            mapping_rows,
            workers=args.workers,
        )
        evidence["input_fingerprints"][args.queue_path.as_posix()] = _sha256(
            args.queue_path
        )
        _write_new(evidence_path, evidence, force=args.force)
        action = "wrote"
    else:
        evidence = _load_json(evidence_path)
        action = "checked"
    decisions = _load_json(decisions_path) if decisions_path.is_file() else None
    issues = audit_batch_evidence(
        evidence, queue, mapping_rows, args.round, decisions,
    )
    if args.check and issues:
        raise SystemExit("; ".join(issues))
    if args.audit:
        print(
            f"{action} exhaustive review round V{args.round}: "
            f"rows={evidence['audit']['rows']}; "
            f"possible missed items="
            f"{evidence['audit']['rows_with_possible_missed_item']}; "
            f"issues={len(issues)}"
        )
        print(json.dumps(evidence["audit"], ensure_ascii=False, indent=2))
        if decisions is not None:
            print(json.dumps(decisions["audit"], ensure_ascii=False, indent=2))
        for issue in issues:
            print(f"  {issue}")


if __name__ == "__main__":
    main()
