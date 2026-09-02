import hashlib
import json
from pathlib import Path

from vn_admin_units import rawcache
from vn_admin_units.names import fold_ward_name
from vn_admin_units.ward_reconcile import (
    CANDIDATE_CACHE,
    BROAD_CANDIDATE_CACHE,
    MAPPING,
    QUERY_PATH,
    RAW_RESULT,
    REVIEW_DECISIONS,
    WARD_HISTORY,
    audit_mapping,
    build_mapping_rows,
    build_parent_qid_index,
    current_candidate_qids,
    fetch_action_api_entities,
    parse_qlever_candidates,
    serialize_mapping,
)


def _binding(value, *, lang=None):
    result = {"type": "literal", "value": value}
    if lang:
        result["xml:lang"] = lang
    return result


def _candidate(qid, name, parent="QP", *, aliases=(), types=("Q2389082",)):
    return {
        "qid": qid,
        "types": list(types),
        "label_vi": name,
        "label_en": "",
        "aliases": list(aliases),
        "parent_qids": [parent],
    }


def _entity(local_id, code, name, parent, *, valid_from="2025-07-01", valid_to=None):
    return {
        "local_id": local_id,
        "gso_codes": [code],
        "name_vi": name,
        "loai_hinh": name.split(" ", 1)[0],
        "valid_from": valid_from,
        "valid_to": valid_to,
        "parent_spans": [{"code": parent}],
    }


def _verified(qid, name, parent="QP", *, p31=("Q2389082",), p576=()):
    return {
        "qid": qid,
        "missing": False,
        "lastrevid": 1,
        "modified": "2026-09-01T00:00:00Z",
        "labels": {"vi": name},
        "aliases": [],
        "p31": list(p31),
        "p131": [parent],
        "p571": [],
        "p576": list(p576),
    }


def _artifact(candidates, verified=()):
    return {
        "audit": {
            "candidates": len(candidates),
            "api_verified_candidates": len(verified),
        },
        "candidates": candidates,
        "action_api_verification": {"entities": list(verified)},
    }


def test_fold_ward_name_ignores_tier_diacritics_and_disambiguator():
    assert fold_ward_name("Phường Hoà Bình") == fold_ward_name("Hòa Bình")
    assert fold_ward_name("Xã Đa Krông (Quảng Trị)") == "dakrong"
    assert fold_ward_name("Đặc khu Côn Đảo") == "condao"


def test_qlever_rows_are_compacted_and_sorted():
    payload = {
        "results": {
            "bindings": [
                {
                    "item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q20"},
                    "types": _binding(
                        "http://www.wikidata.org/entity/Q687188␟"
                        "http://www.wikidata.org/entity/Q2389082"
                    ),
                    "viLabel": _binding("Tân Phú", lang="vi"),
                    "aliases": _binding("Phường Tân Phú␟Tan Phu"),
                    "parents": _binding("http://www.wikidata.org/entity/QP1"),
                },
                {
                    "item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q3"},
                    "types": _binding("http://www.wikidata.org/entity/Q2389082"),
                    "viLabel": _binding("Bình An", lang="vi"),
                },
            ]
        }
    }

    candidates = parse_qlever_candidates(payload)

    assert [row["qid"] for row in candidates] == ["Q3", "Q20"]
    assert candidates[1]["types"] == ["Q2389082", "Q687188"]
    assert candidates[1]["aliases"] == ["Phường Tân Phú", "Tan Phu"]


