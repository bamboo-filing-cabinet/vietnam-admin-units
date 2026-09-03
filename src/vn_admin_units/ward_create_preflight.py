"""Read-only duplicate and sitelink preflight for current ward CREATE items.

The preflight combines one bulk exact-label QLever query, one Wikidata entity
search per proposed item, batched ``wbgetentities`` verification, and batched
Vietnamese Wikipedia title checks.  It never writes to Wikidata or Wikipedia.

Usage:
  uv run python -m vn_admin_units.ward_create_preflight --fetch --audit
  uv run python -m vn_admin_units.ward_create_preflight --check --audit
  uv run python -m vn_admin_units.ward_create_preflight \
    --check --require-upload-ready --max-age-hours 24
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from vn_admin_units.ward_reconcile import (
    USER_AGENT,
    WARD_CLASSES,
    WIKIDATA_API,
    build_parent_qid_index,
    fetch_action_api_entities,
)
from vn_admin_units.ward_reconcile_broad import _request_post_bytes


REFORM_DATE = "2025-07-01"
QLEVER_ENDPOINT = "https://qlever.dev/api/wikidata"
VIWIKI_API = "https://vi.wikipedia.org/w/api.php"
CREATE_MANIFEST = Path("data/ward-wikidata-create-current.json")
WARD_MAPPING = Path("mappings/wards-qid.csv")
REVIEW_DECISIONS = Path("data/ward-wikidata-review-decisions.json")
PREFLIGHT_DECISIONS = Path("data/ward-wikidata-create-preflight-decisions.json")
QUERY_PATH = Path("queries/ward-wikidata-create-preflight.rq")
REPORT_PATH = Path("data/ward-wikidata-create-preflight.json")
_QID = re.compile(r"^Q[1-9][0-9]*$")
_TIER_PREFIX = re.compile(r"^(Xã|Phường|Thị trấn|Đặc khu)\s+", re.IGNORECASE)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _serialize_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _fold(value: str) -> str:
    value = "".join(
        character
        for character in unicodedata.normalize("NFD", value.casefold())
        if unicodedata.category(character) != "Mn"
    ).replace("đ", "d")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


def _normalize_exact_name(value: str) -> str:
    """Normalize spacing and punctuation without erasing Vietnamese tone marks."""
    value = unicodedata.normalize("NFC", value.casefold())
    return " ".join(re.sub(r"[^\w]+", " ", value, flags=re.UNICODE).split())


def _short_name(item: dict) -> str:
    return _TIER_PREFIX.sub("", item["name_vi"]).strip()


def _parent_short_name(item: dict) -> str:
    return re.sub(
        r"^(Tỉnh|Thành phố)\s+", "", item["parent_name_vi"], flags=re.IGNORECASE,
    ).strip()


def _ascii_name(value: str) -> str:
    value = "".join(
        character
        for character in unicodedata.normalize("NFD", value)
        if unicodedata.category(character) != "Mn"
    )
    return re.sub(r"\s+", " ", value.replace("đ", "d").replace("Đ", "D")).strip()


def query_terms(item: dict) -> set[tuple[str, str]]:
    """Return exact label/alias terms in both likely Wikidata languages."""
    full = item["name_vi"].strip()
    short = _short_name(item)
    ascii_full = _ascii_name(full)
    ascii_short = _ascii_name(short)
    return {
        (full, "vi"),
        (short, "vi"),
        (ascii_full, "vi"),
        (ascii_short, "vi"),
        (full, "en"),
        (short, "en"),
        (ascii_full, "en"),
        (ascii_short, "en"),
    }


def _sparql_literal(value: str, language: str) -> str:
    return f"{json.dumps(value, ensure_ascii=False)}@{language}"


def render_query(items: list[dict]) -> str:
    terms = sorted(
        {term for item in items for term in query_terms(item)},
        key=lambda row: (row[1], row[0]),
    )
    values = "\n".join(
        f"    {_sparql_literal(value, language)}" for value, language in terms
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


def parse_qlever_candidates(payload: dict) -> list[dict]:
    indexed: dict[str, dict[tuple[str, str], set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for binding in payload.get("results", {}).get("bindings", []):
        qid = binding.get("item", {}).get("value", "").rsplit("/", 1)[-1]
        term = binding.get("matchedTerm", {})
        value = term.get("value", "")
        language = term.get("xml:lang", "")
        kind = binding.get("matchKind", {}).get("value", "")
        if not _QID.fullmatch(qid) or not value or language not in {"vi", "en"}:
            raise ValueError(f"invalid CREATE preflight QLever binding: {binding}")
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


def _request_json(url: str, *, timeout: int = 60, retries: int = 6) -> dict:
    delay = 2.0
    for attempt in range(retries):
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read())
            if "error" not in payload:
                return payload
        except urllib.error.HTTPError as error:
            if error.code not in {429, 500, 502, 503, 504} or attempt == retries - 1:
                raise
            retry_after = float(error.headers.get("Retry-After", "0") or 0)
            delay = max(delay, retry_after)
        except urllib.error.URLError:
            if attempt == retries - 1:
                raise
        time.sleep(delay)
        delay *= 2
    raise RuntimeError("live API request failed after retries")


def _search_one(item: dict, *, request_fn=_request_json) -> tuple[str, list[dict]]:
    url = WIKIDATA_API + "?" + urllib.parse.urlencode({
        "action": "wbsearchentities",
        "search": item["name_vi"],
        "language": "vi",
        "uselang": "vi",
        "type": "item",
        "limit": "20",
        "format": "json",
        "maxlag": "30",
    })
    payload = request_fn(url)
    rows = [
        {
            "qid": row["id"],
            "label": row.get("label", ""),
            "description": row.get("description", ""),
            "aliases": sorted(set(row.get("aliases", []))),
        }
        for row in payload.get("search", [])
        if _QID.fullmatch(row.get("id", ""))
    ]
    return item["local_id"], rows


def fetch_search_results(
    items: list[dict], *, workers: int = 4, request_fn=_request_json,
) -> dict[str, list[dict]]:
    """Fetch bounded fuzzy search results concurrently and return stable order."""
    if workers < 1:
        raise ValueError("workers must be positive")
    results: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_search_one, item, request_fn=request_fn): item["local_id"]
            for item in items
        }
        for future in as_completed(futures):
            local_id, rows = future.result()
            results[local_id] = rows
    return {item["local_id"]: results[item["local_id"]] for item in items}


def article_titles(item: dict) -> list[dict]:
    quoted = re.findall(r"`([^`]+)`", item.get("review_rationale", ""))
    short = _short_name(item)
    parent = _parent_short_name(item)
    tier = item["loai_hinh"].casefold()
    titles = []
    for title, source in [
        *((title, "prior-review-title") for title in quoted),
        (f"{short}, {parent}", "province-disambiguated"),
        (f"{short} ({tier})", "tier-disambiguated"),
        (short, "short-name"),
    ]:
        if title and title not in {row["title"] for row in titles}:
            titles.append({"title": title, "source": source})
    return titles


def _canonical_title(value: str) -> str:
    return value.replace("_", " ").strip().casefold()


def fetch_viwiki_pages(
    items: list[dict], *, request_fn=_request_json, batch_size: int = 40,
) -> dict[str, list[dict]]:
    """Resolve likely current article titles in batched MediaWiki requests."""
    requested = [
        {"local_id": item["local_id"], **row}
        for item in items
        for row in article_titles(item)
    ]
    unique_titles = list(dict.fromkeys(row["title"] for row in requested))
    page_by_requested_title: dict[str, dict] = {}
    for offset in range(0, len(unique_titles), batch_size):
        batch = unique_titles[offset:offset + batch_size]
        url = VIWIKI_API + "?" + urllib.parse.urlencode({
            "action": "query",
            "titles": "|".join(batch),
            "redirects": "1",
            "prop": "info|pageprops|extracts",
            "inprop": "url",
            "exintro": "1",
            "explaintext": "1",
            "formatversion": "2",
            "format": "json",
            "maxlag": "30",
        })
        payload = request_fn(url)
        aliases = {_canonical_title(title): _canonical_title(title) for title in batch}
        for row in payload.get("query", {}).get("normalized", []):
            aliases[_canonical_title(row["from"])] = _canonical_title(row["to"])
        for row in payload.get("query", {}).get("redirects", []):
            source = _canonical_title(row["from"])
            target = _canonical_title(row["to"])
            aliases[source] = target
            for key, value in list(aliases.items()):
                if value == source:
                    aliases[key] = target
        pages = {
            _canonical_title(page["title"]): {
                "title": page["title"],
                "page_id": page.get("pageid"),
                "last_revision_id": page.get("lastrevid"),
                "touched": page.get("touched", ""),
                "url": page.get("fullurl", ""),
                "missing": "missing" in page,
                "disambiguation": "disambiguation" in page.get("pageprops", {}),
                "wikibase_item": page.get("pageprops", {}).get("wikibase_item", ""),
                "extract": page.get("extract", ""),
            }
            for page in payload.get("query", {}).get("pages", [])
        }
        for title in batch:
            key = aliases.get(_canonical_title(title), _canonical_title(title))
            page_by_requested_title[title] = pages.get(key, {
                "title": title,
                "page_id": None,
                "last_revision_id": None,
                "touched": "",
                "url": "",
                "missing": True,
                "disambiguation": False,
                "wikibase_item": "",
                "extract": "",
            })

    result: dict[str, list[dict]] = defaultdict(list)
    for row in requested:
        page = dict(page_by_requested_title[row["title"]])
        page.update({"requested_title": row["title"], "title_source": row["source"]})
        result[row["local_id"]].append(page)
    return {item["local_id"]: result[item["local_id"]] for item in items}


def _is_current_article(item: dict, page: dict) -> bool:
    if page["missing"] or page["disambiguation"]:
        return False
    title = _fold(page["title"])
    extract = _fold(page["extract"])
    short = _fold(_short_name(item))
    tier = _fold(item["loai_hinh"])
    subject_openings = (
        f"{short} la mot {tier}",
        f"{short} la {tier}",
        f"{tier} {short} la mot {tier}",
        f"{tier} {short} la {tier}",
    )
    return (
        short in title
        and extract.startswith(subject_openings)
        and _fold(_parent_short_name(item)) in extract
    )


def evaluate_article(item: dict, pages: list[dict]) -> dict:
    subjects_by_title = {}
    for page in pages:
        if _is_current_article(item, page):
            subjects_by_title[_canonical_title(page["title"])] = page
    subjects = list(subjects_by_title.values())
    if len(subjects) == 1:
        status = "duplicate" if subjects[0]["wikibase_item"] else "clear"
    else:
        status = "needs-review"
    return {
        "status": status,
        "subject_pages": subjects,
        "tested_pages": pages,
    }


def _review_index(review_decisions: dict) -> dict[str, dict]:
    indexed = {}
    for batch in review_decisions.get("batches", []):
        for decision in batch.get("decisions", []):
            local_id = decision["local_id"]
            if local_id in indexed:
                raise ValueError(f"duplicate ward review decision: {local_id}")
            indexed[local_id] = {**decision, "reviewed_at": batch.get("reviewed_at", "")}
    return indexed


def _preflight_decision_index(payload: dict) -> dict[tuple[str, str], dict]:
    indexed = {}
    for decision in payload.get("decisions", []):
        key = (decision["local_id"], decision["qid"])
        if key in indexed:
            raise ValueError(f"duplicate preflight decision: {key[0]} {key[1]}")
        if decision.get("outcome") != "reject":
            raise ValueError(f"unsupported preflight outcome for {key[0]} {key[1]}")
        indexed[key] = decision
    return indexed


def _current_qids(mapping_rows: list[dict]) -> set[str]:
    return {
        row["wikidata_qid"]
        for row in mapping_rows
        if not row["valid_to"] and _QID.fullmatch(row["wikidata_qid"])
    }


def _exact_candidate_name(item: dict, entity: dict) -> bool:
    expected = {
        _normalize_exact_name(item["name_vi"]),
        _normalize_exact_name(_short_name(item)),
    }
    observed = {
        _normalize_exact_name(value)
        for value in [*entity.get("labels", {}).values(), *entity.get("aliases", [])]
        if value
    }
    return bool(expected & observed)


def evaluate_candidate(
    item: dict,
    entity: dict,
    *,
    article: dict,
    search_rows: list[dict],
    current_qids: set[str],
    parent_index: dict[str, set[str]],
    prior_review: dict,
    manual_decision: dict | None,
) -> dict:
    qid = entity["qid"]
    subject_pages = article["subject_pages"]
    subject_qids = {page["wikibase_item"] for page in subject_pages if page["wikibase_item"]}
    subject_titles = {_canonical_title(page["title"]) for page in subject_pages}
    parent_codes = sorted({
        code
        for parent_qid in entity.get("p131", [])
        for code in parent_index.get(parent_qid, set())
    })
    exact_name = _exact_candidate_name(item, entity)
    expected_type = item["type_qid"]
    p31 = set(entity.get("p31", []))
    reasons = []

    if qid in subject_qids:
        disposition = "duplicate"
        reasons.append("owns-current-viwiki-page")
    elif qid in current_qids:
        disposition = "rejected"
        reasons.append("assigned-to-other-current-unit")
    elif not exact_name:
        disposition = "rejected"
        reasons.append("search-name-mismatch")
    elif any(value <= REFORM_DATE for value in entity.get("p576", [])):
        disposition = "rejected"
        reasons.append("ended-by-current-reform")
    elif p31 and expected_type not in p31:
        disposition = "rejected"
        reasons.append(
            "different-ward-tier" if p31 & set(WARD_CLASSES) else "not-a-ward-tier-item"
        )
    elif parent_codes and item["parent_code"] not in parent_codes:
        disposition = "rejected"
        reasons.append("different-current-province")
    elif (
        entity.get("sitelinks", {}).get("viwiki")
        and _canonical_title(entity["sitelinks"]["viwiki"]) not in subject_titles
    ):
        disposition = "rejected"
        reasons.append("owns-different-viwiki-page")
    elif manual_decision is not None:
        if manual_decision.get("expected_last_revision_id") != entity.get("lastrevid"):
            disposition = "needs-review"
            reasons.append("manual-decision-stale-after-candidate-edit")
        else:
            disposition = "rejected"
            reasons.append("live-preflight-manual-rejection")
    elif qid in set(prior_review.get("candidate_qids_checked", [])):
        if entity.get("modified", "") > prior_review.get("reviewed_at", ""):
            disposition = "needs-review"
            reasons.append("prior-review-stale-after-candidate-edit")
        else:
            disposition = "rejected"
            reasons.append("prior-human-review-rejection")
    else:
        disposition = "needs-review"
        reasons.append("unreviewed-exact-name-candidate")

    matching_search = [row for row in search_rows if row["qid"] == qid]
    return {
        "qid": qid,
        "disposition": disposition,
        "reason_codes": reasons,
        "exact_name": exact_name,
        "parent_codes": parent_codes,
        "labels": entity.get("labels", {}),
        "aliases": entity.get("aliases", []),
        "p31": entity.get("p31", []),
        "p131": entity.get("p131", []),
        "p571": entity.get("p571", []),
        "p576": entity.get("p576", []),
        "p625": entity.get("p625", []),
        "sitelinks": entity.get("sitelinks", {}),
        "last_revision_id": entity.get("lastrevid"),
        "modified": entity.get("modified", ""),
        "search_evidence": matching_search,
        "manual_rationale": manual_decision.get("rationale", "") if manual_decision else "",
        "manual_evidence": manual_decision.get("evidence", {}) if manual_decision else {},
    }


def build_report(
    manifest: dict,
    qlever_payload: dict,
    search_by_local_id: dict[str, list[dict]],
    entities: list[dict],
    viwiki_pages: dict[str, list[dict]],
    mapping_rows: list[dict],
    review_decisions: dict,
    preflight_decisions: dict,
    parent_index: dict[str, set[str]],
    *,
    retrieved_at: str,
    input_fingerprints: dict[str, str],
) -> dict:
    items = manifest["items"]
    exact_candidates = parse_qlever_candidates(qlever_payload)
    term_index: dict[tuple[str, str], set[str]] = defaultdict(set)
    for candidate in exact_candidates:
        for match in candidate["matches"]:
            term_index[(match["value"], match["language"])].add(candidate["qid"])
    entity_by_qid = {entity["qid"]: entity for entity in entities}
    prior_reviews = _review_index(review_decisions)
    manual_decisions = _preflight_decision_index(preflight_decisions)
    assigned_qids = _current_qids(mapping_rows)
    reviewed_items = []
    for item in items:
        local_id = item["local_id"]
        article = evaluate_article(item, viwiki_pages[local_id])
        qids = {
            qid
            for term in query_terms(item)
            for qid in term_index.get(term, set())
        }
        qids.update(row["qid"] for row in search_by_local_id[local_id])
        qids.update(
            page["wikibase_item"]
            for page in article["subject_pages"]
            if page["wikibase_item"]
        )
        candidates = [
            evaluate_candidate(
                item,
                entity_by_qid[qid],
                article=article,
                search_rows=search_by_local_id[local_id],
                current_qids=assigned_qids,
                parent_index=parent_index,
                prior_review=prior_reviews[local_id],
                manual_decision=manual_decisions.get((local_id, qid)),
            )
            for qid in sorted(qids, key=lambda value: int(value[1:]))
        ]
        if article["status"] == "duplicate" or any(
            row["disposition"] == "duplicate" for row in candidates
        ):
            status = "duplicate"
        elif article["status"] != "clear" or any(
            row["disposition"] == "needs-review" for row in candidates
        ):
            status = "needs-review"
        else:
            status = "clear"
        reviewed_items.append({
            "sequence": item["sequence"],
            "local_id": local_id,
            "name_vi": item["name_vi"],
            "parent_code": item["parent_code"],
            "parent_name_vi": item["parent_name_vi"],
            "status": status,
            "article_check": article,
            "candidate_checks": candidates,
        })

    item_statuses = Counter(row["status"] for row in reviewed_items)
    candidate_statuses = Counter(
        candidate["disposition"]
        for item in reviewed_items
        for candidate in item["candidate_checks"]
    )
    return {
        "schema_version": 1,
        "scope": {
            "tier": "ward",
            "effective_date": REFORM_DATE,
            "purpose": "live duplicate and sitelink preflight for current CREATE items",
            "wikidata_write_performed": False,
        },
        "input_fingerprints": input_fingerprints,
        "sources": {
            "retrieved_at": retrieved_at,
            "qlever": {
                "endpoint": QLEVER_ENDPOINT,
                "query_path": QUERY_PATH.as_posix(),
                "query_sha256": input_fingerprints[QUERY_PATH.as_posix()],
                "query_meta": qlever_payload.get("meta", {}),
            },
            "wikidata_search": {
                "endpoint": WIKIDATA_API,
                "method": "one bounded wbsearchentities request per proposed item",
            },
            "wikidata_entities": {
                "endpoint": WIKIDATA_API,
                "method": "batched wbgetentities verification",
            },
            "viwiki": {
                "endpoint": VIWIKI_API,
                "method": "batched candidate-title resolution with pageprops and intro extracts",
            },
        },
        "audit": {
            "items": len(reviewed_items),
            "query_terms": len({term for item in items for term in query_terms(item)}),
            "qlever_result_rows": len(qlever_payload["results"]["bindings"]),
            "candidate_entities_verified": len(entity_by_qid),
            "search_requests": len(items),
            "article_pages_clear": sum(
                row["article_check"]["status"] == "clear" for row in reviewed_items
            ),
            "article_pages_linked": sum(
                row["article_check"]["status"] == "duplicate" for row in reviewed_items
            ),
            "article_pages_needing_review": sum(
                row["article_check"]["status"] == "needs-review" for row in reviewed_items
            ),
            "item_status_counts": dict(sorted(item_statuses.items())),
            "candidate_disposition_counts": dict(sorted(candidate_statuses.items())),
            "uploadable_items": item_statuses["clear"],
            "upload_ready": item_statuses["clear"] == len(reviewed_items),
        },
        "items": reviewed_items,
    }


def fetch_report(
    manifest: dict,
    mapping_rows: list[dict],
    review_decisions: dict,
    preflight_decisions: dict,
    *,
    search_workers: int = 4,
) -> tuple[str, dict]:
    items = manifest["items"]
    query = render_query(items)
    qlever_payload = json.loads(_request_post_bytes(QLEVER_ENDPOINT, query, timeout=180))
    if "results" not in qlever_payload or "bindings" not in qlever_payload["results"]:
        raise ValueError("QLever response is not a SPARQL results document")
    exact_candidates = parse_qlever_candidates(qlever_payload)
    search_by_local_id = fetch_search_results(items, workers=search_workers)
    viwiki_pages = fetch_viwiki_pages(items)
    qids = {
        candidate["qid"] for candidate in exact_candidates
    } | {
        row["qid"] for rows in search_by_local_id.values() for row in rows
    } | {
        page["wikibase_item"]
        for pages in viwiki_pages.values()
        for page in pages
        if page["wikibase_item"]
    }
    entities = fetch_action_api_entities(sorted(qids), batch_size=50, pause=0.1)
    fingerprints = {
        CREATE_MANIFEST.as_posix(): _sha256(CREATE_MANIFEST),
        WARD_MAPPING.as_posix(): _sha256(WARD_MAPPING),
        REVIEW_DECISIONS.as_posix(): _sha256(REVIEW_DECISIONS),
        PREFLIGHT_DECISIONS.as_posix(): _sha256(PREFLIGHT_DECISIONS),
        QUERY_PATH.as_posix(): hashlib.sha256(query.encode()).hexdigest(),
    }
    return query, build_report(
        manifest,
        qlever_payload,
        search_by_local_id,
        entities,
        viwiki_pages,
        mapping_rows,
        review_decisions,
        preflight_decisions,
        build_parent_qid_index(),
        retrieved_at=_utc_now(),
        input_fingerprints=fingerprints,
    )


def report_issues(
    report: dict,
    manifest: dict,
    *,
    max_age_hours: float | None = None,
    now: datetime | None = None,
) -> list[str]:
    issues = []
    expected_query = render_query(manifest["items"])
    if not QUERY_PATH.is_file() or QUERY_PATH.read_text(encoding="utf-8") != expected_query:
        issues.append("saved preflight query is missing or stale")
    for path in (CREATE_MANIFEST, WARD_MAPPING, REVIEW_DECISIONS, PREFLIGHT_DECISIONS):
        if report.get("input_fingerprints", {}).get(path.as_posix()) != _sha256(path):
            issues.append(f"preflight input fingerprint is stale: {path}")
    query_hash = hashlib.sha256(expected_query.encode()).hexdigest()
    if report.get("input_fingerprints", {}).get(QUERY_PATH.as_posix()) != query_hash:
        issues.append("preflight query fingerprint is stale")
    if report.get("audit", {}).get("items") != len(manifest["items"]):
        issues.append("preflight item count does not match CREATE manifest")
    report_items = report.get("items")
    expected_ids = [item["local_id"] for item in manifest["items"]]
    if not isinstance(report_items, list):
        issues.append("preflight item rows are missing")
    else:
        actual_ids = [item.get("local_id") for item in report_items]
        if actual_ids != expected_ids:
            issues.append("preflight item rows do not exactly match CREATE manifest")

        status_counts = dict(sorted(Counter(
            item.get("status", "") for item in report_items
        ).items()))
        if report.get("audit", {}).get("item_status_counts") != status_counts:
            issues.append("preflight item status counts do not match item rows")

        candidate_counts = dict(sorted(Counter(
            candidate.get("disposition", "")
            for item in report_items
            for candidate in item.get("candidate_checks", [])
        ).items()))
        if report.get("audit", {}).get("candidate_disposition_counts") != candidate_counts:
            issues.append("preflight candidate counts do not match candidate rows")

        clear_titles = []
        invalid_clear_article = False
        for item in report_items:
            if item.get("status") != "clear":
                continue
            pages = item.get("article_check", {}).get("subject_pages", [])
            if (
                len(pages) != 1
                or pages[0].get("missing")
                or pages[0].get("disambiguation")
                or pages[0].get("wikibase_item")
                or not pages[0].get("title")
            ):
                invalid_clear_article = True
                continue
            clear_titles.append(_canonical_title(pages[0]["title"]))
        if invalid_clear_article:
            issues.append("a clear preflight row lacks one unlinked subject article")
        if len(clear_titles) != len(set(clear_titles)):
            issues.append("multiple CREATE items resolve to the same viwiki article")

        computed_ready = status_counts.get("clear", 0) == len(expected_ids)
        if report.get("audit", {}).get("upload_ready") is not computed_ready:
            issues.append("preflight upload-ready flag does not match item rows")
    if max_age_hours is not None:
        retrieved = report.get("sources", {}).get("retrieved_at", "")
        try:
            retrieved_at = datetime.fromisoformat(retrieved.replace("Z", "+00:00"))
        except ValueError:
            issues.append("preflight retrieval timestamp is invalid")
        else:
            current = now or datetime.now(timezone.utc)
            age_hours = (current - retrieved_at).total_seconds() / 3600
            if age_hours < 0 or age_hours > max_age_hours:
                issues.append(
                    f"preflight is {age_hours:.1f} hours old; maximum is {max_age_hours:g}"
                )
    return issues


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_mapping() -> list[dict]:
    return list(csv.DictReader(WARD_MAPPING.read_text(encoding="utf-8").splitlines()))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run the read-only duplicate preflight for ward CREATE items",
    )
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--require-upload-ready", action="store_true")
    parser.add_argument("--max-age-hours", type=float)
    parser.add_argument("--search-workers", type=int, default=4)
    args = parser.parse_args(argv)

    manifest = _load_json(CREATE_MANIFEST)
    if args.fetch:
        query, report = fetch_report(
            manifest,
            _read_mapping(),
            _load_json(REVIEW_DECISIONS),
            _load_json(PREFLIGHT_DECISIONS),
            search_workers=args.search_workers,
        )
        _write_atomic(QUERY_PATH, query)
        _write_atomic(REPORT_PATH, _serialize_json(report))
        action = "wrote"
    else:
        report = _load_json(REPORT_PATH)
        action = "checked"

    issues = report_issues(report, manifest, max_age_hours=args.max_age_hours)
    if args.check and issues:
        raise SystemExit("; ".join(issues))
    upload_ready = bool(report.get("audit", {}).get("upload_ready")) and not issues
    if args.audit:
        audit = report["audit"]
        print(
            f"{action} preflight for {audit['items']} items: "
            f"clear={audit['item_status_counts'].get('clear', 0)}, "
            f"needs-review={audit['item_status_counts'].get('needs-review', 0)}, "
            f"duplicate={audit['item_status_counts'].get('duplicate', 0)}"
        )
        print(
            f"  articles clear={audit['article_pages_clear']}, "
            f"linked={audit['article_pages_linked']}, "
            f"needs-review={audit['article_pages_needing_review']}"
        )
        print(
            f"  candidates verified={audit['candidate_entities_verified']}; "
            f"dispositions={audit['candidate_disposition_counts']}"
        )
        for issue in issues:
            print(f"  issue: {issue}")
    if args.require_upload_ready and not upload_ready:
        raise SystemExit("ward CREATE upload remains blocked; inspect the preflight report")


if __name__ == "__main__":
    main()
