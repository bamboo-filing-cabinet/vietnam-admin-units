"""Reconcile observed ward SOAP changes to retained crosswalk evidence.

The annual exports are net comparisons, not an event log. This module assigns
their structured old/new sides to the actual SOAP components inside each
window, preserves every supporting row and narrative note, recognizes code
reuse without asserting identity, and emits narrowly scoped fetch residue when
the net comparison cannot explain an observation.

Usage:
  uv run python -m vn_admin_units.ward_crosswalk_reconciliation
  uv run python -m vn_admin_units.ward_crosswalk_reconciliation --check
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from vn_admin_units import rawcache
from vn_admin_units.crosscheck_decrees import decree_code, is_ward_structural
from vn_admin_units.crosswalk import read_ward_crosswalk
from vn_admin_units.ward_model import normalize_text
from vn_admin_units.ward_observed_changes import soap_manifest_fingerprint
from vn_admin_units.ward_source_coverage import normalize_code, normalize_date


MANIFEST = Path("data/raw/manifest.jsonl")
LEGAL_INDEX = Path("data/raw/nghidinh.json")
OBSERVED_CHANGES = Path("data/ward-observed-changes.json")
OUTPUT = Path("data/ward-crosswalk-reconciliation.json")

SOURCE_FLOOR = "2002-01-01"
AS_OF = "2026-08-27"
LONG_RANGE_WINDOW = ("2002-01-01", "2025-06-30")
REFORM_BOUNDARY = ("2025-06-30", "2025-07-01")
POST_REFORM_WINDOW = ("2025-07-01", "2026-08-27")

_WINDOW = re.compile(r"^crosswalk/ward_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.xls$")
_STRUCTURAL_SAME_CODE_FIELDS = {
    "MaQuanHuyen", "TenQuanHuyen", "TenPhuongXa", "LoaiHinh",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_manifest(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _window_kind(base_date: str, compare_date: str) -> str:
    if (base_date, compare_date) == REFORM_BOUNDARY:
        return "reform_boundary"
    if (base_date, compare_date) == POST_REFORM_WINDOW:
        return "post_reform"
    if base_date.endswith("-01-01") and compare_date.endswith("-01-01"):
        if int(compare_date[:4]) == int(base_date[:4]) + 1:
            return "yearly"
    raise ValueError(f"unexpected primary crosswalk window: {base_date}->{compare_date}")


def _primary_window_entries(manifest: list[dict]) -> list[dict]:
    entries = []
    for entry in manifest:
        match = _WINDOW.fullmatch(entry["path"])
        if match is None:
            continue
        base_date, compare_date = match.groups()
        if (base_date, compare_date) == LONG_RANGE_WINDOW:
            continue
        is_yearly = (
            base_date.endswith("-01-01")
            and compare_date.endswith("-01-01")
            and int(compare_date[:4]) == int(base_date[:4]) + 1
        )
        if not (
            is_yearly
            or (base_date, compare_date) == REFORM_BOUNDARY
            or (base_date, compare_date) == POST_REFORM_WINDOW
        ):
            continue
        entries.append({
            **entry,
            "base_date": base_date,
            "compare_date": compare_date,
            "kind": _window_kind(base_date, compare_date),
        })
    entries.sort(key=lambda entry: (entry["base_date"], entry["compare_date"]))
    if len(entries) != 23:
        raise ValueError(f"expected 23 primary crosswalk windows, got {len(entries)}")
    return entries


def _row_relation(row: dict) -> str:
    if row["base_ma"] and row["succ_ma"]:
        return "same_code" if row["base_ma"] == row["succ_ma"] else "code_change"
    if row["base_ma"]:
        return "base_only"
    if row["succ_ma"]:
        return "successor_only"
    return "empty"


def _note_class(note: str) -> str:
    text = normalize_text(note)
    folded = text.lower()
    if not text:
        return "none"
    if "một phần" in folded:
        return "partial_transfer"
    if "chuyển đổi mã" in folded:
        return "code_transition"
    if any(term in folded for term in ("nhập", "sáp nhập", "sát nhập")):
        return "merge_or_absorption"
    if folded.startswith("thành lập"):
        return "establishment"
    if "đổi tên" in folded:
        return "rename"
    return "other"


def _evidence_rows(source_path: str, rows: list[dict]) -> list[dict]:
    evidence = []
    for offset, source in enumerate(rows, start=2):
        row = {key: normalize_text(value) for key, value in source.items()}
        codes = sorted({
            code for code in (
                decree_code(row["base_nghi_dinh"]),
                decree_code(row["succ_nghi_dinh"]),
            ) if code
        })
        evidence.append({
            "row_id": f"{source_path}#row={offset}",
            "source_path": source_path,
            "source_row": offset,
            "relation_kind": _row_relation(row),
            "note_class": _note_class(row["ghi_chu"]),
            "decree_codes_raw": codes,
            **row,
        })
    return evidence


def _component_records(interval: dict) -> list[dict]:
    records = []
    for kind, observations in (
        ("removal", interval["removals"]),
        ("addition", interval["additions"]),
    ):
        for observation in observations:
            records.append({
                "component_id": f"{interval['event_id']}#{kind}:{observation['code']}",
                "kind": kind,
                "code": observation["code"],
                "before": observation if kind == "removal" else None,
                "after": observation if kind == "addition" else None,
                "changed_fields": [],
                "structural": True,
            })
    for change in interval["same_code_changes"]:
        records.append({
            "component_id": f"{interval['event_id']}#same_code:{change['code']}",
            "kind": "same_code",
            "code": change["code"],
            "before": change["before"],
            "after": change["after"],
            "changed_fields": change["changed_fields"],
            "change_types": change["change_types"],
            "structural": bool(
                set(change["changed_fields"]) & _STRUCTURAL_SAME_CODE_FIELDS
            ),
        })
    return records


def _unique_rows(rows: list[dict]) -> list[dict]:
    by_id = {row["row_id"]: row for row in rows}
    return [by_id[row_id] for row_id in sorted(by_id)]


def _day_offset(value: str, event_date: str) -> int | None:
    if not value:
        return None
    return (date.fromisoformat(value) - date.fromisoformat(event_date)).days


def _reconcile_component(component: dict, event_date: str,
                         base_index: dict[str, list[dict]],
                         successor_index: dict[str, list[dict]]) -> dict:
    code = component["code"]
    base_rows = base_index.get(code, [])
    successor_rows = successor_index.get(code, [])
    candidates = _unique_rows(base_rows + successor_rows)
    before_name = component["before"]["name_vi"] if component["before"] else None
    after_name = component["after"]["name_vi"] if component["after"] else None

    if component["kind"] == "removal":
        name_supported = any(row["base_ten"] == before_name for row in base_rows)
        status = "supported" if name_supported else ("code_only" if base_rows else "unmatched")
        relevant = base_rows
    elif component["kind"] == "addition":
        name_supported = any(row["succ_ten"] == after_name for row in successor_rows)
        status = "supported" if name_supported else (
            "supported_source_correction"
            if successor_rows and not after_name else
            "code_only" if successor_rows else "unmatched"
        )
        relevant = successor_rows
    else:
        stable = [
            row for row in candidates
            if row["base_ma"] == row["succ_ma"] == code
        ]
        outgoing = [row for row in base_rows if row["succ_ma"] != code]
        incoming = [row for row in successor_rows if row["base_ma"] != code]
        stable_supported = any(
            row["base_ten"] == before_name and row["succ_ten"] == after_name
            for row in stable
        )
        reuse_supported = (
            any(row["base_ten"] == before_name for row in outgoing)
            and any(row["succ_ten"] == after_name for row in incoming)
        )
        source_correction = any(
            row["base_ten"] == before_name and not after_name and row["succ_ten"]
            for row in stable
        )
        if stable_supported:
            status = "supported_same_code"
        elif reuse_supported:
            status = "supported_code_reuse"
        elif source_correction:
            status = "supported_source_correction"
        else:
            status = "code_only" if candidates else "unmatched"
        relevant = candidates

    decree_codes = sorted({
        code
        for row in relevant
        for code in row["decree_codes_raw"]
    })
    effective_offsets = sorted({
        offset
        for row in relevant
        if (offset := _day_offset(row["succ_hieu_luc"], event_date)) is not None
    })
    note_classes = sorted({
        row["note_class"] for row in relevant if row["note_class"] != "none"
    })
    signals = {
        "base_name_matches": sum(row["base_ten"] == before_name for row in base_rows),
        "successor_name_matches": sum(
            row["succ_ten"] == after_name for row in successor_rows
        ),
        "before_province_echo_matches": sum(
            component["before"] is not None
            and row["base_tinh"] == component["before"]["province_code_echo"]
            for row in base_rows
        ),
        "after_province_echo_matches": sum(
            component["after"] is not None
            and row["succ_tinh"] == component["after"]["province_code_echo"]
            for row in successor_rows
        ),
        "successor_effective_date_offsets_days": effective_offsets,
        "note_classes": note_classes,
        "decree_codes_raw": decree_codes,
    }
    signals = {key: value for key, value in signals.items() if value}
    result = {
        "component_id": component["component_id"],
        "kind": component["kind"],
        "code": component["code"],
        "status": status,
        "evidence_row_ids": [row["row_id"] for row in relevant],
    }
    if component["changed_fields"]:
        result["changed_fields"] = component["changed_fields"]
        result["change_types"] = component["change_types"]
    if signals:
        result["evidence_signals"] = signals
    return result


def _public_evidence_row(row: dict) -> dict:
    return {
        key: value for key, value in row.items()
        if key not in {"source_path", "source_row", "decree_codes_raw"}
    }


def _target_request(before_date: str, after_date: str, event_id: str,
                    reasons: set[str], component_ids: list[str]) -> dict:
    return {
        "request_id": f"crosswalk:ward:{before_date}->{after_date}",
        "base_date": before_date,
        "compare_date": after_date,
        "fetch_arguments": [
            "--tier", "ward", "--window",
            date.fromisoformat(before_date).strftime("%d/%m/%Y"),
            date.fromisoformat(after_date).strftime("%d/%m/%Y"),
        ],
        "event_ids": [event_id],
        "affected_component_ids": sorted(set(component_ids)),
        "reasons": sorted(reasons),
        "status": "missing",
    }


def reconcile_window(*, source_path: str, kind: str, base_date: str,
                     compare_date: str, rows: list[dict], intervals: list[dict],
                     legal_instruments_by_date: dict[str, list[str]]) -> dict:
    """Assign one retained crosswalk's rows to observed components in its span."""
    evidence = _evidence_rows(source_path, rows)
    base_index: dict[str, list[dict]] = defaultdict(list)
    successor_index: dict[str, list[dict]] = defaultdict(list)
    for row in evidence:
        if row["base_ma"]:
            base_index[row["base_ma"]].append(row)
        if row["succ_ma"]:
            successor_index[row["succ_ma"]].append(row)

    components_by_event = {
        interval["event_id"]: _component_records(interval)
        for interval in intervals
    }
    occurrences = Counter(
        (component["kind"], component["code"])
        for components in components_by_event.values()
        for component in components
    )
    added_codes = {
        component["code"] for components in components_by_event.values()
        for component in components if component["kind"] == "addition"
    }
    removed_codes = {
        component["code"] for components in components_by_event.values()
        for component in components if component["kind"] == "removal"
    }
    ephemeral_codes = added_codes & removed_codes

    linked_row_ids = set()
    event_outputs = []
    targeted = []
    for interval in intervals:
        reconciled = []
        reasons: set[str] = set()
        affected = []
        legal_candidates = legal_instruments_by_date.get(interval["after_date"], [])
        for component in components_by_event[interval["event_id"]]:
            item = _reconcile_component(
                component, interval["after_date"], base_index, successor_index,
            )
            linked_row_ids.update(item["evidence_row_ids"])
            component_reasons = set()
            if item["status"] in {"unmatched", "code_only"}:
                component_reasons.add("soap_crosswalk_disagreement")
                if len(legal_candidates) > 1 and component["structural"]:
                    component_reasons.add("multiple_same_date_instruments")
            if occurrences[(component["kind"], component["code"])] > 1:
                component_reasons.add("multiple_changes_within_window")
            if component["code"] in ephemeral_codes:
                component_reasons.add("ephemeral_within_window")
            if (
                kind == "yearly"
                and "partial_transfer" in item.get("evidence_signals", {}).get(
                    "note_classes", []
                )
            ):
                component_reasons.add("partial_transfer_composition")
            if component_reasons:
                item["targeted_window_reasons"] = sorted(component_reasons)
                affected.append(component["component_id"])
                reasons.update(component_reasons)
            reconciled.append(item)

        if reasons:
            targeted.append(_target_request(
                interval["before_date"], interval["after_date"], interval["event_id"],
                reasons, affected,
            ))
        event_outputs.append({
            "event_id": interval["event_id"],
            "before_date": interval["before_date"],
            "after_date": interval["after_date"],
            "primary_crosswalk_path": source_path,
            "candidate_legal_instrument_ids": legal_candidates,
            "source_anomaly_transitions": interval["source_anomaly_transitions"],
            "components": reconciled,
            "status": "targeted_window_required" if reasons else "crosswalk_supported",
        })

    return {
        "window": {
            "path": source_path,
            "kind": kind,
            "base_date": base_date,
            "compare_date": compare_date,
            "rows": len(evidence),
            "observed_events": len(event_outputs),
        },
        "events": event_outputs,
        "linked_evidence_rows": [
            _public_evidence_row(row)
            for row in evidence if row["row_id"] in linked_row_ids
        ],
        "targeted_windows": targeted,
    }


