import json
from datetime import datetime, timezone
from pathlib import Path

from vn_admin_units.ward_create_preflight import (
    PREFLIGHT_DECISIONS,
    QUERY_PATH,
    REPORT_PATH,
    build_report,
    evaluate_article,
    evaluate_candidate,
    query_terms,
    render_query,
    report_issues,
)


def _item():
    return {
        "sequence": 1,
        "local_id": "w-00001-2025-07-01",
        "name_vi": "Xã Tân Phú",
        "loai_hinh": "Xã",
        "type_qid": "Q2389082",
        "parent_code": "75",
        "parent_name_vi": "Tỉnh Đồng Nai",
        "review_rationale": "The current `Tân Phú, Đồng Nai` page is unlinked.",
    }


def _page(*, qid=""):
    return {
        "title": "Tân Phú, Đồng Nai",
        "page_id": 1,
        "last_revision_id": 2,
        "touched": "2026-09-02T00:00:00Z",
        "url": "https://vi.wikipedia.org/wiki/Tân_Phú,_Đồng_Nai",
        "missing": False,
        "disambiguation": False,
        "wikibase_item": qid,
        "extract": "Tân Phú là một xã thuộc tỉnh Đồng Nai, Việt Nam, thành lập năm 2025.",
        "requested_title": "Tân Phú, Đồng Nai",
        "title_source": "prior-review-title",
    }


def _entity(qid="Q1", **changes):
    entity = {
        "qid": qid,
        "missing": False,
        "lastrevid": 10,
        "modified": "2026-09-01T00:00:00Z",
        "labels": {"vi": "Tân Phú"},
        "aliases": ["Xã Tân Phú"],
        "p31": ["Q2389082"],
        "p131": ["QP"],
        "p571": [],
        "p576": [],
        "p625": [],
        "sitelinks": {},
    }
    entity.update(changes)
    return entity


def test_query_is_bulk_exact_label_and_alias_discovery():
    query = render_query([_item()])

    assert ("Tân Phú", "vi") in query_terms(_item())
    assert '"Tan Phu"@en' in query
    assert "VALUES ?matchedTerm" in query
    assert "rdfs:label" in query
    assert "skos:altLabel" in query
    assert "LIMIT" not in query


def test_article_check_requires_current_subject_and_detects_linked_page():
    clear = evaluate_article(_item(), [_page()])
    duplicate = evaluate_article(_item(), [_page(qid="Q99")])
    old = _page()
    old["extract"] = "Làng Tân Phú nằm trong xã Tân Phú, tỉnh Đồng Nai."

    assert clear["status"] == "clear"
    assert duplicate["status"] == "duplicate"
    assert evaluate_article(_item(), [old])["status"] == "needs-review"


def test_candidate_check_rejects_wrong_place_and_flags_unreviewed_exact_item():
    article = evaluate_article(_item(), [_page()])
    common = {
        "article": article,
        "search_rows": [],
        "current_qids": set(),
        "parent_index": {"QP": {"75"}, "QOTHER": {"79"}},
        "prior_review": {"candidate_qids_checked": [], "reviewed_at": "2026-09-02T00:00:00Z"},
        "manual_decision": None,
    }

    wrong = evaluate_candidate(_item(), _entity(p131=["QOTHER"]), **common)
    unresolved = evaluate_candidate(_item(), _entity(), **common)

    assert wrong["disposition"] == "rejected"
    assert wrong["reason_codes"] == ["different-current-province"]
    assert unresolved["disposition"] == "needs-review"


def test_manual_candidate_decision_is_revision_pinned():
    article = evaluate_article(_item(), [_page()])
    common = {
        "article": article,
        "search_rows": [],
        "current_qids": set(),
        "parent_index": {"QP": {"75"}},
        "prior_review": {"candidate_qids_checked": [], "reviewed_at": ""},
    }
    decision = {
        "outcome": "reject",
        "expected_last_revision_id": 10,
        "rationale": "different historical commune",
    }

    current = evaluate_candidate(
        _item(), _entity(), manual_decision=decision, **common,
    )
    stale = evaluate_candidate(
        _item(), _entity(lastrevid=11), manual_decision=decision, **common,
    )

    assert current["disposition"] == "rejected"
    assert stale["disposition"] == "needs-review"


