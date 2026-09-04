"""Broad Wikidata discovery for unresolved immediate ward predecessors.

This pass queries exact Vietnamese and ASCII label/alias forms without a P31
restriction, then uses the returned P131 values to reduce the live Action API
verification set. It runs only after the ward-class predecessor pass.

No command in this module writes to Wikidata.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from vn_admin_units import rawcache
from vn_admin_units.ward_reconcile import (
    MAPPING,
    QLEVER_ENDPOINT,
    WARD_CLASSES,
    WIKIDATA_API,
    build_district_qid_index,
    fetch_action_api_entities,
    serialize_json,
    write_mapping,
)
from vn_admin_units.ward_reconcile_broad import (
    _request_post_bytes,
    exact_vi_terms,
    query_terms,
)
from vn_admin_units.ward_reconcile_predecessors import (
    ARTIFACT_PATH as PRIMARY_ARTIFACT_PATH,
    EXPECTED_CLASS_BY_TIER,
    _current_assignments_sha256,
    _qid_key,
    _read_csv,
    _sha256,
    _verified_name_matches,
    apply_matches,
)


QUERY_PATH = Path("queries/ward-wikidata-predecessor-unresolved.rq")
RAW_RESULT = "wikidata/ward-predecessor-unresolved-2026-09-04.sparql.json.gz"
CACHE_PATH = Path("data/ward-wikidata-predecessor-unresolved-candidates.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def unresolved_rows(predecessor_artifact: dict) -> list[dict]:
    return [
        row for row in predecessor_artifact["review"]
        if not row["auto_candidate_qids"]
    ]


def _sparql_literal(value: str, language: str) -> str:
    return f"{json.dumps(value, ensure_ascii=False)}@{language}"


def render_query(rows: list[dict]) -> str:
    terms = sorted({
        term for row in rows for term in query_terms(row["name_vi"])
    }, key=lambda item: (item[1], item[0]))
    values = "\n".join(
        f"    {_sparql_literal(value, language)}"
        for value, language in terms
    )
    return f"""PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>

SELECT
  ?item
  ?matchedTerm
  ?matchKind
  (GROUP_CONCAT(DISTINCT STR(?type); separator="␟") AS ?types)
  (GROUP_CONCAT(DISTINCT STR(?parent); separator="␟") AS ?parents)
