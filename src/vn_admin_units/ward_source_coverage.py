"""Build the deterministic ward source/provenance coverage ledger.

This is the offline denominator for historical ward work. It inventories the
verified SOAP, crosswalk, legal-source, observed-change, and crosswalk-
reconciliation artifacts; collapses duplicate legal-index rows without
discarding their variants; and exposes every remaining classification gap.

Usage:
  uv run python -m vn_admin_units.ward_source_coverage
  uv run python -m vn_admin_units.ward_source_coverage --audit
  uv run python -m vn_admin_units.ward_source_coverage --open-note
  uv run python -m vn_admin_units.ward_source_coverage --check
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from vn_admin_units import rawcache
from vn_admin_units.crosscheck_decrees import is_ward_structural
from vn_admin_units.ward_legal_linkage import (
    COMPOSITION_2025,
    OVERRIDES as LEGAL_LINKAGE_OVERRIDES,
    build_legal_linkage,
)
from vn_admin_units.ward_observed_changes import soap_manifest_fingerprint


LEGAL_INDEX = Path("data/raw/nghidinh.json")
MANIFEST = Path("data/raw/manifest.jsonl")
OBSERVED_CHANGES = Path("data/ward-observed-changes.json")
RECONCILIATION = Path("data/ward-crosswalk-reconciliation.json")
LEGAL_SOURCES = Path("data/ward-legal-sources.json")
OFFICIAL_LEADS = Path("data/ward-legal-official-leads.json")
OUTPUT = Path("data/ward-source-coverage.json")
OPEN_NOTE = Path("docs/ward-source-open-instruments.md")

SOURCE_FLOOR = "2002-01-01"
AS_OF = "2026-08-27"

LOCKED = {
    "soap_artifacts": 204,
    "soap_rows": 2_202_543,
    "soap_unique_payloads": 180,
    "ward_crosswalk_artifacts": 39,
    "ward_crosswalk_rows": 417_158,
    "yearly_crosswalks": 21,
    "targeted_crosswalks": 15,
    "legal_index_records": 544,
    "ward_relevant_legal_rows": 453,
    "ward_relevant_effective_dates_from_2005": 179,
    "unique_ward_instruments": 449,
    "duplicate_instrument_keys": 4,
    "verified_2025_resolution_pairs": 34,
    "observed_change_intervals": 179,
}

_WARD_CROSSWALK = re.compile(
    r"^crosswalk/ward_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.xls$"
)
_SOAP = re.compile(r"^soap/DanhMucPhuongXa_(\d{4}-\d{2}-\d{2})\.xml\.gz$")


def normalize_date(value: str) -> str:
    """Normalize NSO DD/MM/YYYY or an existing ISO date to YYYY-MM-DD."""
    value = str(value or "").strip()
    for pattern in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"unsupported date: {value!r}")


def normalize_code(value: str) -> str:
    code = "".join(str(value or "").upper().split())
    if not code:
        raise ValueError("legal instrument has no code")
    return code


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_manifest(path: Path = MANIFEST) -> list[dict]:
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    paths = [record["path"] for record in records]
    if len(paths) != len(set(paths)):
        duplicates = sorted(path for path in set(paths) if paths.count(path) > 1)
        raise ValueError(f"raw manifest contains duplicate paths: {duplicates}")
    return records


def ward_crosswalk_manifest_fingerprint(entries: list[dict]) -> str:
    """Hash only the raw crosswalk inputs consumed by reconciliation."""
    relevant = [
        {
            "path": entry["path"],
            "sha256": entry["sha256"],
            "bytes": entry["bytes"],
            "rows": entry.get("rows", 0),
        }
        for entry in entries
        if _WARD_CROSSWALK.fullmatch(entry["path"])
    ]
    rendered = json.dumps(
        sorted(relevant, key=lambda entry: entry["path"]),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(rendered).hexdigest()


def _require(label: str, actual, expected) -> None:
    if actual != expected:
        raise ValueError(f"locked {label} drifted: expected {expected!r}, got {actual!r}")


def _source_class(entry: dict) -> str:
    method = str(entry.get("method", "")).lower()
    host = (urlparse(str(entry.get("source_url", ""))).hostname or "").lower()
    if method.startswith("official ") or host.endswith("chinhphu.vn"):
        return "official"
    if host.endswith("gov.vn") or host.endswith("quochoi.vn"):
        return "official"
    return "secondary"


def _media_type(path: str) -> str:
    if path.endswith(".pdf"):
        return "pdf"
    if path.endswith(".html") or path.endswith(".htm"):
        return "html"
    return "other"


def _source_descriptor(entry: dict) -> dict:
    return {
        "path": entry["path"],
        "source_url": entry.get("source_url", ""),
        "source_class": _source_class(entry),
        "media_type": _media_type(entry["path"]),
        "method": entry.get("method", ""),
        "sha256": entry["sha256"],
        "bytes": entry["bytes"],
        "retrieved_at": entry.get("retrieved_at", ""),
        "declared_media_type": entry.get("declared_media_type", ""),
        "detected_media_type": entry.get("detected_media_type", ""),
    }


def _document_key(entry: dict) -> tuple[str, str] | None:
    doc = entry.get("doc") or {}
    code = entry.get("document_code") or doc.get("so")
    effective = entry.get("effective_date") or doc.get("hieu_luc")
    if not code or not effective:
        return None
    return normalize_code(code), normalize_date(effective)


def index_legal_sources(manifest: list[dict], verifier=rawcache.raw_is_verified) -> dict:
    """Index verified cached legal artifacts by (code, effective date)."""
    indexed: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for entry in manifest:
        key = _document_key(entry)
        if key is None:
            continue
        if not verifier(entry["path"]):
            raise ValueError(f"cached legal source failed verification: {entry['path']}")
        indexed[key].append(_source_descriptor(entry))
    return {
        key: sorted(value, key=lambda source: (source["media_type"], source["path"]))
        for key, value in indexed.items()
    }


def _is_closed_2025_pair(code: str, effective_date: str, primary: list[dict]) -> bool:
    match = re.fullmatch(r"(\d+)/NQ-UBTVQH15", code)
    media = {source["media_type"] for source in primary}
    return (
        match is not None
        and 1654 <= int(match.group(1)) <= 1687
        and effective_date == "2025-07-01"
        and media == {"html", "pdf"}
    )


def _load_legal_registry(path: Path) -> tuple[dict, dict]:
    registry = json.loads(path.read_text(encoding="utf-8"))
    instruments = registry.get("instruments", [])
    if len(instruments) != LOCKED["unique_ward_instruments"]:
        raise ValueError(
            "legal source registry denominator drifted: "
            f"expected {LOCKED['unique_ward_instruments']}, got {len(instruments)}"
        )
    indexed = {item["instrument_id"]: item for item in instruments}
    if len(indexed) != len(instruments):
        raise ValueError("legal source registry contains duplicate instrument IDs")
    return registry, indexed


def _secondary_registry_sources(item: dict) -> list[dict]:
    return [
        {
            "path": "",
            "source_url": url,
            "source_class": "secondary",
            "media_type": "metadata_url",
            "method": "secondary legal discovery URL (not archived as primary evidence)",
            "sha256": "",
            "bytes": 0,
            "retrieved_at": "",
            "declared_media_type": "",
            "detected_media_type": "",
        }
        for url in item.get("secondary_urls", [])
    ]


def _source_discovery(item: dict | None) -> dict:
    if item is None:
        return {"discovery_status": "not_registered"}
    return {
        key: item[key]
        for key in (
            "discovery_status",
            "source_provider",
            "official_code",
            "code_match_status",
            "issued_date",
            "effective_gap_days",
            "date_match_status",
            "official_effective_date",
            "effective_date_match_status",
            "metadata_url",
        )
        if key in item
    }


def build_instruments(records: list[dict], source_index: dict,
                      registry_index: dict | None = None) -> list[dict]:
    """Collapse legal-index duplicates into stable instrument records."""
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for record in records:
        key = normalize_code(record.get("code", "")), normalize_date(record.get("hieu_luc", ""))
        grouped[key].append(record)

    instruments = []
    registry_index = registry_index or {}
    for (code, effective_date), variants in sorted(grouped.items(), key=lambda item: (item[0][1], item[0][0])):
        sources = source_index.get((code, effective_date), [])
        primary = [source for source in sources if source["source_class"] == "official"]
        instrument_id = f"{code}@{effective_date}"
        registry_item = registry_index.get(instrument_id)
        secondary = [source for source in sources if source["source_class"] != "official"]
        secondary.extend(_secondary_registry_sources(registry_item or {}))
        secondary = sorted(
            {source["source_url"]: source for source in secondary}.values(),
            key=lambda source: (source["media_type"], source["source_url"]),
        )
        urls = sorted({str(record.get("url", "")).strip() for record in variants if str(record.get("url", "")).strip()})
        official_metadata = any(_source_class({"source_url": url}) == "official" for url in urls)
        if primary:
            source_status = "verified_official_artifact"
        elif official_metadata:
            source_status = "official_metadata_only"
        elif secondary or urls:
            source_status = "secondary_only"
        else:
            source_status = "missing"

        closed_2025 = _is_closed_2025_pair(code, effective_date, primary)
        instruments.append({
            "instrument_id": instrument_id,
            "code": code,
            "effective_date": effective_date,
            "index_occurrences": len(variants),
            "title_variants": sorted({str(record.get("noi_dung", "")).strip() for record in variants}),
            "index_urls": urls,
            "classification": "lineage" if closed_2025 else "unresolved",
            "review_status": "verified_2025_boundary" if closed_2025 else "pending",
            "source_status": source_status,
            "source_discovery": _source_discovery(registry_item),
            "primary_sources": primary,
            "secondary_sources": secondary,
            "event_ids": [],
        })
    return instruments


def crosswalk_kind(path: str) -> str:
    match = _WARD_CROSSWALK.fullmatch(path)
    if not match:
        raise ValueError(f"unexpected ward crosswalk path: {path}")
    base, compare = match.groups()
    if (base, compare) == ("2002-01-01", "2025-06-30"):
        return "long_range"
    if (base, compare) == ("2025-06-30", "2025-07-01"):
        return "reform_boundary"
    if (base, compare) == ("2025-07-01", "2026-08-27"):
        return "post_reform"
    base_date = datetime.strptime(base, "%Y-%m-%d").date()
    compare_date = datetime.strptime(compare, "%Y-%m-%d").date()
    if (
        base_date.month == base_date.day == 1
        and compare_date.month == compare_date.day == 1
        and compare_date.year == base_date.year + 1
    ):
        return "yearly"
    return "targeted"


def _verified_entries(entries: list[dict], label: str) -> None:
    failed = [entry["path"] for entry in entries if not rawcache.raw_is_verified(entry["path"])]
    if failed:
        raise ValueError(f"{label} artifacts failed verification: {failed}")


def _soap_inventory(entries: list[dict]) -> dict:
    soap = sorted(
        (entry for entry in entries if _SOAP.fullmatch(entry["path"])),
        key=lambda entry: entry["path"],
    )
    _verified_entries(soap, "ward SOAP")
    artifacts = []
    for entry in soap:
        date = _SOAP.fullmatch(entry["path"]).group(1)
        artifacts.append({
            "date": date,
            "path": entry["path"],
            "sha256": entry["sha256"],
            "bytes": entry["bytes"],
            "content_sha256": entry.get("content_sha256", entry["sha256"]),
            "content_bytes": entry.get("content_bytes", entry["bytes"]),
            "retrieved_at": entry.get("retrieved_at", ""),
            "source_url": entry.get("source_url", ""),
            "params": entry.get("params", {}),
            "reasons": entry.get("reasons", []),
            "rows": entry.get("rows", 0),
            "duplicate_rows": entry.get("duplicate_rows", 0),
            "conflicting_identity_rows": entry.get("conflicting_identity_rows", 0),
            "missing_parent_codes": entry.get("missing_parent_codes", 0),
        })
    return {
        "artifacts": artifacts,
        "rows": sum(item["rows"] for item in artifacts),
        "unique_payloads": len({item["content_sha256"] for item in artifacts}),
        "stored_bytes": sum(item["bytes"] for item in artifacts),
        "decoded_bytes": sum(item["content_bytes"] for item in artifacts),
        "duplicate_rows": sum(item["duplicate_rows"] for item in artifacts),
        "conflicting_identity_rows": sum(item["conflicting_identity_rows"] for item in artifacts),
        "missing_parent_codes": sum(item["missing_parent_codes"] for item in artifacts),
    }


def _source_floor_evidence(soap: dict, events: list[dict]) -> dict:
    """State the bounded conclusion supported by the earliest SOAP anchors."""
    snapshots = {item["date"]: item for item in soap["artifacts"]}
    floor = snapshots.get(SOURCE_FLOOR)
    comparison = snapshots.get("2004-01-01")
    if floor is None or comparison is None:
        raise ValueError("source-floor evidence snapshots are missing")
    _require(
        "2002-to-2004 endpoint content hash",
        comparison["content_sha256"],
        floor["content_sha256"],
    )

    transition_id = "soap:2004-01-01->2004-07-01"
    transition = next(
        (event for event in events if event["event_id"] == transition_id), None,
    )
    if transition is None:
        raise ValueError(f"first observed transition is missing: {transition_id}")
    assignments = transition["legal_evidence"]["component_assignment_counts"]
    if set(assignments) != {"code_scheme_transition"}:
        raise ValueError(
            "first observed transition is no longer exclusively a code-scheme "
            f"transition: {assignments}"
        )

    return {
        "endpoint_interval": {
            "before_date": floor["date"],
            "before_path": floor["path"],
            "after_date": comparison["date"],
            "after_path": comparison["path"],
            "content_sha256": floor["content_sha256"],
            "payload_relation": "identical",
        },
        "verdict": "no_endpoint_state_difference_observed",
        "limitation": (
            "matching_endpoint_payloads_do_not_exclude_transient_"
            "intra_interval_changes"
        ),
        "first_observed_transition": {
            "event_id": transition["event_id"],
            "before_date": transition["before_date"],
            "after_date": transition["after_date"],
            "classification": "code_scheme_transition",
            "component_count": assignments["code_scheme_transition"],
            "status": transition["status"],
        },
    }


def _crosswalk_inventory(entries: list[dict]) -> dict:
    crosswalks = sorted(
        (entry for entry in entries if entry["path"].startswith("crosswalk/ward_")),
        key=lambda entry: entry["path"],
    )
    _verified_entries(crosswalks, "ward crosswalk")
    artifacts = []
    for entry in crosswalks:
        match = _WARD_CROSSWALK.fullmatch(entry["path"])
        if match is None:
            raise ValueError(f"unexpected ward crosswalk path: {entry['path']}")
        base, compare = match.groups()
        artifacts.append({
            "path": entry["path"],
            "kind": crosswalk_kind(entry["path"]),
            "base_date": base,
            "compare_date": compare,
            "sha256": entry["sha256"],
            "bytes": entry["bytes"],
            "retrieved_at": entry.get("retrieved_at", ""),
            "source_url": entry.get("source_url", ""),
            "method": entry.get("method", ""),
            "rows": entry.get("rows", 0),
        })
    return {
        "artifacts": artifacts,
        "rows": sum(item["rows"] for item in artifacts),
        "yearly_count": sum(item["kind"] == "yearly" for item in artifacts),
        "targeted_count": sum(item["kind"] == "targeted" for item in artifacts),
        "bytes": sum(item["bytes"] for item in artifacts),
    }


def _resolution_pairs(instruments: list[dict]) -> list[dict]:
    pairs = []
    for instrument in instruments:
        if instrument["review_status"] != "verified_2025_boundary":
            continue
        by_type = {source["media_type"]: source for source in instrument["primary_sources"]}
        pairs.append({
            "instrument_id": instrument["instrument_id"],
            "code": instrument["code"],
            "effective_date": instrument["effective_date"],
            "html": by_type["html"],
            "pdf": by_type["pdf"],
        })
    return sorted(pairs, key=lambda pair: pair["code"])


def _observed_change_inventory(path: Path, manifest: list[dict]) -> tuple[dict, list[dict]]:
    observed = json.loads(path.read_text(encoding="utf-8"))
    summary = observed.get("summary", {})
    scope = observed.get("scope", {})
    ward_soap = sorted(
        (
            entry for entry in manifest
            if _SOAP.fullmatch(entry["path"])
        ),
        key=lambda entry: entry["path"],
    )
    if (
        observed.get("input_fingerprints", {}).get("ward_soap_manifest_sha256")
        != soap_manifest_fingerprint(ward_soap)
    ):
        raise ValueError("observed-change inventory was not built from the current SOAP manifest")
    _require("observed-change source floor", scope.get("source_floor"), SOURCE_FLOOR)
    _require("observed-change as-of date", scope.get("as_of"), AS_OF)
    _require("observed-change snapshots", summary.get("snapshots"), LOCKED["soap_artifacts"])
    _require("observed-change intervals", summary.get("intervals"), LOCKED["soap_artifacts"] - 1)
    _require(
        "materialized observed snapshot audits",
        len(observed.get("snapshot_audits", [])),
        summary["snapshots"],
    )
    _require(
        "materialized observed intervals",
        len(observed.get("intervals", [])),
        summary["intervals"],
    )
    _require(
        "observed change-bearing intervals",
        summary.get("changed_intervals"),
        LOCKED["observed_change_intervals"],
    )

    events = []
    for interval in observed.get("intervals", []):
        if not interval.get("normalized_changed"):
            continue
        events.append({
            "event_id": interval["event_id"],
            "kind": "observed_snapshot_delta",
            "before_date": interval["before_date"],
            "after_date": interval["after_date"],
            "observation_counts": interval["counts"],
            "observed_evidence": {
                "artifact_path": path.as_posix(),
                "before_path": interval["before_path"],
                "before_content_sha256": interval["before_content_sha256"],
                "after_path": interval["after_path"],
                "after_content_sha256": interval["after_content_sha256"],
            },
            "crosswalk_evidence": [],
            "legal_instrument_ids": [],
            "status": "pending_crosswalk_legal_reconciliation",
        })
    _require("materialized observed events", len(events), summary["changed_intervals"])
    event_ids = [event["event_id"] for event in events]
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("observed-change inventory contains duplicate event IDs")

    inventory = {
        "path": path.as_posix(),
        "sha256": _sha256(path),
        "schema_version": observed.get("schema_version"),
        "snapshots": summary["snapshots"],
        "intervals": summary["intervals"],
        "changed_intervals": summary["changed_intervals"],
        "normalized_no_change_intervals": summary["normalized_no_change_intervals"],
        "same_code_changes": summary["same_code_changes"],
        "additions": summary["additions"],
        "removals": summary["removals"],
        "source_anomaly_transitions": summary["source_anomaly_transitions"],
    }
    return inventory, events


def _crosswalk_reconciliation_inventory(path: Path, *, manifest_path: Path,
                                        legal_index_path: Path,
                                        observed_changes_path: Path) -> tuple[dict, dict]:
    reconciliation = json.loads(path.read_text(encoding="utf-8"))
    fingerprints = reconciliation.get("input_fingerprints", {})
    expected = {
        "ward_crosswalk_manifest_sha256": ward_crosswalk_manifest_fingerprint(
            _load_manifest(manifest_path)
        ),
        "legal_index_sha256": _sha256(legal_index_path),
        "observed_changes_sha256": _sha256(observed_changes_path),
    }
    actual = {key: fingerprints.get(key) for key in expected}
    if actual != expected:
        raise ValueError(
            "crosswalk reconciliation input fingerprints are stale: "
            f"actual={actual}, expected={expected}"
        )
    summary = reconciliation.get("summary", {})
    _require("reconciled observed events", summary.get("observed_events"), 179)
    _require("reconciled targeted windows", summary.get("targeted_windows"), 15)
    _require(
        "targeted windows retaining residue",
        summary.get("targeted_windows_with_residue"),
        1,
    )
    events = reconciliation.get("events", [])
    _require("materialized reconciled events", len(events), summary["observed_events"])
    by_id = {event["event_id"]: event for event in events}
    if len(by_id) != len(events):
        raise ValueError("crosswalk reconciliation contains duplicate event IDs")
    inventory = {
        "path": path.as_posix(),
        "sha256": _sha256(path),
        "schema_version": reconciliation.get("schema_version"),
        **summary,
    }
    return inventory, by_id


def build_coverage(*, manifest_path: Path = MANIFEST,
                   legal_index_path: Path = LEGAL_INDEX,
                   observed_changes_path: Path = OBSERVED_CHANGES,
                   reconciliation_path: Path = RECONCILIATION,
                   legal_sources_path: Path = LEGAL_SOURCES) -> dict:
    """Build and validate the offline source and observed-event ledger."""
    manifest = _load_manifest(manifest_path)
    legal_records = json.loads(legal_index_path.read_text(encoding="utf-8"))
    ward_records = [
        record for record in legal_records
        if is_ward_structural(str(record.get("noi_dung", "")))
    ]
    legal_registry, registry_index = _load_legal_registry(legal_sources_path)
    sources = index_legal_sources(manifest)
    instruments = build_instruments(ward_records, sources, registry_index)
    soap = _soap_inventory(manifest)
    crosswalks = _crosswalk_inventory(manifest)
    resolution_pairs = _resolution_pairs(instruments)
    observed_changes, events = _observed_change_inventory(
        observed_changes_path, manifest,
    )
    reconciliation, reconciled_events = _crosswalk_reconciliation_inventory(
        reconciliation_path,
        manifest_path=manifest_path,
        legal_index_path=legal_index_path,
        observed_changes_path=observed_changes_path,
    )
    for event in events:
        reconciled = reconciled_events.get(event["event_id"])
        if reconciled is None:
            raise ValueError(f"event is absent from crosswalk reconciliation: {event['event_id']}")
        component_statuses = Counter(
            component["status"] for component in reconciled["components"]
        )
        event["crosswalk_evidence"] = {
            "reconciliation_path": reconciliation_path.as_posix(),
            "primary_crosswalk_path": reconciled["primary_crosswalk_path"],
            "targeted_crosswalk_path": reconciled.get("targeted_crosswalk_path"),
            "component_count": len(reconciled["components"]),
            "component_statuses": dict(sorted(component_statuses.items())),
        }
        event["candidate_legal_instrument_ids"] = reconciled[
            "candidate_legal_instrument_ids"
        ]
        event["crosswalk_status"] = (
            "crosswalk_residue_legal_classification_pending"
            if reconciled["status"] != "crosswalk_supported"
            else "crosswalk_supported_legal_reconciliation_pending"
        )
        event["status"] = event["crosswalk_status"]

    linkage = build_legal_linkage(
        instruments,
        events,
        json.loads(reconciliation_path.read_text(encoding="utf-8")),
        json.loads(observed_changes_path.read_text(encoding="utf-8")),
        sources,
    )
    for instrument in instruments:
        review = linkage["instrument_reviews"][instrument["instrument_id"]]
        instrument.update(review)
    for event in events:
        review = linkage["event_reviews"][event["event_id"]]
        event["legal_instrument_ids"] = review["legal_instrument_ids"]
        event["legal_evidence"] = {
            key: value for key, value in review.items()
            if key not in {"legal_instrument_ids", "status"}
        }
        event["status"] = review["status"]

    effective_dates_from_2005 = {
        normalize_date(record["hieu_luc"])
        for record in ward_records
        if normalize_date(record["hieu_luc"]) >= "2005-01-01"
    }
    duplicate_instruments = [
        instrument for instrument in instruments if instrument["index_occurrences"] > 1
    ]
    unresolved = [
        instrument["instrument_id"]
        for instrument in instruments
        if instrument["classification"] == "unresolved"
    ]
    primary_source_open = [
        instrument["instrument_id"]
        for instrument in instruments
        if instrument["source_status"] != "verified_official_artifact"
    ]
    change_bearing_source_open = sorted({
        link["instrument_id"]
        for review in linkage["event_reviews"].values()
        for link in review["instrument_links"]
        if link["component_count"]
        and link["source_status"] != "verified_official_artifact"
    })
    source_floor_evidence = _source_floor_evidence(soap, events)
    source_gate_status = "open" if change_bearing_source_open else "pass"

    summary = {
        "soap_artifacts": len(soap["artifacts"]),
        "soap_rows": soap["rows"],
        "soap_unique_payloads": soap["unique_payloads"],
        "ward_crosswalk_artifacts": len(crosswalks["artifacts"]),
        "ward_crosswalk_rows": crosswalks["rows"],
        "yearly_crosswalks": crosswalks["yearly_count"],
        "targeted_crosswalks": crosswalks["targeted_count"],
        "legal_index_records": len(legal_records),
        "ward_relevant_legal_rows": len(ward_records),
        "ward_relevant_effective_dates_from_2005": len(effective_dates_from_2005),
        "unique_ward_instruments": len(instruments),
        "duplicate_instrument_keys": len(duplicate_instruments),
        "verified_2025_resolution_pairs": len(resolution_pairs),
        "observed_change_intervals": len(events),
        "unclassified_instruments": len(unresolved),
        "classified_legal_index_rows": linkage["summary"]["classified_legal_index_rows"],
        "classified_instruments": linkage["summary"]["classified_instruments"],
        "instrument_classifications": linkage["summary"]["instrument_classifications"],
        "instrument_observation_statuses": linkage["summary"]["instrument_observation_statuses"],
        "reviewed_event_statuses": linkage["summary"]["event_statuses"],
        "component_assignment_counts": linkage["summary"]["component_assignment_counts"],
        "context_only_components": linkage["summary"]["context_only_components"],
        "change_bearing_source_open_instruments": len(change_bearing_source_open),
        "primary_source_open_instruments": len(primary_source_open),
        "official_source_matches": legal_registry["summary"]["official_matches"],
        "official_source_not_found": legal_registry["summary"]["status_counts"].get(
            "official_not_found", 0
        ),
        "secondary_tvpl_urls": legal_registry["summary"]["secondary_tvpl_urls"],
        "events": len(events),
        "crosswalk_supported_events": sum(
            event["crosswalk_status"] == "crosswalk_supported_legal_reconciliation_pending"
            for event in events
        ),
        "crosswalk_residue_events": sum(
            event["crosswalk_status"] == "crosswalk_residue_legal_classification_pending"
            for event in events
        ),
    }
    for label, expected in LOCKED.items():
        _require(label, summary[label], expected)
    _require("SOAP source floor", soap["artifacts"][0]["date"], SOURCE_FLOOR)
    _require("SOAP as-of date", soap["artifacts"][-1]["date"], AS_OF)
    _require("SOAP missing parents", soap["missing_parent_codes"], 0)

    return {
        "schema_version": 6,
        "scope": {
            "tier": "ward",
            "source_floor": SOURCE_FLOOR,
            "as_of": AS_OF,
            "status": (
                "source_audit_complete_bounded_residue"
                if source_gate_status == "open"
                else "source_audit_complete"
            ),
            "source_gate_status": source_gate_status,
            "next_task": 7 if source_gate_status == "open" else 8,
        },
        "source_floor_evidence": source_floor_evidence,
        "input_fingerprints": {
            "manifest_path": manifest_path.as_posix(),
            "manifest_sha256": _sha256(manifest_path),
            "legal_index_path": legal_index_path.as_posix(),
            "legal_index_sha256": _sha256(legal_index_path),
            "observed_changes_path": observed_changes_path.as_posix(),
            "observed_changes_sha256": observed_changes["sha256"],
            "crosswalk_reconciliation_path": reconciliation_path.as_posix(),
            "crosswalk_reconciliation_sha256": reconciliation["sha256"],
            "legal_sources_path": legal_sources_path.as_posix(),
            "legal_sources_sha256": _sha256(legal_sources_path),
            "legal_linkage_overrides_path": LEGAL_LINKAGE_OVERRIDES.as_posix(),
            "legal_linkage_overrides_sha256": _sha256(LEGAL_LINKAGE_OVERRIDES),
            "ward_2025_composition_path": COMPOSITION_2025.as_posix(),
            "ward_2025_composition_sha256": _sha256(COMPOSITION_2025),
        },
        "summary": summary,
        "inventories": {
            "soap": soap,
            "crosswalks": crosswalks,
            "observed_changes": observed_changes,
            "crosswalk_reconciliation": reconciliation,
            "legal_sources": {
                "path": legal_sources_path.as_posix(),
                "sha256": _sha256(legal_sources_path),
                "schema_version": legal_registry.get("schema_version"),
                "input_fingerprints": legal_registry.get("input_fingerprints", {}),
                "summary": legal_registry["summary"],
            },
            "verified_2025_resolution_pairs": resolution_pairs,
        },
        "legal_instruments": instruments,
        "supplemental_legal_instruments": linkage["supplemental_instruments"],
        "events": events,
        "residue": {
            "event_inventory_status": "complete_source_audit_bounded_residue",
            "source_gate_status": source_gate_status,
            "crosswalk_residue_event_ids": [
                event["event_id"] for event in events
                if event["crosswalk_status"] == "crosswalk_residue_legal_classification_pending"
            ],
            "legal_unlinked_event_ids": [],
            "unclassified_instrument_ids": unresolved,
            "primary_source_open_instrument_ids": primary_source_open,
            "change_bearing_source_open_instrument_ids": change_bearing_source_open,
            "duplicate_legal_index_keys": [
                {
                    "instrument_id": instrument["instrument_id"],
                    "index_occurrences": instrument["index_occurrences"],
                    "title_variants": instrument["title_variants"],
                }
                for instrument in duplicate_instruments
            ],
        },
    }


def serialize_coverage(coverage: dict) -> str:
    return json.dumps(coverage, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_coverage(coverage: dict, output: Path = OUTPUT) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(serialize_coverage(coverage), encoding="utf-8")
    temporary.replace(output)


def _load_official_leads(path: Path = OFFICIAL_LEADS) -> dict[str, dict]:
    """Load unarchived official-page leads without treating them as evidence."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported official-lead schema")
    leads = payload.get("leads", [])
    indexed = {lead["instrument_id"]: lead for lead in leads}
    if len(indexed) != len(leads):
        raise ValueError("official leads contain duplicate instrument IDs")
    for lead in leads:
        if not lead.get("official_page_urls"):
            raise ValueError(
                f"official lead has no page URL: {lead['instrument_id']}"
            )
        for url in lead["official_page_urls"]:
            host = (urlparse(url).hostname or "").lower()
            if host not in {"vbpl.vn", "vbpl.moj.gov.vn"}:
                raise ValueError(
                    f"official lead has an unexpected host: {lead['instrument_id']}"
                )
    return indexed


