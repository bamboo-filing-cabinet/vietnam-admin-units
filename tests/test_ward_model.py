import unicodedata

import pytest

from vn_admin_units.ward_model import (
    build_2025_boundary,
    normalize_snapshot,
    normalize_text,
    write_2025_boundary,
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


def test_normalize_text_collapses_whitespace_and_uses_nfc():
    value = "  Phường\n  Ho\u0300a  "
    assert normalize_text(value) == "Phường Hòa"
    assert unicodedata.is_normalized("NFC", normalize_text(value))


def test_snapshot_collapses_exact_duplicates_after_normalization():
    rows, audit = normalize_snapshot([
        _row(),
        _row(TenPhuongXa=" Phường\nTrúc Bạch "),
    ])
    assert len(rows) == 1
    assert rows[0]["TenPhuongXa"] == "Phường Trúc Bạch"
    assert audit["exact_duplicate_rows_collapsed"] == 1


def test_snapshot_rejects_conflicting_identity_rows():
    with pytest.raises(ValueError, match="conflicting ward snapshot rows"):
        normalize_snapshot([_row(), _row(TenPhuongXa="Phường Ba Đình")])


def test_real_2025_boundary_counts_and_source_correction():
    artifact = build_2025_boundary()
    audit = artifact["audit"]
    assert audit["pre"]["normalized_rows"] == 10035
    assert audit["post"]["normalized_rows"] == 3321
    assert audit["structured_primary_links"] == 3316
    assert audit["blank_base_creations"] == 5
    assert audit["absorbed_without_structured_target"] == 6719
    assert audit["composition_notes"] == 3321
    assert audit["composition_notes_at_255_char_source_limit"] == 20
    assert audit["pre_soap_province_echo_code_mismatches"] == 999
    assert audit["pre_soap_province_echo_name_mismatches"] == 159
    assert artifact["corrections"] == [{
        "code": "00070",
        "field": "TenPhuongXa",
        "reason": "blank in post-reform SOAP; filled from official NSO composition crosswalk",
        "source_path": "crosswalk/ward_2025-07-01_2026-08-27.xls",
        "source_value": "Phường Hoàn Kiếm",
    }]


def test_real_boundary_primary_endpoints_and_composition_are_complete():
    artifact = build_2025_boundary()
    links = artifact["structured_primary_links"]
    assert len({row["predecessor_code"] for row in links}) == 3316
    assert len({row["successor_code"] for row in links}) == 3316
    ba_dinh = next(row for row in artifact["composition_notes"] if row["successor_code"] == "00004")
    assert "phường Quán Thánh" in ba_dinh["note"]
    assert ba_dinh["effective_date"] == "2025-07-01"


def test_write_boundary_is_deterministic(tmp_path):
    path = tmp_path / "ward-boundary.json"
    write_2025_boundary(path)
    first = path.read_bytes()
    write_2025_boundary(path)
    assert path.read_bytes() == first
