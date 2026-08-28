from pathlib import Path
import vn_admin_units.soap as soap
from vn_admin_units.soap import parse_province_diffgram

def test_parse_province_diffgram():
    xml = Path("tests/fixtures/danhmuctinh_sample.xml").read_text(encoding="utf-8")
    rows = parse_province_diffgram(xml)
    assert rows == [
        {"ma": "15", "ten": "Tỉnh Lào Cai", "loai_hinh": "Tỉnh"},
        {"ma": "01", "ten": "Thành phố Hà Nội", "loai_hinh": "Thành phố Trung ương"},
    ]


def test_fetch_units_raw_uses_tier_method_and_ordered_params(monkeypatch):
    captured = {}

    def fake_call(method, timeout, **params):
        captured.update(method=method, timeout=timeout, params=params)
        return b"<xml/>"

    monkeypatch.setattr(soap, "soap_call_bytes", fake_call)
    result = soap.fetch_units_raw("ward", "30/06/2025", timeout=17)

    assert result == b"<xml/>"
    assert captured == {
        "method": "DanhMucPhuongXa",
        "timeout": 17,
        "params": {"DenNgay": "30/06/2025", "Tinh": "", "QuanHuyen": ""},
    }
