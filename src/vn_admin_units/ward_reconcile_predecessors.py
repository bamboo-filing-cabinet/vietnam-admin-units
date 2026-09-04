"""Reconcile immediate pre-2025 ward predecessors against saved Wikidata data.

The expensive discovery step is deliberately offline: it indexes the saved
ward-class QLever corpus once by folded name, narrows candidates by the
predecessor's terminal district, and excludes every QID assigned to a current
ward. Only that reduced QID set is refreshed through batched ``wbgetentities``
requests.

No command in this module writes to Wikidata.

Usage:
  uv run python -m vn_admin_units.ward_reconcile_predecessors --rebuild --audit
  uv run python -m vn_admin_units.ward_reconcile_predecessors --verify --audit
  uv run python -m vn_admin_units.ward_reconcile_predecessors --check --audit
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from vn_admin_units.names import fold_ward_name
from vn_admin_units.ward_reconcile import (
    BROAD_CANDIDATE_CACHE,
    CANDIDATE_CACHE,
    DISTRICT_MAPPING,
    MAPPING,
    REVIEW_DECISIONS,
    WARD_CLASSES,
    WARD_HISTORY,
    WIKIDATA_API,
    build_district_qid_index,
    build_mapping_rows,
    build_parent_qid_index,
    fetch_action_api_entities,
    serialize_json,
    serialize_mapping,
    write_mapping,
)


EFFECTIVE_DATE = "2025-07-01"
ARTIFACT_PATH = Path("data/ward-wikidata-predecessor-candidates.json")
BROAD_ARTIFACT_PATH = Path(
    "data/ward-wikidata-predecessor-unresolved-candidates.json"
)
REVIEW_DECISIONS_PATH = Path(
    "data/ward-wikidata-predecessor-review-decisions.json"
)
CREATION_MANIFEST_PATH = Path("data/ward-wikidata-create-predecessors.json")
LOCKED_PREDECESSOR_COUNT = 10_035
EXPECTED_CLASS_BY_TIER = {
    label: qid for qid, label in WARD_CLASSES.items()
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_csv(path: Path) -> list[dict]:
    return list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))


def immediate_predecessor_ids(history: dict) -> list[str]:
    return sorted({
        edge["predecessor"]
        for edge in history["lineage_edges"]
        if edge["effective_date"] == EFFECTIVE_DATE
    })


def _parent_code(entity: dict) -> str:
    spans = entity.get("parent_spans", [])
    return spans[-1]["code"] if spans else ""


def _qid_key(qid: str) -> int:
    return int(qid[1:])


def _current_assignments(mapping_rows: list[dict]) -> dict[str, str]:
    return {
        row["local_id"]: row["wikidata_qid"]
        for row in mapping_rows
        if not row["valid_to"] and row["wikidata_qid"]
    }


def _current_assignments_sha256(mapping_rows: list[dict]) -> str:
    payload = json.dumps(
        _current_assignments(mapping_rows),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _candidate_name_index(candidates: list[dict]) -> dict[str, dict[str, set[str]]]:
    indexed: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for candidate in candidates:
        qid = candidate["qid"]
        for field in ("label_vi", "label_en"):
            value = candidate.get(field, "")
            if value:
                indexed[fold_ward_name(value)][qid].add(field)
        for value in candidate.get("aliases", []):
            indexed[fold_ward_name(value)][qid].add("alias")
    return indexed


def reduce_candidates(
    history: dict,
    candidate_artifact: dict,
    district_qid_index: dict[str, set[str]],
    mapping_rows: list[dict],
    *,
    history_path: Path = WARD_HISTORY,
    candidate_path: Path = CANDIDATE_CACHE,
    district_mapping_path: Path = DISTRICT_MAPPING,
) -> dict:
    """Build the deterministic offline predecessor candidate reduction."""
    entities = {row["local_id"]: row for row in history["entities"]}
    predecessor_ids = immediate_predecessor_ids(history)
    candidates = candidate_artifact["candidates"]
    candidates_by_qid = {row["qid"]: row for row in candidates}
    name_index = _candidate_name_index(candidates)
    current_qids = set(_current_assignments(mapping_rows).values())
    review = []
    shortlisted = set()

    for local_id in predecessor_ids:
        entity = entities[local_id]
        matches = name_index.get(fold_ward_name(entity["name_vi"]), {})
        all_qids = set(matches)
        excluded = all_qids & current_qids
        candidate_qids = all_qids - current_qids
        expected_parent = _parent_code(entity)
        district_qids = {
            qid
            for qid in candidate_qids
            if expected_parent in {
                code
                for parent_qid in candidates_by_qid[qid]["parent_qids"]
                for code in district_qid_index.get(parent_qid, set())
            }
        }
        shortlisted.update(district_qids)
        if not candidate_qids and excluded:
            classification = "current-item-repurposed"
        elif not candidate_qids:
            classification = "no-name-candidate"
        elif not district_qids:
            classification = "no-district-candidate"
        else:
            classification = "awaiting-verification"
        review.append({
            "local_id": local_id,
            "terminal_code": entity["gso_codes"][-1],
            "name_vi": entity["name_vi"],
            "loai_hinh": entity["loai_hinh"],
            "parent_code": expected_parent,
            "classification": classification,
            "candidate_qids": sorted(candidate_qids, key=_qid_key),
            "current_qids_excluded": sorted(excluded, key=_qid_key),
            "district_candidate_qids": sorted(district_qids, key=_qid_key),
            "name_match_kinds": {
                qid: sorted(matches[qid])
                for qid in sorted(all_qids, key=_qid_key)
            },
            "verified_candidate_qids": [],
            "auto_candidate_qids": [],
            "confidence": "",
        })

    classifications = Counter(row["classification"] for row in review)
    return {
        "schema_version": 1,
        "scope": {
            "tier": "ward",
            "effective_date": EFFECTIVE_DATE,
            "purpose": "immediate_predecessor_reconciliation",
            "candidate_snapshot_as_of": candidate_artifact["scope"]["as_of"],
            "wikidata_write_performed": False,
        },
        "source": {
            "history_path": history_path.as_posix(),
            "history_sha256": _sha256(history_path),
            "candidate_path": candidate_path.as_posix(),
            "candidate_sha256": _sha256(candidate_path),
            "district_mapping_path": district_mapping_path.as_posix(),
            "district_mapping_sha256": _sha256(district_mapping_path),
            "current_assignments_sha256": _current_assignments_sha256(mapping_rows),
        },
        "audit": {
            "predecessor_rows": len(review),
            "current_assigned_qids": len(current_qids),
            "rows_with_current_qid_excluded": sum(
                bool(row["current_qids_excluded"]) for row in review
            ),
            "rows_with_name_candidate": sum(
                bool(row["candidate_qids"]) for row in review
            ),
            "rows_with_district_candidate": sum(
                bool(row["district_candidate_qids"]) for row in review
            ),
            "shortlisted_qids": len(shortlisted),
            "api_verified_candidates": 0,
            "rows_with_verified_candidate": 0,
            "auto_matched_rows": 0,
            "unresolved_rows": len(review),
            "classification_counts": dict(sorted(classifications.items())),
        },
        "shortlisted_qids": sorted(shortlisted, key=_qid_key),
        "action_api_verification": {
            "endpoint": WIKIDATA_API,
            "retrieved_at": "",
            "entities": [],
        },
        "review": review,
    }


def _verified_name_matches(row: dict, entity: dict) -> bool:
    wanted = fold_ward_name(row["name_vi"])
    values = list(entity.get("labels", {}).values()) + entity.get("aliases", [])
    return any(fold_ward_name(value) == wanted for value in values)


def evaluate(
    artifact: dict,
    district_qid_index: dict[str, set[str]],
    mapping_rows: list[dict],
) -> dict:
    """Evaluate refreshed API evidence and select collision-free auto matches."""
    result = json.loads(json.dumps(artifact))
    verified = {
        row["qid"]: row
        for row in result["action_api_verification"]["entities"]
    }
    current_qids = set(_current_assignments(mapping_rows).values())
    proposed: dict[str, str] = {}

    for row in result["review"]:
        qids = []
        for qid in row["district_candidate_qids"]:
            entity = verified.get(qid)
            if entity is None or entity.get("missing") or qid in current_qids:
                continue
            parent_codes = {
                code
                for parent_qid in entity.get("p131", [])
                for code in district_qid_index.get(parent_qid, set())
            }
            if row["parent_code"] not in parent_codes:
                continue
            if not set(entity.get("p31", [])) & set(WARD_CLASSES):
                continue
            if not _verified_name_matches(row, entity):
                continue
            qids.append(qid)
        row["verified_candidate_qids"] = qids
        row["auto_candidate_qids"] = []
        row["confidence"] = ""
        if not row["district_candidate_qids"]:
            continue
        if not qids:
            row["classification"] = "verification-rejected"
            continue
        selected = qids
        if len(qids) > 1:
            expected_class = EXPECTED_CLASS_BY_TIER[row["loai_hinh"]]
            exact_type = [qid for qid in qids if expected_class in verified[qid]["p31"]]
            if len(exact_type) == 1:
                selected = exact_type
        if len(selected) != 1:
            row["classification"] = "ambiguous-verified-candidates"
            continue
        qid = selected[0]
        proposed[row["local_id"]] = qid
        row["auto_candidate_qids"] = [qid]
        row["classification"] = "verified-unique"
        row["confidence"] = (
            "exact-folded-name+terminal-district+ward-class+batched-wbgetentities"
        )

    proposal_counts = Counter(proposed.values())
    for row in result["review"]:
        qids = row["auto_candidate_qids"]
        if qids and proposal_counts[qids[0]] > 1:
            row["auto_candidate_qids"] = []
            row["classification"] = "qid-collision"
            row["confidence"] = ""

    classifications = Counter(row["classification"] for row in result["review"])
    auto_matched = sum(bool(row["auto_candidate_qids"]) for row in result["review"])
    result["audit"].update({
        "api_verified_candidates": len(verified),
        "rows_with_verified_candidate": sum(
            bool(row["verified_candidate_qids"]) for row in result["review"]
        ),
        "auto_matched_rows": auto_matched,
        "unresolved_rows": len(result["review"]) - auto_matched,
        "classification_counts": dict(sorted(classifications.items())),
    })
    return result


def verify(
    artifact: dict,
    district_qid_index: dict[str, set[str]],
    mapping_rows: list[dict],
    *,
    fetch_fn=fetch_action_api_entities,
) -> dict:
    result = json.loads(json.dumps(artifact))
    shortlisted = set(result["shortlisted_qids"])
    existing = {
        row["qid"]: row
        for row in result["action_api_verification"].get("entities", [])
        if row["qid"] in shortlisted
    }
    missing = sorted(shortlisted - set(existing), key=_qid_key)
    fetched = fetch_fn(missing) if missing else []
    combined = {**existing, **{row["qid"]: row for row in fetched}}
    prior_retrieved_at = result["action_api_verification"].get("retrieved_at", "")
    result["action_api_verification"] = {
        "endpoint": WIKIDATA_API,
        "retrieved_at": _utc_now(),
        "reused_from_retrieved_at": prior_retrieved_at,
        "reused_candidates": len(existing),
        "fetched_candidates": len(fetched),
        "entities": [combined[qid] for qid in sorted(combined, key=_qid_key)],
    }
    return evaluate(result, district_qid_index, mapping_rows)


def reevaluate(
    artifact: dict,
    history: dict,
    candidate_artifact: dict,
    district_qid_index: dict[str, set[str]],
    mapping_rows: list[dict],
) -> dict:
    rebuilt = reduce_candidates(
        history, candidate_artifact, district_qid_index, mapping_rows,
    )
    rebuilt["action_api_verification"] = artifact["action_api_verification"]
    return evaluate(rebuilt, district_qid_index, mapping_rows)


def apply_matches(mapping_rows: list[dict], artifact: dict) -> list[dict]:
    """Apply only collision-free automatic predecessor matches to the mapping."""
    rows = json.loads(json.dumps(mapping_rows))
    by_id = {row["local_id"]: row for row in rows}
    for review in artifact["review"]:
        if not review["auto_candidate_qids"]:
            continue
        row = by_id[review["local_id"]]
        if not row["valid_to"]:
            raise ValueError(f"predecessor match targets current row: {row['local_id']}")
        qid = review["auto_candidate_qids"][0]
        broad = artifact.get("scope", {}).get("purpose") == (
            "unresolved_predecessor_broad_name_discovery"
        )
        row.update({
            "wikidata_qid": qid,
            "qid_status": "existing",
            "match_status": "verified",
            "candidate_qids": (
                qid if broad else "|".join(review["verified_candidate_qids"])
            ),
            "match_notes": (
                "predecessor broad exact-vi-name+terminal-district+ward-class+"
                "batched-wbgetentities" if broad else
                "predecessor exact-name+terminal-district+ward-class+"
                "batched-wbgetentities"
            ),
        })
    return rows


def apply_review_decisions(mapping_rows: list[dict], decisions: dict) -> list[dict]:
    rows = json.loads(json.dumps(mapping_rows))
    by_id = {row["local_id"]: row for row in rows}
    assigned = {
        row["wikidata_qid"]: row["local_id"]
        for row in rows if row["wikidata_qid"]
    }
    seen = set()
    for batch in decisions.get("batches", []):
        batch_id = batch.get("batch_id", "")
        if not batch_id:
            raise ValueError("predecessor review batch lacks batch_id")
        for decision in batch.get("decisions", []):
            local_id = decision.get("local_id", "")
            qid = decision.get("wikidata_qid", "")
            if not local_id or local_id in seen:
                raise ValueError(f"duplicate predecessor review local_id: {local_id}")
            if decision.get("outcome") != "assign" or not (
                qid.startswith("Q") and qid[1:].isdigit()
            ):
                raise ValueError(f"invalid predecessor review assignment: {local_id}")
            row = by_id.get(local_id)
            if row is None or not row["valid_to"]:
                raise ValueError(f"predecessor review targets invalid row: {local_id}")
            owner = assigned.get(qid)
            if owner and owner != local_id:
                raise ValueError(
                    f"predecessor review QID collision: {qid} <- {owner}, {local_id}"
                )
            candidates = {
                *filter(None, row["candidate_qids"].split("|")),
                *decision.get("candidate_qids_checked", []),
                qid,
            }
            row.update({
                "wikidata_qid": qid,
                "qid_status": "existing",
                "match_status": "manual",
                "candidate_qids": "|".join(sorted(candidates, key=_qid_key)),
                "match_notes": (
                    f"predecessor review {batch_id}: "
                    f"{decision.get('mapping_note', 'human identity review')}"
                ),
            })
            assigned[qid] = local_id
            seen.add(local_id)
    return rows


def apply_creation_gaps(mapping_rows: list[dict], manifest: dict) -> list[dict]:
    rows = json.loads(json.dumps(mapping_rows))
    by_id = {row["local_id"]: row for row in rows}
    for item in manifest.get("items", []):
        local_id = item["local_id"]
        row = by_id.get(local_id)
        if row is None or not row["valid_to"] or row["wikidata_qid"]:
            raise ValueError(f"invalid predecessor creation gap: {local_id}")
        row.update({
            "qid_status": "new",
            "match_status": "gap",
            "candidate_qids": "",
            "match_notes": (
                "reviewed predecessor creation gap after ward-class and broad "
                "district-scoped preflight"
            ),
        })
    return rows


def audit(artifact: dict, mapping_rows: list[dict]) -> list[str]:
    issues = []
    review = artifact["review"]
    if len(review) != LOCKED_PREDECESSOR_COUNT:
        issues.append(f"PREDECESSOR-COUNT {len(review)}")
    if len({row["local_id"] for row in review}) != len(review):
        issues.append("DUPLICATE-LOCAL-ID")
    shortlisted = {
        qid for row in review for qid in row["district_candidate_qids"]
    }
    if set(artifact["shortlisted_qids"]) != shortlisted:
        issues.append("SHORTLIST-QID-SET")
    verified = {
        row["qid"] for row in artifact["action_api_verification"]["entities"]
    }
    if verified and verified != shortlisted:
        issues.append("API-VERIFIED-QID-SET")
    if any(
        row.get("missing")
        for row in artifact["action_api_verification"]["entities"]
    ):
        issues.append("API-MISSING-ENTITY")
    current_qids = set(_current_assignments(mapping_rows).values())
    automatic = [
        (row["local_id"], row["auto_candidate_qids"][0])
        for row in review if row["auto_candidate_qids"]
    ]
    assigned = [qid for _, qid in automatic]
    if len(assigned) != len(set(assigned)):
        issues.append("AUTO-QID-COLLISION")
    if set(assigned) & current_qids:
        issues.append("AUTO-CURRENT-QID-REUSE")
    mapping_by_id = {row["local_id"]: row for row in mapping_rows}
    for local_id, qid in automatic:
        row = mapping_by_id.get(local_id)
        if row is None or row["wikidata_qid"] != qid or row["match_status"] != "verified":
            issues.append(f"MAPPING-DRIFT {local_id}")
    return issues


def format_audit(artifact: dict, issues: list[str]) -> str:
    data = artifact["audit"]
    return (
        "ward predecessor reconciliation: "
        f"{data['auto_matched_rows']}/{data['predecessor_rows']} auto matched; "
        f"{data['shortlisted_qids']} shortlisted QIDs, "
        f"{data['api_verified_candidates']} API-verified; {len(issues)} issues"
    )


def _load_primary_inputs() -> tuple[dict, dict, list[dict], dict[str, set[str]]]:
    history = json.loads(WARD_HISTORY.read_text(encoding="utf-8"))
    candidates = json.loads(CANDIDATE_CACHE.read_text(encoding="utf-8"))
    mapping = _read_csv(MAPPING)
    return history, candidates, mapping, build_district_qid_index()


def _base_mapping(history: dict, candidates: dict) -> list[dict]:
    broad = json.loads(BROAD_CANDIDATE_CACHE.read_text(encoding="utf-8"))
    decisions = json.loads(REVIEW_DECISIONS.read_text(encoding="utf-8"))
    return build_mapping_rows(
        history,
        candidates,
        build_parent_qid_index(),
        district_qid_index=build_district_qid_index(),
        broad_artifact=broad,
        review_decisions=decisions,
    )


def _write_artifact(artifact: dict, path: Path = ARTIFACT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(serialize_json(artifact), encoding="utf-8")
    temporary.replace(path)
    return path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Reconcile immediate pre-2025 ward predecessors"
    )
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)

    history, candidates, committed_mapping, district_index = _load_primary_inputs()
    if args.verify:
        artifact = reduce_candidates(
            history, candidates, district_index, committed_mapping,
        )
        if ARTIFACT_PATH.is_file():
            saved = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
            artifact["action_api_verification"] = saved[
                "action_api_verification"
            ]
        artifact = verify(artifact, district_index, committed_mapping)
    elif ARTIFACT_PATH.is_file():
        saved = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
        artifact = reevaluate(
            saved, history, candidates, district_index, committed_mapping,
        )
    else:
        artifact = reduce_candidates(
            history, candidates, district_index, committed_mapping,
        )

    base_mapping = _base_mapping(history, candidates)
    rendered_mapping = apply_matches(base_mapping, artifact)
    if BROAD_ARTIFACT_PATH.is_file():
        broad_artifact = json.loads(BROAD_ARTIFACT_PATH.read_text(encoding="utf-8"))
        rendered_mapping = apply_matches(rendered_mapping, broad_artifact)
    if REVIEW_DECISIONS_PATH.is_file():
        decisions = json.loads(REVIEW_DECISIONS_PATH.read_text(encoding="utf-8"))
        rendered_mapping = apply_review_decisions(rendered_mapping, decisions)
    if CREATION_MANIFEST_PATH.is_file():
        creation_manifest = json.loads(
            CREATION_MANIFEST_PATH.read_text(encoding="utf-8")
        )
        rendered_mapping = apply_creation_gaps(rendered_mapping, creation_manifest)
    if args.check:
        if not ARTIFACT_PATH.is_file() or (
            ARTIFACT_PATH.read_text(encoding="utf-8") != serialize_json(artifact)
        ):
            raise SystemExit(f"predecessor artifact is missing or stale: {ARTIFACT_PATH}")
        if MAPPING.read_text(encoding="utf-8") != serialize_mapping(rendered_mapping):
            raise SystemExit(f"ward Wikidata mapping is stale: {MAPPING}")
        action = "verified"
    elif args.rebuild or args.verify:
        _write_artifact(artifact)
        write_mapping(rendered_mapping)
        action = "wrote"
    else:
        action = "evaluated"

    issues = audit(artifact, rendered_mapping)
    if args.audit:
        print(f"{action} {ARTIFACT_PATH} and {MAPPING}")
        print(format_audit(artifact, issues))
        print(json.dumps(artifact["audit"], ensure_ascii=False, indent=2))
        for issue in issues[:20]:
            print(f"  {issue}")
    if issues:
        raise SystemExit("ward predecessor reconciliation has audit issues")
    if args.strict and artifact["audit"]["unresolved_rows"]:
        raise SystemExit(
            "ward predecessor reconciliation is incomplete: "
            f"{artifact['audit']['unresolved_rows']} rows unresolved"
        )


if __name__ == "__main__":
    main()
