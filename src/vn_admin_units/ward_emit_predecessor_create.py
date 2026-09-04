"""Prepare provisional CREATE statements for missing pre-2025 ward items.

This package is derived only after both predecessor discovery passes and the
small manual ambiguity ledger have been applied. It creates base items; the
separate lineage package adds dissolution and succession statements after the
new QIDs are ingested.

No command in this module writes to Wikidata.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from vn_admin_units.core import p31_target, ref_s854
from vn_admin_units.ward_reconcile import (
    DISTRICT_MAPPING,
    MAPPING,
    WARD_HISTORY,
    serialize_mapping,
    write_mapping,
)
from vn_admin_units.ward_reconcile_predecessors import (
    ARTIFACT_PATH as PREDECESSOR_ARTIFACT_PATH,
    BROAD_ARTIFACT_PATH,
    REVIEW_DECISIONS_PATH,
    apply_creation_gaps,
)


REFORM_DATE = "2025-07-01"
COUNTRY_QID = "Q881"
MANIFEST_PATH = Path("data/ward-wikidata-create-predecessors.json")
STATEMENTS_PATH = Path("statements/na-wards-create-predecessors.qs")
PREFLIGHT_PATH = Path("data/ward-wikidata-create-predecessors-preflight.json")
SAFE_GAP_CLASSIFICATIONS = {
    "assigned-item-only",
    "no-broad-candidate",
    "no-broad-district-candidate",
    "verification-rejected",
}


def _read_csv(path: Path) -> list[dict]:
    return list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _serialize_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _assignment_sha256(mapping_rows: list[dict]) -> str:
    assignments = {
        row["local_id"]: row["wikidata_qid"]
        for row in mapping_rows if row["wikidata_qid"]
    }
    content = json.dumps(
        assignments, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    ).encode()
    return hashlib.sha256(content).hexdigest()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _qs_string(value: str) -> str:
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _district_parent_index(district_rows: list[dict]) -> tuple[dict, dict]:
    by_identity: dict[tuple[str, str], set[str]] = defaultdict(set)
    by_code: dict[str, set[str]] = defaultdict(set)
    details = {}
    for row in district_rows:
        qid = row.get("wikidata_qid", "")
        if not qid:
            continue
        identity = (
            " ".join(row["name_vi"].casefold().split()),
            row["parent_code"],
        )
        by_identity[identity].add(qid)
        by_code[row["terminal_code"]].add(qid)
        details[qid] = row
    return (by_identity, by_code), details


def _district_parent(
    entity: dict,
    indexes: tuple[dict, dict],
    details: dict[str, dict],
) -> dict:
    parent = entity["parent_spans"][-1]
    province_code = entity["province_echo_spans"][-1]["code"]
    identity = (
        " ".join(parent["name_vi"].casefold().split()),
        province_code,
    )
    by_identity, by_code = indexes
    qids = by_identity.get(identity, set()) or by_code.get(parent["code"], set())
    if len(qids) != 1:
        raise ValueError(
            f"{entity['local_id']} has {len(qids)} district parents: {sorted(qids)}"
        )
    qid = next(iter(qids))
    return {
        "code": parent["code"],
        "name_vi": parent["name_vi"],
        "qid": qid,
        "mapping_local_id": details[qid]["local_id"],
    }


def _description(entity: dict, parent: dict) -> str:
    parent_name = parent["name_vi"][:1].lower() + parent["name_vi"][1:]
    return (
        f"{entity['loai_hinh'].lower()} cũ thuộc {parent_name}, Việt Nam, "
        "giải thể năm 2025"
    )


def build_manifest(
    history: dict,
    mapping_rows: list[dict],
    district_rows: list[dict],
    predecessor_artifact: dict,
    broad_artifact: dict,
    *,
    review_group_size: int = 10,
    input_fingerprints: dict[str, str] | None = None,
) -> dict:
    if review_group_size < 1:
        raise ValueError("review_group_size must be positive")
    entities = {row["local_id"]: row for row in history["entities"]}
    mapping = {row["local_id"]: row for row in mapping_rows}
    reform_edges = [
        edge for edge in history["lineage_edges"]
        if edge["effective_date"] == REFORM_DATE
    ]
    predecessors = {edge["predecessor"] for edge in reform_edges}
    edges_by_predecessor: dict[str, list[dict]] = defaultdict(list)
    for edge in reform_edges:
        edges_by_predecessor[edge["predecessor"]].append(edge)
    primary_review = {
        row["local_id"]: row for row in predecessor_artifact["review"]
    }
    broad_review = {row["local_id"]: row for row in broad_artifact["review"]}
    district_indexes, district_details = _district_parent_index(district_rows)
    gaps = sorted(
        (
            mapping[local_id] for local_id in predecessors
            if not mapping[local_id]["wikidata_qid"]
        ),
        key=lambda row: (row["terminal_code"], row["local_id"]),
    )
    entries = []
    for sequence, row in enumerate(gaps, start=1):
        entity = entities[row["local_id"]]
        primary = primary_review[row["local_id"]]
        broad = broad_review[row["local_id"]]
        if broad["classification"] == "ambiguous-verified-candidates":
            raise ValueError(f"unresolved predecessor ambiguity: {row['local_id']}")
        parent = _district_parent(entity, district_indexes, district_details)
        edges = edges_by_predecessor[row["local_id"]]
        references = {edge["reference_url"] for edge in edges}
        if len(references) != 1 or not next(iter(references)).startswith("http"):
            raise ValueError(f"{row['local_id']} lacks one official reform reference")
        successor_qids = sorted({
            mapping[edge["successor"]]["wikidata_qid"] for edge in edges
        }, key=lambda qid: int(qid[1:]))
        if not successor_qids or any(not qid for qid in successor_qids):
            raise ValueError(f"{row['local_id']} has an unreconciled successor")
        checked = sorted({
            *primary["candidate_qids"],
            *primary["current_qids_excluded"],
            *broad["candidate_qids"],
            *broad["assigned_qids_excluded"],
        }, key=lambda qid: int(qid[1:]))
        entries.append({
            "sequence": sequence,
            "review_group": (sequence - 1) // review_group_size + 1,
            "local_id": row["local_id"],
            "gso_code": row["terminal_code"],
            "name_vi": entity["name_vi"],
            "description_vi": _description(entity, parent),
            "loai_hinh": entity["loai_hinh"],
            "type_qid": p31_target(entity["loai_hinh"]),
            "country_qid": COUNTRY_QID,
            "parent_code": parent["code"],
            "parent_name_vi": parent["name_vi"],
            "parent_qid": parent["qid"],
            "parent_mapping_local_id": parent["mapping_local_id"],
            "valid_from": entity["valid_from"],
            "valid_to": entity["valid_to"],
            "successor_qids": successor_qids,
            "reference_url": next(iter(references)),
            "primary_classification": primary["classification"],
            "broad_classification": broad["classification"],
            "candidate_qids_checked": checked,
            "current_or_assigned_qids_excluded": sorted({
                *primary["current_qids_excluded"],
                *broad["assigned_qids_excluded"],
            }, key=lambda qid: int(qid[1:])),
        })
    duplicate_keys = [
        key for key, count in Counter(
            (row["name_vi"], row["parent_qid"], row["type_qid"])
            for row in entries
        ).items() if count > 1
    ]
    if duplicate_keys:
        raise ValueError(f"duplicate predecessor CREATE identities: {duplicate_keys[:5]}")
    return {
        "schema_version": 1,
        "scope": {
            "tier": "ward",
            "effective_date": REFORM_DATE,
            "purpose": "provisional former-item creation gaps pending sampled audit",
            "wikidata_write_performed": False,
            "statement_file": STATEMENTS_PATH.as_posix(),
            "review_group_size": review_group_size,
            "lineage_statements_deferred_until_qid_ingestion": True,
        },
        "input_fingerprints": input_fingerprints or {},
        "audit": {
            "items": len(entries),
            "statement_files": 1 if entries else 0,
            "review_groups": (
                (len(entries) + review_group_size - 1) // review_group_size
            ),
            "type_counts": dict(sorted(Counter(
                row["loai_hinh"] for row in entries
            ).items())),
            "district_count": len({row["parent_qid"] for row in entries}),
            "official_reference_urls": len({
                row["reference_url"] for row in entries
            }),
            "rows_excluding_assigned_qid": sum(
                bool(row["current_or_assigned_qids_excluded"]) for row in entries
            ),
            "primary_classification_counts": dict(sorted(Counter(
                row["primary_classification"] for row in entries
            ).items())),
            "broad_classification_counts": dict(sorted(Counter(
                row["broad_classification"] for row in entries
            ).items())),
        },
        "items": entries,
    }


def emit_item(item: dict) -> str:
    ref = ref_s854(item["reference_url"])
    return "\n".join([
        "CREATE",
        f"LAST\tLvi\t{_qs_string(item['name_vi'])}",
        f"LAST\tDvi\t{_qs_string(item['description_vi'])}",
        f"LAST\tP31\t{item['type_qid']}\t{ref}",
        f"LAST\tP17\t{item['country_qid']}\t{ref}",
        f"LAST\tP131\t{item['parent_qid']}\t{ref}",
    ]) + "\n"


def render_statements(manifest: dict) -> str:
    return "\n".join(
        emit_item(item).rstrip("\n") for item in manifest["items"]
    ) + ("\n" if manifest["items"] else "")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def build_preflight(
    manifest: dict,
    broad_artifact: dict,
    *,
    max_age_hours: float | None = None,
    now: datetime | None = None,
) -> dict:
    broad = {row["local_id"]: row for row in broad_artifact["review"]}
    source_at = broad_artifact["source"]["retrieved_at"]
    api_at = broad_artifact["action_api_verification"]["retrieved_at"]
    age_hours = None
    if max_age_hours is not None:
        now = now or datetime.now(timezone.utc)
        age_hours = max(
            (now - _parse_time(source_at)).total_seconds() / 3600,
            (now - _parse_time(api_at)).total_seconds() / 3600,
        )
    fresh = max_age_hours is None or age_hours <= max_age_hours
    items = []
    issues = []
    for item in manifest["items"]:
        evidence = broad.get(item["local_id"])
        if evidence is None:
            status = "needs-review"
            issues.append(f"MISSING-BROAD-ROW {item['local_id']}")
            classification = ""
        else:
            classification = evidence["classification"]
            status = "clear" if classification in SAFE_GAP_CLASSIFICATIONS else "needs-review"
            if status != "clear":
                issues.append(
                    f"UNSAFE-CLASSIFICATION {item['local_id']} {classification}"
                )
        items.append({
            "local_id": item["local_id"],
            "name_vi": item["name_vi"],
            "parent_qid": item["parent_qid"],
            "classification": classification,
            "status": status,
        })
    if not fresh:
        issues.append(f"STALE-PREFLIGHT {age_hours:.2f}h")
    clear = sum(row["status"] == "clear" for row in items)
    return {
        "schema_version": 1,
        "scope": {
            "tier": "ward",
            "effective_date": REFORM_DATE,
            "purpose": "former-item creation duplicate preflight",
            "wikidata_write_performed": False,
        },
        "input_fingerprints": {
            "manifest_content_sha256": hashlib.sha256(
                _serialize_json(manifest).encode()
            ).hexdigest(),
            BROAD_ARTIFACT_PATH.as_posix(): _sha256(BROAD_ARTIFACT_PATH),
        },
        "evidence": {
            "qlever_retrieved_at": source_at,
            "action_api_retrieved_at": api_at,
            "age_hours_at_check": (
                round(age_hours, 6) if age_hours is not None else None
            ),
            "max_age_hours": max_age_hours,
        },
        "audit": {
            "items": len(items),
            "clear_items": clear,
            "needs_review_items": len(items) - clear,
            "fresh": fresh,
            "upload_ready": clear == len(items) and fresh and not issues,
        },
        "issues": issues,
        "items": items,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Prepare CREATE statements for missing ward predecessors"
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--require-upload-ready", action="store_true")
    parser.add_argument("--max-preflight-age-hours", type=float, default=24)
    args = parser.parse_args(argv)
    history = json.loads(WARD_HISTORY.read_text(encoding="utf-8"))
    mapping = _read_csv(MAPPING)
    districts = _read_csv(DISTRICT_MAPPING)
    predecessor = json.loads(PREDECESSOR_ARTIFACT_PATH.read_text(encoding="utf-8"))
    broad = json.loads(BROAD_ARTIFACT_PATH.read_text(encoding="utf-8"))
    fingerprints = {
        path.as_posix(): _sha256(path)
        for path in (
            WARD_HISTORY, DISTRICT_MAPPING, PREDECESSOR_ARTIFACT_PATH,
            BROAD_ARTIFACT_PATH, REVIEW_DECISIONS_PATH,
        )
    }
    fingerprints[f"{MAPPING.as_posix()}#qid-assignments"] = (
        _assignment_sha256(mapping)
    )
    manifest = build_manifest(
        history, mapping, districts, predecessor, broad,
        input_fingerprints=fingerprints,
    )
    statements = render_statements(manifest)
    preflight = build_preflight(manifest, broad)
    runtime_preflight = (
        build_preflight(
            manifest, broad, max_age_hours=args.max_preflight_age_hours,
        ) if args.require_upload_ready else preflight
    )
    mapped = apply_creation_gaps(mapping, manifest)
    if args.check:
        if MANIFEST_PATH.read_text(encoding="utf-8") != _serialize_json(manifest):
            raise SystemExit(f"predecessor CREATE manifest is stale: {MANIFEST_PATH}")
        if STATEMENTS_PATH.read_text(encoding="utf-8") != statements:
            raise SystemExit(f"predecessor CREATE statements are stale: {STATEMENTS_PATH}")
        if PREFLIGHT_PATH.read_text(encoding="utf-8") != _serialize_json(preflight):
            raise SystemExit(f"predecessor CREATE preflight is stale: {PREFLIGHT_PATH}")
        if MAPPING.read_text(encoding="utf-8") != serialize_mapping(mapped):
            raise SystemExit(f"ward Wikidata mapping is stale: {MAPPING}")
        action = "verified"
    else:
        _write(MANIFEST_PATH, _serialize_json(manifest))
        _write(STATEMENTS_PATH, statements)
        _write(PREFLIGHT_PATH, _serialize_json(preflight))
        write_mapping(mapped)
        action = "wrote"
    print(f"{action} {len(manifest['items'])} predecessor CREATE items")
    if args.audit:
        print(json.dumps(manifest["audit"], ensure_ascii=False, indent=2))
        print(json.dumps(runtime_preflight["audit"], ensure_ascii=False, indent=2))
    if args.require_upload_ready and not runtime_preflight["audit"]["upload_ready"]:
        raise SystemExit(
            "predecessor CREATE package is not upload-ready: "
            + ", ".join(runtime_preflight["issues"][:10])
        )


if __name__ == "__main__":
    main()
