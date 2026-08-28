import json

from vn_admin_units.ward_crosswalk_reconciliation import (
    build_crosswalk_reconciliation,
    reconcile_window,
    serialize_reconciliation,
)


def _observation(code, name, province="01"):
    return {
        "code": code,
        "name_vi": name,
        "loai_hinh": name.split(" ", 1)[0],
        "district_code": "001",
        "district_name_vi": "Quận mẫu",
        "province_code_echo": province,
        "province_name_echo": "Tỉnh mẫu",
    }


def _interval(before, after, *, same=(), additions=(), removals=()):
    return {
        "event_id": f"soap:{before}->{after}",
        "before_date": before,
        "after_date": after,
        "normalized_changed": True,
        "same_code_changes": list(same),
        "additions": list(additions),
        "removals": list(removals),
        "source_anomaly_transitions": [],
    }


def _row(**overrides):
    row = {
        "base_tinh": "01",
        "base_tinh_ten": "Tỉnh mẫu",
        "base_ma": "00001",
        "base_ten": "Xã Cũ",
        "base_nghi_dinh": "",
        "base_hieu_luc": "2004-06-30",
        "succ_ten": "Xã Mới",
        "succ_ma": "00001",
        "succ_nghi_dinh": "Số: 1/NQ-CP",
        "succ_hieu_luc": "2020-02-01",
        "succ_tinh_ten": "Tỉnh mẫu",
        "succ_tinh": "01",
        "ghi_chu": "",
    }
    row.update(overrides)
    return row


def _same(code="00001", before="Xã Cũ", after="Xã Mới"):
    return {
        "code": code,
        "before": _observation(code, before),
        "after": _observation(code, after),
        "changed_fields": ["TenPhuongXa"],
        "change_types": ["name"],
        "identity_inference": "none_same_code_observation_only",
    }


def test_same_code_row_supports_observation_without_asserting_identity():
    result = reconcile_window(
        source_path="crosswalk/ward_2020-01-01_2021-01-01.xls",
        kind="yearly",
        base_date="2020-01-01",
        compare_date="2021-01-01",
        rows=[_row()],
        intervals=[_interval("2020-01-01", "2020-02-01", same=[_same()])],
        legal_instruments_by_date={},
    )

    component = result["events"][0]["components"][0]
    assert component["status"] == "supported_same_code"
    assert result["targeted_windows"] == []


def test_same_code_observation_can_resolve_as_code_reuse():
    rows = [
        _row(base_ma="00001", base_ten="Xã Cũ", succ_ma="", succ_ten=""),
        _row(base_ma="00002", base_ten="Xã Khác", succ_ma="00001", succ_ten="Xã Mới"),
    ]
    result = reconcile_window(
        source_path="crosswalk/ward_2020-01-01_2021-01-01.xls",
        kind="yearly",
        base_date="2020-01-01",
        compare_date="2021-01-01",
        rows=rows,
        intervals=[_interval("2020-01-01", "2020-02-01", same=[_same()])],
        legal_instruments_by_date={},
    )

    component = result["events"][0]["components"][0]
    assert component["status"] == "supported_code_reuse"
    assert len(component["evidence_row_ids"]) == 2


def test_repeated_and_ephemeral_changes_request_narrow_windows():
    same = _same()
    intervals = [
        _interval(
            "2020-01-01", "2020-02-01",
            same=[same],
            additions=[_observation("00002", "Xã Thoáng qua")],
        ),
        _interval(
            "2020-02-01", "2020-03-01",
            same=[same],
            removals=[_observation("00002", "Xã Thoáng qua")],
        ),
    ]
    result = reconcile_window(
        source_path="crosswalk/ward_2020-01-01_2021-01-01.xls",
        kind="yearly",
        base_date="2020-01-01",
        compare_date="2021-01-01",
        rows=[_row()],
        intervals=intervals,
        legal_instruments_by_date={},
    )

    assert [item["base_date"] for item in result["targeted_windows"]] == [
        "2020-01-01", "2020-02-01",
    ]
    reasons = {
        reason
        for item in result["targeted_windows"]
        for reason in item["reasons"]
    }
    assert "multiple_changes_within_window" in reasons
    assert "ephemeral_within_window" in reasons
    assert "soap_crosswalk_disagreement" in reasons


def test_real_crosswalk_reconciliation_is_deterministic():
    artifact = build_crosswalk_reconciliation()
    summary = artifact["summary"]

    assert summary["observed_events"] == 179
    assert summary["primary_crosswalk_windows"] == 23
    assert summary["primary_crosswalk_rows"] == 244_987
    assert summary["event_components"] == 35_350
    assert summary["source_anomaly_transitions"] == 15
    assert summary["linked_crosswalk_rows"] == 24_886
    assert summary["code_reuse_components"] == 27
    assert summary["long_range_fallback_components_supported"] == 206
    assert summary["targeted_windows"] == 15
    assert summary["targeted_windows_reconciled"] == 14
    assert summary["targeted_windows_with_residue"] == 1
    assert summary["targeted_remaining_reason_counts"] == {
        "soap_crosswalk_disagreement": 1,
    }
    assert summary["component_statuses"] == {
        "supported": 29_421,
        "supported_code_reuse": 27,
        "supported_long_range": 191,
        "supported_long_range_code_transition": 15,
        "supported_same_code": 5_687,
        "supported_source_correction": 1,
        "unmatched": 8,
    }
    evidence_ids = {row["row_id"] for row in artifact["crosswalk_evidence_rows"]}
    assert all(
        row_id in evidence_ids
        for event in artifact["events"]
        for component in event["components"]
        for row_id in component["evidence_row_ids"]
    )
    assert json.loads(serialize_reconciliation(artifact)) == artifact
    assert serialize_reconciliation(artifact) == serialize_reconciliation(artifact)