def _legal_instruments_by_date(path: Path) -> dict[str, list[str]]:
    records = json.loads(path.read_text(encoding="utf-8"))
    grouped: dict[str, set[str]] = defaultdict(set)
    for record in records:
        if not is_ward_structural(str(record.get("noi_dung", ""))):
            continue
        code = normalize_code(record.get("code", ""))
        effective_date = normalize_date(record.get("hieu_luc", ""))
        grouped[effective_date].add(f"{code}@{effective_date}")
    return {key: sorted(value) for key, value in grouped.items()}


def _uncovered_event(interval: dict, legal_candidates: list[str]) -> tuple[dict, dict]:
    components = []
    for component in _component_records(interval):
        components.append({
            "component_id": component["component_id"],
            "kind": component["kind"],
            "code": component["code"],
            "status": "no_primary_crosswalk_window",
            "evidence_row_ids": [],
            "targeted_window_reasons": ["no_primary_crosswalk_window"],
            **(
                {
                    "changed_fields": component["changed_fields"],
                    "change_types": component["change_types"],
                }
                if component["changed_fields"] else {}
            ),
        })
    event = {
        "event_id": interval["event_id"],
        "before_date": interval["before_date"],
        "after_date": interval["after_date"],
        "primary_crosswalk_path": None,
        "candidate_legal_instrument_ids": legal_candidates,
        "source_anomaly_transitions": interval["source_anomaly_transitions"],
        "components": components,
        "status": "targeted_window_required",
    }
    request = _target_request(
        interval["before_date"], interval["after_date"], interval["event_id"],
        {"no_primary_crosswalk_window"},
        [component["component_id"] for component in components],
    )
    return event, request


