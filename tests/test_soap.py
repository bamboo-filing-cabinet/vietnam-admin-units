from pathlib import Path
from vn_admin_units.soap import parse_province_diffgram

def test_parse_province_diffgram():
    xml = Path("tests/fixtures/danhmuctinh_sample.xml").read_text(encoding="utf-8")
    rows = parse_province_diffgram(xml)
    assert rows == [
        {"ma": "15", "ten": "Tỉnh Lào Cai", "loai_hinh": "Tỉnh"},
        {"ma": "01", "ten": "Thành phố Hà Nội", "loai_hinh": "Thành phố Trung ương"},
    ]
