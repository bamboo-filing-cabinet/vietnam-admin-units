"""Collect reproducible live evidence for a random predecessor-gap sample.

The primary and broad reconciliation passes deliberately favor precision. This
audit samples provisional CREATE rows and searches Wikidata and Vietnamese
Wikipedia more broadly, so spelling variants and incomplete P131 statements can
be inspected before any mass creation is authorized.

No command in this module writes to Wikidata or Wikipedia.
"""
from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import json
import re
import urllib.parse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from vn_admin_units.ward_reconcile import (
    MAPPING,
    WIKIDATA_API,
    _request_bytes,
    fetch_action_api_entities,
    fold_ward_name,
)


VIWIKI_API = "https://vi.wikipedia.org/w/api.php"
MANIFEST_PATH = Path("data/ward-wikidata-create-predecessors.json")
EVIDENCE_PATH = Path("data/ward-wikidata-predecessor-gap-sample.json")
DECISIONS_PATH = Path(
    "data/ward-wikidata-predecessor-gap-sample-decisions.json"
)
DEFAULT_SEED = "2026-09-04-predecessor-gap-audit-v1"
DEFAULT_SAMPLE_SIZE = 50
DEFAULT_BATCH_SIZE = 10
_TIER_PREFIX = re.compile(r"^(Xã|Phường|Thị trấn|Đặc khu)\s+", re.IGNORECASE)
_PARENT_PREFIX = re.compile(
    r"^(Huyện|Quận|Thị xã|Thành phố)\s+", re.IGNORECASE,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_csv(path: Path) -> list[dict]:
    return list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))


def _serialize_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def select_sample(items: list[dict], seed: str, size: int) -> list[dict]:
    """Return a deterministic simple random sample without replacement."""
    if size < 1 or size > len(items):
        raise ValueError(f"sample size must be between 1 and {len(items)}")

    def priority(item: dict) -> tuple[str, str]:
        digest = hashlib.sha256(
            f"{seed}\0{item['local_id']}".encode("utf-8")
        ).hexdigest()
        return digest, item["local_id"]

    return sorted(items, key=priority)[:size]


def search_terms(item: dict) -> list[str]:
    short_name = _TIER_PREFIX.sub("", item["name_vi"]).strip()
    parent_name = _PARENT_PREFIX.sub("", item["parent_name_vi"]).strip()
    return list(dict.fromkeys([
        item["name_vi"],
        short_name,
        f"{short_name} {parent_name}",
    ]))


def _request_json(url: str) -> dict:
    return json.loads(_request_bytes(url, timeout=60))


def _wikidata_search(item: dict, *, request_fn=_request_json) -> list[dict]:
    indexed: dict[str, dict] = {}
    for term in search_terms(item):
        url = WIKIDATA_API + "?" + urllib.parse.urlencode({
            "action": "wbsearchentities",
            "search": term,
            "language": "vi",
            "uselang": "vi",
            "type": "item",
            "limit": 10,
            "format": "json",
            "maxlag": "30",
        })
        payload = request_fn(url)
        if "error" in payload:
            raise RuntimeError(f"Wikidata search failed: {payload['error']}")
        for rank, result in enumerate(payload.get("search", []), start=1):
            qid = result.get("id", "")
            if not re.fullmatch(r"Q[1-9][0-9]*", qid):
                continue
            row = indexed.setdefault(qid, {
                "qid": qid,
                "label": result.get("label", ""),
                "description": result.get("description", ""),
                "matched_terms": [],
                "best_rank": rank,
            })
            row["matched_terms"].append(term)
            row["best_rank"] = min(row["best_rank"], rank)
    return sorted(
        indexed.values(), key=lambda row: (row["best_rank"], int(row["qid"][1:])),
    )


