"""Enumerate normalized observed changes across the ward SOAP archive.

This stage reports source observations, not legal lineage. Same-code matching is
explicitly non-identifying, historical province values remain labeled as SOAP
echoes, and conflicted source rows are routed to anomaly transitions instead of
being guessed into administrative events.

Usage:
  uv run python -m vn_admin_units.ward_observed_changes
  uv run python -m vn_admin_units.ward_observed_changes --check
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from vn_admin_units import rawcache
from vn_admin_units.soap import parse_rows
from vn_admin_units.ward_model import IDENTITY_FIELDS, WARD_FIELDS, normalize_text


MANIFEST = Path("data/raw/manifest.jsonl")
OUTPUT = Path("data/ward-observed-changes.json")
SOURCE_FLOOR = "2002-01-01"
AS_OF = "2026-08-27"

FIELD_CHANGE_TYPES = {
    "MaTinh": "province_echo_code",
    "TenTinh": "province_echo_label",
    "MaQuanHuyen": "district_parent_code",
    "TenQuanHuyen": "district_parent_label",
    "TenPhuongXa": "name",
    "LoaiHinh": "type",
}


def _normalized_row(row: dict) -> dict:
    return {field: normalize_text(row.get(field, "")) for field in WARD_FIELDS}


def _row_tuple(row: dict) -> tuple[str, ...]:
    return tuple(row[field] for field in WARD_FIELDS)


def _row_from_tuple(values: tuple[str, ...]) -> dict:
    return dict(zip(WARD_FIELDS, values))


def _observation(row: dict) -> dict:
    return {
        "province_code_echo": row["MaTinh"],
        "province_name_echo": row["TenTinh"],
        "district_code": row["MaQuanHuyen"],
        "district_name_vi": row["TenQuanHuyen"],
        "code": row["MaPhuongXa"],
        "name_vi": row["TenPhuongXa"],
        "loai_hinh": row["LoaiHinh"],
    }


def normalize_snapshot_variants(rows: list[dict]) -> tuple[dict, dict]:
    """Normalize a snapshot while preserving conflicting source variants.

    Exact normalized duplicates collapse. Any identity key with multiple
    distinct rows, or any national ward code attached to multiple identity
    keys, is excluded from ordinary deltas and retained under
    ``anomalies_by_code``.
    """
    by_identity: dict[tuple[str, str, str], Counter] = defaultdict(Counter)
    for source_row in rows:
        row = _normalized_row(source_row)
        key = tuple(row[field] for field in IDENTITY_FIELDS)
        if not all(key):
            raise ValueError(f"ward snapshot has an incomplete identity key: {key}")
        by_identity[key][_row_tuple(row)] += 1

    exact_duplicates = sum(
        count - 1
        for variants in by_identity.values()
        for count in variants.values()
    )
    conflicting_identity_rows = sum(max(0, len(variants) - 1) for variants in by_identity.values())
    conflicted_keys = {key for key, variants in by_identity.items() if len(variants) > 1}

    groups_by_code: dict[str, list[tuple[tuple[str, str, str], tuple[str, ...], int]]] = defaultdict(list)
    for key, variants in by_identity.items():
        for values, occurrences in variants.items():
            groups_by_code[key[2]].append((key, values, occurrences))

    resolved_by_code = {}
    anomalies_by_code = {}
    duplicate_code_groups = 0
    for code, variants in sorted(groups_by_code.items()):
        identity_keys = {key for key, _, _ in variants}
        has_identity_conflict = any(key in conflicted_keys for key in identity_keys)
        if len(identity_keys) == 1 and len(variants) == 1 and not has_identity_conflict:
            resolved_by_code[code] = _row_from_tuple(variants[0][1])
            continue
        if len(identity_keys) > 1:
            duplicate_code_groups += 1
        kind = "identity_conflict" if has_identity_conflict else "duplicate_national_code"
        anomaly_variants = []
        for key, values, occurrences in sorted(
            variants,
            key=lambda item: (item[2], item[1], item[0]),
        ):
            anomaly_variants.append({
                "identity_key": {
                    "province_code_echo": key[0],
                    "district_code": key[1],
                    "code": key[2],
                },
                "observation": _observation(_row_from_tuple(values)),
                "source_occurrences": occurrences,
            })
        anomalies_by_code[code] = {
            "kind": kind,
            "variants": anomaly_variants,
        }

    audit = {
        "source_rows": len(rows),
        "identity_keys": len(by_identity),
        "resolved_codes": len(resolved_by_code),
        "distinct_codes": len(groups_by_code),
        "exact_duplicate_rows_collapsed": exact_duplicates,
        "conflicting_identity_rows": conflicting_identity_rows,
        "conflicted_identity_keys": len(conflicted_keys),
        "duplicate_national_code_groups": duplicate_code_groups,
        "missing_district_codes": sum(
            not key[1] for key in by_identity
        ),
    }
    return {
        "resolved_by_code": resolved_by_code,
        "anomalies_by_code": anomalies_by_code,
    }, audit


def _anomaly_side(state: dict, code: str) -> dict:
    if code in state["anomalies_by_code"]:
        return {
            "status": "source_anomaly",
            **state["anomalies_by_code"][code],
        }
    if code in state["resolved_by_code"]:
        return {
            "status": "resolved",
            "observation": _observation(state["resolved_by_code"][code]),
        }
    return {"status": "absent"}


def diff_states(before: dict, after: dict) -> dict:
    """Diff two normalized states without making cross-date identity claims."""
    anomaly_codes = set(before["anomalies_by_code"]) | set(after["anomalies_by_code"])
    anomaly_transitions = []
    for code in sorted(anomaly_codes):
        before_side = _anomaly_side(before, code)
        after_side = _anomaly_side(after, code)
        if before_side != after_side:
            anomaly_transitions.append({
                "code": code,
                "before": before_side,
                "after": after_side,
            })

    before_rows = {
        code: row for code, row in before["resolved_by_code"].items()
        if code not in anomaly_codes
    }
    after_rows = {
        code: row for code, row in after["resolved_by_code"].items()
        if code not in anomaly_codes
    }
    before_codes = set(before_rows)
    after_codes = set(after_rows)

    removals = [_observation(before_rows[code]) for code in sorted(before_codes - after_codes)]
    additions = [_observation(after_rows[code]) for code in sorted(after_codes - before_codes)]
    same_code_changes = []
    unchanged_codes = 0
    field_change_counts = Counter()
    for code in sorted(before_codes & after_codes):
        old = before_rows[code]
        new = after_rows[code]
        changed_fields = [field for field in WARD_FIELDS if old[field] != new[field]]
        if not changed_fields:
            unchanged_codes += 1
            continue
        for field in changed_fields:
            field_change_counts[field] += 1
        same_code_changes.append({
            "code": code,
            "changed_fields": changed_fields,
            "change_types": [FIELD_CHANGE_TYPES[field] for field in changed_fields],
            "before": _observation(old),
            "after": _observation(new),
            "identity_inference": "none_same_code_observation_only",
        })

    counts = {
        "unchanged_codes": unchanged_codes,
        "same_code_changes": len(same_code_changes),
        "additions": len(additions),
        "removals": len(removals),
        "source_anomaly_transitions": len(anomaly_transitions),
        "excluded_anomalous_codes": len(anomaly_codes),
        "field_changes": dict(sorted(field_change_counts.items())),
    }
    return {
        "counts": counts,
        "same_code_changes": same_code_changes,
        "additions": additions,
        "removals": removals,
        "source_anomaly_transitions": anomaly_transitions,
    }


def _manifest_entries(path: Path = MANIFEST) -> list[dict]:
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    ward = sorted(
        (
            record for record in records
            if record["path"].startswith("soap/DanhMucPhuongXa_")
            and record["path"].endswith(".xml.gz")
        ),
        key=lambda record: record["path"],
    )
    if len(ward) != 204:
        raise ValueError(f"locked ward SOAP inventory drifted: expected 204, got {len(ward)}")
    return ward


def _snapshot_date(entry: dict) -> str:
    return entry["path"].removeprefix("soap/DanhMucPhuongXa_").removesuffix(".xml.gz")


def _verify_snapshot_metrics(entry: dict, audit: dict) -> None:
    expected = {
        "source_rows": entry.get("rows"),
        "exact_duplicate_rows_collapsed": entry.get("duplicate_rows", 0),
        "conflicting_identity_rows": entry.get("conflicting_identity_rows", 0),
        "missing_district_codes": entry.get("missing_parent_codes", 0),
    }
    actual = {key: audit[key] for key in expected}
    if actual != expected:
        raise ValueError(
            f"snapshot normalization disagrees with manifest for {entry['path']}: "
            f"actual={actual}, expected={expected}"
        )


def _load_state(entry: dict) -> tuple[dict, dict]:
    if not rawcache.raw_is_verified(entry["path"]):
        raise ValueError(f"ward SOAP artifact failed verification: {entry['path']}")
    source = rawcache.read_raw(entry["path"]).decode("utf-8")
    rows = parse_rows(source, list(WARD_FIELDS))
    state, audit = normalize_snapshot_variants(rows)
    _verify_snapshot_metrics(entry, audit)
    return state, audit


def _snapshot_audit(entry: dict, audit: dict, state: dict) -> dict:
    return {
        "date": _snapshot_date(entry),
        "path": entry["path"],
        "sha256": entry["sha256"],
        "content_sha256": entry.get("content_sha256", entry["sha256"]),
        "rows": entry.get("rows"),
        "reasons": entry.get("reasons", []),
        **audit,
        "source_anomalies": [
            {"code": code, **anomaly}
            for code, anomaly in sorted(state["anomalies_by_code"].items())
        ],
    }


def _interval(before_entry: dict, after_entry: dict, before: dict, after: dict) -> dict:
    delta = diff_states(before, after)
    counts = delta["counts"]
    normalized_changed = any(counts[key] for key in (
        "same_code_changes", "additions", "removals", "source_anomaly_transitions"
    ))
    before_date = _snapshot_date(before_entry)
    after_date = _snapshot_date(after_entry)
    return {
        "event_id": f"soap:{before_date}->{after_date}",
        "before_date": before_date,
        "after_date": after_date,
        "before_path": before_entry["path"],
        "after_path": after_entry["path"],
        "before_content_sha256": before_entry.get("content_sha256", before_entry["sha256"]),
        "after_content_sha256": after_entry.get("content_sha256", after_entry["sha256"]),
        "payload_relation": (
            "identical"
            if before_entry.get("content_sha256", before_entry["sha256"])
            == after_entry.get("content_sha256", after_entry["sha256"])
            else "different"
        ),
        "normalized_changed": normalized_changed,
        "status": (
            "pending_crosswalk_legal_reconciliation"
            if normalized_changed else "no_observed_change"
        ),
        **delta,
    }


def build_observed_changes(manifest_path: Path = MANIFEST) -> dict:
    """Build the complete chronological observed-change inventory offline."""
    entries = _manifest_entries(manifest_path)
    first_date = _snapshot_date(entries[0])
    last_date = _snapshot_date(entries[-1])
    if (first_date, last_date) != (SOURCE_FLOOR, AS_OF):
        raise ValueError(
            f"ward SOAP date bounds drifted: {(first_date, last_date)}"
        )

    before_entry = entries[0]
    before_state, before_metrics = _load_state(before_entry)
    snapshot_audits = [_snapshot_audit(before_entry, before_metrics, before_state)]
    intervals = []
    for after_entry in entries[1:]:
        before_hash = before_entry.get("content_sha256", before_entry["sha256"])
        after_hash = after_entry.get("content_sha256", after_entry["sha256"])
        if before_hash == after_hash:
            if not rawcache.raw_is_verified(after_entry["path"]):
                raise ValueError(
                    f"ward SOAP artifact failed verification: {after_entry['path']}"
                )
            after_state = before_state
            after_metrics = before_metrics
            _verify_snapshot_metrics(after_entry, after_metrics)
        else:
            after_state, after_metrics = _load_state(after_entry)
        snapshot_audits.append(_snapshot_audit(after_entry, after_metrics, after_state))
        intervals.append(_interval(before_entry, after_entry, before_state, after_state))
        before_entry, before_state, before_metrics = after_entry, after_state, after_metrics

    changed_intervals = [interval for interval in intervals if interval["normalized_changed"]]
    aggregate_field_changes = Counter()
    for interval in intervals:
        aggregate_field_changes.update(interval["counts"]["field_changes"])
    summary = {
        "snapshots": len(snapshot_audits),
        "intervals": len(intervals),
        "source_rows": sum(snapshot["source_rows"] for snapshot in snapshot_audits),
        "exact_duplicate_rows_collapsed": sum(
            snapshot["exact_duplicate_rows_collapsed"] for snapshot in snapshot_audits
        ),
        "conflicting_identity_rows": sum(
            snapshot["conflicting_identity_rows"] for snapshot in snapshot_audits
        ),
        "snapshots_with_source_anomalies": sum(
            bool(snapshot["source_anomalies"]) for snapshot in snapshot_audits
        ),
        "byte_identical_intervals": sum(
            interval["payload_relation"] == "identical" for interval in intervals
        ),
        "normalized_no_change_intervals": len(intervals) - len(changed_intervals),
        "payload_changed_but_normalized_no_change_intervals": sum(
            interval["payload_relation"] == "different" and not interval["normalized_changed"]
            for interval in intervals
        ),
        "changed_intervals": len(changed_intervals),
        "same_code_changes": sum(
            interval["counts"]["same_code_changes"] for interval in intervals
        ),
        "additions": sum(interval["counts"]["additions"] for interval in intervals),
        "removals": sum(interval["counts"]["removals"] for interval in intervals),
        "source_anomaly_transitions": sum(
            interval["counts"]["source_anomaly_transitions"] for interval in intervals
        ),
        "field_changes": dict(sorted(aggregate_field_changes.items())),
    }
    return {
        "schema_version": 1,
        "scope": {
            "tier": "ward",
            "source_floor": SOURCE_FLOOR,
            "as_of": AS_OF,
            "semantics": "observed SOAP deltas only; no cross-date identity or legal-lineage inference",
        },
        "input_fingerprints": {
            "manifest_path": manifest_path.as_posix(),
            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        },
        "summary": summary,
        "snapshot_audits": snapshot_audits,
        "intervals": intervals,
    }


def serialize_observed_changes(artifact: dict) -> str:
    return json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_observed_changes(artifact: dict, output: Path = OUTPUT) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(serialize_observed_changes(artifact), encoding="utf-8")
    temporary.replace(output)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Enumerate normalized ward SOAP changes offline.")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--check", action="store_true",
                        help="fail if the existing output differs from a fresh offline build")
    args = parser.parse_args(argv)

    artifact = build_observed_changes()
    rendered = serialize_observed_changes(artifact)
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != rendered:
            raise SystemExit(f"observed-change artifact is missing or stale: {args.output}")
        action = "verified"
    else:
        write_observed_changes(artifact, args.output)
        action = "wrote"
    summary = artifact["summary"]
    print(
        f"{action} {args.output}: {summary['snapshots']} snapshots, "
        f"{summary['changed_intervals']} changed intervals, "
        f"{summary['same_code_changes']} same-code changes, "
        f"{summary['additions']} additions, {summary['removals']} removals"
    )


if __name__ == "__main__":
    main()