def test_parent_index_maps_stale_province_and_district_qids_to_current(tmp_path: Path):
    province_entities = tmp_path / "entities.json"
    province_entities.write_text(json.dumps([
        {"local_id": "p-70-pre2025", "gso_codes": ["70"]},
        {"local_id": "p-75-post2025", "gso_codes": ["75"]},
    ]), encoding="utf-8")
    province_lineage = tmp_path / "lineage.json"
    province_lineage.write_text(json.dumps([{
        "predecessor": "p-70-pre2025",
        "successor": "p-75-post2025",
        "effective_date": "2025-07-01",
    }]), encoding="utf-8")
    province_mapping = tmp_path / "provinces.csv"
    province_mapping.write_text(
        "gso_code,era,wikidata_qid\n"
        "70,pre2025,QOLDPROV\n"
        "75,post2025,QNEWPROV\n",
        encoding="utf-8",
    )
    district_mapping = tmp_path / "districts.csv"
    district_mapping.write_text(
        "local_id,parent_code,wikidata_qid\n"
        "d-689-base,70,QOLDDIST\n",
        encoding="utf-8",
    )

    index = build_parent_qid_index(
        province_mapping=province_mapping,
        district_mapping=district_mapping,
        province_entity_path=province_entities,
        province_lineage_path=province_lineage,
    )

    assert index == {
        "QNEWPROV": {"75"},
        "QOLDDIST": {"75"},
        "QOLDPROV": {"75"},
    }


def test_mapping_requires_batched_api_name_tier_parent_and_active_evidence():
    history = {"entities": [
        _entity("w-1-2025-07-01", "00001", "Xã Tân Phú", "75"),
        _entity(
            "w-old-base", "90001", "Xã Cũ", "70",
            valid_from=None, valid_to="2025-06-30",
        ),
    ]}
    candidates = [
        _candidate("Q1", "Tân Phú"),
        _candidate("Q2", "Tân Phú", parent="QOLD"),
    ]
    verified = [
        # A stale P31 is tolerated because it remains ward-tier; parent + name identify it.
        _verified("Q1", "Tân Phú", p31=("Q687188",)),
        _verified("Q2", "Tân Phú", parent="QOLD", p576=("2025-06-30",)),
    ]

    rows = build_mapping_rows(
        history,
        _artifact(candidates, verified),
        {"QP": {"75"}, "QOLD": {"75"}},
    )
    by_id = {row["local_id"]: row for row in rows}

    assert by_id["w-1-2025-07-01"]["wikidata_qid"] == "Q1"
    assert by_id["w-1-2025-07-01"]["match_status"] == "matched"
    assert by_id["w-old-base"]["match_status"] == "deferred-historical"


def test_mapping_keeps_ambiguous_and_unverified_candidates_unassigned():
    entity = _entity("w-1-2025-07-01", "00001", "Xã Tân Phú", "75")
    candidates = [_candidate("Q1", "Tân Phú"), _candidate("Q2", "Tân Phú")]
    parent_index = {"QP": {"75"}}

    unverified = build_mapping_rows(
        {"entities": [entity]}, _artifact(candidates), parent_index,
    )[0]
    ambiguous = build_mapping_rows(
        {"entities": [entity]},
        _artifact(candidates, [_verified("Q1", "Tân Phú"), _verified("Q2", "Tân Phú")]),
        parent_index,
    )[0]

    assert unverified["wikidata_qid"] == ""
    assert unverified["match_status"] == "unverified-candidate"
    assert ambiguous["wikidata_qid"] == ""
    assert ambiguous["match_status"] == "ambiguous"


def test_mapping_keeps_a_qid_shared_by_current_rows_unassigned():
    history = {"entities": [
        _entity("w-1-2025-07-01", "00001", "Xã Tân Phú", "75"),
        _entity("w-2-2025-07-01", "00002", "Xã Tân Phú", "75"),
    ]}
    artifact = _artifact(
        [_candidate("Q1", "Tân Phú")],
        [_verified("Q1", "Tân Phú")],
    )

    rows = build_mapping_rows(history, artifact, {"QP": {"75"}})

    assert {row["match_status"] for row in rows} == {"ambiguous"}
    assert {row["wikidata_qid"] for row in rows} == {""}
    assert all("candidate Q1 also matches" in row["match_notes"] for row in rows)