WHERE {{
  {{
    VALUES ?matchedTerm {{
{values}
    }}
    ?item rdfs:label ?matchedTerm .
    BIND("label" AS ?matchKind)
  }}
  UNION
  {{
    VALUES ?matchedTerm {{
{values}
    }}
    ?item skos:altLabel ?matchedTerm .
    BIND("alias" AS ?matchKind)
  }}
  OPTIONAL {{ ?item wdt:P31 ?type . }}
  OPTIONAL {{ ?item wdt:P131 ?parent . }}
  FILTER(REGEX(STR(?item), "/Q[1-9][0-9]*$"))
}}
GROUP BY ?item ?matchedTerm ?matchKind
ORDER BY ?item ?matchedTerm ?matchKind
"""


def _binding_value(binding: dict, key: str) -> str:
    return binding.get(key, {}).get("value", "")


def _qid_from_uri(value: str) -> str:
    qid = value.rsplit("/", 1)[-1]
    return qid if qid.startswith("Q") and qid[1:].isdigit() else ""


def _split_qids(value: str) -> list[str]:
    return sorted({
        qid for part in value.split("␟")
        if (qid := _qid_from_uri(part.strip()))
    }, key=_qid_key)


def parse_candidates(payload: dict) -> list[dict]:
    indexed: dict[str, dict] = {}
    for binding in payload["results"]["bindings"]:
        qid = _qid_from_uri(_binding_value(binding, "item"))
        term = binding.get("matchedTerm", {})
        value = term.get("value", "")
        language = term.get("xml:lang", "")
        kind = _binding_value(binding, "matchKind")
        if not qid or not value or language not in {"vi", "en"}:
            raise ValueError(f"invalid predecessor broad binding: {binding}")
        candidate = indexed.setdefault(qid, {
            "qid": qid,
            "types": set(),
            "parent_qids": set(),
            "matches": defaultdict(set),
        })
        candidate["types"].update(_split_qids(_binding_value(binding, "types")))
        candidate["parent_qids"].update(
            _split_qids(_binding_value(binding, "parents"))
        )
        candidate["matches"][(value, language)].add(kind)
    return [
        {
            "qid": qid,
            "types": sorted(candidate["types"], key=_qid_key),
            "parent_qids": sorted(candidate["parent_qids"], key=_qid_key),
            "matches": [
                {
                    "value": value,
                    "language": language,
                    "kinds": sorted(kinds),
                }
                for (value, language), kinds in sorted(candidate["matches"].items())
            ],
        }
        for qid, candidate in sorted(indexed.items(), key=lambda item: _qid_key(item[0]))
    ]


def _term_index(candidates: list[dict]) -> dict[tuple[str, str], set[str]]:
    indexed: dict[tuple[str, str], set[str]] = defaultdict(set)
    for candidate in candidates:
        for match in candidate["matches"]:
            indexed[(match["value"], match["language"])].add(candidate["qid"])
    return indexed


def _assigned_by_qid(mapping_rows: list[dict]) -> dict[str, set[str]]:
    indexed: dict[str, set[str]] = defaultdict(set)
    for row in mapping_rows:
        if row["wikidata_qid"]:
            indexed[row["wikidata_qid"]].add(row["local_id"])
    return indexed


def build_review(
    artifact: dict,
    predecessor_artifact: dict,
    mapping_rows: list[dict],
    district_qid_index: dict[str, set[str]],
) -> dict:
    result = json.loads(json.dumps(artifact))
    candidates = {row["qid"]: row for row in result["candidates"]}
    term_index = _term_index(result["candidates"])
    assigned_by_qid = _assigned_by_qid(mapping_rows)
    review = []
    shortlisted = set()
    for row in unresolved_rows(predecessor_artifact):
        all_qids = {
            qid
            for term in query_terms(row["name_vi"])
            for qid in term_index.get(term, set())
        }
        excluded = {
            qid for qid in all_qids
            if assigned_by_qid.get(qid, set()) - {row["local_id"]}
        }
        qids = all_qids - excluded
        district_qids = {
            qid for qid in qids
            if row["parent_code"] in {
                code
                for parent_qid in candidates[qid]["parent_qids"]
                for code in district_qid_index.get(parent_qid, set())
            }
        }
        shortlisted.update(district_qids)
        if not qids and excluded:
            classification = "assigned-item-only"
        elif not qids:
            classification = "no-broad-candidate"
        elif not district_qids:
            classification = "no-broad-district-candidate"
        else:
            classification = "awaiting-verification"
        review.append({
            "local_id": row["local_id"],
            "terminal_code": row["terminal_code"],
            "name_vi": row["name_vi"],
            "loai_hinh": row["loai_hinh"],
            "parent_code": row["parent_code"],
            "prior_classification": row["classification"],
            "classification": classification,
            "candidate_qids": sorted(qids, key=_qid_key),
            "assigned_qids_excluded": sorted(excluded, key=_qid_key),
            "district_candidate_qids": sorted(district_qids, key=_qid_key),
            "verified_candidate_qids": [],
            "auto_candidate_qids": [],
            "confidence": "",
        })
    classifications = Counter(row["classification"] for row in review)
    result["review"] = review
    result["shortlisted_qids"] = sorted(shortlisted, key=_qid_key)
    result["audit"].update({
        "unresolved_predecessor_rows": len(review),
        "rows_with_any_candidate": sum(bool(row["candidate_qids"]) for row in review),
        "rows_with_district_candidate": sum(
            bool(row["district_candidate_qids"]) for row in review
        ),
        "shortlisted_qids": len(shortlisted),
        "api_verified_candidates": 0,
        "rows_with_verified_candidate": 0,
        "auto_matched_rows": 0,
        "unresolved_rows": len(review),
        "classification_counts": dict(sorted(classifications.items())),
    })
    return result


def evaluate(
    artifact: dict,
    mapping_rows: list[dict],
    district_qid_index: dict[str, set[str]],
) -> dict:
    result = json.loads(json.dumps(artifact))
    candidates = {row["qid"]: row for row in result["candidates"]}
    verified = {
        row["qid"]: row for row in result["action_api_verification"]["entities"]
    }
    assigned_by_qid = _assigned_by_qid(mapping_rows)
    proposed = {}
    for row in result["review"]:
        hits = []
        exact_terms = exact_vi_terms(row["name_vi"])
        for qid in row["district_candidate_qids"]:
            entity = verified.get(qid)
            if (
                entity is None
                or entity.get("missing")
                or assigned_by_qid.get(qid, set()) - {row["local_id"]}
            ):
                continue
            parent_codes = {
                code
                for parent_qid in entity.get("p131", [])
                for code in district_qid_index.get(parent_qid, set())
            }
            matched_terms = {
                (match["value"], match["language"])
                for match in candidates[qid]["matches"]
            }
            if row["parent_code"] not in parent_codes:
                continue
            if not set(entity.get("p31", [])) & set(WARD_CLASSES):
                continue
            if not _verified_name_matches(row, entity):
                continue
            if not matched_terms & exact_terms:
                continue
            hits.append(qid)
        row["verified_candidate_qids"] = hits
        row["auto_candidate_qids"] = []
        row["confidence"] = ""
        if not row["district_candidate_qids"]:
            continue
        if not hits:
            row["classification"] = "verification-rejected"
            continue
        selected = hits
        if len(hits) > 1:
            expected_class = EXPECTED_CLASS_BY_TIER[row["loai_hinh"]]
            exact_type = [qid for qid in hits if expected_class in verified[qid]["p31"]]
            if len(exact_type) == 1:
                selected = exact_type
        if len(selected) > 1:
            with_viwiki = [
                qid for qid in selected
                if verified[qid].get("sitelinks", {}).get("viwiki")
            ]
            if len(with_viwiki) == 1:
                selected = with_viwiki
        if len(selected) != 1:
            row["classification"] = "ambiguous-verified-candidates"
            continue
        qid = selected[0]
        row["auto_candidate_qids"] = [qid]
        row["classification"] = "verified-unique"
        row["confidence"] = (
            "exact-vi-name+terminal-district+ward-class+batched-wbgetentities"
        )
        proposed[row["local_id"]] = qid

    proposal_rows: dict[str, list[dict]] = defaultdict(list)
    for row in result["review"]:
        if row["auto_candidate_qids"]:
            proposal_rows[row["auto_candidate_qids"][0]].append(row)
    for row in result["review"]:
        qids = row["auto_candidate_qids"]
        if not qids or len(proposal_rows[qids[0]]) == 1:
            continue
        qid = qids[0]
        exact_type_rows = [
            candidate_row for candidate_row in proposal_rows[qid]
            if EXPECTED_CLASS_BY_TIER[candidate_row["loai_hinh"]]
            in verified[qid]["p31"]
        ]
        keep = exact_type_rows[0] if len(exact_type_rows) == 1 else None
        if row is not keep:
            row["auto_candidate_qids"] = []
            row["classification"] = "qid-collision"
            row["confidence"] = ""
    classifications = Counter(row["classification"] for row in result["review"])
    auto = sum(bool(row["auto_candidate_qids"]) for row in result["review"])
    result["audit"].update({
        "api_verified_candidates": len(verified),
        "rows_with_verified_candidate": sum(
            bool(row["verified_candidate_qids"]) for row in result["review"]
        ),
        "auto_matched_rows": auto,
        "unresolved_rows": len(result["review"]) - auto,
        "classification_counts": dict(sorted(classifications.items())),
    })
    return result


def fetch_result(
    rows: list[dict],
    *,
    request_fn=_request_post_bytes,
) -> Path:
    query = QUERY_PATH.read_text(encoding="utf-8")
    content = request_fn(QLEVER_ENDPOINT, query)
    payload = json.loads(content)
    if "results" not in payload or "bindings" not in payload["results"]:
        raise ValueError("QLever response is not a SPARQL results document")
    return rawcache.save_raw_gzip(RAW_RESULT, content, {
        "source_url": QLEVER_ENDPOINT,
        "source_class": "live_wikidata_query",
        "source_role": "ward_predecessor_unresolved_candidates",
        "method": "saved broad-name QLever SPARQL query with P31/P131 reduction",
        "query_path": QUERY_PATH.as_posix(),
        "query_sha256": _sha256(QUERY_PATH),
        "query_result_rows": len(payload["results"]["bindings"]),
        "predecessor_artifact_path": PRIMARY_ARTIFACT_PATH.as_posix(),
        "predecessor_artifact_sha256": _sha256(PRIMARY_ARTIFACT_PATH),
        "unresolved_predecessor_rows": len(rows),
        "query_terms": len({term for row in rows for term in query_terms(row["name_vi"])}),
    })


def normalize_result() -> dict:
    payload = json.loads(rawcache.read_raw(RAW_RESULT))
    manifest = rawcache.manifest_entry(RAW_RESULT)
    if manifest is None:
        raise ValueError(f"raw QLever result is not registered: {RAW_RESULT}")
    candidates = parse_candidates(payload)
    return {
        "schema_version": 1,
        "scope": {
            "tier": "ward",
            "effective_date": "2025-07-01",
            "purpose": "unresolved_predecessor_broad_name_discovery",
            "wikidata_write_performed": False,
        },
        "source": {
            "endpoint": manifest["source_url"],
            "retrieved_at": manifest["retrieved_at"],
            "query_path": QUERY_PATH.as_posix(),
            "query_sha256": _sha256(QUERY_PATH),
            "raw_result_path": RAW_RESULT,
            "raw_result_sha256": manifest["sha256"],
            "raw_content_sha256": manifest["content_sha256"],
            "predecessor_artifact_path": PRIMARY_ARTIFACT_PATH.as_posix(),
            "predecessor_artifact_sha256": manifest["predecessor_artifact_sha256"],
            "qlever_meta": payload.get("meta", {}),
        },
        "audit": {
            "query_terms": manifest["query_terms"],
            "query_result_rows": len(payload["results"]["bindings"]),
            "candidate_items": len(candidates),
        },
        "candidates": candidates,
        "shortlisted_qids": [],
        "action_api_verification": {
            "endpoint": WIKIDATA_API,
            "retrieved_at": "",
            "entities": [],
        },
        "review": [],
    }


def verify(
    artifact: dict,
    mapping_rows: list[dict],
    district_qid_index: dict[str, set[str]],
    *,
    fetch_fn=fetch_action_api_entities,
) -> dict:
    result = json.loads(json.dumps(artifact))
    result["action_api_verification"] = {
        "endpoint": WIKIDATA_API,
        "retrieved_at": _utc_now(),
        "entities": fetch_fn(result["shortlisted_qids"]),
    }
    return evaluate(result, mapping_rows, district_qid_index)


def audit(artifact: dict, predecessor_artifact: dict, mapping_rows: list[dict]) -> list[str]:
    issues = []
    if not rawcache.raw_is_verified(RAW_RESULT):
        issues.append("RAW-RESULT-INTEGRITY")
    if artifact["source"]["query_sha256"] != _sha256(QUERY_PATH):
        issues.append("QUERY-HASH")
    if artifact["source"]["predecessor_artifact_sha256"] != _sha256(
        PRIMARY_ARTIFACT_PATH
    ):
        issues.append("PREDECESSOR-ARTIFACT-HASH")
    unresolved = unresolved_rows(predecessor_artifact)
    if len(artifact["review"]) != len(unresolved):
        issues.append("REVIEW-ROW-COUNT")
    if {row["local_id"] for row in artifact["review"]} != {
        row["local_id"] for row in unresolved
    }:
        issues.append("REVIEW-LOCAL-ID-SET")
    shortlisted = {
        qid for row in artifact["review"] for qid in row["district_candidate_qids"]
    }
    if set(artifact["shortlisted_qids"]) != shortlisted:
        issues.append("SHORTLIST-QID-SET")
    verified = {
        row["qid"] for row in artifact["action_api_verification"]["entities"]
    }
    if verified and verified != shortlisted:
        issues.append("API-VERIFIED-QID-SET")
    if any(row.get("missing") for row in artifact["action_api_verification"]["entities"]):
        issues.append("API-MISSING-ENTITY")
    automatic = [
        (row["local_id"], row["auto_candidate_qids"][0])
        for row in artifact["review"] if row["auto_candidate_qids"]
    ]
    if len({qid for _, qid in automatic}) != len(automatic):
        issues.append("AUTO-QID-COLLISION")
    mapping_by_id = {row["local_id"]: row for row in mapping_rows}
    for local_id, qid in automatic:
        if mapping_by_id[local_id]["wikidata_qid"] != qid:
            issues.append(f"MAPPING-DRIFT {local_id}")
    return issues


def format_audit(artifact: dict, issues: list[str]) -> str:
    data = artifact["audit"]
    return (
        "broad predecessor discovery: "
        f"{data['auto_matched_rows']}/{data['unresolved_predecessor_rows']} auto matched; "
        f"{data['candidate_items']} candidates, {data['shortlisted_qids']} shortlisted; "
        f"{len(issues)} issues"
    )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Broad discovery for unresolved ward predecessors"
    )
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--audit", action="store_true")
    args = parser.parse_args(argv)

    predecessor_artifact = json.loads(PRIMARY_ARTIFACT_PATH.read_text(encoding="utf-8"))
    rows = unresolved_rows(predecessor_artifact)
    mapping = _read_csv(MAPPING)
    district_index = build_district_qid_index()
    query = render_query(rows)
    if args.fetch:
        _write(QUERY_PATH, query)
        path = fetch_result(rows)
        print(f"saved exact broad predecessor QLever result: {path}")
        artifact = build_review(
            normalize_result(), predecessor_artifact, mapping, district_index,
        )
    else:
        artifact = json.loads(CACHE_PATH.read_text(encoding="utf-8"))

    if args.verify:
        artifact = verify(artifact, mapping, district_index)
    elif artifact["action_api_verification"]["entities"]:
        normalized = build_review(
            normalize_result(), predecessor_artifact, mapping, district_index,
        )
        normalized["action_api_verification"] = artifact["action_api_verification"]
        artifact = evaluate(normalized, mapping, district_index)

    rendered_mapping = apply_matches(mapping, artifact)
    if args.check:
        if QUERY_PATH.read_text(encoding="utf-8") != query:
            raise SystemExit(f"broad predecessor query is stale: {QUERY_PATH}")
        if CACHE_PATH.read_text(encoding="utf-8") != serialize_json(artifact):
            raise SystemExit(f"broad predecessor cache is stale: {CACHE_PATH}")
        action = "verified"
    elif args.fetch or args.verify or args.rebuild:
        _write(CACHE_PATH, serialize_json(artifact))
        write_mapping(rendered_mapping)
        action = "wrote"
    else:
        action = "evaluated"

    issues = audit(artifact, predecessor_artifact, rendered_mapping)
    if args.audit:
        print(f"{action} {CACHE_PATH}")
        print(format_audit(artifact, issues))
        print(json.dumps(artifact["audit"], ensure_ascii=False, indent=2))
        for issue in issues[:20]:
            print(f"  {issue}")
    if issues:
        raise SystemExit("broad predecessor discovery has audit issues")


if __name__ == "__main__":
    main()