def _viwiki_search(item: dict, *, request_fn=_request_json) -> list[dict]:
    short_name = _TIER_PREFIX.sub("", item["name_vi"]).strip()
    parent_name = _PARENT_PREFIX.sub("", item["parent_name_vi"]).strip()
    query = f'"{short_name}" "{parent_name}"'
    url = VIWIKI_API + "?" + urllib.parse.urlencode({
        "action": "query",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": 0,
        "gsrlimit": 10,
        "prop": "pageprops|extracts",
        "exintro": 1,
        "explaintext": 1,
        "exchars": 800,
        "redirects": 1,
        "format": "json",
        "formatversion": 2,
    })
    payload = request_fn(url)
    if "error" in payload:
        raise RuntimeError(f"Vietnamese Wikipedia search failed: {payload['error']}")
    pages = payload.get("query", {}).get("pages", [])
    return [
        {
            "page_id": page.get("pageid"),
            "title": page.get("title", ""),
            "wikibase_item": page.get("pageprops", {}).get("wikibase_item", ""),
            "extract": page.get("extract", ""),
        }
        for page in sorted(pages, key=lambda page: page.get("index", 9999))
        if not page.get("missing")
    ]


def _parallel_by_local_id(items: list[dict], function, workers: int) -> dict:
    results = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(function, item): item for item in items}
        for future in as_completed(futures):
            item = futures[future]
            results[item["local_id"]] = future.result()
    return results


def _candidate_flags(
    item: dict,
    candidate: dict,
    *,
    assigned_qids: dict[str, list[str]],
    checked_qids: set[str],
    viwiki_pages: list[dict],
) -> list[str]:
    flags = []
    qid = candidate["qid"]
    wanted_name = fold_ward_name(item["name_vi"])
    names = [
        candidate.get("search_label", ""),
        *candidate.get("labels", {}).values(),
        *candidate.get("aliases", []),
    ]
    names = [value for value in names if value]
    exact_name = any(fold_ward_name(value) == wanted_name for value in names)
    name_similarity = max(
        (
            difflib.SequenceMatcher(None, wanted_name, fold_ward_name(value)).ratio()
            for value in names
        ),
        default=0,
    )
    parent_in_description = fold_ward_name(
        _PARENT_PREFIX.sub("", item["parent_name_vi"])
    ) in fold_ward_name(candidate.get("search_description", ""))
    context = " ".join(
        page.get("extract", "") for page in viwiki_pages
        if page.get("wikibase_item") == qid
    )
    parent_in_article = name_similarity >= 0.8 and fold_ward_name(
        _PARENT_PREFIX.sub("", item["parent_name_vi"])
    ) in fold_ward_name(context)

    if qid in assigned_qids:
        flags.append("assigned-to-reconciled-unit")
    if qid in checked_qids:
        flags.append("already-checked-by-machine-pass")
    else:
        flags.append("new-broader-search-candidate")
    if exact_name:
        flags.append("exact-folded-name")
    elif name_similarity >= 0.8:
        flags.append("similar-folded-name")
    if item["parent_qid"] in candidate.get("p131", []):
        flags.append("expected-district-p131")
    if parent_in_description:
        flags.append("expected-district-in-search-description")
    if parent_in_article:
        flags.append("expected-district-in-viwiki-extract")
    return flags