def _manifest_by_path(manifest: list[dict]) -> dict[str, dict]:
    indexed = {}
    for entry in manifest:
        path = entry["path"]
        if path in indexed:
            raise ValueError(f"raw manifest contains duplicate path: {path}")
        indexed[path] = entry
    return indexed


def _merge_targeted_event(primary: dict, targeted: dict, source_path: str) -> dict:
    primary_components = {
        component["component_id"]: component
        for component in primary["components"]
    }
    merged_components = []
    for component in targeted["components"]:
        earlier = primary_components[component["component_id"]]
        primary_ids = earlier["evidence_row_ids"]
        targeted_ids = component["evidence_row_ids"]
        merged = {
            **component,
            "primary_status": earlier["status"],
            "primary_evidence_row_count": len(primary_ids),
            "evidence_row_ids": targeted_ids,
        }
        merged_components.append(merged)
    if set(primary_components) != {item["component_id"] for item in merged_components}:
        raise ValueError(f"targeted crosswalk changed the component set for {primary['event_id']}")
    return {
        **targeted,
        "primary_crosswalk_path": primary["primary_crosswalk_path"],
        "targeted_crosswalk_path": source_path,
        "components": merged_components,
        "status": targeted["status"],
    }


def _merge_long_range_fallback(current: dict, fallback: dict,
                               evidence_by_id: dict[str, dict],
                               source_path: str) -> tuple[dict, int]:
    fallback_components = {
        component["component_id"]: component
        for component in fallback["components"]
    }
    removal_codes = {
        component["code"] for component in current["components"]
        if component["kind"] == "removal"
    }
    addition_codes = {
        component["code"] for component in current["components"]
        if component["kind"] == "addition"
    }
    supported = 0
    components = []
    for component in current["components"]:
        if component["status"] not in {"unmatched", "code_only"}:
            components.append(component)
            continue
        fallback_component = fallback_components[component["component_id"]]
        fallback_status = fallback_component["status"]
        linked_transition = False
        for row_id in fallback_component["evidence_row_ids"]:
            row = evidence_by_id[row_id]
            if row["note_class"] != "code_transition":
                continue
            if (
                component["kind"] == "addition"
                and row["base_ma"] in removal_codes
            ) or (
                component["kind"] == "removal"
                and row["succ_ma"] in addition_codes
            ):
                linked_transition = True
                break
        if fallback_status.startswith("supported"):
            resolved_status = "supported_long_range"
        elif fallback_status == "code_only" and linked_transition:
            resolved_status = "supported_long_range_code_transition"
        else:
            components.append(component)
            continue
        merged = {
            **component,
            "targeted_status": component["status"],
            "status": resolved_status,
            "evidence_row_ids": fallback_component["evidence_row_ids"],
            "long_range_fallback_path": source_path,
        }
        merged.pop("targeted_window_reasons", None)
        if fallback_component.get("evidence_signals"):
            merged["evidence_signals"] = fallback_component["evidence_signals"]
        components.append(merged)
        supported += 1
    has_residue = any(
        component["status"] in {"unmatched", "code_only"}
        for component in components
    )
    return {
        **current,
        "long_range_fallback_path": source_path,
        "components": components,
        "status": "targeted_window_required" if has_residue else "crosswalk_supported",
    }, supported


