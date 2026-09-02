"""Offline, fail-closed preparation for ward Wikidata statements.

This module does not write to Wikidata. It builds the reviewed CREATE package
for current wards that have no item and records whether the 2025 lineage is
ready for a separate statement batch. Lineage rendering refuses to run unless
every predecessor and successor has a QID.

Usage:
  uv run python -m vn_admin_units.ward_emit --audit
  uv run python -m vn_admin_units.ward_emit --check --audit
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from vn_admin_units.core import p31_target, predecessor_ends, ref_s854, wd_date


REFORM_DATE = "2025-07-01"
COUNTRY_QID = "Q881"
HISTORY = Path("data/ward-history.json")
MAPPING = Path("mappings/wards-qid.csv")
PROVINCE_MAPPING = Path("mappings/provinces-qid.csv")
LEGAL_SOURCES = Path("data/ward-legal-sources.json")
REVIEW_DECISIONS = Path("data/ward-wikidata-review-decisions.json")
CREATE_MANIFEST = Path("data/ward-wikidata-create-current.json")
READINESS = Path("data/ward-wikidata-emission-readiness.json")
CREATE_STATEMENTS = Path("statements/na-wards-create-current.qs")
CREATE_BATCH_DIR = Path("statements/wards-create-current")
_QID = re.compile(r"^Q[1-9][0-9]*$")


def _read_csv(path: Path) -> list[dict]:
    return list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _serialize_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _review_index(review_decisions: dict) -> dict[str, dict]:
    indexed = {}
    for batch in review_decisions.get("batches", []):
        for decision in batch.get("decisions", []):
            local_id = decision["local_id"]
            if local_id in indexed:
                raise ValueError(f"duplicate ward review decision: {local_id}")
            indexed[local_id] = decision
    return indexed


def _official_reference(entity: dict, sources_by_id: dict[str, dict]) -> tuple[str, str]:
    instrument_ids = entity.get("creation_evidence", {}).get("instrument_ids", [])
    if len(instrument_ids) != 1:
        raise ValueError(
            f"{entity['local_id']} must have exactly one creating instrument; "
            f"found {instrument_ids}"
        )
    instrument_id = instrument_ids[0]
    source = sources_by_id.get(instrument_id)
    if source is None:
        raise ValueError(f"{entity['local_id']} has unknown instrument {instrument_id}")

    attachments = sorted(
        (
            row for row in source.get("attachments", [])
            if str(row.get("url", "")).startswith(("http://", "https://"))
        ),
        key=lambda row: (row.get("media_type") != "pdf", row.get("url", "")),
    )
    url = attachments[0]["url"] if attachments else source.get("metadata_url", "")
    if not str(url).startswith(("http://", "https://")):
        raise ValueError(f"{entity['local_id']} has no official creating-instrument URL")
    return instrument_id, url


def _description(loai_hinh: str, parent_name: str) -> str:
    parent = parent_name[:1].lower() + parent_name[1:]
    return f"{loai_hinh.lower()} thuộc {parent}, Việt Nam, thành lập năm 2025"


def build_current_creation_manifest(
    history: dict,
    mapping_rows: list[dict],
    province_rows: list[dict],
    legal_sources: dict,
    review_decisions: dict,
    *,
    review_group_size: int = 10,
    input_fingerprints: dict[str, str] | None = None,
) -> dict:
    """Build the deterministic manifest for reviewed current item gaps."""
    if review_group_size < 1:
        raise ValueError("review_group_size must be positive")

    entities = {row["local_id"]: row for row in history["entities"]}
    current_ids = {
        local_id for local_id, entity in entities.items()
        if entity["valid_to"] is None
    }
    rows_by_id = {row["local_id"]: row for row in mapping_rows}
    if set(rows_by_id) != set(entities):
        raise ValueError("ward mapping local IDs do not exactly match the history graph")

    provinces = {
        row["gso_code"]: row
        for row in province_rows
        if row.get("era") == "post2025"
    }
    sources_by_id = {
        row["instrument_id"]: row for row in legal_sources["instruments"]
    }
    decisions = _review_index(review_decisions)
    gaps = [
        row for row in mapping_rows
        if row["local_id"] in current_ids and not row["wikidata_qid"]
    ]
    entries = []
    for sequence, row in enumerate(
        sorted(gaps, key=lambda item: (item["terminal_code"], item["local_id"])),
        start=1,
    ):
        if row["match_status"] != "reviewed-unresolved":
            raise ValueError(
                f"{row['local_id']} is an unreviewed current gap: {row['match_status']}"
            )
        decision = decisions.get(row["local_id"])
        if not decision or decision.get("outcome") != "retain-unresolved":
            raise ValueError(f"{row['local_id']} lacks a retain-unresolved decision")

        entity = entities[row["local_id"]]
        parent_code = entity["parent_spans"][-1]["code"]
        province = provinces.get(parent_code)
        if not province or not _QID.fullmatch(province.get("wikidata_qid", "")):
            raise ValueError(f"{row['local_id']} has no reconciled current province")
        type_qid = p31_target(entity["loai_hinh"])
        if not _QID.fullmatch(type_qid):
            raise ValueError(f"{row['local_id']} has no ward-class P31 target")
        instrument_id, reference_url = _official_reference(entity, sources_by_id)
        entries.append({
            "sequence": sequence,
            "review_group": (sequence - 1) // review_group_size + 1,
            "local_id": row["local_id"],
            "gso_code": row["terminal_code"],
            "name_vi": entity["name_vi"],
            "description_vi": _description(entity["loai_hinh"], province["name_vi"]),
            "loai_hinh": entity["loai_hinh"],
            "type_qid": type_qid,
            "country_qid": COUNTRY_QID,
            "parent_code": parent_code,
            "parent_name_vi": province["name_vi"],
            "parent_qid": province["wikidata_qid"],
            "valid_from": entity["valid_from"],
            "creating_instrument_id": instrument_id,
            "reference_url": reference_url,
            "candidate_qids_checked": decision.get("candidate_qids_checked", []),
            "review_note": decision.get("mapping_note", ""),
            "review_rationale": decision.get("rationale", ""),
        })

    return {
        "schema_version": 1,
        "scope": {
            "tier": "ward",
            "effective_date": REFORM_DATE,
            "purpose": "reviewed current Wikidata item-creation gaps",
            "wikidata_write_performed": False,
            "statement_file": CREATE_STATEMENTS.as_posix(),
            "review_group_size": review_group_size,
        },
        "input_fingerprints": input_fingerprints or {},
        "audit": {
            "items": len(entries),
            "statement_files": 1 if entries else 0,
            "review_groups": (
                (len(entries) + review_group_size - 1) // review_group_size
            ),
            "type_counts": dict(sorted(Counter(row["loai_hinh"] for row in entries).items())),
            "province_count": len({row["parent_code"] for row in entries}),
            "official_reference_urls": len({row["reference_url"] for row in entries}),
        },
        "items": entries,
    }


def _qs_string(value: str) -> str:
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def emit_creation_item(item: dict) -> str:
    """Render one self-contained CREATE block without succession back-links."""
    ref = ref_s854(item["reference_url"])
    return "\n".join([
        "CREATE",
        f"LAST\tLvi\t{_qs_string(item['name_vi'])}",
        f"LAST\tDvi\t{_qs_string(item['description_vi'])}",
        f"LAST\tP31\t{item['type_qid']}\t{ref}",
        f"LAST\tP17\t{item['country_qid']}\t{ref}",
        f"LAST\tP131\t{item['parent_qid']}\t{ref}",
        f"LAST\tP571\t{wd_date(item['valid_from'])}\t{ref}",
    ]) + "\n"


def render_creation_statements(manifest: dict) -> str:
    return "\n".join(
        emit_creation_item(item).rstrip("\n") for item in manifest["items"]
    ) + ("\n" if manifest["items"] else "")


def build_emission_readiness(
    history: dict,
    mapping_rows: list[dict],
    *,
    input_fingerprints: dict[str, str] | None = None,
) -> dict:
    """Measure endpoint closure without treating expected incompleteness as an error."""
    qids = {row["local_id"]: row["wikidata_qid"] for row in mapping_rows}
    entities = {row["local_id"]: row for row in history["entities"]}
    if set(qids) != set(entities):
        raise ValueError("ward mapping local IDs do not exactly match the history graph")
    current_ids = {key for key, row in entities.items() if row["valid_to"] is None}
    historical_ids = set(entities) - current_ids
    edges = [
        row for row in history["lineage_edges"]
        if row["effective_date"] == REFORM_DATE
    ]
    predecessors = {row["predecessor"] for row in edges}
    successors = {row["successor"] for row in edges}
    both = sum(bool(qids[row["predecessor"]] and qids[row["successor"]]) for row in edges)
    refs = sum(
        str(row.get("reference_url", "")).startswith(("http://", "https://"))
        for row in edges
    )
    current_unmapped = {key for key in current_ids if not qids[key]}
    predecessor_unmapped = {key for key in predecessors if not qids[key]}
    blockers = []
    if current_unmapped:
        blockers.append({
            "gate": "current_successor_qids",
            "missing": len(current_unmapped),
            "resolution": "create the reviewed current items and record their QIDs in mappings/wards-qid.csv",
        })
    if predecessor_unmapped:
        blockers.append({
            "gate": "historical_predecessor_qids",
            "missing": len(predecessor_unmapped),
            "resolution": "reconcile the immediate pre-2025 predecessor set before lineage emission",
        })
    if refs != len(edges):
        blockers.append({
            "gate": "official_event_references",
            "missing": len(edges) - refs,
            "resolution": "attach an HTTP(S) establishing-resolution URL to every reform edge",
        })
    return {
        "schema_version": 1,
        "scope": {
            "tier": "ward",
            "effective_date": REFORM_DATE,
            "wikidata_write_performed": False,
        },
        "input_fingerprints": input_fingerprints or {},
        "audit": {
            "entities": len(entities),
            "current_entities": len(current_ids),
            "current_qids": len(current_ids) - len(current_unmapped),
            "current_item_creation_gaps": len(current_unmapped),
            "historical_entities": len(historical_ids),
            "historical_qids": sum(bool(qids[key]) for key in historical_ids),
            "reform_edges": len(edges),
            "distinct_reform_predecessors": len(predecessors),
            "reconciled_reform_predecessors": len(predecessors) - len(predecessor_unmapped),
            "distinct_reform_successors": len(successors),
            "reconciled_reform_successors": sum(bool(qids[key]) for key in successors),
            "reform_edges_with_both_qids": both,
            "reform_edges_with_official_reference": refs,
        },
        "gates": {
            "current_creation_package_ready": all(
                rows["match_status"] == "reviewed-unresolved"
                for rows in mapping_rows
                if rows["local_id"] in current_unmapped
            ),
            "lineage_endpoint_qids_ready": both == len(edges),
            "official_event_references_ready": refs == len(edges),
            "ward_lineage_emit_ready": not blockers,
        },
        "blockers": blockers,
    }


def emit_ward_lineage_quickstatements(history: dict, mapping_rows: list[dict]) -> str:
    """Render the 2025 succession graph, but only after complete QID closure."""
    readiness = build_emission_readiness(history, mapping_rows)
    if not readiness["gates"]["ward_lineage_emit_ready"]:
        details = ", ".join(
            f"{row['gate']}={row['missing']}" for row in readiness["blockers"]
        )
        raise ValueError(f"ward lineage emission is blocked: {details}")

    qids = {row["local_id"]: row["wikidata_qid"] for row in mapping_rows}
    lines = []
    seen = set()
    for edge in history["lineage_edges"]:
        if edge["effective_date"] != REFORM_DATE:
            continue
        if not predecessor_ends(edge["relation"]):
            raise ValueError(
                f"unsupported non-ending 2025 ward relation: {edge['relation']}"
            )
        predecessor = qids[edge["predecessor"]]
        successor = qids[edge["successor"]]
        if predecessor == successor:
            raise ValueError(f"same-QID ward lineage edge: {edge['predecessor']} -> {edge['successor']}")
        date = wd_date(edge["effective_date"])
        ref = ref_s854(edge["reference_url"])
        candidates = [
            f"{predecessor}\tP576\t{date}\t{ref}",
            f"{predecessor}\tP7888\t{successor}\tP585\t{date}\t{ref}",
            f"{predecessor}\tP1366\t{successor}\tP585\t{date}\t{ref}",
            f"{successor}\tP1365\t{predecessor}\tP585\t{date}\t{ref}",
        ]
        for line in candidates:
            if line not in seen:
                seen.add(line)
                lines.append(line)
    return "\n".join(lines) + "\n"


def _load_inputs() -> tuple[dict, list[dict], list[dict], dict, dict]:
    return (
        json.loads(HISTORY.read_text(encoding="utf-8")),
        _read_csv(MAPPING),
        _read_csv(PROVINCE_MAPPING),
        json.loads(LEGAL_SOURCES.read_text(encoding="utf-8")),
        json.loads(REVIEW_DECISIONS.read_text(encoding="utf-8")),
    )


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def write_package(manifest: dict, readiness: dict) -> None:
    _write_atomic(CREATE_MANIFEST, _serialize_json(manifest))
    _write_atomic(READINESS, _serialize_json(readiness))
    _write_atomic(CREATE_STATEMENTS, render_creation_statements(manifest))
    if CREATE_BATCH_DIR.is_dir():
        for stale in CREATE_BATCH_DIR.glob("*.qs"):
            stale.unlink()
        try:
            CREATE_BATCH_DIR.rmdir()
        except OSError:
            pass


def check_package(manifest: dict, readiness: dict) -> None:
    expected = {
        CREATE_MANIFEST: _serialize_json(manifest),
        READINESS: _serialize_json(readiness),
        CREATE_STATEMENTS: render_creation_statements(manifest),
    }
    for path, content in expected.items():
        if not path.is_file() or path.read_text(encoding="utf-8") != content:
            raise SystemExit(f"ward emission artifact is missing or stale: {path}")
    legacy_batches = set(CREATE_BATCH_DIR.glob("*.qs")) if CREATE_BATCH_DIR.is_dir() else set()
    if legacy_batches:
        raise SystemExit("legacy ward creation batch files remain beside the consolidated file")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Prepare offline ward Wikidata statement artifacts")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--require-lineage-ready", action="store_true")
    args = parser.parse_args(argv)

    history, mapping, provinces, sources, decisions = _load_inputs()
    manifest_fingerprints = {
        path.as_posix(): _sha256(path)
        for path in (
            HISTORY, MAPPING, PROVINCE_MAPPING, LEGAL_SOURCES, REVIEW_DECISIONS,
        )
    }
    manifest = build_current_creation_manifest(
        history, mapping, provinces, sources, decisions,
        input_fingerprints=manifest_fingerprints,
    )
    readiness = build_emission_readiness(
        history,
        mapping,
        input_fingerprints={
            path.as_posix(): _sha256(path) for path in (HISTORY, MAPPING)
        },
    )
    if args.check:
        check_package(manifest, readiness)
        action = "verified"
    else:
        write_package(manifest, readiness)
        action = "wrote"

    if args.audit:
        audit = readiness["audit"]
        print(
            f"{action} {manifest['audit']['items']} current CREATE items in one file; "
            f"lineage edges ready {audit['reform_edges_with_both_qids']}/"
            f"{audit['reform_edges']}; blockers {len(readiness['blockers'])}"
        )
        for blocker in readiness["blockers"]:
            print(f"  {blocker['gate']}: {blocker['missing']} missing")
    if args.require_lineage_ready and not readiness["gates"]["ward_lineage_emit_ready"]:
        raise SystemExit("ward lineage emission remains blocked; see readiness artifact")


if __name__ == "__main__":
    main()
