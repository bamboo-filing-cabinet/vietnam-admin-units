import json
from pathlib import Path

from vn_admin_units.ward_source_coverage import (
    build_coverage,
    build_instruments,
    crosswalk_kind,
    format_audit,
    index_legal_sources,
    normalize_date,
    render_open_source_note,
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


def test_open_source_note_rejects_leads_that_are_no_longer_open(tmp_path: Path):
    coverage = {
        "summary": {"primary_source_open_instruments": 0},
        "residue": {
            "primary_source_open_instrument_ids": [],
            "change_bearing_source_open_instrument_ids": [],
        },
        "legal_instruments": [],
    }
    leads = tmp_path / "leads.json"
    leads.write_text(json.dumps({
        "schema_version": 1,
        "leads": [{
            "instrument_id": "resolved@2026-08-28",
            "official_page_urls": ["https://vbpl.vn/example"],
        }],
    }), encoding="utf-8")

    try:
        render_open_source_note(coverage, leads)
    except ValueError as error:
        assert "no longer source-open" in str(error)
    else:
        raise AssertionError("stale official lead was accepted")


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
    assert summary["unclassified_instruments"] == 0
    assert summary["classified_legal_index_rows"] == 453
    assert summary["classified_instruments"] == 449
    assert summary["instrument_classifications"] == {
        "duplicate_or_superseded": 2,
        "lineage": 430,
        "parent_or_boundary_only": 12,
        "rename_or_retype": 5,
    }
    assert summary["instrument_observation_statuses"] == {
        "no_observable_roster_change": 4,
        "resolution_clauses_linked": 34,
        "source_only_before_first_reliable_national_code_transition": 36,
        "source_only_inside_2004_code_scheme_transition": 18,
        "source_only_normalized_quiet_soap_interval": 1,
        "superseded_by_canonical_correction": 2,
        "topology_components_linked": 354,
    }
    assert summary["change_bearing_source_open_instruments"] == 35
    assert summary["primary_source_open_instruments"] == 37
    assert summary["official_source_matches"] == 412
    assert summary["official_source_not_found"] == 37
    assert summary["secondary_tvpl_urls"] == 109
    assert summary["observed_change_intervals"] == 179
    assert summary["events"] == 179
    assert summary["crosswalk_supported_events"] == 178
    assert summary["crosswalk_residue_events"] == 1
    assert coverage["scope"]["next_task"] == 7
    assert coverage["scope"]["status"] == "source_audit_complete_bounded_residue"
    assert coverage["scope"]["source_gate_status"] == "open"
    assert coverage["residue"]["event_inventory_status"] == (
        "complete_source_audit_bounded_residue"
    )
    assert coverage["source_floor_evidence"] == {
        "endpoint_interval": {
            "before_date": "2002-01-01",
            "before_path": "soap/DanhMucPhuongXa_2002-01-01.xml.gz",
            "after_date": "2004-01-01",
            "after_path": "soap/DanhMucPhuongXa_2004-01-01.xml.gz",
            "content_sha256": (
                "84ad76c48cc7dc291f5d3149a865c5bf3e767919a16766534f5fbdd90cb92724"
            ),
            "payload_relation": "identical",
        },
        "verdict": "no_endpoint_state_difference_observed",
        "limitation": (
            "matching_endpoint_payloads_do_not_exclude_transient_"
            "intra_interval_changes"
        ),
        "first_observed_transition": {
            "event_id": "soap:2004-01-01->2004-07-01",
            "before_date": "2004-01-01",
            "after_date": "2004-07-01",
            "classification": "code_scheme_transition",
            "component_count": 21_287,
            "status": "explicitly_classified_non_legal_transition",
        },
    }
    assert format_audit(coverage) == (
        "ward source audit: OPEN — 412/449 official; 37 primary-source open; "
        "35 change-bearing open\n"
        "source floor verdict: no_endpoint_state_difference_observed — "
        "2002-01-01 and 2004-01-01 are identical; transient intra-interval "
        "changes are not excluded"
    )
    open_note = render_open_source_note(coverage)
    assert open_note.count("- [ ]") == 37
    assert open_note.count("- [ ] **Change-bearing**") == 35
    assert open_note.count("- [ ] **Context-only / superseded index row**") == 2
    assert "`07/NĐ-CP@2009-01-07`" in open_note
    assert "`721/NQ-UBTVQH15@2023-04-10`" not in open_note
    assert "TVPL links are included only to confirm identity" in open_note
    assert "commit `89107d0` recorded **39 open instruments**" in open_note
    assert open_note.count("Official lead (not yet archived)") == 23
    assert "**18 of the 37 current items**" in open_note
    assert "`84.2005.ND.CP.doc`" in open_note
    assert "`137.2007.ND.CP.zip`" in open_note
    assert "`26.NQ-CP.zip`" in open_note
    assert "`29.NQ-CP.zip`" in open_note
    assert "official effective 2006-07-16" in open_note
    assert "official effective 2007-09-18" in open_note
    assert "official effective 2009-01-18" in open_note
    assert "official effective 2009-06-29" in open_note
    assert coverage["residue"]["crosswalk_residue_event_ids"] == [
        "soap:2004-01-01->2004-07-01",
    ]
    assert coverage["residue"]["legal_unlinked_event_ids"] == []
    assert coverage["residue"]["unclassified_instrument_ids"] == []
    assert coverage["events"][0]["event_id"] == "soap:2004-01-01->2004-07-01"
    assert coverage["events"][0]["status"] == (
        "explicitly_classified_non_legal_transition"
    )
    assert coverage["events"][-1]["event_id"] == "soap:2026-04-29->2026-04-30"
    boundary_2008 = next(
        event for event in coverage["events"]
        if event["event_id"] == "soap:2008-07-02->2008-08-03"
    )
    assert boundary_2008["legal_instrument_ids"] == [
        "14/2008/QH12@2008-07-01",
        "15/2008/QH12@2008-08-01",
    ]
    assert [
        item["instrument_id"]
        for item in coverage["supplemental_legal_instruments"]
    ] == [
        "14/2008/QH12@2008-07-01",
        "15/2008/QH12@2008-08-01",
    ]
    assert all(
        link["classification"] != "unresolved"
        for event in coverage["events"]
        for link in event["legal_evidence"]["instrument_links"]
    )
    assert json.loads(serialize_coverage(coverage)) == coverage
    assert serialize_coverage(coverage) == serialize_coverage(coverage)
