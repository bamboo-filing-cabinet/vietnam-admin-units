import json

from vn_admin_units.ward_observed_changes import (
    build_observed_changes,
    diff_states,
    normalize_snapshot_variants,
    serialize_observed_changes,
)


def _row(**overrides):
    row = {
        "MaTinh": "01",
        "TenTinh": "Thành phố Hà Nội",
        "MaQuanHuyen": "001",
        "TenQuanHuyen": "Quận Ba Đình",
        "MaPhuongXa": "00004",
        "TenPhuongXa": "Phường Trúc Bạch",
        "LoaiHinh": "Phường",
    }
    row.update(overrides)
    return row


def test_normalization_collapses_exact_duplicates_and_preserves_conflicts():
    state, audit = normalize_snapshot_variants([
        _row(),
        _row(TenPhuongXa=" Phường\nTrúc Bạch "),
        _row(LoaiHinh="Thị trấn"),
    ])

    assert audit["source_rows"] == 3
    assert audit["exact_duplicate_rows_collapsed"] == 1
    assert audit["conflicting_identity_rows"] == 1
    assert audit["conflicted_identity_keys"] == 1
    assert state["resolved_by_code"] == {}
    assert state["anomalies_by_code"]["00004"]["kind"] == "identity_conflict"
    assert [variant["source_occurrences"] for variant in state["anomalies_by_code"]["00004"]["variants"]] == [
        1, 2,
    ]


def test_conflicted_code_is_not_reported_as_an_administrative_addition():
    before, _ = normalize_snapshot_variants([_row(), _row(LoaiHinh="Thị trấn")])
    after, _ = normalize_snapshot_variants([_row()])

    delta = diff_states(before, after)

    assert delta["additions"] == []
    assert delta["removals"] == []
    assert delta["same_code_changes"] == []
    assert [item["code"] for item in delta["source_anomaly_transitions"]] == ["00004"]


def test_same_code_change_types_separate_parent_from_province_echo():
    before, _ = normalize_snapshot_variants([_row()])
    after, _ = normalize_snapshot_variants([_row(
        MaTinh="79",
        TenTinh="Thành phố Hồ Chí Minh",
        MaQuanHuyen="760",
        TenQuanHuyen="Quận 1",
        TenPhuongXa="Phường Bến Nghé",
        LoaiHinh="Xã",
    )])

    delta = diff_states(before, after)
    change = delta["same_code_changes"][0]

    assert change["code"] == "00004"
    assert change["changed_fields"] == [
        "MaTinh",
        "TenTinh",
        "MaQuanHuyen",
        "TenQuanHuyen",
        "TenPhuongXa",
        "LoaiHinh",
    ]
    assert change["change_types"] == [
        "province_echo_code",
        "province_echo_label",
        "district_parent_code",
        "district_parent_label",
        "name",
        "type",
    ]
    assert change["identity_inference"] == "none_same_code_observation_only"


def test_additions_and_removals_are_explicit_after_same_code_matching():
    before, _ = normalize_snapshot_variants([
        _row(MaPhuongXa="00001"),
        _row(MaPhuongXa="00002"),
    ])
    after, _ = normalize_snapshot_variants([
        _row(MaPhuongXa="00002"),
        _row(MaPhuongXa="00003"),
    ])

    delta = diff_states(before, after)

    assert [row["code"] for row in delta["removals"]] == ["00001"]
    assert [row["code"] for row in delta["additions"]] == ["00003"]
    assert delta["counts"]["unchanged_codes"] == 1


def test_real_observed_change_inventory_is_deterministic():
    artifact = build_observed_changes()
    summary = artifact["summary"]

    assert summary["snapshots"] == 204
    assert summary["intervals"] == 203
    assert summary["source_rows"] == 2_202_543
    assert summary["exact_duplicate_rows_collapsed"] == 3_327
    assert summary["conflicting_identity_rows"] == 34
    assert summary["snapshots_with_source_anomalies"] == 52
    assert summary["byte_identical_intervals"] == 24
    assert summary["normalized_no_change_intervals"] == 24
    assert summary["payload_changed_but_normalized_no_change_intervals"] == 0
    assert summary["changed_intervals"] == 179
    assert summary["same_code_changes"] == 5_715
    assert summary["additions"] == 11_209
    assert summary["removals"] == 18_426
    assert summary["source_anomaly_transitions"] == 15
    assert summary["field_changes"] == {
        "LoaiHinh": 1_398,
        "MaQuanHuyen": 4_148,
        "MaTinh": 1_308,
        "TenPhuongXa": 3_507,
        "TenQuanHuyen": 4_142,
        "TenTinh": 1_686,
    }
    assert artifact["scope"]["source_floor"] == "2002-01-01"
    assert artifact["scope"]["as_of"] == "2026-08-27"

    first = artifact["intervals"][0]
    assert (first["before_date"], first["after_date"]) == (
        "2002-01-01", "2004-01-01",
    )
    assert first["payload_relation"] == "identical"
    assert first["normalized_changed"] is False

    reform = next(
        interval for interval in artifact["intervals"]
        if interval["before_date"] == "2025-06-30"
        and interval["after_date"] == "2025-07-01"
    )
    assert reform["counts"] == {
        "unchanged_codes": 0,
        "same_code_changes": 3_316,
        "additions": 5,
        "removals": 6_719,
        "source_anomaly_transitions": 0,
        "excluded_anomalous_codes": 0,
        "field_changes": {
            "LoaiHinh": 634,
            "MaQuanHuyen": 3_316,
            "MaTinh": 950,
            "TenPhuongXa": 2_178,
            "TenQuanHuyen": 3_316,
            "TenTinh": 1_323,
        },
    }

    anomaly_codes = {
        anomaly["code"]
        for snapshot in artifact["snapshot_audits"]
        for anomaly in snapshot["source_anomalies"]
    }
    assert anomaly_codes == {
        "09541", "09595", "09601", "09607", "09886", "10117", "10123", "7070901",
    }
    assert json.loads(serialize_observed_changes(artifact)) == artifact
    assert serialize_observed_changes(artifact) == serialize_observed_changes(artifact)