def test_mapping_uses_predecessor_district_to_break_current_ambiguity():
    history = {
        "entities": [
            _entity(
                "w-old-base", "90001", "Xã Cũ", "001",
                valid_from=None, valid_to="2025-06-30",
            ),
            _entity("w-new-2025-07-01", "00001", "Xã Tân Phú", "75"),
        ],
        "lineage_edges": [{
            "predecessor": "w-old-base",
            "successor": "w-new-2025-07-01",
        }],
    }
    candidates = [
        _candidate("Q1", "Tân Phú", parent="Q900"),
        _candidate("Q2", "Tân Phú", parent="Q901"),
    ]
    verified = [
        _verified("Q1", "Tân Phú", parent="Q900"),
        _verified("Q2", "Tân Phú", parent="Q901"),
    ]

    rows = build_mapping_rows(
        history,
        _artifact(candidates, verified),
        {"Q900": {"75"}, "Q901": {"75"}},
        district_qid_index={"Q900": {"001"}, "Q901": {"002"}},
    )
    current = next(row for row in rows if not row["valid_to"])

    assert current["wikidata_qid"] == "Q1"
    assert current["match_status"] == "matched"
    assert "predecessor-district" in current["match_notes"]


def test_mapping_uses_one_exact_active_broad_candidate_after_primary_fails():
    entity = _entity("w-1-2025-07-01", "00001", "Xã Tân Phú", "75")
    broad = {
        "candidates": [{"qid": "Q3"}],
        "action_api_verification": {"entities": [_verified("Q3", "Tân Phú")]},
        "review": [{
            "local_id": entity["local_id"],
            "auto_candidate_qids": ["Q3"],
        }],
    }

    row = build_mapping_rows(
        {"entities": [entity]},
        _artifact([]),
        {"QP": {"75"}},
        broad_artifact=broad,
    )[0]

    assert row["wikidata_qid"] == "Q3"
    assert row["match_status"] == "matched"
    assert row["candidate_qids"] == "Q3"
    assert row["match_notes"].startswith("broad-exact-vi")


def test_mapping_applies_assign_and_retain_unresolved_review_decisions():
    history = {"entities": [
        _entity("w-1-2025-07-01", "00001", "Xã Tân Phú", "75"),
        _entity("w-2-2025-07-01", "00002", "Xã Bình An", "75"),
    ]}
    decisions = {"batches": [{
        "batch_id": "2026-09-02.01",
        "decisions": [
            {
                "local_id": "w-1-2025-07-01",
                "outcome": "assign",
                "wikidata_qid": "Q99",
                "candidate_qids_checked": ["Q98", "Q99"],
                "mapping_note": "reviewed identity",
            },
            {
                "local_id": "w-2-2025-07-01",
                "outcome": "retain-unresolved",
                "wikidata_qid": "",
                "candidate_qids_checked": [],
                "mapping_note": "insufficient identity evidence",
            },
        ],
    }]}

    rows = build_mapping_rows(
        history, _artifact([]), {}, review_decisions=decisions,
    )
    by_id = {row["local_id"]: row for row in rows}

    assert by_id["w-1-2025-07-01"]["wikidata_qid"] == "Q99"
    assert by_id["w-1-2025-07-01"]["match_status"] == "manual"
    assert by_id["w-1-2025-07-01"]["candidate_qids"] == "Q98|Q99"
    assert by_id["w-2-2025-07-01"]["match_status"] == "reviewed-unresolved"


def test_action_api_verification_is_batched_and_compacted():
    calls = []

    def fake_request(url, timeout=0):
        calls.append(url)
        ids = urllib_parse(url)["ids"][0].split("|")
        return json.dumps({
            "entities": {
                qid: {
                    "id": qid,
                    "labels": {"vi": {"language": "vi", "value": f"Tên {qid}"}},
                    "aliases": {},
                    "claims": {
                        "P31": [{"rank": "normal", "mainsnak": {
                            "datavalue": {"value": {"id": "Q2389082"}}
                        }}],
                        "P131": [{"rank": "normal", "mainsnak": {
                            "datavalue": {"value": {"id": "Q900"}}
                        }}],
                    },
                }
                for qid in ids
            }
        }).encode()

    rows = fetch_action_api_entities(
        ["Q3", "Q1", "Q2"], request_fn=fake_request, batch_size=2, pause=0,
    )

    assert len(calls) == 2
    assert [row["qid"] for row in rows] == ["Q1", "Q2", "Q3"]
    assert rows[0]["p31"] == ["Q2389082"]
    assert rows[0]["p131"] == ["Q900"]


