from vn_admin_units.ward_legal_linkage import classify_instrument_title


def test_title_classification_distinguishes_structural_change_kinds():
    assert classify_instrument_title(
        "Sắp xếp các đơn vị hành chính cấp xã thuộc tỉnh Bắc Giang"
    )[0] == "lineage"
    assert classify_instrument_title(
        "Đổi tên phường 6 thành phường Thắng Nhì thuộc thành phố Vũng Tàu"
    )[0] == "rename_or_retype"
    assert classify_instrument_title(
        "Điều chỉnh địa giới hành chính giữa xã Ba Liên và xã Phổ Phong"
    )[0] == "parent_or_boundary_only"


def test_title_classification_does_not_hide_an_unknown_shape():
    assert classify_instrument_title("Văn bản không có nội dung cấu trúc") == (
        "unresolved",
        [],
    )