def test_committed_preflight_artifacts_match_current_manifest_when_present():
    if not REPORT_PATH.is_file() or not QUERY_PATH.is_file():
        return
    manifest = json.loads(
        Path("data/ward-wikidata-create-current.json").read_text(encoding="utf-8")
    )
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert PREFLIGHT_DECISIONS.is_file()
    assert report_issues(report, manifest) == []
    assert report["audit"]["items"] == 0


def test_report_age_check_is_explicit_not_implicit(monkeypatch, tmp_path):
    item = _item()
    manifest = {"items": [item]}
    query = render_query([item])
    paths = {
        "manifest": tmp_path / "manifest.json",
        "mapping": tmp_path / "mapping.csv",
        "reviews": tmp_path / "reviews.json",
        "decisions": tmp_path / "decisions.json",
        "query": tmp_path / "query.rq",
    }
    for path in paths.values():
        path.write_text("x", encoding="utf-8")
    paths["query"].write_text(query, encoding="utf-8")
    import vn_admin_units.ward_create_preflight as module

    monkeypatch.setattr(module, "CREATE_MANIFEST", paths["manifest"])
    monkeypatch.setattr(module, "WARD_MAPPING", paths["mapping"])
    monkeypatch.setattr(module, "REVIEW_DECISIONS", paths["reviews"])
    monkeypatch.setattr(module, "PREFLIGHT_DECISIONS", paths["decisions"])
    monkeypatch.setattr(module, "QUERY_PATH", paths["query"])
    fingerprints = {
        path.as_posix(): module._sha256(path) for path in paths.values()
    }
    report = {
        "input_fingerprints": fingerprints,
        "sources": {"retrieved_at": "2026-09-01T00:00:00Z"},
        "audit": {
            "items": 1,
            "item_status_counts": {"clear": 1},
            "candidate_disposition_counts": {},
            "upload_ready": True,
        },
        "items": [{
            "local_id": item["local_id"],
            "status": "clear",
            "article_check": {"subject_pages": [_page()]},
            "candidate_checks": [],
        }],
    }

    assert report_issues(report, manifest) == []
    issues = report_issues(
        report,
        manifest,
        max_age_hours=24,
        now=datetime(2026, 9, 3, tzinfo=timezone.utc),
    )
    assert issues == ["preflight is 48.0 hours old; maximum is 24"]


def test_report_rejects_reused_viwiki_article(monkeypatch, tmp_path):
    first = _item()
    second = {**_item(), "sequence": 2, "local_id": "w-00002-2025-07-01"}
    manifest = {"items": [first, second]}
    query = render_query(manifest["items"])
    paths = {
        "manifest": tmp_path / "manifest.json",
        "mapping": tmp_path / "mapping.csv",
        "reviews": tmp_path / "reviews.json",
        "decisions": tmp_path / "decisions.json",
        "query": tmp_path / "query.rq",
    }
    for path in paths.values():
        path.write_text("x", encoding="utf-8")
    paths["query"].write_text(query, encoding="utf-8")
    import vn_admin_units.ward_create_preflight as module

    monkeypatch.setattr(module, "CREATE_MANIFEST", paths["manifest"])
    monkeypatch.setattr(module, "WARD_MAPPING", paths["mapping"])
    monkeypatch.setattr(module, "REVIEW_DECISIONS", paths["reviews"])
    monkeypatch.setattr(module, "PREFLIGHT_DECISIONS", paths["decisions"])
    monkeypatch.setattr(module, "QUERY_PATH", paths["query"])
    fingerprints = {path.as_posix(): module._sha256(path) for path in paths.values()}
    rows = [{
        "local_id": item["local_id"],
        "status": "clear",
        "article_check": {"subject_pages": [_page()]},
        "candidate_checks": [],
    } for item in manifest["items"]]
    report = {
        "input_fingerprints": fingerprints,
        "sources": {"retrieved_at": "2026-09-02T00:00:00Z"},
        "audit": {
            "items": 2,
            "item_status_counts": {"clear": 2},
            "candidate_disposition_counts": {},
            "upload_ready": True,
        },
        "items": rows,
    }

    assert "multiple CREATE items resolve to the same viwiki article" in report_issues(
        report, manifest,
    )
