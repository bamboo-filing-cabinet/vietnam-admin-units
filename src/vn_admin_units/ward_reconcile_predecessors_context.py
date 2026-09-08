"""Recover predecessors from exact names plus explicit geographic context.

This pass consumes the saved Action API evidence collected by the article-owner
pass. It does not make additional network requests. A candidate must match the
Vietnamese spelling and exact ward tier, and either name a recorded historical
parent in its Wikidata description or use a reconciled 2025 successor as P131.
Same-name successors and non-unique context candidates remain unresolved.

No command in this module writes to Wikidata or Wikipedia.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from vn_admin_units.ward_reconcile import MAPPING, serialize_json, write_mapping
from vn_admin_units.ward_reconcile_predecessors import (
    EXPECTED_CLASS_BY_TIER,
    _qid_key,
    _sha256,
    apply_matches,
)
from vn_admin_units.ward_reconcile_predecessors_article import (
    ARTIFACT_PATH as ARTICLE_ARTIFACT_PATH,
    _context_support_flags,
    _verified_exact_name_match_kinds,
)


ARTIFACT_PATH = Path("data/ward-wikidata-predecessor-context-candidates.json")
_CONTEXT_MATCH_NOTE = "predecessor exact-vietnamese-name+exact-tier+"


def _read_csv(path: Path) -> list[dict]:
    return list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))


def _clear_prior_context_matches(mapping_rows: list[dict]) -> list[dict]:
    rows = json.loads(json.dumps(mapping_rows))
    for row in rows:
        if row.get("match_notes", "").startswith(_CONTEXT_MATCH_NOTE):
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


def build_artifact(article: dict, mapping_rows: list[dict]) -> dict:
    verified = {
        row["qid"]: row
        for row in article["action_api_verification"]["entities"]
    }
    assigned: dict[str, set[str]] = defaultdict(set)
    for row in mapping_rows:
        if row["wikidata_qid"]:
            assigned[row["wikidata_qid"]].add(row["local_id"])
    review = []
    proposed = {}
    for source in article["review"]:
        if source["auto_candidate_qids"]:
            continue
        exact_qids = []
        support = {}
        for qid in source["candidate_qids"]:
            entity = verified[qid]
            expected_class = EXPECTED_CLASS_BY_TIER[source["loai_hinh"]]
            if (
                entity.get("missing")
                or assigned.get(qid, set()) - {source["local_id"]}
                or expected_class not in entity.get("p31", [])
            ):
                continue
            name_kinds = _verified_exact_name_match_kinds(source, entity)
            if not name_kinds:
                continue
            exact_qids.append(qid)
            flags = _context_support_flags(source, entity)
            if flags:
                support[qid] = flags
        context_qids = sorted(support, key=_qid_key)
        auto = []
        confidence = ""
        if not exact_qids:
            classification = "no-exact-vietnamese-name-candidate"
        elif not context_qids:
            classification = "no-parent-or-successor-context"
        elif source["same_name_successor"]:
            classification = "same-name-successor-risk"
        elif len(context_qids) > 1:
            classification = "ambiguous-context-candidates"
        else:
            qid = context_qids[0]
            auto = [qid]
            classification = "verified-unique"
            confidence = (
                "exact-vietnamese-name+exact-tier+historical-parent-or-"
                "successor-context+batched-wbgetentities"
            )
            proposed[source["local_id"]] = qid
        review.append({
            "local_id": source["local_id"],
            "terminal_code": source["terminal_code"],
            "name_vi": source["name_vi"],
            "loai_hinh": source["loai_hinh"],
            "parent_code": source["parent_code"],
            "parent_codes": source["parent_codes"],
            "successor_names_vi": source["successor_names_vi"],
            "successor_qids": source["successor_qids"],
            "same_name_successor": source["same_name_successor"],
            "candidate_qids": source["candidate_qids"],
            "verified_candidate_qids": sorted(exact_qids, key=_qid_key),
            "context_candidate_qids": context_qids,
            "context_support_flags": support,
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
    return {
        "schema_version": 1,
        "scope": {
            "tier": "ward",
            "effective_date": "2025-07-01",
            "purpose": "unresolved_predecessor_geographic_context",
            "wikidata_write_performed": False,
        },
        "source": {
            "article_artifact_path": ARTICLE_ARTIFACT_PATH.as_posix(),
            "article_artifact_sha256": _sha256(ARTICLE_ARTIFACT_PATH),
        },
        "audit": {
            "unresolved_input_rows": len(review),
            "rows_with_exact_vietnamese_name": sum(
                bool(row["verified_candidate_qids"]) for row in review
            ),
            "rows_with_parent_or_successor_context": sum(
                bool(row["context_candidate_qids"]) for row in review
            ),
            "auto_matched_rows": auto,
            "unresolved_rows": len(review) - auto,
            "classification_counts": dict(sorted(classifications.items())),
        },
        "review": review,
    }


def audit(artifact: dict, mapping_rows: list[dict]) -> list[str]:
    issues = []
    if artifact["source"]["article_artifact_sha256"] != _sha256(
        ARTICLE_ARTIFACT_PATH
    ):
        issues.append("ARTICLE-ARTIFACT-DRIFT")
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
        description="Recover predecessors from exact names and context",
    )
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--audit", action="store_true")
    args = parser.parse_args(argv)

    mapping = _clear_prior_context_matches(_read_csv(MAPPING))
    article = json.loads(ARTICLE_ARTIFACT_PATH.read_text(encoding="utf-8"))
    artifact = build_artifact(article, mapping)
    rendered_mapping = apply_matches(mapping, artifact)
    if args.check:
        if (
            not ARTIFACT_PATH.is_file()
            or ARTIFACT_PATH.read_text(encoding="utf-8") != serialize_json(artifact)
        ):
            raise SystemExit(f"context artifact is stale: {ARTIFACT_PATH}")
        from vn_admin_units.ward_reconcile import serialize_mapping

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
        raise SystemExit("predecessor context reconciliation has audit issues")


if __name__ == "__main__":
    main()