def test_action_api_retries_json_error_and_rejects_incomplete_batches():
    calls = 0

    def fake_request(url, timeout=0):
        nonlocal calls
        calls += 1
        if calls == 1:
            return json.dumps({"error": {"code": "maxlag"}}).encode()
        return json.dumps({
            "entities": {"Q1": {"id": "Q1", "claims": {}}},
        }).encode()

    rows = fetch_action_api_entities(
        ["Q1"], request_fn=fake_request, pause=0, retries=2, retry_pause=0,
    )

    assert calls == 2
    assert rows[0]["qid"] == "Q1"
    assert not rows[0]["missing"]


def test_current_verification_candidates_are_prefiltered_by_bulk_parent():
    history = {"entities": [
        _entity("w-1-2025-07-01", "00001", "Xã Tân Phú", "75"),
    ]}
    candidates = [
        _candidate("Q1", "Tân Phú", parent="Q900"),
        _candidate("Q2", "Tân Phú", parent="Q901"),
    ]

    qids = current_candidate_qids(
        history, candidates, {"Q900": {"75"}, "Q901": {"79"}},
    )

    assert qids == ["Q1"]


def urllib_parse(url):
    from urllib.parse import parse_qs, urlparse

    return parse_qs(urlparse(url).query)


def test_saved_query_is_bulk_and_qlever_portable():
    query = Path("queries/ward-wikidata-candidates.rq").read_text(encoding="utf-8")
    assert "VALUES ?type" in query
    assert "GROUP_CONCAT" in query
    assert "SERVICE wikibase:label" not in query
    assert "LIMIT" not in query


def test_saved_snapshot_cache_and_mapping_are_reproducible():
    assert rawcache.raw_is_verified(RAW_RESULT)
    artifact = json.loads(CANDIDATE_CACHE.read_text(encoding="utf-8"))
    broad = json.loads(BROAD_CANDIDATE_CACHE.read_text(encoding="utf-8"))
    review_decisions = json.loads(REVIEW_DECISIONS.read_text(encoding="utf-8"))
    history = json.loads(WARD_HISTORY.read_text(encoding="utf-8"))
    query_hash = hashlib.sha256(QUERY_PATH.read_bytes()).hexdigest()

    assert artifact["source"]["query_sha256"] == query_hash
    assert artifact["audit"] == {
        "api_verified_candidates": 2878,
        "candidates": 11838,
        "type_counts": {
            "Q1070942": 536,
            "Q134999516": 12,
            "Q2389082": 9726,
            "Q687188": 1721,
        },
        "with_aliases": 10831,
        "with_parents": 10990,
        "with_vi_label": 11168,
    }
    assert not any(
        row["missing"]
        for row in artifact["action_api_verification"]["entities"]
    )

    rows = build_mapping_rows(
        history,
        artifact,
        build_parent_qid_index(),
        broad_artifact=broad,
        review_decisions=review_decisions,
    )
    assert MAPPING.read_text(encoding="utf-8") == serialize_mapping(rows)
    audit = audit_mapping(history, artifact, rows, broad, review_decisions)
    assert audit["summary"]["status_counts"] == {
        "deferred-historical": 11223,
        "manual": 46,
        "matched": 2670,
        "needs-lookup": 280,
        "needs-review": 324,
        "reviewed-unresolved": 1,
    }
    assert audit["summary"]["review_decisions"] == 47
    assert audit["summary"]["current_fold_collisions"] == 10
    assert audit["issues"] == []
