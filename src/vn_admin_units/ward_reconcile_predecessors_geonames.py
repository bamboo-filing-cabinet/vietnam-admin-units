"""Recover predecessor wards through exact Wikidata/GeoNames/GSO identifiers.

The fallback is deliberately narrow. A Wikidata candidate must already have an
exact Vietnamese name and ward tier, link to a GeoNames record through P1566,
and have coordinates agreeing within one kilometre. Normally the GeoNames row
must repeat both historical GSO ward and district codes. Records from one known
GeoNames import pattern that lacks both codes are accepted only when the name
is globally unique among predecessors, the successor has a different name,
and the province code agrees with the historical or post-merger province.

No command in this module writes to Wikidata or GeoNames.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from vn_admin_units import rawcache
from vn_admin_units.ward_reconcile import (
    MAPPING,
    PROVINCE_ENTITIES,
    PROVINCE_LINEAGE,
    WARD_HISTORY,
    serialize_json,
    serialize_mapping,
    write_mapping,
)
from vn_admin_units.ward_reconcile_predecessors import (
    _qid_key,
    _sha256,
    apply_matches,
)
from vn_admin_units.ward_reconcile_predecessors_article import (
    ARTIFACT_PATH as ARTICLE_ARTIFACT_PATH,
    _normalized_vi_name,
)
from vn_admin_units.ward_reconcile_predecessors_context import (
    ARTIFACT_PATH as CONTEXT_ARTIFACT_PATH,
)


ARTIFACT_PATH = Path("data/ward-wikidata-predecessor-geonames-candidates.json")
GEONAMES_RAW_RESULT = "geonames/VN-2026-09-04.zip"
GEONAMES_MEMBER = "VN.txt"
MAX_COORDINATE_DISTANCE_KM = 1.0
_GEONAMES_MATCH_NOTE = "predecessor exact-geonames-gso-code+"


def _read_csv(path: Path) -> list[dict]:
    return list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))


def _geonames_names(row: dict) -> list[str]:
    return [
        row["name"],
        *[value for value in row["alternate_names"].split(",") if value],
    ]


def parse_geonames_dump(archive: bytes) -> dict[str, dict]:
    with zipfile.ZipFile(io.BytesIO(archive)) as source:
        content = source.read(GEONAMES_MEMBER).decode("utf-8")
    rows = {}
    for line in content.splitlines():
        columns = line.split("\t")
        if len(columns) < 14:
            raise ValueError("GeoNames row has fewer than 14 columns")
        geonames_id = columns[0]
        if geonames_id in rows:
            raise ValueError(f"duplicate GeoNames ID: {geonames_id}")
        rows[geonames_id] = {
            "geonames_id": geonames_id,
            "name": columns[1],
            "alternate_names": columns[3],
            "latitude": float(columns[4]),
            "longitude": float(columns[5]),
            "feature_class": columns[6],
            "feature_code": columns[7],
            "country_code": columns[8],
            "admin1_code": columns[10],
            "admin2_code": columns[11],
            "admin3_code": columns[12],
        }
    return rows


def _distance_km(left: dict, right: dict) -> float:
    latitude_left = math.radians(left["latitude"])
    latitude_right = math.radians(right["latitude"])
    latitude_delta = latitude_right - latitude_left
    longitude_delta = math.radians(right["longitude"] - left["longitude"])
    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(latitude_left)
        * math.cos(latitude_right)
        * math.sin(longitude_delta / 2) ** 2
    )
    return 12_742 * math.asin(math.sqrt(haversine))


def _record_evidence(source: dict, entity: dict, record: dict) -> dict | None:
    expected_name = _normalized_vi_name(source["name_vi"])
    if not any(
        _normalized_vi_name(name) == expected_name
        for name in _geonames_names(record)
    ):
        return None
    if (
        record["country_code"] != "VN"
        or record["feature_class"] != "A"
        or record["feature_code"] != "ADM3"
        or not entity.get("p625")
    ):
        return None
    distance = min(
        _distance_km(coordinate, record)
        for coordinate in entity["p625"]
    )
    if distance > MAX_COORDINATE_DISTANCE_KM:
        return None
    exact_gso_codes = (
        record["admin3_code"] in source["gso_codes"]
        and record["admin2_code"] in source["parent_codes"]
    )
    unique_name_province = (
        source["unique_predecessor_name_tier"]
        and not source["same_name_successor"]
        and not record["admin2_code"]
        and record["admin3_code"] == record["geonames_id"]
        and record["admin1_code"] in source["province_codes"]
    )
    if not exact_gso_codes and not unique_name_province:
        return None
    return {
        "geonames_id": record["geonames_id"],
        "gso_ward_code": record["admin3_code"],
        "gso_district_code": record["admin2_code"],
        "province_code": record["admin1_code"],
        "coordinate_distance_km": round(distance, 6),
        "match_basis": (
            "exact-ward-and-district-gso-codes" if exact_gso_codes
            else "unique-name-tier+province-code+missing-geonames-hierarchy"
        ),
    }


def _province_code_successors(entities: list[dict], lineage: list[dict]) -> dict:
    codes_by_id = {
        row["local_id"]: set(row["gso_codes"]) for row in entities
    }
    successors: dict[str, set[str]] = defaultdict(set)
    for edge in lineage:
        if edge.get("effective_date") != "2025-07-01":
            continue
        for source_code in codes_by_id.get(edge["predecessor"], set()):
            successors[source_code].update(
                codes_by_id.get(edge["successor"], set())
            )
    return successors


def _clear_prior_geonames_matches(mapping_rows: list[dict]) -> list[dict]:
    rows = json.loads(json.dumps(mapping_rows))
    for row in rows:
        if row.get("match_notes", "").startswith(_GEONAMES_MATCH_NOTE):
            row.update({
                "wikidata_qid": "",
                "qid_status": "new",
                "match_status": "gap",
                "candidate_qids": "",
                "match_notes": (
                    "provisional predecessor creation gap after ward-class and "
                    "broad district-scoped preflight"
                ),
            })
    return rows


def build_artifact(
    history: dict,
    article: dict,
    context: dict,
    geonames: dict[str, dict],
    mapping_rows: list[dict],
    *,
    province_entities: list[dict] | None = None,
    province_lineage: list[dict] | None = None,
) -> dict:
    history_by_id = {row["local_id"]: row for row in history["entities"]}
    entities = {
        row["qid"]: row
        for row in article["action_api_verification"]["entities"]
    }
    assigned: dict[str, set[str]] = defaultdict(set)
    for row in mapping_rows:
        if row["wikidata_qid"]:
            assigned[row["wikidata_qid"]].add(row["local_id"])
    predecessor_ids = {
        edge["predecessor"] for edge in history["lineage_edges"]
        if edge.get("effective_date") == "2025-07-01"
    }
    name_occurrences = Counter(
        (
            _normalized_vi_name(history_by_id[local_id]["name_vi"]),
            history_by_id[local_id]["loai_hinh"],
        )
        for local_id in predecessor_ids
    )
    province_successors = _province_code_successors(
        province_entities or [], province_lineage or [],
    )

    review = []
    proposed = {}
    for source in context["review"]:
        if source["auto_candidate_qids"]:
            continue
        historical = history_by_id[source["local_id"]]
        historical_province_codes = {
            span["code"] for span in historical.get("province_echo_spans", [])
        }
        province_codes = {
            *historical_province_codes,
            *(
                successor
                for code in historical_province_codes
                for successor in province_successors.get(code, set())
            ),
        }
        unique_name_tier = name_occurrences[
            (_normalized_vi_name(source["name_vi"]), source["loai_hinh"])
        ] == 1
        input_qids = []
        evidence = {}
        for qid in source["verified_candidate_qids"]:
            entity = entities.get(qid)
            if entity is None or assigned.get(qid, set()) - {source["local_id"]}:
                continue
            input_qids.append(qid)
            qid_evidence = []
            for geonames_id in entity.get("geonames_ids", []):
                record = geonames.get(geonames_id)
                if record is None:
                    continue
                match = _record_evidence({
                    **source,
                    "gso_codes": historical["gso_codes"],
                    "province_codes": province_codes,
                    "unique_predecessor_name_tier": unique_name_tier,
                }, entity, record)
                if match:
                    qid_evidence.append(match)
            if qid_evidence:
                evidence[qid] = qid_evidence

        matched_qids = sorted(evidence, key=_qid_key)
        auto = []
        confidence = ""
        if not input_qids:
            classification = "no-exact-name-tier-candidate"
        elif not matched_qids:
            classification = "no-exact-geonames-gso-code"
        elif len(matched_qids) > 1:
            classification = "ambiguous-geonames-gso-candidates"
        else:
            qid = matched_qids[0]
            auto = [qid]
            classification = "verified-unique"
            confidence = (
                "exact-geonames-gso-code+district-code+name+tier+coordinates"
            )
            proposed[source["local_id"]] = qid
        review.append({
            "local_id": source["local_id"],
            "terminal_code": source["terminal_code"],
            "name_vi": source["name_vi"],
            "loai_hinh": source["loai_hinh"],
            "parent_code": source["parent_code"],
            "parent_codes": source["parent_codes"],
            "gso_codes": historical["gso_codes"],
            "province_codes": sorted(province_codes),
            "unique_predecessor_name_tier": unique_name_tier,
            "candidate_qids": sorted(input_qids, key=_qid_key),
            "verified_candidate_qids": sorted(input_qids, key=_qid_key),
            "geonames_candidate_qids": matched_qids,
            "geonames_evidence": evidence,
            "auto_candidate_qids": auto,
            "classification": classification,
            "confidence": confidence,
        })

    proposal_counts = Counter(proposed.values())
    for row in review:
        qids = row["auto_candidate_qids"]
        if qids and proposal_counts[qids[0]] > 1:
            row["auto_candidate_qids"] = []
            row["classification"] = "qid-collision"
            row["confidence"] = ""

    classifications = Counter(row["classification"] for row in review)
    auto = sum(bool(row["auto_candidate_qids"]) for row in review)
    manifest = rawcache.manifest_entry(GEONAMES_RAW_RESULT)
    if manifest is None:
        raise ValueError("GeoNames raw dump is missing from the manifest")
    return {
        "schema_version": 1,
        "scope": {
            "tier": "ward",
            "effective_date": "2025-07-01",
            "purpose": "unresolved predecessor exact GeoNames/GSO identity",
            "wikidata_write_performed": False,
        },
        "source": {
            "history_path": WARD_HISTORY.as_posix(),
            "history_sha256": _sha256(WARD_HISTORY),
            "article_artifact_path": ARTICLE_ARTIFACT_PATH.as_posix(),
            "article_artifact_sha256": _sha256(ARTICLE_ARTIFACT_PATH),
            "context_artifact_path": CONTEXT_ARTIFACT_PATH.as_posix(),
            "context_artifact_sha256": _sha256(CONTEXT_ARTIFACT_PATH),
            "province_entities_path": PROVINCE_ENTITIES.as_posix(),
            "province_entities_sha256": _sha256(PROVINCE_ENTITIES),
            "province_lineage_path": PROVINCE_LINEAGE.as_posix(),
            "province_lineage_sha256": _sha256(PROVINCE_LINEAGE),
            "geonames_raw_path": GEONAMES_RAW_RESULT,
            "geonames_raw_sha256": manifest["sha256"],
            "geonames_source_url": manifest["source_url"],
            "geonames_retrieved_at": manifest["retrieved_at"],
        },
        "audit": {
            "unresolved_input_rows": len(review),
            "geonames_records": len(geonames),
            "rows_with_exact_name_tier_candidate": sum(
                bool(row["candidate_qids"]) for row in review
            ),
            "rows_with_exact_geonames_gso_code": sum(
                bool(row["geonames_candidate_qids"]) for row in review
            ),
            "auto_matched_rows": auto,
            "unresolved_rows": len(review) - auto,
            "classification_counts": dict(sorted(classifications.items())),
        },
        "review": review,
    }


def audit(artifact: dict, mapping_rows: list[dict]) -> list[str]:
    issues = []
    source = artifact["source"]
    for key, path in (
        ("history_sha256", WARD_HISTORY),
        ("article_artifact_sha256", ARTICLE_ARTIFACT_PATH),
        ("context_artifact_sha256", CONTEXT_ARTIFACT_PATH),
        ("province_entities_sha256", PROVINCE_ENTITIES),
        ("province_lineage_sha256", PROVINCE_LINEAGE),
    ):
        if source[key] != _sha256(path):
            issues.append(f"SOURCE-DRIFT {path}")
    manifest = rawcache.manifest_entry(GEONAMES_RAW_RESULT)
    if (
        manifest is None
        or not rawcache.raw_is_verified(GEONAMES_RAW_RESULT)
        or source["geonames_raw_sha256"] != manifest["sha256"]
    ):
        issues.append("GEONAMES-RAW-INTEGRITY")
    automatic = [
        (row["local_id"], row["auto_candidate_qids"][0])
        for row in artifact["review"] if row["auto_candidate_qids"]
    ]
    if len({qid for _, qid in automatic}) != len(automatic):
        issues.append("AUTO-QID-COLLISION")
    mapping = {row["local_id"]: row for row in mapping_rows}
    for local_id, qid in automatic:
        row = mapping.get(local_id)
        if row is None or row["wikidata_qid"] != qid:
            issues.append(f"MAPPING-DRIFT {local_id}")
    return issues


def _write_artifact(artifact: dict) -> None:
    temporary = ARTIFACT_PATH.with_name(f".{ARTIFACT_PATH.name}.tmp")
    temporary.write_text(serialize_json(artifact), encoding="utf-8")
    temporary.replace(ARTIFACT_PATH)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Recover predecessors through exact GeoNames/GSO identity",
    )
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--audit", action="store_true")
    args = parser.parse_args(argv)

    history = json.loads(WARD_HISTORY.read_text(encoding="utf-8"))
    article = json.loads(ARTICLE_ARTIFACT_PATH.read_text(encoding="utf-8"))
    context = json.loads(CONTEXT_ARTIFACT_PATH.read_text(encoding="utf-8"))
    province_entities = json.loads(PROVINCE_ENTITIES.read_text(encoding="utf-8"))
    province_lineage = json.loads(PROVINCE_LINEAGE.read_text(encoding="utf-8"))
    geonames = parse_geonames_dump(rawcache.read_raw(GEONAMES_RAW_RESULT))
    mapping = _clear_prior_geonames_matches(_read_csv(MAPPING))
    artifact = build_artifact(
        history, article, context, geonames, mapping,
        province_entities=province_entities,
        province_lineage=province_lineage,
    )
    rendered_mapping = apply_matches(mapping, artifact)
    if args.check:
        if (
            not ARTIFACT_PATH.is_file()
            or ARTIFACT_PATH.read_text(encoding="utf-8")
            != serialize_json(artifact)
        ):
            raise SystemExit(f"GeoNames artifact is stale: {ARTIFACT_PATH}")
        if MAPPING.read_text(encoding="utf-8") != serialize_mapping(rendered_mapping):
            raise SystemExit(f"ward Wikidata mapping is stale: {MAPPING}")
        action = "verified"
    elif args.rebuild:
        _write_artifact(artifact)
        write_mapping(rendered_mapping)
        action = "wrote"
    else:
        action = "evaluated"

    issues = audit(artifact, rendered_mapping)
    if args.audit:
        data = artifact["audit"]
        print(
            f"{action} {ARTIFACT_PATH}: {data['auto_matched_rows']}/"
            f"{data['unresolved_input_rows']} auto matched; {len(issues)} issues"
        )
        print(json.dumps(data, ensure_ascii=False, indent=2))
        for issue in issues[:20]:
            print(f"  {issue}")
    if issues:
        raise SystemExit("predecessor GeoNames reconciliation has audit issues")


if __name__ == "__main__":
    main()
