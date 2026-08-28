import json

from vn_admin_units.ward_source_coverage import (
    build_coverage,
    build_instruments,
    crosswalk_kind,
    index_legal_sources,
    normalize_date,
    serialize_coverage,
    ward_crosswalk_manifest_fingerprint,
)


def test_normalize_date_accepts_source_and_iso_forms():
    assert normalize_date("01/07/2025") == "2025-07-01"
    assert normalize_date("2025-07-01") == "2025-07-01"


def test_duplicate_legal_rows_collapse_without_losing_title_variants():
    records = [
        {
            "code": "1240/NQ-UBTVQH15",
            "hieu_luc": "01/12/2024",
            "noi_dung": "sắp xếp giai đoạn 2023-2025",
            "url": "",
        },
        {
            "code": "1240/NQ-UBTVQH15",
            "hieu_luc": "01/12/2024",
            "noi_dung": "sắp xếp giai đoạn 2023 - 2025",
            "url": "",
        },
    ]

    instruments = build_instruments(records, {})

    assert instruments == [{
        "instrument_id": "1240/NQ-UBTVQH15@2024-12-01",
        "code": "1240/NQ-UBTVQH15",
        "effective_date": "2024-12-01",
        "index_occurrences": 2,
        "title_variants": [
            "sắp xếp giai đoạn 2023 - 2025",
            "sắp xếp giai đoạn 2023-2025",
        ],
        "index_urls": [],
        "classification": "unresolved",
        "review_status": "pending",
        "source_status": "missing",
        "source_discovery": {"discovery_status": "not_registered"},
        "primary_sources": [],
        "secondary_sources": [],
        "event_ids": [],
    }]


def test_complete_2025_official_pair_is_reused_as_closed_source_evidence():
    records = [{
        "code": "1656/NQ-UBTVQH15",
        "hieu_luc": "01/07/2025",
        "noi_dung": "Nghị quyết sắp xếp đơn vị hành chính cấp xã của Hà Nội",
        "url": "",
    }]
    manifest = [
        {
            "path": "resolutions/ward-2025/1656-nq-ubtvqh15.pdf",
            "sha256": "pdfhash",
            "bytes": 123,
            "source_url": "https://datafiles.chinhphu.vn/1656.pdf",
            "method": "official signed resolution PDF",
            "document_code": "1656/NQ-UBTVQH15",
            "effective_date": "01/07/2025",
        },
        {
            "path": "resolutions/ward-2025/1656-nq-ubtvqh15.html",
            "sha256": "htmlhash",
            "bytes": 456,
            "source_url": "https://xaydungchinhsach.chinhphu.vn/1656.htm",
            "method": "official full-text resolution HTML",
            "document_code": "1656/NQ-UBTVQH15",
            "effective_date": "01/07/2025",
        },
    ]

    sources = index_legal_sources(manifest, verifier=lambda _: True)
    instrument = build_instruments(records, sources)[0]

    assert instrument["classification"] == "lineage"
    assert instrument["review_status"] == "verified_2025_boundary"
    assert instrument["source_status"] == "verified_official_artifact"
    assert [source["media_type"] for source in instrument["primary_sources"]] == [
        "html", "pdf",
    ]
    assert instrument["secondary_sources"] == []


def test_crosswalk_kinds_are_explicit():
    assert crosswalk_kind("crosswalk/ward_2004-01-01_2005-01-01.xls") == "yearly"
    assert crosswalk_kind("crosswalk/ward_2002-01-01_2025-06-30.xls") == "long_range"
    assert crosswalk_kind("crosswalk/ward_2025-06-30_2025-07-01.xls") == "reform_boundary"
    assert crosswalk_kind("crosswalk/ward_2025-07-01_2026-08-27.xls") == "post_reform"


def test_crosswalk_fingerprint_ignores_unrelated_legal_artifacts():
    crosswalk = {
        "path": "crosswalk/ward_2024-01-01_2025-01-01.xls",
        "sha256": "crosswalk-hash",
        "bytes": 123,
        "rows": 10,
    }
    legal = {
        "path": "legal/ward/2026-04-30/237.metadata.html",
        "sha256": "legal-hash",
        "bytes": 456,
    }

    assert ward_crosswalk_manifest_fingerprint([crosswalk]) == (
        ward_crosswalk_manifest_fingerprint([crosswalk, legal])
    )
    assert ward_crosswalk_manifest_fingerprint([crosswalk]) != (
        ward_crosswalk_manifest_fingerprint([{**crosswalk, "sha256": "changed"}])
    )


def test_real_locked_baseline_builds_deterministically():
    coverage = build_coverage()
    summary = coverage["summary"]

    assert summary["soap_artifacts"] == 204
    assert summary["soap_rows"] == 2_202_543
    assert summary["soap_unique_payloads"] == 180
    assert summary["ward_crosswalk_artifacts"] == 39
    assert summary["ward_crosswalk_rows"] == 417_158
    assert summary["yearly_crosswalks"] == 21
    assert summary["targeted_crosswalks"] == 15
    assert summary["legal_index_records"] == 544
    assert summary["ward_relevant_legal_rows"] == 453
    assert summary["unique_ward_instruments"] == 449
    assert summary["duplicate_instrument_keys"] == 4
    assert summary["verified_2025_resolution_pairs"] == 34
    assert summary["unclassified_instruments"] == 415
    assert summary["primary_source_open_instruments"] == 57
    assert summary["official_source_matches"] == 392
    assert summary["official_source_not_found"] == 57
    assert summary["secondary_tvpl_urls"] == 107
    assert summary["observed_change_intervals"] == 179
    assert summary["events"] == 179
    assert summary["crosswalk_supported_events"] == 178
    assert summary["crosswalk_residue_events"] == 1
    assert coverage["scope"]["next_task"] == 6
    assert coverage["residue"]["event_inventory_status"] == (
        "legal_sources_preserved_classification_linking_pending"
    )
    assert coverage["residue"]["crosswalk_residue_event_ids"] == [
        "soap:2004-01-01->2004-07-01",
    ]
    assert len(coverage["residue"]["legal_unlinked_event_ids"]) == 179
    assert coverage["events"][0]["event_id"] == "soap:2004-01-01->2004-07-01"
    assert coverage["events"][-1]["event_id"] == "soap:2026-04-29->2026-04-30"
    assert json.loads(serialize_coverage(coverage)) == coverage
    assert serialize_coverage(coverage) == serialize_coverage(coverage)
