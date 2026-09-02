"""Read-only Wikidata reconciliation for the canonical ward graph.

The network path is intentionally bulk-oriented:

1. one saved QLever query discovers every Vietnamese ward-tier candidate;
2. the exact JSON response is preserved in deterministic gzip;
3. a compact normalized cache drives ordinary offline builds; and
4. only candidates relevant to current wards are verified through batched
   ``wbgetentities`` calls.

No command in this module writes to Wikidata.

Usage:
  uv run python -m vn_admin_units.ward_reconcile --fetch --verify-current --audit
  uv run python -m vn_admin_units.ward_reconcile --check --audit
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from vn_admin_units import rawcache
from vn_admin_units.names import fold_ward_name


AS_OF = "2026-08-27"
QUERY_PATH = Path("queries/ward-wikidata-candidates.rq")
RAW_RESULT = "wikidata/ward-candidates-2026-09-01.sparql.json.gz"
CANDIDATE_CACHE = Path("data/ward-wikidata-candidates.json")
BROAD_CANDIDATE_CACHE = Path("data/ward-wikidata-unresolved-candidates.json")
REVIEW_DECISIONS = Path("data/ward-wikidata-review-decisions.json")
WARD_HISTORY = Path("data/ward-history.json")
PROVINCE_ENTITIES = Path("data/entities.json")
PROVINCE_LINEAGE = Path("data/lineage.json")
PROVINCE_MAPPING = Path("mappings/provinces-qid.csv")
DISTRICT_MAPPING = Path("mappings/districts-qid.csv")
MAPPING = Path("mappings/wards-qid.csv")

QLEVER_ENDPOINT = "https://qlever.dev/api/wikidata"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
USER_AGENT = (
    "vn-admin-units/0.1 ward reconciliation "
    "(https://github.com/bamboo-filing-cabinet/vietnam-admin-units)"
)

WARD_CLASSES = {
    "Q2389082": "Xã",
    "Q687188": "Phường",
    "Q1070942": "Thị trấn",
    "Q134999516": "Đặc khu",
}
MAPPING_HEADER = [
    "local_id",
    "terminal_code",
    "name_vi",
    "loai_hinh",
    "parent_code",
    "valid_from",
    "valid_to",
    "wikidata_qid",
    "qid_status",
    "match_status",
    "candidate_qids",
    "match_notes",
]
LOCKED_GRAPH_COUNTS = {"entities": 14_544, "current": 3_321}
_QID = re.compile(r"^Q[1-9][0-9]*$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _request_bytes(url: str, *, timeout: int = 120, retries: int = 5) -> bytes:
    delay = 2.0
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/sparql-results+json, application/json",
            "User-Agent": USER_AGENT,
        },
    )
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


def qlever_url(query: str, endpoint: str = QLEVER_ENDPOINT) -> str:
    return endpoint + "?" + urllib.parse.urlencode({"query": query})


def fetch_qlever_result(
    *,
    query_path: Path = QUERY_PATH,
    raw_result: str = RAW_RESULT,
    endpoint: str = QLEVER_ENDPOINT,
    request_fn=_request_bytes,
) -> Path:
    """Run the saved bulk query and preserve the exact response bytes."""
    query = query_path.read_text(encoding="utf-8")
    content = request_fn(qlever_url(query, endpoint))
    payload = json.loads(content)
    if "results" not in payload or "bindings" not in payload["results"]:
        raise ValueError("QLever response is not a SPARQL results document")
    return rawcache.save_raw_gzip(raw_result, content, {
        "source_url": endpoint,
        "source_class": "live_wikidata_query",
        "source_role": "ward_reconciliation_candidates",
        "method": "saved bulk QLever SPARQL query",
        "query_path": query_path.as_posix(),
        "query_sha256": _sha256(query_path),
        "query_result_rows": len(payload["results"]["bindings"]),
        "as_of": AS_OF,
    })


def _binding_value(binding: dict, key: str) -> str:
    return binding.get(key, {}).get("value", "")


def _qid_from_uri(value: str) -> str:
    candidate = value.rsplit("/", 1)[-1]
    return candidate if _QID.fullmatch(candidate) else ""


def _split_values(value: str) -> list[str]:
    return sorted({item.strip() for item in value.split("␟") if item.strip()})


def parse_qlever_candidates(payload: dict) -> list[dict]:
    candidates = []
    for binding in payload["results"]["bindings"]:
        qid = _qid_from_uri(_binding_value(binding, "item"))
        if not qid:
            raise ValueError(f"candidate row lacks a Wikidata item: {binding}")
        types = sorted(filter(None, (
            _qid_from_uri(value) for value in _split_values(
                _binding_value(binding, "types")
            )
        )))
        parents = sorted(filter(None, (
            _qid_from_uri(value) for value in _split_values(
                _binding_value(binding, "parents")
            )
        )))
        candidates.append({
            "qid": qid,
            "types": types,
            "label_vi": _binding_value(binding, "viLabel"),
            "label_en": _binding_value(binding, "enLabel"),
            "aliases": _split_values(_binding_value(binding, "aliases")),
            "parent_qids": parents,
        })

    candidates.sort(key=lambda row: int(row["qid"][1:]))
    if len({row["qid"] for row in candidates}) != len(candidates):
        raise ValueError("normalized QLever candidates contain duplicate QIDs")
    return candidates


def normalize_qlever_result(
    *,
    raw_result: str = RAW_RESULT,
    query_path: Path = QUERY_PATH,
) -> dict:
    """Convert the exact QLever result into a compact stable candidate cache."""
    payload = json.loads(rawcache.read_raw(raw_result))
    candidates = parse_qlever_candidates(payload)
    manifest = rawcache.manifest_entry(raw_result)
    if manifest is None:
        raise ValueError(f"raw QLever result is not registered: {raw_result}")
    type_counts = Counter(
        qid for candidate in candidates for qid in candidate["types"]
    )
    return {
        "schema_version": 1,
        "scope": {
            "tier": "ward",
            "as_of": AS_OF,
            "query_mode": "bulk_qlever_then_batched_action_api",
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
            "qlever_meta": payload.get("meta", {}),
        },
        "audit": {
            "candidates": len(candidates),
            "with_vi_label": sum(bool(row["label_vi"]) for row in candidates),
            "with_aliases": sum(bool(row["aliases"]) for row in candidates),
            "with_parents": sum(bool(row["parent_qids"]) for row in candidates),
            "type_counts": dict(sorted(type_counts.items())),
            "api_verified_candidates": 0,
        },
        "candidates": candidates,
        "action_api_verification": {
            "endpoint": WIKIDATA_API,
            "retrieved_at": "",
            "entities": [],
        },
    }


def serialize_json(payload: dict) -> str:
    return json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    ) + "\n"


def write_candidate_cache(payload: dict, path: Path = CANDIDATE_CACHE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(serialize_json(payload), encoding="utf-8")
    temporary.replace(path)
    return path


def _claim_ids(entity: dict, prop: str) -> list[str]:
    values = set()
    for claim in entity.get("claims", {}).get(prop, []):
        if claim.get("rank") == "deprecated":
            continue
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if isinstance(value, dict) and _QID.fullmatch(value.get("id", "")):
            values.add(value["id"])
    return sorted(values)


def _claim_times(entity: dict, prop: str) -> list[str]:
    values = set()
    for claim in entity.get("claims", {}).get(prop, []):
        if claim.get("rank") == "deprecated":
            continue
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        raw = value.get("time", "") if isinstance(value, dict) else ""
        match = re.match(r"^[+-](\d{4}-\d{2}-\d{2})T", raw)
        if match:
            values.add(match.group(1))
    return sorted(values)


def _claim_coordinates(entity: dict) -> list[dict]:
    values = {}
    for claim in entity.get("claims", {}).get("P625", []):
        if claim.get("rank") == "deprecated":
            continue
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if not isinstance(value, dict):
            continue
        latitude = value.get("latitude")
        longitude = value.get("longitude")
        if latitude is None or longitude is None:
            continue
        key = (latitude, longitude, value.get("precision"))
        values[key] = {
            "latitude": latitude,
            "longitude": longitude,
            "precision": value.get("precision"),
        }
    return [values[key] for key in sorted(values)]


def _normalize_api_entity(qid: str, entity: dict) -> dict:
    labels = {
        lang: value["value"]
        for lang, value in entity.get("labels", {}).items()
        if lang in {"vi", "en"} and value.get("value")
    }
    aliases = sorted({
        alias["value"]
        for lang, values in entity.get("aliases", {}).items()
        if lang in {"vi", "en"}
        for alias in values
        if alias.get("value")
    })
    return {
        "qid": qid,
        "missing": "missing" in entity,
        "lastrevid": entity.get("lastrevid"),
        "modified": entity.get("modified", ""),
        "labels": labels,
        "aliases": aliases,
        "p31": _claim_ids(entity, "P31"),
        "p131": _claim_ids(entity, "P131"),
        "p571": _claim_times(entity, "P571"),
        "p576": _claim_times(entity, "P576"),
        "p625": _claim_coordinates(entity),
        "sitelinks": {
            site: value["title"]
            for site, value in sorted(entity.get("sitelinks", {}).items())
            if site in {"viwiki", "enwiki"} and value.get("title")
        },
    }


def fetch_action_api_entities(
    qids: list[str],
    *,
    endpoint: str = WIKIDATA_API,
    request_fn=_request_bytes,
    batch_size: int = 50,
    pause: float = 0.25,
    retries: int = 5,
    retry_pause: float = 2.0,
) -> list[dict]:
    """Verify selected candidates through batched ``wbgetentities`` calls."""
    qids = sorted(set(qids), key=lambda qid: int(qid[1:]))
    results = []
    for offset in range(0, len(qids), batch_size):
        batch = qids[offset:offset + batch_size]
        url = endpoint + "?" + urllib.parse.urlencode({
            "action": "wbgetentities",
            "ids": "|".join(batch),
            "props": "info|labels|aliases|claims|sitelinks",
            "languages": "vi|en",
            "format": "json",
            "maxlag": "30",
        })
        payload = None
        for attempt in range(retries):
            candidate_payload = json.loads(request_fn(url, timeout=60))
            entities = candidate_payload.get("entities", {})
            if "error" not in candidate_payload and set(batch) <= set(entities):
                payload = candidate_payload
                break
            if attempt < retries - 1 and retry_pause:
                time.sleep(retry_pause * 2 ** attempt)
        if payload is None:
            error = candidate_payload.get("error", {})
            code = error.get("code", "incomplete-response")
            raise RuntimeError(
                f"wbgetentities batch failed after {retries} attempts: {code}"
            )
        entities = payload["entities"]
        results.extend(
            _normalize_api_entity(qid, entities[qid])
            for qid in batch
        )
        if offset + batch_size < len(qids) and pause:
            time.sleep(pause)
    return results


def _read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))


def _province_successors(
    entity_path: Path = PROVINCE_ENTITIES,
    lineage_path: Path = PROVINCE_LINEAGE,
) -> dict[str, str]:
    entities = json.loads(entity_path.read_text(encoding="utf-8"))
    codes = {row["local_id"]: row["gso_codes"][-1] for row in entities}
    successors = {}
    for edge in json.loads(lineage_path.read_text(encoding="utf-8")):
        if edge["effective_date"] == "2025-07-01":
            successors[codes[edge["predecessor"]]] = codes[edge["successor"]]
    return successors


def build_parent_qid_index(
    *,
    province_mapping: Path = PROVINCE_MAPPING,
    district_mapping: Path = DISTRICT_MAPPING,
    province_entity_path: Path = PROVINCE_ENTITIES,
    province_lineage_path: Path = PROVINCE_LINEAGE,
) -> dict[str, set[str]]:
    """Map current and stale P131 QIDs to current two-tier province codes."""
    successors = _province_successors(
        province_entity_path, province_lineage_path,
    )
    indexed: dict[str, set[str]] = defaultdict(set)
    for row in _read_csv(province_mapping):
        qid = row.get("wikidata_qid", "")
        if not qid:
            continue
        code = row["gso_code"]
        current_code = code if row["era"] == "post2025" else successors.get(code)
        if current_code:
            indexed[qid].add(current_code)
    for row in _read_csv(district_mapping):
        qid = row.get("wikidata_qid", "")
        current_code = successors.get(row.get("parent_code", ""))
        if qid and current_code:
            indexed[qid].add(current_code)
    return dict(indexed)


def build_district_qid_index(
    mapping_path: Path = DISTRICT_MAPPING,
) -> dict[str, set[str]]:
    """Map former district QIDs to their terminal three-digit codes."""
    indexed: dict[str, set[str]] = defaultdict(set)
    for row in _read_csv(mapping_path):
        qid = row.get("wikidata_qid", "")
        code = row.get("terminal_code", "")
        if qid and code:
            indexed[qid].add(code)
    return dict(indexed)


def _predecessor_parent_codes(history: dict) -> dict[str, set[str]]:
    entities = {row["local_id"]: row for row in history["entities"]}
    indexed: dict[str, set[str]] = defaultdict(set)
    for edge in history.get("lineage_edges", []):
        predecessor = entities.get(edge["predecessor"])
        successor = entities.get(edge["successor"])
        if predecessor is None or successor is None or not _is_current(successor):
            continue
        parent_code = _parent_code(predecessor)
        if parent_code:
            indexed[successor["local_id"]].add(parent_code)
    return dict(indexed)


def _candidate_indexes(candidates: list[dict]) -> tuple[dict, dict]:
    by_label: dict[str, set[str]] = defaultdict(set)
    by_alias: dict[str, set[str]] = defaultdict(set)
    for candidate in candidates:
        for label in (candidate.get("label_vi", ""), candidate.get("label_en", "")):
            if label:
                by_label[fold_ward_name(label)].add(candidate["qid"])
        for alias in candidate.get("aliases", []):
            by_alias[fold_ward_name(alias)].add(candidate["qid"])
    return by_label, by_alias


def _candidate_qids(entity: dict, indexes: tuple[dict, dict]) -> tuple[list[str], str]:
    key = fold_ward_name(entity["name_vi"])
    by_label, by_alias = indexes
    if by_label.get(key):
        return sorted(by_label[key], key=lambda qid: int(qid[1:])), "label"
    return sorted(by_alias.get(key, set()), key=lambda qid: int(qid[1:])), "alias"


def _parent_prefiltered_qids(
    entity: dict,
    qids: list[str],
    by_qid: dict[str, dict],
    parent_index: dict[str, set[str]],
) -> list[str]:
    expected_parent = _parent_code(entity)
    return [
        qid for qid in qids
        if expected_parent in {
            code
            for parent_qid in by_qid[qid]["parent_qids"]
            for code in parent_index.get(parent_qid, set())
        }
    ]


def current_candidate_qids(
    history: dict,
    candidates: list[dict],
    parent_index: dict[str, set[str]],
) -> list[str]:
    """Return only named candidates whose bulk P131 resolves to the ward province."""
    indexes = _candidate_indexes(candidates)
    by_qid = {candidate["qid"]: candidate for candidate in candidates}
    return sorted({
        qid
        for entity in history["entities"]
        if entity["valid_to"] is None
        for qid in _parent_prefiltered_qids(
            entity,
            _candidate_qids(entity, indexes)[0],
            by_qid,
            parent_index,
        )
    }, key=lambda qid: int(qid[1:]))


def verify_current_candidates(
    artifact: dict,
    history: dict,
    parent_index: dict[str, set[str]],
    *,
    fetch_fn=fetch_action_api_entities,
) -> dict:
    qids = current_candidate_qids(
        history, artifact["candidates"], parent_index,
    )
    verified = fetch_fn(qids)
    result = json.loads(json.dumps(artifact))
    result["action_api_verification"] = {
        "endpoint": WIKIDATA_API,
        "retrieved_at": _utc_now(),
        "entities": verified,
    }
    result["audit"]["api_verified_candidates"] = len(verified)
    return result


def _is_current(entity: dict) -> bool:
    return entity["valid_to"] is None


def _parent_code(entity: dict) -> str:
    spans = entity.get("parent_spans", [])
    return spans[-1]["code"] if spans else ""


def _api_name_matches(entity: dict, verified: dict) -> bool:
    wanted = fold_ward_name(entity["name_vi"])
    values = list(verified.get("labels", {}).values()) + verified.get("aliases", [])
    return any(fold_ward_name(value) == wanted for value in values)


def _verified_match(
    entity: dict,
    verified: dict | None,
    parent_index: dict[str, set[str]],
) -> bool:
    if not verified or verified.get("missing"):
        return False
    if not set(verified.get("p31", [])) & set(WARD_CLASSES):
        return False
    if not _api_name_matches(entity, verified):
        return False
    expected_parent = _parent_code(entity)
    parent_codes = {
        code
        for qid in verified.get("p131", [])
        for code in parent_index.get(qid, set())
    }
    if expected_parent not in parent_codes:
        return False
    return not any(value <= AS_OF for value in verified.get("p576", []))


def _base_mapping_row(entity: dict) -> dict:
    return {
        "local_id": entity["local_id"],
        "terminal_code": entity["gso_codes"][-1],
        "name_vi": entity["name_vi"],
        "loai_hinh": entity["loai_hinh"],
        "parent_code": _parent_code(entity),
        "valid_from": entity["valid_from"] or "",
        "valid_to": entity["valid_to"] or "",
        "wikidata_qid": "",
        "qid_status": "",
        "match_status": "",
        "candidate_qids": "",
        "match_notes": "",
    }


def _review_decision_index(artifact: dict | None) -> dict[str, tuple[str, dict]]:
    indexed = {}
    for batch in (artifact or {}).get("batches", []):
        batch_id = batch.get("batch_id", "")
        if not batch_id:
            raise ValueError("ward review batch lacks batch_id")
        for decision in batch.get("decisions", []):
            local_id = decision.get("local_id", "")
            outcome = decision.get("outcome", "")
            qid = decision.get("wikidata_qid", "")
            if not local_id or local_id in indexed:
                raise ValueError(
                    f"duplicate or missing ward review local_id: {local_id}"
                )
            if outcome not in {"assign", "retain-unresolved"}:
                raise ValueError(
                    f"invalid ward review outcome for {local_id}: {outcome}"
                )
            if outcome == "assign" and not _QID.fullmatch(qid):
                raise ValueError(
                    f"assigned ward review QID is invalid for {local_id}: {qid}"
                )
            if outcome == "retain-unresolved" and qid:
                raise ValueError(
                    f"unresolved ward review unexpectedly assigns {local_id}: {qid}"
                )
            indexed[local_id] = (batch_id, decision)
    return indexed


def apply_review_decisions(
    rows: list[dict], artifact: dict | None,
) -> list[dict]:
    """Apply explicit human decisions after automatic reconciliation."""
    by_id = {row["local_id"]: row for row in rows}
    for local_id, (batch_id, decision) in _review_decision_index(artifact).items():
        row = by_id.get(local_id)
        if row is None:
            raise ValueError(f"ward review references unknown local_id: {local_id}")
        if row["valid_to"]:
            raise ValueError(f"ward review references historical row: {local_id}")

        qid = decision.get("wikidata_qid", "")
        checked = {
            *filter(None, row["candidate_qids"].split("|")),
            *decision.get("candidate_qids_checked", []),
            *([qid] if qid else []),
        }
        if any(not _QID.fullmatch(value) for value in checked):
            raise ValueError(f"ward review has invalid candidate QID: {local_id}")
        row["candidate_qids"] = "|".join(
            sorted(checked, key=lambda value: int(value[1:]))
        )
        note = decision.get("mapping_note", "human identity review")
        if decision["outcome"] == "assign":
            row.update({
                "wikidata_qid": qid,
                "qid_status": "existing",
                "match_status": "manual",
                "match_notes": f"review {batch_id}: {note}",
            })
        else:
            row.update({
                "wikidata_qid": "",
                "qid_status": "",
                "match_status": "reviewed-unresolved",
                "match_notes": f"review {batch_id}: {note}",
            })
    return rows


def build_mapping_rows(
    history: dict,
    candidate_artifact: dict,
    parent_index: dict[str, set[str]],
    *,
    district_qid_index: dict[str, set[str]] | None = None,
    broad_artifact: dict | None = None,
    prior_rows: list[dict] | None = None,
    review_decisions: dict | None = None,
) -> list[dict]:
    """Build all graph rows while reconciling only the current 3,321 entities."""
    candidates = candidate_artifact["candidates"]
    by_qid = {row["qid"]: row for row in candidates}
    indexes = _candidate_indexes(candidates)
    verified = {
        row["qid"]: row
        for row in candidate_artifact.get("action_api_verification", {}).get(
            "entities", []
        )
    }
    if district_qid_index is None:
        district_qid_index = build_district_qid_index()
    predecessor_parents = _predecessor_parent_codes(history)
    prior = {row["local_id"]: row for row in (prior_rows or [])}
    rows = []
    for entity in sorted(history["entities"], key=lambda row: row["local_id"]):
        row = _base_mapping_row(entity)
        old = prior.get(entity["local_id"], {})
        if not _is_current(entity):
            if old.get("wikidata_qid") and old.get("match_status") in {
                "verified", "manual",
            }:
                row.update({
                    "wikidata_qid": old["wikidata_qid"],
                    "qid_status": old.get("qid_status") or "existing",
                    "match_status": old["match_status"],
                    "match_notes": old.get("match_notes", "human-locked"),
                })
            else:
                row["match_status"] = "deferred-historical"
            rows.append(row)
            continue

        name_qids, source = _candidate_qids(entity, indexes)
        row["candidate_qids"] = "|".join(name_qids)
        if old.get("wikidata_qid") and old.get("match_status") in {
            "verified", "manual",
        }:
            row.update({
                "wikidata_qid": old["wikidata_qid"],
                "qid_status": old.get("qid_status") or "existing",
                "match_status": old["match_status"],
                "match_notes": old.get("match_notes", "human-locked"),
            })
            rows.append(row)
            continue

        if not name_qids:
            row["match_status"] = (
                "gap" if old.get("match_status") == "gap" else "needs-lookup"
            )
            row["qid_status"] = "new" if row["match_status"] == "gap" else ""
            row["match_notes"] = "no folded label or alias candidate"
            rows.append(row)
            continue

        qids = _parent_prefiltered_qids(
            entity, name_qids, by_qid, parent_index,
        )
        if not qids:
            row["match_status"] = "needs-review"
            row["match_notes"] = (
                f"{len(name_qids)} {source} candidate(s), but no bulk P131 "
                "resolves to the current province"
            )
            rows.append(row)
            continue

        verified_hits = [
            qid for qid in qids
            if _verified_match(entity, verified.get(qid), parent_index)
        ]
        if len(verified_hits) == 1:
            qid = verified_hits[0]
            row.update({
                "wikidata_qid": qid,
                "qid_status": "existing",
                "match_status": "matched",
                "match_notes": (
                    f"qlever-{source}+current-province+batched-wbgetentities"
                ),
            })
        elif len(verified_hits) > 1:
            predecessor_codes = predecessor_parents.get(entity["local_id"], set())
            component_hits = [
                qid for qid in verified_hits
                if predecessor_codes & {
                    code
                    for parent_qid in verified[qid].get("p131", [])
                    for code in district_qid_index.get(parent_qid, set())
                }
            ]
            if len(component_hits) == 1:
                row.update({
                    "wikidata_qid": component_hits[0],
                    "qid_status": "existing",
                    "match_status": "matched",
                    "match_notes": (
                        f"qlever-{source}+predecessor-district+"
                        "batched-wbgetentities"
                    ),
                })
            else:
                row["match_status"] = "ambiguous"
                row["match_notes"] = (
                    f"{len(verified_hits)} verified {source} candidates match "
                    f"current province; {len(component_hits)} match predecessor districts"
                )
        elif not verified:
            row["match_status"] = "unverified-candidate"
            row["match_notes"] = f"{len(qids)} QLever {source} candidate(s)"
        elif any(qid not in verified for qid in qids):
            row["match_status"] = "unverified-candidate"
            row["match_notes"] = "candidate set is not completely API-verified"
        else:
            row["match_status"] = "needs-review"
            row["match_notes"] = (
                "candidate name, tier, active-date, or current-province evidence disagrees"
            )
        rows.append(row)

    if broad_artifact is not None:
        broad_review = {
            row["local_id"]: row for row in broad_artifact.get("review", [])
        }
        broad_entities = {
            row["qid"]: row
            for row in broad_artifact.get("action_api_verification", {}).get(
                "entities", []
            )
        }
        eligible = {
            row["local_id"]: broad_review.get(row["local_id"], {}).get(
                "auto_candidate_qids", []
            )
            for row in rows
            if not row["valid_to"] and not row["wikidata_qid"]
        }
        proposed = Counter(
            qids[0] for qids in eligible.values() if len(qids) == 1
        )
        already_assigned = {
            row["wikidata_qid"] for row in rows if row["wikidata_qid"]
        }
        for row in rows:
            qids = eligible.get(row["local_id"], [])
            if len(qids) != 1:
                continue
            qid = qids[0]
            row["candidate_qids"] = "|".join(sorted({
                *filter(None, row["candidate_qids"].split("|")), qid,
            }, key=lambda value: int(value[1:])))
            if qid in already_assigned or proposed[qid] > 1:
                row["match_status"] = "ambiguous"
                row["match_notes"] = f"broad candidate {qid} is already assigned"
                continue
            if qid not in broad_entities:
                continue
            row.update({
                "wikidata_qid": qid,
                "qid_status": "existing",
                "match_status": "matched",
                "match_notes": (
                    "broad-exact-vi+current-province+ward-class+"
                    "batched-wbgetentities"
                ),
            })

    automatic_by_qid: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row["wikidata_qid"] and row["match_status"] == "matched":
            automatic_by_qid[row["wikidata_qid"]].append(row)
    for qid, assigned in automatic_by_qid.items():
        if len(assigned) < 2:
            continue
        local_ids = ",".join(row["local_id"] for row in assigned)
        for row in assigned:
            row.update({
                "wikidata_qid": "",
                "qid_status": "",
                "match_status": "ambiguous",
                "match_notes": f"candidate {qid} also matches {local_ids}",
            })
    return apply_review_decisions(rows, review_decisions)


def serialize_mapping(rows: list[dict]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=MAPPING_HEADER, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def write_mapping(rows: list[dict], path: Path = MAPPING) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(serialize_mapping(rows), encoding="utf-8")
    temporary.replace(path)
    return path


def audit_mapping(
    history: dict,
    candidate_artifact: dict,
    rows: list[dict],
    broad_artifact: dict | None = None,
    review_decisions: dict | None = None,
) -> dict:
    issues = []
    if len(rows) != LOCKED_GRAPH_COUNTS["entities"]:
        issues.append(f"ROW-COUNT {len(rows)}")
    entity_by_id = {row["local_id"]: row for row in history["entities"]}
    if len(entity_by_id) != len(history["entities"]):
        issues.append("GRAPH-DUPLICATE-LOCAL-ID")
    if len({row["local_id"] for row in rows}) != len(rows):
        issues.append("MAPPING-DUPLICATE-LOCAL-ID")

    current = [row for row in rows if not row["valid_to"]]
    if len(current) != LOCKED_GRAPH_COUNTS["current"]:
        issues.append(f"CURRENT-COUNT {len(current)}")
    current_keys = [
        (row["parent_code"], fold_ward_name(row["name_vi"])) for row in current
    ]
    current_fold_collisions = len(current_keys) - len(set(current_keys))

    candidate_ids = {row["qid"] for row in candidate_artifact["candidates"]}
    verified_ids = {
        row["qid"]
        for row in candidate_artifact.get("action_api_verification", {}).get(
            "entities", []
        )
    }
    if broad_artifact is not None:
        candidate_ids.update(
            row["qid"] for row in broad_artifact.get("candidates", [])
        )
        verified_ids.update(
            row["qid"]
            for row in broad_artifact.get("action_api_verification", {}).get(
                "entities", []
            )
        )
    decisions = _review_decision_index(review_decisions)
    candidate_ids.update(
        decision.get("wikidata_qid", "")
        for _, decision in decisions.values()
        if decision.get("wikidata_qid")
    )
    broad_auto = {
        row["local_id"]: set(row.get("auto_candidate_qids", []))
        for row in (broad_artifact or {}).get("review", [])
    }
    by_qid: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        entity = entity_by_id.get(row["local_id"])
        if entity is None:
            issues.append(f"UNKNOWN-LOCAL-ID {row['local_id']}")
            continue
        expected = _base_mapping_row(entity)
        for field in (
            "terminal_code", "name_vi", "loai_hinh", "parent_code",
            "valid_from", "valid_to",
        ):
            if row[field] != expected[field]:
                issues.append(f"GRAPH-DRIFT {row['local_id']} {field}")
        listed = [qid for qid in row["candidate_qids"].split("|") if qid]
        if any(qid not in candidate_ids for qid in listed):
            issues.append(f"UNKNOWN-CANDIDATE {row['local_id']}")
        qid = row["wikidata_qid"]
        if qid:
            if not _QID.fullmatch(qid):
                issues.append(f"INVALID-QID {row['local_id']} {qid}")
            by_qid[qid].append(row)
            if row["match_status"] == "matched":
                if qid not in listed:
                    issues.append(f"MATCH-NOT-CANDIDATE {row['local_id']} {qid}")
                if qid not in verified_ids:
                    issues.append(f"MATCH-NOT-API-VERIFIED {row['local_id']} {qid}")
                if row["match_notes"].startswith("broad-") and qid not in broad_auto.get(
                    row["local_id"], set()
                ):
                    issues.append(f"BROAD-MATCH-NOT-AUTO {row['local_id']} {qid}")

    for qid, assigned in sorted(by_qid.items()):
        if len(assigned) > 1:
            issues.append(
                f"QID-COLLISION {qid} <- "
                + " | ".join(row["local_id"] for row in assigned)
            )

    rows_by_id = {row["local_id"]: row for row in rows}
    for local_id, (_, decision) in decisions.items():
        row = rows_by_id.get(local_id)
        if row is None:
            issues.append(f"REVIEW-UNKNOWN-LOCAL-ID {local_id}")
        elif decision["outcome"] == "assign" and (
            row["wikidata_qid"] != decision["wikidata_qid"]
            or row["match_status"] != "manual"
        ):
            issues.append(f"REVIEW-ASSIGNMENT-DRIFT {local_id}")
        elif decision["outcome"] == "retain-unresolved" and (
            row["wikidata_qid"] or row["match_status"] != "reviewed-unresolved"
        ):
            issues.append(f"REVIEW-UNRESOLVED-DRIFT {local_id}")

    statuses = Counter(row["match_status"] for row in rows)
    unresolved_current = sum(
        not row["wikidata_qid"] and row["match_status"] != "gap"
        for row in current
    )
    return {
        "summary": {
            "rows": len(rows),
            "current_rows": len(current),
            "historical_rows": len(rows) - len(current),
            "current_resolved": sum(bool(row["wikidata_qid"]) for row in current),
            "current_unresolved": unresolved_current,
            "current_acknowledged_gaps": sum(
                row["match_status"] == "gap" for row in current
            ),
            "current_fold_collisions": current_fold_collisions,
            "distinct_assigned_qids": len(by_qid),
            "status_counts": dict(sorted(statuses.items())),
            "candidate_snapshot_rows": candidate_artifact["audit"]["candidates"],
            "api_verified_candidates": candidate_artifact["audit"][
                "api_verified_candidates"
            ],
            "review_decisions": len(decisions),
            "structural_issues": len(issues),
        },
        "issues": issues,
    }


def format_audit(audit: dict) -> str:
    summary = audit["summary"]
    return (
        f"ward Wikidata reconciliation: {summary['current_resolved']}/"
        f"{summary['current_rows']} current resolved; "
        f"{summary['candidate_snapshot_rows']} bulk candidates, "
        f"{summary['api_verified_candidates']} API-verified; "
        f"{summary['structural_issues']} structural issues"
    )


def _load_inputs() -> tuple[dict, dict, dict[str, set[str]], dict | None, dict]:
    history = json.loads(WARD_HISTORY.read_text(encoding="utf-8"))
    if history["audit"]["entities"] != LOCKED_GRAPH_COUNTS["entities"]:
        raise ValueError("ward history entity count drifted")
    candidate_artifact = json.loads(CANDIDATE_CACHE.read_text(encoding="utf-8"))
    parent_index = build_parent_qid_index()
    broad_artifact = None
    if BROAD_CANDIDATE_CACHE.is_file():
        broad_artifact = json.loads(
            BROAD_CANDIDATE_CACHE.read_text(encoding="utf-8")
        )
    review_decisions = {"batches": []}
    if REVIEW_DECISIONS.is_file():
        review_decisions = json.loads(
            REVIEW_DECISIONS.read_text(encoding="utf-8")
        )
    return (
        history, candidate_artifact, parent_index, broad_artifact,
        review_decisions,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Build the read-only ward-to-Wikidata reconciliation mapping"
    )
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--normalize", action="store_true")
    parser.add_argument("--verify-current", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--output", type=Path, default=MAPPING)
    args = parser.parse_args(argv)

    if args.fetch:
        path = fetch_qlever_result()
        print(f"saved exact QLever result: {path}")
        args.normalize = True
    if args.normalize:
        path = write_candidate_cache(normalize_qlever_result())
        print(f"wrote normalized candidates: {path}")
    if args.verify_current:
        artifact = json.loads(CANDIDATE_CACHE.read_text(encoding="utf-8"))
        history = json.loads(WARD_HISTORY.read_text(encoding="utf-8"))
        artifact = verify_current_candidates(
            artifact, history, build_parent_qid_index(),
        )
        write_candidate_cache(artifact)
        print(
            "verified current candidate set through wbgetentities: "
            f"{artifact['audit']['api_verified_candidates']} items"
        )

    history, candidates, parent_index, broad, review_decisions = _load_inputs()
    prior = _read_csv(args.output)
    rows = build_mapping_rows(
        history, candidates, parent_index,
        broad_artifact=broad,
        prior_rows=prior,
        review_decisions=review_decisions,
    )
    rendered = serialize_mapping(rows)
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != rendered:
            raise SystemExit(f"ward Wikidata mapping is missing or stale: {args.output}")
        action = "verified"
    else:
        write_mapping(rows, args.output)
        action = "wrote"

    audit = audit_mapping(
        history, candidates, rows, broad, review_decisions,
    )
    if args.audit:
        print(f"{action} {args.output}\n{format_audit(audit)}")
        for issue in audit["issues"][:20]:
            print(f"  {issue}")
    else:
        print(f"{action} {args.output}: {len(rows)} rows")
    if audit["issues"]:
        raise SystemExit("ward Wikidata mapping has structural issues")
    if args.strict and audit["summary"]["current_unresolved"]:
        raise SystemExit(
            "ward Wikidata mapping is not review-complete: "
            f"{audit['summary']['current_unresolved']} current rows unresolved"
        )


if __name__ == "__main__":
    main()
