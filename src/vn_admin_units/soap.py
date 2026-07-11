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


# --- canonical generic SOAP access (use these instead of ad-hoc scripts) ---

# tier -> (SOAP method, ordered field names, code field)
TIERS = {
    "province": ("DanhMucTinh",
                 ["MaTinh", "TenTinh", "LoaiHinh"], "MaTinh"),
    "district": ("DanhMucQuanHuyen",
                 ["MaTinh", "TenTinh", "MaQuanHuyen", "TenQuanHuyen", "LoaiHinh"], "MaQuanHuyen"),
    "ward":     ("DanhMucPhuongXa",
                 ["MaTinh", "TenTinh", "MaQuanHuyen", "TenQuanHuyen",
                  "MaPhuongXa", "TenPhuongXa", "LoaiHinh"], "MaPhuongXa"),
}


def soap_call(method: str, timeout: int = 180, **params: str) -> str:
    """POST a DMDVHC SOAP method with ordered string params; return verbatim XML."""
    body = "".join(f"<{k}>{v}</{k}>" for k, v in params.items())
    env = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        f'<soap:Body><{method} xmlns="{NS}">{body}</{method}></soap:Body></soap:Envelope>'
    )
    req = urllib.request.Request(
        URL, data=env.encode("utf-8"),
        headers={"Content-Type": "text/xml; charset=utf-8",
                 "SOAPAction": f'"{NS}{method}"'},
    )
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8")


def parse_rows(xml: str, fields: list[str]) -> list[dict]:
    """Generic diffgram parser: one dict per <TABLE> in <DocumentElement>, with the
    named fields. Scoped to DocumentElement so any <diffgr:before> block is ignored."""
    m = re.search(r"<DocumentElement\b[^>]*>(.*?)</DocumentElement>", xml, re.S)
    scope = m.group(1) if m else xml
    rows = []
    for block in re.findall(r"<TABLE\b[^>]*>(.*?)</TABLE>", scope, re.S):
        row = {}
        for f in fields:
            mm = re.search(rf"<{f}>(.*?)</{f}>", block)
            row[f] = mm.group(1) if mm else ""
        rows.append(row)
    return rows


def parse_rows_all(xml: str) -> list[dict]:
    """Like parse_rows but captures EVERY child tag of each <TABLE> (field-agnostic).
    Use to inspect fields the fixed tier list omits (LoaiDoThi, Vung, KhuVuc, …)."""
    m = re.search(r"<DocumentElement\b[^>]*>(.*?)</DocumentElement>", xml, re.S)
    scope = m.group(1) if m else xml
    rows = []
    for block in re.findall(r"<TABLE\b[^>]*>(.*?)</TABLE>", scope, re.S):
        rows.append(dict(re.findall(r"<(\w+)>(.*?)</\1>", block, re.S)))
    return rows


def _params(tier: str, den_ngay: str, tinh: str, quan_huyen: str) -> dict:
    params: dict[str, str] = {"DenNgay": den_ngay}
    if tier in ("district", "ward"):
        params["Tinh"] = tinh
    if tier == "ward":
        params["QuanHuyen"] = quan_huyen
    return params


def fetch_units_full(tier: str, den_ngay: str, tinh: str = "", quan_huyen: str = "",
                     timeout: int = 180) -> list[dict]:
    """Canonical fetch returning ALL fields per row (for full-row comparison)."""
    method = TIERS[tier][0]
    return parse_rows_all(soap_call(method, timeout, **_params(tier, den_ngay, tinh, quan_huyen)))


def fetch_units(tier: str, den_ngay: str, tinh: str = "", quan_huyen: str = "",
                timeout: int = 180) -> list[dict]:
    """Canonical fetch of any tier at an as-of date. Params built in WSDL order.
    tinh/quan_huyen empty = whole tier nationally."""
    method, fields, _ = TIERS[tier]
    return parse_rows(soap_call(method, timeout, **_params(tier, den_ngay, tinh, quan_huyen)), fields)


def fetch_provinces_raw(den_ngay: str, timeout: int = 90) -> str:
    """Verbatim DanhMucTinh SOAP XML for an as-of date (dd/mm/yyyy)."""
    return soap_call("DanhMucTinh", timeout, DenNgay=den_ngay)


def fetch_provinces(den_ngay: str, timeout: int = 90) -> list[dict]:
    """DanhMucTinh -> [{ma,ten,loai_hinh}] (the province-pipeline shape)."""
    return parse_province_diffgram(fetch_provinces_raw(den_ngay, timeout))
