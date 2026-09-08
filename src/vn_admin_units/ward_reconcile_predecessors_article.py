"""Recover former wards with strong article ownership but unusable P131.

This pass starts only from unresolved exact-name candidates in the saved
ward-class corpus. It refreshes those candidates through batched
``wbgetentities`` calls and accepts a match only when one exact-tier candidate
uniquely owns the matching Vietnamese Wikipedia article. Rows whose 2025
successor kept the same name are withheld because article ownership alone
cannot distinguish a current item from its predecessor.

No command in this module writes to Wikidata or Wikipedia.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from vn_admin_units.names import fold_ward_name
from vn_admin_units.ward_reconcile import (
    CANDIDATE_CACHE,
    MAPPING,
    WARD_HISTORY,
    WIKIDATA_API,
    fetch_action_api_entities,
    serialize_json,
    write_mapping,
)
from vn_admin_units.ward_reconcile_predecessors import (
    ARTIFACT_PATH as PRIMARY_ARTIFACT_PATH,
    BROAD_ARTIFACT_PATH,
    EXPECTED_CLASS_BY_TIER,
    _qid_key,
    _sha256,
    _verified_name_match_kinds,
    apply_matches,
)


ARTIFACT_PATH = Path("data/ward-wikidata-predecessor-article-candidates.json")
_TIER_PREFIX = re.compile(
    r"^(xã|phường|thị trấn|đặc khu)\s+", re.IGNORECASE,
)
_PARENT_PREFIX = re.compile(
    r"^(huyện|quận|thị xã|thành phố|tỉnh)\s+", re.IGNORECASE,
)
_ARTICLE_MATCH_NOTE = "predecessor unique-matching-viwiki-article+"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_csv(path: Path) -> list[dict]:
    return list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))


def _normalized_vi_name(value: str) -> str:
    value = _TIER_PREFIX.sub("", value.strip())
    value = re.sub(r"\s*\([^)]*\)\s*$", "", value)
    value = " ".join(value.casefold().split())
    return unicodedata.normalize("NFC", value)


def _article_title_match_kind(name_vi: str, title: str) -> str:
    wanted = _normalized_vi_name(name_vi)
    if _normalized_vi_name(title) == wanted:
        return "exact"
    if "," in title and _normalized_vi_name(title.split(",", 1)[0]) == wanted:
        return "qualified"
    return ""


def _verified_exact_name_match_kinds(row: dict, entity: dict) -> list[str]:
    wanted = _normalized_vi_name(row["name_vi"])
    kinds = set()
    for language, value in entity.get("labels", {}).items():
        if _normalized_vi_name(value) == wanted:
            kinds.add(f"label_{language}")
        if (
            "," in value
            and _normalized_vi_name(value.split(",", 1)[0]) == wanted
        ):
            kinds.add(f"label_{language}-qualified")
    if any(
        _normalized_vi_name(value) == wanted
        for value in entity.get("aliases", [])
    ):
        kinds.add("alias")
    return sorted(kinds)


def _successor_context(
    history: dict,
    mapping_rows: list[dict],
) -> dict[str, dict[str, list[str]]]:
    entities = {row["local_id"]: row for row in history["entities"]}
    mapping = {row["local_id"]: row for row in mapping_rows}
    names: dict[str, set[str]] = defaultdict(set)
    qids: dict[str, set[str]] = defaultdict(set)
    for edge in history["lineage_edges"]:
        if edge["effective_date"] != "2025-07-01":
            continue
        successor = entities[edge["successor"]]
        predecessor = edge["predecessor"]
        names[predecessor].add(successor["name_vi"])
        qid = mapping[successor["local_id"]]["wikidata_qid"]
        if qid:
            qids[predecessor].add(qid)
    return {
        local_id: {
            "names": sorted(names[local_id]),
            "qids": sorted(qids[local_id], key=_qid_key),
        }
        for local_id in names
    }


def _context_names(entity: dict, key: str) -> list[str]:
    values = {
        span.get("name_vi", "").strip()
        for span in entity.get(key, [])
    }
    return sorted(value for value in values if value)


def _description_mentions_parent(row: dict, description: str) -> bool:
    folded_description = fold_ward_name(description)
    province_bases = {
        fold_ward_name(_PARENT_PREFIX.sub("", value))
        for value in row["province_names_vi"]
    }
    for parent in row["parent_names_vi"]:
        full = fold_ward_name(parent)
        base = fold_ward_name(_PARENT_PREFIX.sub("", parent))
        if full in folded_description:
            return True
        if base not in province_bases and base in folded_description:
            return True
    return False


def _article_title_mentions_context(row: dict, title: str) -> bool:
    if "," not in title:
        return False
    qualifier = fold_ward_name(title.split(",", 1)[1])
    return any(
        fold_ward_name(_PARENT_PREFIX.sub("", value)) in qualifier
        for value in [*row["parent_names_vi"], *row["province_names_vi"]]
    )


def _context_support_flags(row: dict, entity: dict) -> list[str]:
    description = " ".join(entity.get("descriptions", {}).values())
    flags = []
    if set(entity.get("p131", [])) & set(row["successor_qids"]):
        flags.append("successor-p131")
    if _description_mentions_parent(row, description):
        flags.append("historical-parent-in-description")
    return flags


def _clear_prior_article_matches(mapping_rows: list[dict]) -> list[dict]:
    rows = json.loads(json.dumps(mapping_rows))
    for row in rows:
        if row.get("match_notes", "").startswith(_ARTICLE_MATCH_NOTE):
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


def build_review(
    history: dict,
    candidates: dict,
    primary: dict,
    broad: dict,
    mapping_rows: list[dict],
) -> dict:
    candidate_by_qid = {row["qid"]: row for row in candidates["candidates"]}
    history_by_id = {row["local_id"]: row for row in history["entities"]}
    broad_resolved = {
        row["local_id"] for row in broad["review"]
        if row["auto_candidate_qids"]
    }
    primary_resolved = {
        row["local_id"] for row in primary["review"]
        if row["auto_candidate_qids"]
    }
    mapping_by_id = {row["local_id"]: row for row in mapping_rows}
    assigned: dict[str, set[str]] = defaultdict(set)
    for row in mapping_rows:
        if row["wikidata_qid"] and (
            not row.get("valid_to")
            or row.get("match_status") == "manual"
            or row["local_id"] in primary_resolved
            or row["local_id"] in broad_resolved
        ):
            assigned[row["wikidata_qid"]].add(row["local_id"])
    successor_context = _successor_context(history, mapping_rows)
    name_occurrences = Counter(
        _normalized_vi_name(row["name_vi"]) for row in primary["review"]
    )
    province_name_occurrences = Counter()
    for row in primary["review"]:
        entity = history_by_id[row["local_id"]]
        for code in {
            span["code"] for span in entity.get("province_echo_spans", [])
        }:
            province_name_occurrences[
                (_normalized_vi_name(row["name_vi"]), row["loai_hinh"], code)
            ] += 1
    review = []
    shortlisted = set()
    for row in primary["review"]:
        local_id = row["local_id"]
        mapping_row = mapping_by_id[local_id]
        if (
            row["auto_candidate_qids"]
            or local_id in broad_resolved
            or (
                mapping_row["wikidata_qid"]
                and mapping_row["match_status"] == "manual"
            )
        ):
            continue
        expected_class = EXPECTED_CLASS_BY_TIER[row["loai_hinh"]]
        qids = [
            qid for qid in row["candidate_qids"]
            if expected_class in candidate_by_qid[qid]["types"]
            and not (assigned.get(qid, set()) - {local_id})
        ]
        successors = successor_context.get(local_id, {"names": [], "qids": []})
        same_name_successor = any(
            _normalized_vi_name(name) == _normalized_vi_name(row["name_vi"])
            for name in successors["names"]
        )
        province_codes = sorted({
            span["code"]
            for span in history_by_id[local_id].get("province_echo_spans", [])
        })
        province_occurrences = [
            province_name_occurrences[
                (_normalized_vi_name(row["name_vi"]), row["loai_hinh"], code)
            ]
            for code in province_codes
        ]
        shortlisted.update(qids)
        review.append({
            "local_id": local_id,
            "terminal_code": row["terminal_code"],
            "name_vi": row["name_vi"],
            "loai_hinh": row["loai_hinh"],
            "parent_code": row["parent_code"],
            "parent_codes": row.get("parent_codes", [row["parent_code"]]),
            "successor_names_vi": successors["names"],
            "successor_qids": successors["qids"],
            "same_name_successor": same_name_successor,
            "predecessor_name_occurrences": name_occurrences[
                _normalized_vi_name(row["name_vi"])
            ],
            "name_tier_province_occurrences": (
                min(province_occurrences) if province_occurrences else 0
            ),
            "parent_names_vi": _context_names(
                history_by_id[local_id], "parent_spans",
            ),
            "province_names_vi": _context_names(
                history_by_id[local_id], "province_echo_spans",
            ),
            "prior_classification": row["classification"],
            "classification": (
                "awaiting-verification" if qids
                else "no-exact-tier-name-candidate"
            ),
            "candidate_qids": sorted(qids, key=_qid_key),
            "verified_candidate_qids": [],
            "article_candidate_qids": [],
            "article_title_match_kinds": {},
            "article_support_flags": {},
            "auto_candidate_qids": [],
            "confidence": "",
        })
    classifications = Counter(row["classification"] for row in review)
    return {
        "schema_version": 1,
        "scope": {
            "tier": "ward",
            "effective_date": "2025-07-01",
            "purpose": "unresolved_predecessor_unique_viwiki_article",
            "wikidata_write_performed": False,
        },
        "source": {
            "history_path": WARD_HISTORY.as_posix(),
            "history_sha256": _sha256(WARD_HISTORY),
            "candidate_path": CANDIDATE_CACHE.as_posix(),
            "candidate_sha256": _sha256(CANDIDATE_CACHE),
            "primary_path": PRIMARY_ARTIFACT_PATH.as_posix(),
            "primary_sha256": _sha256(PRIMARY_ARTIFACT_PATH),
            "broad_path": BROAD_ARTIFACT_PATH.as_posix(),
            "broad_sha256": _sha256(BROAD_ARTIFACT_PATH),
        },
        "audit": {
            "unresolved_input_rows": len(review),
            "rows_with_exact_tier_name_candidate": sum(
                bool(row["candidate_qids"]) for row in review
            ),
            "shortlisted_qids": len(shortlisted),
            "api_verified_candidates": 0,
            "rows_with_matching_viwiki_article": 0,
            "auto_matched_rows": 0,
            "unresolved_rows": len(review),
            "classification_counts": dict(sorted(classifications.items())),
        },
        "shortlisted_qids": sorted(shortlisted, key=_qid_key),
        "action_api_verification": {
            "endpoint": WIKIDATA_API,
            "retrieved_at": "",
            "entities": [],
        },
        "review": review,
    }


def evaluate(artifact: dict, mapping_rows: list[dict]) -> dict:
    result = json.loads(json.dumps(artifact))
    verified = {
        row["qid"]: row
        for row in result["action_api_verification"]["entities"]
    }
    assigned: dict[str, set[str]] = defaultdict(set)
    for row in mapping_rows:
        if row["wikidata_qid"] and (
            not row.get("valid_to") or row.get("match_status") == "manual"
        ):
            assigned[row["wikidata_qid"]].add(row["local_id"])
    proposed = {}
    for row in result["review"]:
        expected_class = EXPECTED_CLASS_BY_TIER[row["loai_hinh"]]
        name_qids = []
        article_qids = []
        title_kinds = {}
        support_flags_by_qid = {}
        for qid in row["candidate_qids"]:
            entity = verified.get(qid)
            if (
                entity is None
                or entity.get("missing")
                or assigned.get(qid, set()) - {row["local_id"]}
                or expected_class not in entity.get("p31", [])
                or not _verified_name_match_kinds(row, entity)
            ):
                continue
            name_qids.append(qid)
            title = entity.get("sitelinks", {}).get("viwiki", "")
            kind = _article_title_match_kind(row["name_vi"], title)
            if kind:
                article_qids.append(qid)
                title_kinds[qid] = kind
                flags = []
                if row["predecessor_name_occurrences"] == 1:
                    flags.append("unique-predecessor-name")
                flags.extend(_context_support_flags(row, entity))
                if (
                    _article_title_mentions_context(row, title)
                    and row["name_tier_province_occurrences"] == 1
                ):
                    flags.append("historical-context-in-article-title")
                support_flags_by_qid[qid] = flags
        row["verified_candidate_qids"] = name_qids
        row["article_candidate_qids"] = article_qids
        row["article_title_match_kinds"] = title_kinds
        row["article_support_flags"] = support_flags_by_qid
        row["auto_candidate_qids"] = []
        row["confidence"] = ""
        if not row["candidate_qids"]:
            continue
        supported_article_qids = [
            qid for qid in article_qids if support_flags_by_qid[qid]
        ]
        if not article_qids:
            row["classification"] = "no-matching-viwiki-article"
            continue
        if not supported_article_qids:
            row["classification"] = "no-geographic-or-uniqueness-support"
            continue
        if row["same_name_successor"]:
            row["classification"] = "same-name-successor-risk"
            continue
        if len(supported_article_qids) != 1:
            row["classification"] = "ambiguous-viwiki-articles"
            continue
        qid = supported_article_qids[0]
        row["auto_candidate_qids"] = [qid]
        row["classification"] = "verified-unique"
        row["confidence"] = (
            "unique-matching-viwiki-article+exact-tier+different-name-successor+"
            "batched-wbgetentities"
        )
        proposed[row["local_id"]] = qid

    proposal_counts = Counter(proposed.values())
    for row in result["review"]:
        qids = row["auto_candidate_qids"]
        if qids and proposal_counts[qids[0]] > 1:
            row["auto_candidate_qids"] = []
            row["classification"] = "qid-collision"
            row["confidence"] = ""

    classifications = Counter(row["classification"] for row in result["review"])
    auto = sum(bool(row["auto_candidate_qids"]) for row in result["review"])
    result["audit"].update({
        "api_verified_candidates": len(verified),
        "rows_with_matching_viwiki_article": sum(
            bool(row["article_candidate_qids"]) for row in result["review"]
        ),
        "auto_matched_rows": auto,
        "unresolved_rows": len(result["review"]) - auto,
        "classification_counts": dict(sorted(classifications.items())),
    })
    return result


def verify(
    artifact: dict,
    mapping_rows: list[dict],
    reused_entities: list[dict],
    *,
    fetch_fn=fetch_action_api_entities,
) -> dict:
    result = json.loads(json.dumps(artifact))
    shortlisted = set(result["shortlisted_qids"])
    existing = {
        row["qid"]: row for row in [
            *reused_entities,
            *result["action_api_verification"].get("entities", []),
        ]
        if (
            row["qid"] in shortlisted
            and row.get("lastrevid") is not None
            and "geonames_ids" in row
        )
    }
    missing = sorted(shortlisted - set(existing), key=_qid_key)
    fetched = fetch_fn(missing) if missing else []
    combined = {**existing, **{row["qid"]: row for row in fetched}}
    result["action_api_verification"] = {
        "endpoint": WIKIDATA_API,
        "retrieved_at": _utc_now(),
        "reused_candidates": len(existing),
        "fetched_candidates": len(fetched),
        "entities": [combined[qid] for qid in sorted(combined, key=_qid_key)],
    }
    return evaluate(result, mapping_rows)


def audit(artifact: dict, mapping_rows: list[dict]) -> list[str]:
    issues = []
    for key, path in (
        ("history_sha256", WARD_HISTORY),
        ("candidate_sha256", CANDIDATE_CACHE),
        ("primary_sha256", PRIMARY_ARTIFACT_PATH),
        ("broad_sha256", BROAD_ARTIFACT_PATH),
    ):
        if artifact["source"][key] != _sha256(path):
            issues.append(f"SOURCE-DRIFT {path}")
    shortlisted = {
        qid for row in artifact["review"] for qid in row["candidate_qids"]
    }
    if set(artifact["shortlisted_qids"]) != shortlisted:
        issues.append("SHORTLIST-QID-SET")
    verified = {
        row["qid"] for row in artifact["action_api_verification"]["entities"]
    }
    if verified and verified != shortlisted:
        issues.append("API-VERIFIED-QID-SET")
    automatic = [
        (row["local_id"], row["auto_candidate_qids"][0])
        for row in artifact["review"] if row["auto_candidate_qids"]
    ]
    if len({qid for _, qid in automatic}) != len(automatic):
        issues.append("AUTO-QID-COLLISION")
    mapping_by_id = {row["local_id"]: row for row in mapping_rows}
    for local_id, qid in automatic:
        row = mapping_by_id.get(local_id)
        if row is None or row["wikidata_qid"] != qid:
            issues.append(f"MAPPING-DRIFT {local_id}")
    return issues


def _write_artifact(artifact: dict) -> None:
    temporary = ARTIFACT_PATH.with_name(f".{ARTIFACT_PATH.name}.tmp")
    temporary.write_text(serialize_json(artifact), encoding="utf-8")
    temporary.replace(ARTIFACT_PATH)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Recover predecessors with unique viwiki article ownership",
    )
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--audit", action="store_true")
    args = parser.parse_args(argv)

    history = json.loads(WARD_HISTORY.read_text(encoding="utf-8"))
    candidates = json.loads(CANDIDATE_CACHE.read_text(encoding="utf-8"))
    primary = json.loads(PRIMARY_ARTIFACT_PATH.read_text(encoding="utf-8"))
    broad = json.loads(BROAD_ARTIFACT_PATH.read_text(encoding="utf-8"))
    mapping = _clear_prior_article_matches(_read_csv(MAPPING))
    artifact = build_review(history, candidates, primary, broad, mapping)
    saved = (
        json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
        if ARTIFACT_PATH.is_file() else None
    )
    if saved:
        shortlisted = set(artifact["shortlisted_qids"])
        artifact["action_api_verification"] = {
            **saved["action_api_verification"],
            "entities": [
                entity
                for entity in saved["action_api_verification"]["entities"]
                if entity["qid"] in shortlisted
            ],
        }
    if args.verify:
        reused = [
            *primary["action_api_verification"]["entities"],
            *broad["action_api_verification"]["entities"],
        ]
        artifact = verify(artifact, mapping, reused)
    elif artifact["action_api_verification"]["entities"]:
        artifact = evaluate(artifact, mapping)

    rendered_mapping = apply_matches(mapping, artifact)
    if args.check:
        if (
            not ARTIFACT_PATH.is_file()
            or ARTIFACT_PATH.read_text(encoding="utf-8") != serialize_json(artifact)
        ):
            raise SystemExit(f"article-owner artifact is stale: {ARTIFACT_PATH}")
        if MAPPING.read_text(encoding="utf-8") != _serialize_mapping(rendered_mapping):
            raise SystemExit(f"ward Wikidata mapping is stale: {MAPPING}")
        action = "verified"
    elif args.verify or args.rebuild:
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
            f"{data['unresolved_input_rows']} auto matched; "
            f"{data['shortlisted_qids']} API candidates; {len(issues)} issues"
        )
        print(json.dumps(data, ensure_ascii=False, indent=2))
        for issue in issues[:20]:
            print(f"  {issue}")
    if issues:
        raise SystemExit("predecessor article-owner reconciliation has audit issues")


def _serialize_mapping(rows: list[dict]) -> str:
    from vn_admin_units.ward_reconcile import serialize_mapping

    return serialize_mapping(rows)


if __name__ == "__main__":
    main()