def build_evidence(
    manifest: dict,
    mapping_rows: list[dict],
    *,
    seed: str = DEFAULT_SEED,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    batch_size: int = DEFAULT_BATCH_SIZE,
    workers: int = 8,
    wikidata_search_fn=_wikidata_search,
    viwiki_search_fn=_viwiki_search,
    entity_fetch_fn=fetch_action_api_entities,
) -> dict:
    if batch_size < 1:
        raise ValueError("batch size must be positive")
    selected = select_sample(manifest["items"], seed, sample_size)
    wikidata = _parallel_by_local_id(selected, wikidata_search_fn, workers)
    viwiki = _parallel_by_local_id(selected, viwiki_search_fn, workers)
    qids = {
        result["qid"] for rows in wikidata.values() for result in rows
    } | {
        page["wikibase_item"]
        for pages in viwiki.values() for page in pages if page["wikibase_item"]
    }
    entities = {row["qid"]: row for row in entity_fetch_fn(sorted(qids))}
    search_rows = {
        local_id: {row["qid"]: row for row in rows}
        for local_id, rows in wikidata.items()
    }
    assigned_qids: dict[str, list[str]] = defaultdict(list)
    for row in mapping_rows:
        if row.get("wikidata_qid"):
            assigned_qids[row["wikidata_qid"]].append(row["local_id"])

    rows = []
    flagged = 0
    for offset, item in enumerate(selected):
        local_id = item["local_id"]
        candidate_qids = {
            *search_rows[local_id],
            *(page["wikibase_item"] for page in viwiki[local_id]
              if page["wikibase_item"]),
        }
        checked = set(item["candidate_qids_checked"])
        candidates = []
        for qid in sorted(candidate_qids, key=lambda value: int(value[1:])):
            entity = dict(entities[qid])
            search = search_rows[local_id].get(qid, {})
            entity["search_label"] = search.get("label", "")
            entity["search_description"] = search.get("description", "")
            entity["search_terms"] = search.get("matched_terms", [])
            entity["search_best_rank"] = search.get("best_rank")
            entity["assigned_local_ids"] = assigned_qids.get(qid, [])
            entity["flags"] = _candidate_flags(
                item,
                entity,
                assigned_qids=assigned_qids,
                checked_qids=checked,
                viwiki_pages=viwiki[local_id],
            )
            name_related = any(flag in entity["flags"] for flag in (
                "exact-folded-name", "similar-folded-name",
            ))
            if name_related and (
                "expected-district-p131" in entity["flags"]
                or "expected-district-in-search-description" in entity["flags"]
                or "expected-district-in-viwiki-extract" in entity["flags"]
            ) and "assigned-to-reconciled-unit" not in entity["flags"]:
                entity["review_priority"] = "possible-missed-item"
            else:
                entity["review_priority"] = "context-check"
            candidates.append(entity)
        possible = [
            row["qid"] for row in candidates
            if row["review_priority"] == "possible-missed-item"
        ]
        flagged += bool(possible)
        rows.append({
            "sample_number": offset + 1,
            "batch_number": offset // batch_size + 1,
            "local_id": local_id,
            "name_vi": item["name_vi"],
            "loai_hinh": item["loai_hinh"],
            "gso_code": item["gso_code"],
            "parent_name_vi": item["parent_name_vi"],
            "parent_qid": item["parent_qid"],
            "valid_from": item["valid_from"],
            "valid_to": item["valid_to"],
            "successor_qids": item["successor_qids"],
            "broad_classification": item["broad_classification"],
            "candidate_qids_checked": item["candidate_qids_checked"],
            "search_terms": search_terms(item),
            "wikidata_candidates": candidates,
            "viwiki_pages": viwiki[local_id],
            "possible_missed_qids": possible,
            "review_outcome": "pending",
        })

    return {
        "schema_version": 1,
        "scope": {
            "tier": "ward",
            "purpose": "random audit of provisional predecessor creation gaps",
            "wikidata_write_performed": False,
        },
        "sampling": {
            "method": "lowest SHA-256(seed + NUL + local_id)",
            "seed": seed,
            "population": len(manifest["items"]),
            "sample_size": sample_size,
            "batch_size": batch_size,
            "batches": (sample_size + batch_size - 1) // batch_size,
        },
        "sources": {
            "retrieved_at": _utc_now(),
            "wikidata_search_endpoint": WIKIDATA_API,
            "wikidata_entity_endpoint": WIKIDATA_API,
            "viwiki_search_endpoint": VIWIKI_API,
        },
        "input_fingerprints": {
            MANIFEST_PATH.as_posix(): _sha256(MANIFEST_PATH),
            MAPPING.as_posix(): _sha256(MAPPING),
        },
        "audit": {
            "rows": len(rows),
            "unique_local_ids": len({row["local_id"] for row in rows}),
            "classification_counts": dict(sorted(Counter(
                row["broad_classification"] for row in rows
            ).items())),
            "wikidata_candidate_items": len(qids),
            "rows_with_possible_missed_item": flagged,
        },
        "rows": rows,
    }


