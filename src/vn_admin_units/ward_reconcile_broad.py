"""Saved broad-name discovery for unresolved current ward mappings.

This second pass deliberately does not assign QIDs. It finds Wikidata items of
any type whose Vietnamese or English labels/aliases exactly match a current
unresolved ward name, then records hierarchy, type, date, coordinate, and
sitelink evidence for later review.

Usage:
  uv run python -m vn_admin_units.ward_reconcile_broad --fetch --verify --audit
  uv run python -m vn_admin_units.ward_reconcile_broad --check --audit
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from vn_admin_units import rawcache
from vn_admin_units.ward_reconcile import (
    AS_OF,
    CANDIDATE_CACHE,
    MAPPING,
    QLEVER_ENDPOINT,
    USER_AGENT,
    WARD_CLASSES,
    WARD_HISTORY,
    WIKIDATA_API,
    build_mapping_rows,
    build_parent_qid_index,
    fetch_action_api_entities,
    serialize_mapping,
    serialize_json,
)


QUERY_PATH = Path("queries/ward-wikidata-unresolved-names.rq")
RAW_RESULT = "wikidata/ward-unresolved-names-2026-09-01.sparql.json.gz"
CACHE_PATH = Path("data/ward-wikidata-unresolved-candidates.json")
UNRESOLVED_STATUSES = {"ambiguous", "needs-review", "needs-lookup"}
EXPECTED_CLASS_BY_TIER = {
    label: qid for qid, label in WARD_CLASSES.items()
}
_QID = re.compile(r"^Q[1-9][0-9]*$")
_TIER_PREFIX = re.compile(
    r"^(xã|phường|thị trấn|đặc khu)\s+", re.IGNORECASE,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _base_mapping_rows(
    primary_artifact: dict,
    parent_index: dict[str, set[str]],
) -> list[dict]:
    history = json.loads(WARD_HISTORY.read_text(encoding="utf-8"))
    return build_mapping_rows(history, primary_artifact, parent_index)


def _mapping_sha256(rows: list[dict]) -> str:
    return hashlib.sha256(serialize_mapping(rows).encode()).hexdigest()


def unresolved_current_rows(rows: list[dict]) -> list[dict]:
    return [
        row for row in rows
        if not row["valid_to"] and row["match_status"] in UNRESOLVED_STATUSES
    ]


def _ascii_name(value: str) -> str:
    value = "".join(
        char for char in unicodedata.normalize("NFD", value)
        if unicodedata.category(char) != "Mn"
    )
    return re.sub(r"\s+", " ", value.replace("đ", "d").replace("Đ", "D")).strip()


def query_terms(name_vi: str) -> set[tuple[str, str]]:
    short = _TIER_PREFIX.sub("", name_vi.strip())
    ascii_short = _ascii_name(short)
    return {
        (name_vi.strip(), "vi"),
        (short, "vi"),
        (ascii_short, "vi"),
        (ascii_short, "en"),
    }


def exact_vi_terms(name_vi: str) -> set[tuple[str, str]]:
    return {
        (name_vi.strip(), "vi"),
        (_TIER_PREFIX.sub("", name_vi.strip()), "vi"),
    }


def _sparql_literal(value: str, language: str) -> str:
    return f"{json.dumps(value, ensure_ascii=False)}@{language}"


def render_query(rows: list[dict]) -> str:
    terms = sorted({
        term
        for row in unresolved_current_rows(rows)
        for term in query_terms(row["name_vi"])
    }, key=lambda item: (item[1], item[0]))
    values = "\n".join(
        f"    {_sparql_literal(value, language)}"
        for value, language in terms
    )
    return f"""PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>