def render_open_source_note(
    coverage: dict,
    official_leads_path: Path = OFFICIAL_LEADS,
) -> str:
    """Render the source-open instruments as a human-searchable checklist."""
    open_ids = set(coverage["residue"]["primary_source_open_instrument_ids"])
    change_bearing_ids = set(
        coverage["residue"]["change_bearing_source_open_instrument_ids"]
    )
    instruments = [
        instrument for instrument in coverage["legal_instruments"]
        if instrument["instrument_id"] in open_ids
    ]
    if len(instruments) != coverage["summary"]["primary_source_open_instruments"]:
        raise ValueError("source-open note denominator does not match the audit")
    official_leads = _load_official_leads(official_leads_path)
    stale_leads = sorted(set(official_leads) - open_ids)
    if stale_leads:
        raise ValueError(f"official leads are no longer source-open: {stale_leads}")

    lines = [
        "# Ward legal sources still open",
        "",
        (
            "Generated from `data/ward-source-coverage.json` by "
            "`vn_admin_units.ward_source_coverage --open-note`."
        ),
        "",
        (
            f"Current audit: **{len(instruments)} primary-source-open instruments**; "
            f"**{len(change_bearing_ids)} are tied to observed ward changes**."
        ),
        "",
        "## Queue history",
        "",
        (
            "The personal-search checkpoint at commit `89107d0` recorded **39 open "
            "instruments**, including **37 change-bearing instruments**. Resolution "
            "721/NQ-UBTVQH15 was subsequently recovered from the National Assembly, "
            "and Resolution 39/NQ-CP from the Government legal portal. Later "
            "recoveries, if any, are reflected in the live counts above."
        ),
        "",
        (
            f"Exact official-page leads are recorded below for **{len(official_leads)} "
            f"of the {len(instruments)} current items**. These links are leads only: "
            "none count as "
            "recovered provenance until the full official page or original attachment "
            "is saved, hashed, registered, and verified offline."
        ),
        "",
        "## What counts as a useful find",
        "",
        (
            "Please look for a complete enacted text or original signed/publication "
            "file on an official government source. Useful hosts include `vbpl.vn`, "
            "`chinhphu.vn`, `quochoi.vn`, the Government Gazette, and provincial "
            "or agency `gov.vn` sites."
        ),
        "",
        (
            "Send back the instrument ID below, the exact official page URL, and the "
            "direct PDF/DOC/RTF/ZIP URL or a browser-saved copy when one exists. Date "
            "or code discrepancies are useful evidence; do not edit them away."
        ),
        "",
        (
            "TVPL links are included only to confirm identity and title. TVPL pages, "
            "search snippets, news articles, and editorial summaries do **not** close "
            "the official-source requirement."
        ),
        "",
        "## Checklist",
    ]
    current_year = None
    evidence_labels = {
        "missing": "no source URL recorded",
        "secondary_only": "secondary identity reference only",
        "official_metadata_only": "official metadata only; original still needed",
    }
    for instrument in instruments:
        year = instrument["effective_date"][:4]
        if year != current_year:
            lines.extend(["", f"### {year}", ""])
            current_year = year
        priority = (
            "**Change-bearing**"
            if instrument["instrument_id"] in change_bearing_ids
            else "**Context-only / superseded index row**"
        )
        title = " / ".join(instrument["title_variants"])
        lines.append(
            f"- [ ] {priority} `{instrument['instrument_id']}` — {title}"
        )
        lines.append(
            "  - Current evidence: "
            f"{evidence_labels.get(instrument['source_status'], instrument['source_status'])}."
        )
        references = sorted({
            source["source_url"]
            for source in instrument["secondary_sources"]
            if source.get("source_url")
        })
        for reference in references:
            lines.append(f"  - Identity reference only: <{reference}>")
        lead = official_leads.get(instrument["instrument_id"])
        if lead:
            for url in lead["official_page_urls"]:
                lines.append(f"  - Official lead (not yet archived): <{url}>")
            for filename in lead.get("expected_attachment_names", []):
                lines.append(f"  - Expected original attachment: `{filename}`")
            discrepancy = lead.get("date_discrepancy")
            if discrepancy:
                lines.append(
                    "  - Date discrepancy to preserve: registry effective "
                    f"{discrepancy['registry_effective_date']}; official issue "
                    f"{discrepancy['official_issue_date']}; official effective "
                    f"{discrepancy['official_effective_date']}."
                )
            lines.append(f"  - Retrieval note: {lead['retrieval_notes']}")
    return "\n".join(lines) + "\n"