def audit_decisions(evidence: dict, decisions: dict) -> list[str]:
    issues = []
    evidence_by_number = {
        row["sample_number"]: row for row in evidence["rows"]
    }
    reviewed = [
        row for batch in decisions.get("batches", [])
        for row in batch.get("decisions", [])
    ]
    if len(reviewed) != evidence["sampling"]["sample_size"]:
        issues.append("DECISION-COUNT")
    if len({row.get("sample_number") for row in reviewed}) != len(reviewed):
        issues.append("DUPLICATE-DECISION-NUMBER")
    allowed = {
        "existing-predecessor-item",
        "existing-predecessor-item-after-current-swap",
        "no-distinct-item-found",
    }
    for decision in reviewed:
        number = decision.get("sample_number")
        evidence_row = evidence_by_number.get(number)
        if evidence_row is None or evidence_row["local_id"] != decision.get("local_id"):
            issues.append(f"DECISION-ROW {number}")
            continue
        if decision.get("outcome") not in allowed:
            issues.append(f"DECISION-OUTCOME {number}")
        qid = decision.get("wikidata_qid", "")
        candidates = {
            row["qid"] for row in evidence_row["wikidata_candidates"]
        }
        if qid and qid not in candidates:
            issues.append(f"DECISION-QID {number} {qid}")
    existing = sum(
        row.get("outcome", "").startswith("existing-predecessor-item")
        for row in reviewed
    )
    no_item = sum(
        row.get("outcome") == "no-distinct-item-found" for row in reviewed
    )
    audit_data = decisions.get("audit", {})
    expected_audit = {
        "reviewed_rows": len(reviewed),
        "existing_predecessor_items": existing,
        "current_mapping_swaps": sum(
            row.get("outcome") == "existing-predecessor-item-after-current-swap"
            for row in reviewed
        ),
        "no_distinct_item_found": no_item,
        "sample_miss_rate": round(existing / len(reviewed), 6) if reviewed else 0,
        "creation_batch_authorized": existing == 0 and len(reviewed) == len(evidence_by_number),
    }
    if audit_data != expected_audit:
        issues.append("DECISION-AUDIT")
    return issues


def audit(
    evidence: dict,
    manifest: dict,
    mapping_rows: list[dict],
    decisions: dict | None = None,
) -> list[str]:
    issues = []
    sampling = evidence["sampling"]
    baseline_manifest = evidence["input_fingerprints"].get(
        MANIFEST_PATH.as_posix()
    ) == _sha256(MANIFEST_PATH)
    if baseline_manifest:
        expected = select_sample(
            manifest["items"], sampling["seed"], sampling["sample_size"],
        )
        if [row["local_id"] for row in evidence["rows"]] != [
            row["local_id"] for row in expected
        ]:
            issues.append("SAMPLE-DRIFT")
        if sampling["population"] != len(manifest["items"]):
            issues.append("POPULATION-DRIFT")
    if len({row["local_id"] for row in evidence["rows"]}) != len(evidence["rows"]):
        issues.append("DUPLICATE-SAMPLE-ROW")
    assigned = {
        row["wikidata_qid"] for row in mapping_rows if row.get("wikidata_qid")
    }
    baseline_mapping = evidence["input_fingerprints"].get(
        MAPPING.as_posix()
    ) == _sha256(MAPPING)
    if baseline_mapping:
        for row in evidence["rows"]:
            for candidate in row["wikidata_candidates"]:
                if bool(candidate["assigned_local_ids"]) != (
                    candidate["qid"] in assigned
                ):
                    issues.append(
                        f"ASSIGNMENT-DRIFT {row['local_id']} {candidate['qid']}"
                    )
    if decisions is not None:
        issues.extend(audit_decisions(evidence, decisions))
    return issues


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Audit a deterministic random sample of predecessor gaps",
    )
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--seed", default=DEFAULT_SEED)
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(argv)

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    mapping = _read_csv(MAPPING)
    if args.fetch:
        evidence = build_evidence(
            manifest,
            mapping,
            seed=args.seed,
            sample_size=args.sample_size,
            batch_size=args.batch_size,
            workers=args.workers,
        )
        _write(EVIDENCE_PATH, _serialize_json(evidence))
        action = "wrote"
    else:
        evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
        action = "checked"
    decisions = (
        json.loads(DECISIONS_PATH.read_text(encoding="utf-8"))
        if DECISIONS_PATH.is_file() else None
    )
    issues = audit(evidence, manifest, mapping, decisions)
    if args.check and issues:
        raise SystemExit("; ".join(issues))
    if args.audit:
        print(
            f"{action} {evidence['audit']['rows']} sampled predecessor gaps in "
            f"{evidence['sampling']['batches']} batches; "
            f"possible missed items={evidence['audit']['rows_with_possible_missed_item']}; "
            f"issues={len(issues)}"
        )
        print(json.dumps(evidence["audit"], ensure_ascii=False, indent=2))
        if decisions is not None:
            print(json.dumps(decisions["audit"], ensure_ascii=False, indent=2))
        for issue in issues:
            print(f"  {issue}")


if __name__ == "__main__":
    main()