SELECT DISTINCT ?item ?matchedTerm ?matchKind
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
}}
ORDER BY ?item ?matchedTerm ?matchKind
"""


def write_query(content: str, path: Path = QUERY_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
    return path


def _request_post_bytes(
    endpoint: str,
    query: str,
    *,
    timeout: int = 120,
    retries: int = 5,
) -> bytes:
    data = urllib.parse.urlencode({"query": query}).encode()
    request = urllib.request.Request(
        endpoint,
        data=data,
        headers={
            "Accept": "application/sparql-results+json, application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": USER_AGENT,
        },
    )
    delay = 2.0
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code not in {429, 500, 502, 503, 504} or attempt == retries - 1:
                raise
        except urllib.error.URLError:
            if attempt == retries - 1:
                raise
        time.sleep(delay)
        delay *= 2
    raise RuntimeError("unreachable retry state")


def fetch_result(
    rows: list[dict],
    *,
    query_path: Path = QUERY_PATH,
    raw_result: str = RAW_RESULT,
    endpoint: str = QLEVER_ENDPOINT,
    request_fn=_request_post_bytes,
) -> Path:
    query = query_path.read_text(encoding="utf-8")
    content = request_fn(endpoint, query)
    payload = json.loads(content)
    if "results" not in payload or "bindings" not in payload["results"]:
        raise ValueError("QLever response is not a SPARQL results document")
    unresolved = unresolved_current_rows(rows)
    return rawcache.save_raw_gzip(raw_result, content, {
        "source_url": endpoint,
        "source_class": "live_wikidata_query",
        "source_role": "ward_reconciliation_unresolved_name_candidates",
        "method": "saved broad-name QLever SPARQL query",
        "query_path": query_path.as_posix(),
        "query_sha256": _sha256(query_path),
        "query_result_rows": len(payload["results"]["bindings"]),
        "mapping_path": MAPPING.as_posix(),
        "mapping_sha256": _mapping_sha256(rows),
        "unresolved_current_rows": len(unresolved),
        "query_terms": len({
            term for row in unresolved for term in query_terms(row["name_vi"])
        }),
        "as_of": AS_OF,
    })


def _binding_value(binding: dict, key: str) -> str:
    return binding.get(key, {}).get("value", "")


def _qid_from_uri(value: str) -> str:
    qid = value.rsplit("/", 1)[-1]
    return qid if _QID.fullmatch(qid) else ""


def parse_candidates(payload: dict) -> list[dict]:
    indexed: dict[str, dict[tuple[str, str], set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for binding in payload["results"]["bindings"]:
        qid = _qid_from_uri(_binding_value(binding, "item"))
        term = binding.get("matchedTerm", {})
        value = term.get("value", "")
        language = term.get("xml:lang", "")
        kind = _binding_value(binding, "matchKind")
        if not qid or not value or language not in {"vi", "en"}:
            raise ValueError(f"invalid broad candidate binding: {binding}")
        indexed[qid][(value, language)].add(kind)
    return [
        {
            "qid": qid,
            "matches": [
                {
                    "value": value,
                    "language": language,
                    "kinds": sorted(kinds),
                }
                for (value, language), kinds in sorted(indexed[qid].items())
            ],
        }
        for qid in sorted(indexed, key=lambda value: int(value[1:]))
    ]


def normalize_result(
    *,
    raw_result: str = RAW_RESULT,
    query_path: Path = QUERY_PATH,
) -> dict:
    payload = json.loads(rawcache.read_raw(raw_result))
    candidates = parse_candidates(payload)
    manifest = rawcache.manifest_entry(raw_result)
    if manifest is None:
        raise ValueError(f"raw QLever result is not registered: {raw_result}")
    return {
        "schema_version": 1,
        "scope": {
            "tier": "ward",
            "as_of": AS_OF,
            "purpose": "unresolved_current_broad_name_discovery",
            "wikidata_write_performed": False,
        },
        "source": {
            "endpoint": manifest["source_url"],
            "retrieved_at": manifest["retrieved_at"],
            "query_path": query_path.as_posix(),
            "query_sha256": _sha256(query_path),
            "raw_result_path": raw_result,
            "raw_result_sha256": manifest["sha256"],
            "raw_content_sha256": manifest["content_sha256"],
            "mapping_path": MAPPING.as_posix(),
            "mapping_sha256": manifest["mapping_sha256"],
            "qlever_meta": payload.get("meta", {}),
        },
        "audit": {
            "unresolved_current_rows": manifest["unresolved_current_rows"],
            "query_terms": manifest["query_terms"],
            "query_result_rows": len(payload["results"]["bindings"]),
            "candidate_items": len(candidates),
            "api_verified_candidates": 0,
        },
        "candidates": candidates,
        "action_api_verification": {
            "endpoint": WIKIDATA_API,
            "retrieved_at": "",
            "entities": [],
        },
        "review": [],
    }


def _term_index(candidates: list[dict]) -> dict[tuple[str, str], set[str]]:
    indexed: dict[tuple[str, str], set[str]] = defaultdict(set)
    for candidate in candidates:
        for match in candidate["matches"]:
            indexed[(match["value"], match["language"])].add(candidate["qid"])
    return indexed


def evaluate(
    artifact: dict,
    rows: list[dict],
    primary_artifact: dict,
    parent_index: dict[str, set[str]],
) -> dict:
    result = json.loads(json.dumps(artifact))
    term_index = _term_index(result["candidates"])
    candidate_by_qid = {
        row["qid"]: row for row in result["candidates"]
    }
    entities = {
        row["qid"]: row
        for row in result["action_api_verification"]["entities"]
    }
    primary_ids = {row["qid"] for row in primary_artifact["candidates"]}
    review = []
    for row in unresolved_current_rows(rows):
        qids = sorted({
            qid
            for term in query_terms(row["name_vi"])
            for qid in term_index.get(term, set())
        }, key=lambda value: int(value[1:]))
        province_qids = []
        ward_class_qids = []
        nonward_qids = []
        exact_active_ward_qids = []
        for qid in qids:
            entity = entities.get(qid)
            if entity is None or entity.get("missing"):
                continue
            parent_codes = {
                code
                for parent_qid in entity.get("p131", [])
                for code in parent_index.get(parent_qid, set())
            }
            if row["parent_code"] not in parent_codes:
                continue
            province_qids.append(qid)
            if set(entity.get("p31", [])) & set(WARD_CLASSES):
                ward_class_qids.append(qid)
                candidate = candidate_by_qid[qid]
                matched_terms = {
                    (match["value"], match["language"])
                    for match in candidate["matches"]
                }
                active = not any(
                    value <= AS_OF for value in entity.get("p576", [])
                )
                if active and matched_terms & exact_vi_terms(row["name_vi"]):
                    exact_active_ward_qids.append(qid)
            else:
                nonward_qids.append(qid)
        auto_candidate_qids = list(exact_active_ward_qids)
        if len(auto_candidate_qids) > 1:
            expected_class = EXPECTED_CLASS_BY_TIER[row["loai_hinh"]]
            exact_type_qids = [
                qid for qid in auto_candidate_qids
                if expected_class in entities[qid].get("p31", [])
            ]
            auto_candidate_qids = (
                exact_type_qids if len(exact_type_qids) == 1 else []
            )
        if nonward_qids:
            classification = "current-province-nonward-candidate"
        elif ward_class_qids:
            classification = "current-province-ward-candidate"
        elif qids:
            classification = "name-candidate-other-or-missing-parent"
        else:
            classification = "no-broad-name-candidate"
        review.append({
            "local_id": row["local_id"],
            "name_vi": row["name_vi"],
            "loai_hinh": row["loai_hinh"],
            "parent_code": row["parent_code"],
            "prior_status": row["match_status"],
            "classification": classification,
            "candidate_qids": qids,
            "new_candidate_qids": [qid for qid in qids if qid not in primary_ids],
            "current_province_qids": province_qids,
            "current_province_ward_qids": ward_class_qids,
            "current_province_nonward_qids": nonward_qids,
            "exact_active_ward_qids": exact_active_ward_qids,
            "auto_candidate_qids": auto_candidate_qids,
        })
    classifications = Counter(row["classification"] for row in review)
    result["review"] = review
    result["audit"].update({
        "api_verified_candidates": len(entities),
        "review_rows": len(review),
        "classification_counts": dict(sorted(classifications.items())),
        "rows_with_any_candidate": sum(bool(row["candidate_qids"]) for row in review),
        "rows_with_new_candidate": sum(bool(row["new_candidate_qids"]) for row in review),
        "rows_with_current_province_candidate": sum(
            bool(row["current_province_qids"]) for row in review
        ),
        "rows_with_current_province_nonward_candidate": sum(
            bool(row["current_province_nonward_qids"]) for row in review
        ),
        "rows_with_one_auto_candidate": sum(
            len(row["auto_candidate_qids"]) == 1 for row in review
        ),
    })
    return result


def verify(
    artifact: dict,
    rows: list[dict],
    primary_artifact: dict,
    parent_index: dict[str, set[str]],
    *,
    fetch_fn=fetch_action_api_entities,
) -> dict:
    qids = [row["qid"] for row in artifact["candidates"]]
    result = json.loads(json.dumps(artifact))
    result["action_api_verification"] = {
        "endpoint": WIKIDATA_API,
        "retrieved_at": _utc_now(),
        "entities": fetch_fn(qids),
    }
    return evaluate(result, rows, primary_artifact, parent_index)


def write_cache(payload: dict, path: Path = CACHE_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(serialize_json(payload), encoding="utf-8")
    temporary.replace(path)
    return path


def audit(artifact: dict, rows: list[dict]) -> list[str]:
    issues = []
    unresolved = unresolved_current_rows(rows)
    if artifact["audit"]["unresolved_current_rows"] != len(unresolved):
        issues.append("UNRESOLVED-ROW-COUNT")
    if artifact["audit"].get("review_rows") != len(unresolved):
        issues.append("REVIEW-ROW-COUNT")
    expected_local_ids = {row["local_id"] for row in unresolved}
    actual_local_ids = {row["local_id"] for row in artifact["review"]}
    if actual_local_ids != expected_local_ids:
        issues.append("REVIEW-LOCAL-ID-SET")
    candidate_qids = {row["qid"] for row in artifact["candidates"]}
    verified_qids = {
        row["qid"] for row in artifact["action_api_verification"]["entities"]
    }
    if verified_qids != candidate_qids:
        issues.append("API-VERIFIED-QID-SET")
    if any(
        row.get("missing")
        for row in artifact["action_api_verification"]["entities"]
    ):
        issues.append("API-MISSING-ENTITY")
    if not rawcache.raw_is_verified(RAW_RESULT):
        issues.append("RAW-RESULT-INTEGRITY")
    if artifact["source"]["query_sha256"] != _sha256(QUERY_PATH):
        issues.append("QUERY-HASH")
    if artifact["source"]["mapping_sha256"] != _mapping_sha256(rows):
        issues.append("MAPPING-HASH")
    return issues


def format_audit(artifact: dict, issues: list[str]) -> str:
    data = artifact["audit"]
    return (
        "broad unresolved discovery: "
        f"{data['candidate_items']} items from {data['query_result_rows']} rows; "
        f"{data.get('rows_with_new_candidate', 0)}/"
        f"{data['unresolved_current_rows']} wards have a new candidate; "
        f"{len(issues)} issues"
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Discover broad-name Wikidata candidates for unresolved wards"
    )
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--audit", action="store_true")
    args = parser.parse_args(argv)

    primary = json.loads(CANDIDATE_CACHE.read_text(encoding="utf-8"))
    parent_index = build_parent_qid_index()
    rows = _base_mapping_rows(primary, parent_index)
    rendered_query = render_query(rows)
    if args.fetch:
        write_query(rendered_query)
        path = fetch_result(rows)
        print(f"saved exact broad QLever result: {path}")
        artifact = normalize_result()
        write_cache(artifact)
    else:
        artifact = json.loads(CACHE_PATH.read_text(encoding="utf-8"))

    if args.verify:
        artifact = verify(artifact, rows, primary, parent_index)
        write_cache(artifact)
        print(
            "verified broad candidate set through wbgetentities: "
            f"{artifact['audit']['api_verified_candidates']} items"
        )
    elif artifact["action_api_verification"]["entities"]:
        artifact = evaluate(artifact, rows, primary, parent_index)
        if args.rebuild:
            write_cache(artifact)

    if args.check:
        if QUERY_PATH.read_text(encoding="utf-8") != rendered_query:
            raise SystemExit(f"broad query is stale: {QUERY_PATH}")
        if CACHE_PATH.read_text(encoding="utf-8") != serialize_json(artifact):
            raise SystemExit(f"broad candidate cache is stale: {CACHE_PATH}")

    issues = audit(artifact, rows)
    if args.audit:
        print(format_audit(artifact, issues))
        print(json.dumps(artifact["audit"], ensure_ascii=False, indent=2))
        for issue in issues:
            print(f"  {issue}")
    if issues:
        raise SystemExit("broad unresolved discovery has audit issues")


if __name__ == "__main__":
    main()
