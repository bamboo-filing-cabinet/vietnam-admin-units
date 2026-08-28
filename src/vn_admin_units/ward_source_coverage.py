"""Build the deterministic ward source/provenance coverage ledger.

This is the offline denominator for historical ward work. It inventories the
verified SOAP, crosswalk, and legal-source cache; collapses duplicate legal-index
rows without discarding their variants; and exposes source/classification
residue before event matching begins.

Usage:
  uv run python -m vn_admin_units.ward_source_coverage
  uv run python -m vn_admin_units.ward_source_coverage --check
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from vn_admin_units import rawcache
from vn_admin_units.crosscheck_decrees import is_ward_structural


LEGAL_INDEX = Path("data/raw/nghidinh.json")
MANIFEST = Path("data/raw/manifest.jsonl")
OBSERVED_CHANGES = Path("data/ward-observed-changes.json")
OUTPUT = Path("data/ward-source-coverage.json")

SOURCE_FLOOR = "2002-01-01"
AS_OF = "2026-08-27"

LOCKED = {
    "soap_artifacts": 204,
    "soap_rows": 2_202_543,
    "soap_unique_payloads": 180,
    "ward_crosswalk_artifacts": 24,
    "ward_crosswalk_rows": 256_149,
    "yearly_crosswalks": 21,
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


def build_instruments(records: list[dict], source_index: dict) -> list[dict]:
    """Collapse legal-index duplicates into stable instrument records."""
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for record in records:
        key = normalize_code(record.get("code", "")), normalize_date(record.get("hieu_luc", ""))
        grouped[key].append(record)

    instruments = []
    for (code, effective_date), variants in sorted(grouped.items(), key=lambda item: (item[0][1], item[0][0])):
        sources = source_index.get((code, effective_date), [])
        primary = [source for source in sources if source["source_class"] == "official"]
        secondary = [source for source in sources if source["source_class"] != "official"]
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
            "instrument_id": f"{code}@{effective_date}",
            "code": code,
            "effective_date": effective_date,
            "index_occurrences": len(variants),
            "title_variants": sorted({str(record.get("noi_dung", "")).strip() for record in variants}),
            "index_urls": urls,
            "classification": "lineage" if closed_2025 else "unresolved",
            "review_status": "verified_2025_boundary" if closed_2025 else "pending",
            "source_status": source_status,
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


def _observed_change_inventory(path: Path, manifest_path: Path) -> tuple[dict, list[dict]]:
    observed = json.loads(path.read_text(encoding="utf-8"))
    summary = observed.get("summary", {})
    scope = observed.get("scope", {})
    manifest_sha256 = _sha256(manifest_path)
    if observed.get("input_fingerprints", {}).get("manifest_sha256") != manifest_sha256:
        raise ValueError("observed-change inventory was not built from the current raw manifest")
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


def build_coverage(*, manifest_path: Path = MANIFEST,
                   legal_index_path: Path = LEGAL_INDEX,
                   observed_changes_path: Path = OBSERVED_CHANGES) -> dict:
    """Build and validate the offline source and observed-event ledger."""
    manifest = _load_manifest(manifest_path)
    legal_records = json.loads(legal_index_path.read_text(encoding="utf-8"))
    ward_records = [
        record for record in legal_records
        if is_ward_structural(str(record.get("noi_dung", "")))
    ]
    sources = index_legal_sources(manifest)
    instruments = build_instruments(ward_records, sources)
    soap = _soap_inventory(manifest)
    crosswalks = _crosswalk_inventory(manifest)
    resolution_pairs = _resolution_pairs(instruments)
    observed_changes, events = _observed_change_inventory(
        observed_changes_path, manifest_path,
    )

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

    summary = {
        "soap_artifacts": len(soap["artifacts"]),
        "soap_rows": soap["rows"],
        "soap_unique_payloads": soap["unique_payloads"],
        "ward_crosswalk_artifacts": len(crosswalks["artifacts"]),
        "ward_crosswalk_rows": crosswalks["rows"],
        "yearly_crosswalks": crosswalks["yearly_count"],
        "legal_index_records": len(legal_records),
        "ward_relevant_legal_rows": len(ward_records),
        "ward_relevant_effective_dates_from_2005": len(effective_dates_from_2005),
        "unique_ward_instruments": len(instruments),
        "duplicate_instrument_keys": len(duplicate_instruments),
        "verified_2025_resolution_pairs": len(resolution_pairs),
        "observed_change_intervals": len(events),
        "unclassified_instruments": len(unresolved),
        "primary_source_open_instruments": len(primary_source_open),
        "events": len(events),
    }
    for label, expected in LOCKED.items():
        _require(label, summary[label], expected)
    _require("SOAP source floor", soap["artifacts"][0]["date"], SOURCE_FLOOR)
    _require("SOAP as-of date", soap["artifacts"][-1]["date"], AS_OF)
    _require("SOAP missing parents", soap["missing_parent_codes"], 0)

    return {
        "schema_version": 2,
        "scope": {
            "tier": "ward",
            "source_floor": SOURCE_FLOOR,
            "as_of": AS_OF,
            "status": "observed_changes_enumerated_reconciliation_pending",
            "next_task": 4,
        },
        "input_fingerprints": {
            "manifest_path": manifest_path.as_posix(),
            "manifest_sha256": _sha256(manifest_path),
            "legal_index_path": legal_index_path.as_posix(),
            "legal_index_sha256": _sha256(legal_index_path),
            "observed_changes_path": observed_changes_path.as_posix(),
            "observed_changes_sha256": observed_changes["sha256"],
        },
        "summary": summary,
        "inventories": {
            "soap": soap,
            "crosswalks": crosswalks,
            "observed_changes": observed_changes,
            "verified_2025_resolution_pairs": resolution_pairs,
        },
        "legal_instruments": instruments,
        "events": events,
        "residue": {
            "event_inventory_status": "complete_pending_task_4_crosswalk_reconciliation",
            "unreconciled_event_ids": [event["event_id"] for event in events],
            "unclassified_instrument_ids": unresolved,
            "primary_source_open_instrument_ids": primary_source_open,
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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the offline ward source coverage ledger.")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--check", action="store_true",
                        help="fail if the existing output differs from a fresh offline build")
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
    summary = coverage["summary"]
    print(
        f"{action} {args.output}: {summary['soap_artifacts']} SOAP, "
        f"{summary['ward_crosswalk_artifacts']} crosswalks, "
        f"{summary['unique_ward_instruments']} instruments, "
        f"{summary['unclassified_instruments']} unclassified"
    )


if __name__ == "__main__":
    main()
