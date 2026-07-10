import re
import urllib.request

URL = "https://danhmuchanhchinh.nso.gov.vn/DMDVHC.asmx"
NS = "http://tempuri.org/"


def parse_province_diffgram(xml: str) -> list[dict]:
    """Extract province rows from a DanhMucTinh SOAP diffgram response.

    Scoped to the current-state <DocumentElement>; any <diffgr:before> block is
    ignored (.02 confirmed reads return a single DocumentElement, no before-block —
    this guard prevents double-counting if that ever changes)."""
    m = re.search(r"<DocumentElement\b[^>]*>(.*?)</DocumentElement>", xml, re.S)
    scope = m.group(1) if m else xml
    rows = []
    for block in re.findall(r"<TABLE\b[^>]*>(.*?)</TABLE>", scope, re.S):
        def field(name: str) -> str:
            mm = re.search(rf"<{name}>(.*?)</{name}>", block)
            return mm.group(1) if mm else ""
        rows.append({
            "ma": field("MaTinh"),
            "ten": field("TenTinh"),
            "loai_hinh": field("LoaiHinh"),
        })
    return rows


def fetch_provinces_raw(den_ngay: str, timeout: int = 90) -> str:
    """Return the verbatim DanhMucTinh SOAP XML response for an as-of date (dd/mm/yyyy)."""
    env = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        f'<soap:Body><DanhMucTinh xmlns="{NS}"><DenNgay>{den_ngay}</DenNgay>'
        "</DanhMucTinh></soap:Body></soap:Envelope>"
    )
    req = urllib.request.Request(
        URL, data=env.encode("utf-8"),
        headers={"Content-Type": "text/xml; charset=utf-8",
                 "SOAPAction": f'"{NS}DanhMucTinh"'},
    )
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8")


def fetch_provinces(den_ngay: str, timeout: int = 90) -> list[dict]:
    """Call DanhMucTinh for an as-of date (dd/mm/yyyy) and parse to rows. Live network call."""
    return parse_province_diffgram(fetch_provinces_raw(den_ngay, timeout))