def write_open_source_note(coverage: dict, output: Path = OPEN_NOTE) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(render_open_source_note(coverage), encoding="utf-8")
    temporary.replace(output)


def format_audit(coverage: dict) -> str:
    """Render the concise Task-7 source gate and source-floor verdict."""
    summary = coverage["summary"]
    floor = coverage["source_floor_evidence"]
    return "\n".join([
        (
            f"ward source audit: {coverage['scope']['source_gate_status'].upper()} — "
            f"{summary['official_source_matches']}/"
            f"{summary['unique_ward_instruments']} official; "
            f"{summary['primary_source_open_instruments']} primary-source open; "
            f"{summary['change_bearing_source_open_instruments']} "
            "change-bearing open"
        ),
        (
            f"source floor verdict: {floor['verdict']} — "
            f"{floor['endpoint_interval']['before_date']} and "
            f"{floor['endpoint_interval']['after_date']} are identical; "
            "transient intra-interval changes are not excluded"
        ),
    ])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the offline ward source coverage ledger.")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--check", action="store_true",
                        help="fail if the existing output differs from a fresh offline build")
    parser.add_argument(
        "--audit", action="store_true",
        help="print the concise source-gate and bounded source-floor verdict",
    )
    parser.add_argument(
        "--open-note", action="store_true",
        help="write or check the human-searchable source-open checklist",
    )
    parser.add_argument("--open-note-output", type=Path, default=OPEN_NOTE)
    args = parser.parse_args(argv)

    coverage = build_coverage()
    rendered = serialize_coverage(coverage)
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != rendered:
            raise SystemExit(f"coverage ledger is missing or stale: {args.output}")
        action = "verified"
    else:
        write_coverage(coverage, args.output)
        action = "wrote"
    if args.open_note:
        open_note_rendered = render_open_source_note(coverage)
        if args.check:
            if (
                not args.open_note_output.is_file()
                or args.open_note_output.read_text(encoding="utf-8")
                != open_note_rendered
            ):
                raise SystemExit(
                    f"source-open note is missing or stale: {args.open_note_output}"
                )
        else:
            write_open_source_note(coverage, args.open_note_output)
        print(f"{action} {args.open_note_output}")
    if args.audit:
        print(f"{action} {args.output}\n{format_audit(coverage)}")
    else:
        summary = coverage["summary"]
        print(
            f"{action} {args.output}: {summary['soap_artifacts']} SOAP, "
            f"{summary['ward_crosswalk_artifacts']} crosswalks, "
            f"{summary['unique_ward_instruments']} instruments, "
            f"{summary['unclassified_instruments']} unclassified"
        )


if __name__ == "__main__":
    main()