def build_crosswalk_reconciliation(*, manifest_path: Path = MANIFEST,
                                   legal_index_path: Path = LEGAL_INDEX,
                                   observed_changes_path: Path = OBSERVED_CHANGES) -> dict:
    """Build the complete offline Task-4 crosswalk reconciliation artifact."""
    manifest = _load_manifest(manifest_path)
    manifest_by_path = _manifest_by_path(manifest)
    observed = json.loads(observed_changes_path.read_text(encoding="utf-8"))
    soap_entries = sorted(
        (
            entry for entry in manifest
            if entry["path"].startswith("soap/DanhMucPhuongXa_")
            and entry["path"].endswith(".xml.gz")
        ),
        key=lambda entry: entry["path"],
    )
    if (
        observed["input_fingerprints"]["ward_soap_manifest_sha256"]
        != soap_manifest_fingerprint(soap_entries)
    ):
        raise ValueError("observed changes were not built from the current SOAP manifest")
    if (
        observed["scope"]["source_floor"], observed["scope"]["as_of"]
    ) != (SOURCE_FLOOR, AS_OF):
        raise ValueError("observed-change scope drifted")

    changed_intervals = [
        interval for interval in observed["intervals"]
        if interval["normalized_changed"]
    ]
    if len(changed_intervals) != 179:
        raise ValueError(f"expected 179 observed events, got {len(changed_intervals)}")
    legal_by_date = _legal_instruments_by_date(legal_index_path)

    windows = []
    event_outputs = []
    evidence_rows = []
    targeted_windows = []
    assigned_event_ids = set()
    for entry in _primary_window_entries(manifest):
        if not rawcache.raw_is_verified(entry["path"]):
            raise ValueError(f"crosswalk failed verification: {entry['path']}")
        rows = read_ward_crosswalk(io.BytesIO(rawcache.read_raw(entry["path"])))
        if len(rows) != entry.get("rows"):
            raise ValueError(
                f"crosswalk row count drifted for {entry['path']}: "
                f"manifest={entry.get('rows')}, parsed={len(rows)}"
            )
        intervals = [
            interval for interval in changed_intervals
            if entry["base_date"] < interval["after_date"] <= entry["compare_date"]
        ]
        overlap = assigned_event_ids & {interval["event_id"] for interval in intervals}
        if overlap:
            raise ValueError(f"primary crosswalk windows overlap observed events: {sorted(overlap)}")
        assigned_event_ids.update(interval["event_id"] for interval in intervals)
        result = reconcile_window(
            source_path=entry["path"],
            kind=entry["kind"],
            base_date=entry["base_date"],
            compare_date=entry["compare_date"],
            rows=rows,
            intervals=intervals,
            legal_instruments_by_date=legal_by_date,
        )
        windows.append({
            **result["window"],
            "sha256": entry["sha256"],
            "bytes": entry["bytes"],
            "source_url": entry.get("source_url", ""),
            "params": entry.get("params", {}),
        })
        event_outputs.extend(result["events"])
        evidence_rows.extend(result["linked_evidence_rows"])
        targeted_windows.extend(result["targeted_windows"])

    for interval in changed_intervals:
        if interval["event_id"] in assigned_event_ids:
            continue
        event, request = _uncovered_event(
            interval, legal_by_date.get(interval["after_date"], []),
        )
        event_outputs.append(event)
        targeted_windows.append(request)

    events_by_id = {event["event_id"]: event for event in event_outputs}
    intervals_by_id = {interval["event_id"]: interval for interval in changed_intervals}
    targeted_sources = []
    reconciled_requests = []
    for request in targeted_windows:
        source_path = (
            f"crosswalk/ward_{request['base_date']}_{request['compare_date']}.xls"
        )
        entry = manifest_by_path.get(source_path)
        if entry is None or not rawcache.raw_is_verified(source_path):
            reconciled_requests.append(request)
            continue
        rows = read_ward_crosswalk(io.BytesIO(rawcache.read_raw(source_path)))
        if len(rows) != entry.get("rows"):
            raise ValueError(
                f"targeted crosswalk row count drifted for {source_path}: "
                f"manifest={entry.get('rows')}, parsed={len(rows)}"
            )
        interval = intervals_by_id[request["event_ids"][0]]
        result = reconcile_window(
            source_path=source_path,
            kind="targeted",
            base_date=request["base_date"],
            compare_date=request["compare_date"],
            rows=rows,
            intervals=[interval],
            legal_instruments_by_date=legal_by_date,
        )
        targeted_event = result["events"][0]
        events_by_id[interval["event_id"]] = _merge_targeted_event(
            events_by_id[interval["event_id"]], targeted_event, source_path,
        )
        evidence_rows.extend(result["linked_evidence_rows"])
        remaining_reasons = sorted({
            reason
            for component in targeted_event["components"]
            for reason in component.get("targeted_window_reasons", [])
        })
        reconciled_requests.append({
            **request,
            "status": "verified_residue" if remaining_reasons else "verified_reconciled",
            "source_path": source_path,
            "sha256": entry["sha256"],
            "bytes": entry["bytes"],
            "rows": len(rows),
            "remaining_reasons": remaining_reasons,
        })
        targeted_sources.append({
            "path": source_path,
            "base_date": request["base_date"],
            "compare_date": request["compare_date"],
            "sha256": entry["sha256"],
            "bytes": entry["bytes"],
            "rows": len(rows),
            "source_url": entry.get("source_url", ""),
            "params": entry.get("params", {}),
        })

    long_range_path = (
        f"crosswalk/ward_{LONG_RANGE_WINDOW[0]}_{LONG_RANGE_WINDOW[1]}.xls"
    )
    long_range_entry = manifest_by_path[long_range_path]
    if not rawcache.raw_is_verified(long_range_path):
        raise ValueError(f"long-range crosswalk failed verification: {long_range_path}")
    long_range_rows = read_ward_crosswalk(io.BytesIO(rawcache.read_raw(long_range_path)))
    if len(long_range_rows) != long_range_entry.get("rows"):
        raise ValueError("long-range crosswalk row count drifted")
    fallback_intervals = [
        intervals_by_id[event_id]
        for event_id, event in events_by_id.items()
        if any(
            component["status"] in {"unmatched", "code_only"}
            for component in event["components"]
        )
    ]
    fallback_result = reconcile_window(
        source_path=long_range_path,
        kind="long_range_fallback",
        base_date=LONG_RANGE_WINDOW[0],
        compare_date=LONG_RANGE_WINDOW[1],
        rows=long_range_rows,
        intervals=fallback_intervals,
        legal_instruments_by_date=legal_by_date,
    )
    fallback_rows_by_id = {
        row["row_id"]: row for row in fallback_result["linked_evidence_rows"]
    }
    fallback_events_by_id = {
        event["event_id"]: event for event in fallback_result["events"]
    }
    long_range_supported = 0
    for interval in fallback_intervals:
        event_id = interval["event_id"]
        events_by_id[event_id], count = _merge_long_range_fallback(
            events_by_id[event_id], fallback_events_by_id[event_id],
            fallback_rows_by_id, long_range_path,
        )
        long_range_supported += count
    evidence_rows.extend(fallback_result["linked_evidence_rows"])

    for request in reconciled_requests:
        event = events_by_id[request["event_ids"][0]]
        remaining = sorted({
            reason
            for component in event["components"]
            if component["status"] in {"unmatched", "code_only"}
            for reason in component.get(
                "targeted_window_reasons", ["soap_crosswalk_disagreement"]
            )
        })
        request["remaining_reasons"] = remaining
        request["status"] = "verified_residue" if remaining else "verified_reconciled"

    event_outputs = sorted(
        events_by_id.values(), key=lambda event: (event["after_date"], event["event_id"])
    )
    final_evidence_ids = {
        row_id
        for event in event_outputs
        for component in event["components"]
        for row_id in component["evidence_row_ids"]
    }
    evidence_rows = [
        row for row in evidence_rows if row["row_id"] in final_evidence_ids
    ]
    evidence_rows.sort(key=lambda row: row["row_id"])
    targeted_windows = sorted(
        reconciled_requests, key=lambda item: (item["compare_date"], item["base_date"])
    )
    targeted_sources.sort(key=lambda item: (item["compare_date"], item["base_date"]))
    component_statuses = Counter(
        component["status"]
        for event in event_outputs for component in event["components"]
    )
    acquisition_reason_counts = Counter(
        reason for request in targeted_windows for reason in request["reasons"]
    )
    remaining_reason_counts = Counter(
        reason for request in targeted_windows for reason in request.get("remaining_reasons", [])
    )
    summary = {
        "observed_events": len(event_outputs),
        "primary_crosswalk_windows": len(windows),
        "primary_crosswalk_rows": sum(window["rows"] for window in windows),
        "events_with_primary_crosswalk": sum(
            event["primary_crosswalk_path"] is not None for event in event_outputs
        ),
        "events_without_primary_crosswalk": sum(
            event["primary_crosswalk_path"] is None for event in event_outputs
        ),
        "event_components": sum(len(event["components"]) for event in event_outputs),
        "source_anomaly_transitions": sum(
            len(event["source_anomaly_transitions"]) for event in event_outputs
        ),
        "linked_crosswalk_rows": len(evidence_rows),
        "component_statuses": dict(sorted(component_statuses.items())),
        "code_reuse_components": component_statuses["supported_code_reuse"],
        "long_range_fallback_components_supported": long_range_supported,
        "targeted_windows": len(targeted_windows),
        "targeted_windows_reconciled": sum(
            request["status"] == "verified_reconciled" for request in targeted_windows
        ),
        "targeted_windows_with_residue": sum(
            request["status"] == "verified_residue" for request in targeted_windows
        ),
        "targeted_acquisition_reason_counts": dict(sorted(acquisition_reason_counts.items())),
        "targeted_remaining_reason_counts": dict(sorted(remaining_reason_counts.items())),
        "events_with_multiple_same_date_instruments": sum(
            len(event["candidate_legal_instrument_ids"]) > 1 for event in event_outputs
        ),
    }
    return {
        "schema_version": 1,
        "scope": {
            "tier": "ward",
            "source_floor": SOURCE_FLOOR,
            "as_of": AS_OF,
            "semantics": "crosswalk net evidence assigned to SOAP observations; no identity inference",
            "status": "targeted_crosswalk_reconciliation_complete_with_explicit_residue",
            "next_task": 5,
        },
        "input_fingerprints": {
            "manifest_path": manifest_path.as_posix(),
            "manifest_sha256": _sha256(manifest_path),
            "legal_index_path": legal_index_path.as_posix(),
            "legal_index_sha256": _sha256(legal_index_path),
            "observed_changes_path": observed_changes_path.as_posix(),
            "observed_changes_sha256": _sha256(observed_changes_path),
        },
        "summary": summary,
        "primary_windows": windows,
        "long_range_fallback_source": {
            "path": long_range_path,
            "sha256": long_range_entry["sha256"],
            "bytes": long_range_entry["bytes"],
            "rows": len(long_range_rows),
            "source_url": long_range_entry.get("source_url", ""),
            "params": long_range_entry.get("params", {}),
        },
        "targeted_sources": targeted_sources,
        "events": event_outputs,
        "crosswalk_evidence_rows": evidence_rows,
        "targeted_windows": targeted_windows,
    }


def serialize_reconciliation(artifact: dict) -> str:
    return json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_reconciliation(artifact: dict, output: Path = OUTPUT) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(serialize_reconciliation(artifact), encoding="utf-8")
    temporary.replace(output)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Reconcile ward SOAP changes to crosswalks.")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    artifact = build_crosswalk_reconciliation()
    rendered = serialize_reconciliation(artifact)
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != rendered:
            raise SystemExit(f"ward crosswalk reconciliation is missing or stale: {args.output}")
        action = "verified"
    else:
        write_reconciliation(artifact, args.output)
        action = "wrote"
    summary = artifact["summary"]
    print(
        f"{action} {args.output}: {summary['observed_events']} events, "
        f"{summary['event_components']} components, "
        f"{summary['linked_crosswalk_rows']} evidence rows, "
        f"{summary['targeted_windows']} targeted windows"
    )


if __name__ == "__main__":
    main()
