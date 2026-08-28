"""Discover and preserve official legal sources for historical ward changes.

The NSO legal index deliberately supplies the historical instrument denominator,
but it does not expose source URLs.  This module searches the Government's own
document lists, validates exact instrument metadata, writes a deterministic
source registry, and archives the official metadata page plus every linked
original attachment.

The existing 1654--1687/NQ-UBTVQH15 pairs are reused in place.  All other
artifacts use paths derived from normalized effective date + instrument code.

Usage:
  uv run python -m vn_admin_units.ward_legal_fetch --discover
  uv run python -m vn_admin_units.ward_legal_fetch --gazette-recover
  uv run python -m vn_admin_units.ward_legal_fetch --fetch-supplemental
  uv run python -m vn_admin_units.ward_legal_fetch --fetch
  uv run python -m vn_admin_units.ward_legal_fetch --check
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from lxml import html

from vn_admin_units import rawcache
from vn_admin_units.crosscheck_decrees import is_ward_structural
from vn_admin_units.ward_source_coverage import normalize_code, normalize_date


LEGAL_INDEX = Path("data/raw/nghidinh.json")
SECONDARY_URLS = (
    Path("data/decree-urls.json"),
    Path("data/ward-legal-secondary-urls.json"),
)
REGISTRY = Path("data/ward-legal-sources.json")
LEGAL_LINKAGE_OVERRIDES = Path("data/ward-legal-linkage-overrides.json")

PORTAL_ROOT = "https://chinhphu.vn"
PORTAL_LIST = f"{PORTAL_ROOT}/he-thong-van-ban"
FORM_PREFIX = "ctrl_191017_163$"
GAZETTE_ROOT = "https://congbao.chinhphu.vn"
GAZETTE_SEARCH = "https://api-searchcongbao.chinhphu.vn/search/van-ban"
EXPECTED_INSTRUMENTS = 449
EXPECTED_REUSED_2025 = 34

_OFFICIAL_HOSTS = {
    "api-searchcongbao.chinhphu.vn",
    "baochinhphu.vn",
    "chinhphu.vn",
    "congbao.chinhphu.vn",
    "datafiles.chinhphu.vn",
    "gov.vn",
    "quochoi.vn",
    "vanban.chinhphu.vn",
    "vbpl.vn",
    "xaydungchinhsach.chinhphu.vn",
}
_ATTACHMENT_EXTENSIONS = {"doc", "docx", "htm", "html", "pdf", "rtf", "zip"}


def _fold_text(value: str) -> str:
    value = unicodedata.normalize("NFD", str(value or "").casefold()).replace("đ", "d")
    value = "".join(char for char in value if unicodedata.category(char) != "Mn")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


def code_slug(code: str) -> str:
    slug = _fold_text(normalize_code(code)).replace(" ", "-")
    if not slug:
        raise ValueError(f"cannot derive a path slug from {code!r}")
    return slug


def cache_base(code: str, effective_date: str) -> str:
    return f"legal/ward/{normalize_date(effective_date)}/{code_slug(code)}"


def metadata_relpath(code: str, effective_date: str) -> str:
    return f"{cache_base(code, effective_date)}.metadata.html"


def _attachment_extension(url: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower().lstrip(".")
    return suffix if suffix in _ATTACHMENT_EXTENSIONS else "bin"


def attachment_relpaths(code: str, effective_date: str,
                        attachment_urls: list[str]) -> list[str]:
    base = cache_base(code, effective_date)
    if len(attachment_urls) == 1:
        return [f"{base}.original.{_attachment_extension(attachment_urls[0])}"]
    return [
        f"{base}.original-{index:02d}.{_attachment_extension(url)}"
        for index, url in enumerate(attachment_urls, start=1)
    ]


def _instrument_records(path: Path = LEGAL_INDEX) -> list[dict]:
    records = json.loads(path.read_text(encoding="utf-8"))
    grouped: dict[tuple[str, str], list[dict]] = {}
    for record in records:
        if not is_ward_structural(str(record.get("noi_dung", ""))):
            continue
        key = normalize_code(record.get("code", "")), normalize_date(record.get("hieu_luc", ""))
        grouped.setdefault(key, []).append(record)

    instruments = []
    for (code, effective_date), variants in sorted(
            grouped.items(), key=lambda item: (item[0][1], item[0][0])):
        instruments.append({
            "instrument_id": f"{code}@{effective_date}",
            "code": code,
            "effective_date": effective_date,
            "title_variants": sorted({
                " ".join(str(record.get("noi_dung", "")).split())
                for record in variants
            }),
        })
    if len(instruments) != EXPECTED_INSTRUMENTS:
        raise ValueError(
            f"ward instrument denominator drifted: expected {EXPECTED_INSTRUMENTS}, "
            f"got {len(instruments)}"
        )
    return instruments


def _is_reused_2025(record: dict) -> bool:
    match = re.fullmatch(r"(\d+)/NQ-UBTVQH15", record["code"])
    return (
        match is not None
        and 1654 <= int(match.group(1)) <= 1687
        and record["effective_date"] == "2025-07-01"
    )


def _portal_class(code: str) -> str:
    code = normalize_code(code)
    if "NQ-CP" in code:
        return "509"
    if "NQ-UBTVQH" in code or "/UBTVQH" in code:
        return "2"
    return "1"


def _portal_list_url(code: str) -> str:
    return f"{PORTAL_LIST}?classid={_portal_class(code)}&mode=1&maxresults=50"


def _decode_html(content: bytes, label: str):
    try:
        return html.fromstring(content, parser=html.HTMLParser(encoding="utf-8"))
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{label} is not parseable HTML") from exc


def _form_values(document) -> dict[str, str]:
    forms = document.xpath('//form[@id="form1"]')
    if len(forms) != 1:
        raise ValueError(f"official document list has {len(forms)} search forms")
    data: dict[str, str] = {}
    for element in forms[0].xpath('.//input[@name] | .//select[@name]'):
        name = element.get("name")
        if element.tag == "select":
            selected = element.xpath('./option[@selected]')
            value = selected[0].get("value", "") if selected else ""
        else:
            input_type = element.get("type", "").lower()
            if input_type in {"button", "file", "image", "submit"}:
                continue
            if input_type in {"checkbox", "radio"} and element.get("checked") is None:
                continue
            value = element.get("value", "")
        data[name] = value
    return data


def parse_search_results(content: bytes) -> list[dict]:
    document = _decode_html(content, "official document search response")
    rows = []
    for row in document.xpath('//table[@id="ctrl_191017_163_grvDocument"]//tr[td]'):
        code = " ".join(row.xpath('string(.//span[contains(@class,"code")])').split())
        if not code:
            continue
        issued = " ".join(
            row.xpath('string(./td[2]//span[contains(@class,"issued-date")])').split()
        )
        title = " ".join(
            row.xpath('string(.//span[contains(@class,"substract")])').split()
        )
        detail_hrefs = row.xpath(
            './td[1]/a/@href | ./td[3]/a[.//span[contains(@class,"substract")]]/@href'
        )
        attachment_urls = [
            urljoin(PORTAL_ROOT, value)
            for value in row.xpath('.//div[contains(@class,"bl-doc-file")]/a/@href')
        ]
        if not detail_hrefs:
            raise ValueError(f"official search result for {code} has no detail URL")
        rows.append({
            "code": normalize_code(code),
            "issued_date": normalize_issue_date(issued),
            "title": title,
            "metadata_url": urljoin(PORTAL_ROOT, detail_hrefs[0]),
            "attachment_urls": list(dict.fromkeys(attachment_urls)),
        })
    return rows


def normalize_issue_date(value: str) -> str:
    value = " ".join(str(value or "").split())
    for pattern in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"unsupported official issue date: {value!r}")


def _detail_fields(document) -> dict[str, str]:
    fields = {}
    for row in document.xpath('//tr[td]'):
        cells = row.xpath('./td')
        if len(cells) < 2:
            continue
        label = _fold_text(" ".join(cells[0].itertext()))
        if label in {"so ky hieu", "ngay ban hanh", "trich yeu"}:
            fields[label] = " ".join(" ".join(cells[1].itertext()).split())
    return fields


def parse_official_detail(content: bytes, source_url: str) -> dict:
    document = _decode_html(content, f"official metadata page {source_url}")
    fields = _detail_fields(document)
    missing = sorted({"so ky hieu", "ngay ban hanh", "trich yeu"} - fields.keys())
    if missing:
        raise ValueError(f"official metadata page is missing fields: {missing}")
    attachments = [
        urljoin(source_url, value)
        for value in document.xpath('//a[contains(@class,"view-file")]/@href')
    ]
    if not attachments:
        attachments = [
            urljoin(source_url, value)
            for value in document.xpath('//a[@download and contains(@href,"/files/vbpq/")]/@href')
        ]
    return {
        "code": normalize_code(fields["so ky hieu"]),
        "issued_date": normalize_issue_date(fields["ngay ban hanh"]),
        "title": fields["trich yeu"],
        "attachment_urls": list(dict.fromkeys(attachments)),
    }


def _title_similarity(expected: list[str], actual: str) -> float:
    actual_folded = _fold_text(actual)
    return max(
        SequenceMatcher(None, _fold_text(title), actual_folded).ratio()
        for title in expected
    )


def _validate_candidate(record: dict, candidate: dict, *,
                        allow_code_mismatch: bool = False) -> float:
    if candidate["code"] != record["code"] and not allow_code_mismatch:
        raise ValueError(
            f"official code mismatch: expected {record['code']}, got {candidate['code']}"
        )
    issued = date.fromisoformat(candidate["issued_date"])
    effective = date.fromisoformat(record["effective_date"])
    delta = (effective - issued).days
    if delta < 0 or delta > 730:
        raise ValueError(
            f"official issue/effective dates are inconsistent for {record['instrument_id']}: "
            f"issued {issued}, effective {effective}"
        )
    similarity = _title_similarity(record["title_variants"], candidate["title"])
    if similarity < 0.55:
        raise ValueError(
            f"official title mismatch for {record['instrument_id']} "
            f"(similarity {similarity:.3f}): {candidate['title']!r}"
        )
    return similarity


def _require_official_url(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not any(
            host == allowed or host.endswith(f".{allowed}") for allowed in _OFFICIAL_HOSTS):
        raise ValueError(f"not an allowlisted official HTTPS URL: {url}")


class PortalSearch:
    """One reusable session for the Government ASP.NET document-list form."""

    def __init__(self, *, timeout: int = 120, session=None):
        self.timeout = timeout
        self.session = session or requests.Session()
        self._states: dict[str, tuple[str, dict[str, str]]] = {}

    def _state(self, code: str) -> tuple[str, dict[str, str]]:
        class_id = _portal_class(code)
        if class_id not in self._states:
            url = _portal_list_url(code)
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            document = _decode_html(response.content, f"official document list {url}")
            self._states[class_id] = url, _form_values(document)
        return self._states[class_id]

    def search(self, code: str, query: str | None = None) -> list[dict]:
        class_id = _portal_class(code)
        url, state = self._state(code)
        data = dict(state)
        data[f"{FORM_PREFIX}txtSearchKeyword"] = query or code
        data[f"{FORM_PREFIX}drdRecordPerPage"] = "50"
        data[f"{FORM_PREFIX}btnSearch"] = "Tìm kiếm"
        response = self.session.post(url, data=data, timeout=self.timeout)
        response.raise_for_status()
        document = _decode_html(response.content, f"official search response for {code}")
        self._states[class_id] = url, _form_values(document)
        return parse_search_results(response.content)


def _gazette_metadata_url(item: dict) -> str:
    document_type = "-".join(
        _fold_text(str(item.get("loai_van_ban", "van ban"))).split()
    )
    code = code_slug(str(item["so_ky_hieu"]))
    return f"{GAZETTE_ROOT}/van-ban/{document_type}-so-{code}-{item['id_van_ban']}.htm"


def _is_gazette_pdf(file: dict) -> bool:
    extension = str(file.get("file_extension", "")).casefold()
    url_path = urlparse(str(file.get("duong_dan", ""))).path.casefold()
    return extension == "pdf" or extension.endswith("pdf") or url_path.endswith("pdf")


def parse_gazette_results(payload: dict) -> list[dict]:
    """Normalize official Gazette API hits and retain publication PDFs."""
    if payload.get("success") is not True or not isinstance(payload.get("data"), list):
        raise ValueError("official Gazette search response has an unexpected shape")
    results = []
    for item in payload["data"]:
        required = ("id_van_ban", "so_ky_hieu", "ngay_ban_hanh", "trich_yeu")
        if not all(item.get(key) for key in required):
            continue
        pdf_urls = list(dict.fromkeys(
            str(file.get("duong_dan", ""))
            for file in item.get("danh_sach_tep_van_ban") or []
            if file.get("duong_dan") and _is_gazette_pdf(file)
        ))
        if not pdf_urls:
            continue
        results.append({
            "code": normalize_code(item["so_ky_hieu"]),
            "issued_date": normalize_issue_date(str(item["ngay_ban_hanh"])[:10]),
            "title": " ".join(str(item["trich_yeu"]).split()),
            "metadata_url": _gazette_metadata_url(item),
            "attachment_urls": pdf_urls,
            "gazette_record_id": int(item["id_van_ban"]),
        })
    return results


def parse_gazette_detail(content: bytes, source_url: str) -> dict:
    """Read validation fields and direct publication PDFs from a Gazette page."""
    document = _decode_html(content, f"official Gazette metadata page {source_url}")
    fields = {}
    rows = document.xpath(
        '//div[contains(concat(" ", normalize-space(@class), " "), " row ")]'
    )
    for row in rows:
        label = _fold_text(
            " ".join(row.xpath('string(.//*[contains(@class,"name")])').split())
        )
        value = " ".join(
            row.xpath('string(.//*[contains(@class,"value")])').split()
        )
        if label in {"so ky hieu", "ngay ban hanh", "trich yeu"} and value:
            fields[label] = value
    missing = sorted({"so ky hieu", "ngay ban hanh", "trich yeu"} - fields.keys())
    if missing:
        raise ValueError(f"official Gazette metadata page is missing fields: {missing}")
    attachments = list(dict.fromkeys(document.xpath(
        '//div[@data-contentvanban="loadtep"]//a[@data-href]/@data-href'
    )))
    if not attachments:
        raise ValueError("official Gazette metadata page has no direct publication PDF")
    return {
        "code": normalize_code(fields["so ky hieu"]),
        "issued_date": normalize_issue_date(fields["ngay ban hanh"]),
        "title": fields["trich yeu"],
        "attachment_urls": attachments,
    }


class GazetteSearch:
    """Search the public Government Gazette API with year-bounded titles."""

    def __init__(self, *, timeout: int = 120, session=None):
        self.timeout = timeout
        self.session = session or requests.Session()

    def search(self, record: dict) -> list[dict]:
        effective_year = date.fromisoformat(record["effective_date"]).year
        candidates = {}
        for title in record["title_variants"]:
            response = self.session.post(
                GAZETTE_SEARCH,
                json={
                    "filters": {
                        "filters_mode": "or",
                        "nam": [str(effective_year - 1), str(effective_year)],
                    },
                    "page": 1,
                    "page_size": 100,
                    "query": title,
                },
                headers={"accept": "application/json"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            for candidate in parse_gazette_results(response.json()):
                candidates[candidate["metadata_url"]] = candidate
        return list(candidates.values())


def _secondary_url_map(paths: tuple[Path, ...] = SECONDARY_URLS) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for path in paths:
        if not path.is_file():
            continue
        urls = json.loads(path.read_text(encoding="utf-8"))
        for code, url in urls.items():
            host = (urlparse(str(url)).hostname or "").lower()
            if host == "thuvienphapluat.vn" or host.endswith(".thuvienphapluat.vn"):
                result.setdefault(normalize_code(code), []).append(str(url))
    return {key: sorted(set(value)) for key, value in result.items()}


def _input_fingerprints() -> dict:
    paths = (LEGAL_INDEX, *SECONDARY_URLS)
    return {
        path.as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
        if path.is_file()
    }


def _reused_registry_entry(record: dict, secondary_urls: list[str]) -> dict:
    number = int(record["code"].split("/", 1)[0])
    return {
        **record,
        "discovery_status": "reused_existing_2025_pair",
        "issued_date": "2025-06-16",
        "metadata_url": "",
        "metadata_path": f"resolutions/ward-2025/{number}-nq-ubtvqh15.html",
        "attachments": [{
            "url": f"https://datafiles.chinhphu.vn/cpp/files/vbpq/2025/6/{number}-nq.signed.pdf",
            "path": f"resolutions/ward-2025/{number}-nq-ubtvqh15.pdf",
            "media_type": "pdf",
        }],
        "secondary_urls": secondary_urls,
    }


def discover_instrument(record: dict, *, search: PortalSearch,
                        secondary_urls: list[str] | None = None) -> dict:
    if _is_reused_2025(record):
        return _reused_registry_entry(record, secondary_urls or [])
    try:
        exact_results = search.search(record["code"])
        candidates = [
            {**candidate, "code_match_status": "exact"}
            for candidate in exact_results
            if candidate["code"] == record["code"]
        ]
        if not candidates:
            fallback_results = []
            for title in record["title_variants"]:
                fallback_results.extend(search.search(record["code"], query=title[:90]))
            unique_fallback = {
                candidate["metadata_url"]: candidate for candidate in fallback_results
            }
            for candidate in unique_fallback.values():
                similarity = _title_similarity(record["title_variants"], candidate["title"])
                issued = date.fromisoformat(candidate["issued_date"])
                effective = date.fromisoformat(record["effective_date"])
                delta = (effective - issued).days
                if similarity >= 0.85 and 0 <= delta <= 730:
                    candidates.append({
                        **candidate,
                        "code_match_status": (
                            "exact" if candidate["code"] == record["code"]
                            else "official_code_differs"
                        ),
                    })
        ranked = []
        for candidate in candidates:
            if not candidate["attachment_urls"]:
                continue
            try:
                similarity = _validate_candidate(
                    record,
                    candidate,
                    allow_code_mismatch=(
                        candidate["code_match_status"] == "official_code_differs"
                    ),
                )
            except ValueError:
                continue
            delta = (
                date.fromisoformat(record["effective_date"])
                - date.fromisoformat(candidate["issued_date"])
            ).days
            ranked.append((-similarity, delta, candidate["metadata_url"], candidate))
        if not ranked:
            return {
                **record,
                "discovery_status": "official_not_found",
                "metadata_url": "",
                "metadata_path": metadata_relpath(record["code"], record["effective_date"]),
                "attachments": [],
                "secondary_urls": secondary_urls or [],
            }
        candidate = sorted(ranked)[0][-1]
        _require_official_url(candidate["metadata_url"])
        for url in candidate["attachment_urls"]:
            _require_official_url(url)
        paths = attachment_relpaths(
            record["code"], record["effective_date"], candidate["attachment_urls"],
        )
        effective_gap_days = (
            date.fromisoformat(record["effective_date"])
            - date.fromisoformat(candidate["issued_date"])
        ).days
        return {
            **record,
            "discovery_status": "verified_official_match",
            "official_code": candidate["code"],
            "code_match_status": candidate["code_match_status"],
            "issued_date": candidate["issued_date"],
            "effective_gap_days": effective_gap_days,
            "date_match_status": (
                "plausible_effective_lag"
                if effective_gap_days <= 366
                else "index_date_anomaly"
            ),
            "metadata_url": candidate["metadata_url"],
            "metadata_path": metadata_relpath(record["code"], record["effective_date"]),
            "attachments": [
                {"url": url, "path": path, "media_type": _attachment_extension(url)}
                for url, path in zip(candidate["attachment_urls"], paths, strict=True)
            ],
            "secondary_urls": secondary_urls or [],
        }
    except (requests.RequestException, ValueError) as exc:
        return {
            **record,
            "discovery_status": "discovery_error",
            "metadata_url": "",
            "metadata_path": metadata_relpath(record["code"], record["effective_date"]),
            "attachments": [],
            "secondary_urls": secondary_urls or [],
            "error_type": type(exc).__name__,
        }


def _gazette_attachment_relpaths(code: str, effective_date: str,
                                 count: int) -> list[str]:
    base = cache_base(code, effective_date)
    if count == 1:
        return [f"{base}.gazette.pdf"]
    return [f"{base}.gazette-{index:02d}.pdf" for index in range(1, count + 1)]


def _same_instrument_number(left: str, right: str) -> bool:
    left_match = re.match(r"^(\d+)", normalize_code(left))
    right_match = re.match(r"^(\d+)", normalize_code(right))
    return bool(
        left_match and right_match and left_match.group(1) == right_match.group(1)
    )


def discover_gazette_instrument(record: dict, *, search: GazetteSearch,
                                secondary_urls: list[str] | None = None) -> dict | None:
    """Return a verified Gazette replacement, or ``None`` when none qualifies."""
    try:
        ranked = []
        for candidate in search.search(record):
            code_match_status = (
                "exact" if candidate["code"] == record["code"]
                else "official_code_differs"
            )
            similarity = _title_similarity(record["title_variants"], candidate["title"])
            if code_match_status == "official_code_differs" and (
                similarity < 0.85
                or not _same_instrument_number(record["code"], candidate["code"])
            ):
                continue
            try:
                similarity = _validate_candidate(
                    record,
                    candidate,
                    allow_code_mismatch=(code_match_status == "official_code_differs"),
                )
            except ValueError:
                continue
            issued = date.fromisoformat(candidate["issued_date"])
            effective = date.fromisoformat(record["effective_date"])
            ranked.append((
                code_match_status != "exact",
                -similarity,
                (effective - issued).days,
                candidate["metadata_url"],
                code_match_status,
                candidate,
            ))
        if not ranked:
            return None
        *_, code_match_status, candidate = sorted(ranked)[0]
        _require_official_url(candidate["metadata_url"])
        for url in candidate["attachment_urls"]:
            _require_official_url(url)
        paths = _gazette_attachment_relpaths(
            record["code"], record["effective_date"], len(candidate["attachment_urls"]),
        )
        effective_gap_days = (
            date.fromisoformat(record["effective_date"])
            - date.fromisoformat(candidate["issued_date"])
        ).days
        return {
            **record,
            "discovery_status": "verified_official_match",
            "source_provider": "government_gazette",
            "gazette_record_id": candidate["gazette_record_id"],
            "official_code": candidate["code"],
            "code_match_status": code_match_status,
            "issued_date": candidate["issued_date"],
            "effective_gap_days": effective_gap_days,
            "date_match_status": (
                "plausible_effective_lag"
                if effective_gap_days <= 366
                else "index_date_anomaly"
            ),
            "metadata_url": candidate["metadata_url"],
            "metadata_path": metadata_relpath(record["code"], record["effective_date"]),
            "attachments": [
                {"url": url, "path": path, "media_type": "pdf"}
                for url, path in zip(candidate["attachment_urls"], paths, strict=True)
            ],
            "secondary_urls": secondary_urls or [],
        }
    except (requests.RequestException, ValueError):
        return None


def discover_registry(*, workers: int = 4, timeout: int = 120,
                      records: list[dict] | None = None) -> dict:
    instruments = records or _instrument_records()
    secondary = _secondary_url_map()
    local = threading.local()

    def discover(record):
        if not hasattr(local, "search"):
            local.search = PortalSearch(timeout=timeout)
        return discover_instrument(
            record,
            search=local.search,
            secondary_urls=secondary.get(record["code"], []),
        )

    results = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(discover, record): record for record in instruments}
        for completed, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            print(
                f"  {completed:>3}/{len(instruments)} "
                f"{result['discovery_status']:<29} {result['instrument_id']}"
            )
    results.sort(key=lambda item: (item["effective_date"], item["code"]))
    return {
        "schema_version": 1,
        "source_hierarchy": [
            "official_attachment",
            "official_metadata",
            "secondary_thuvienphapluat",
        ],
        "instruments": results,
        "summary": _registry_summary(results),
    }


def retry_registry(*, path: Path = REGISTRY, workers: int = 2,
                   timeout: int = 120) -> dict:
    """Retry only unresolved discovery rows and retain already verified work."""
    registry = json.loads(path.read_text(encoding="utf-8"))
    unresolved = [
        item for item in registry["instruments"]
        if item["discovery_status"] not in {
            "reused_existing_2025_pair", "verified_official_match",
        }
    ]
    local = threading.local()

    def retry(item):
        if not hasattr(local, "search"):
            local.search = PortalSearch(timeout=timeout)
        record = {
            key: item[key]
            for key in ("instrument_id", "code", "effective_date", "title_variants")
        }
        return discover_instrument(
            record,
            search=local.search,
            secondary_urls=item.get("secondary_urls", []),
        )

    replacements = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(retry, item): item for item in unresolved}
        for completed, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            replacements[result["instrument_id"]] = result
            print(
                f"  {completed:>3}/{len(unresolved)} "
                f"{result['discovery_status']:<29} {result['instrument_id']}"
            )
    instruments = [
        replacements.get(item["instrument_id"], item)
        for item in registry["instruments"]
    ]
    registry["instruments"] = instruments
    registry["summary"] = _registry_summary(instruments)
    write_registry(registry, path)
    return registry


def recover_registry_from_gazette(*, path: Path = REGISTRY, workers: int = 4,
                                  timeout: int = 120) -> dict:
    """Search unresolved rows in the official Gazette and retain validated hits."""
    registry = json.loads(path.read_text(encoding="utf-8"))
    instruments = []
    for item in registry["instruments"]:
        if (
            item.get("source_provider") == "government_gazette"
            and item.get("code_match_status") == "official_code_differs"
            and not _same_instrument_number(item["code"], item["official_code"])
        ):
            item = {
                key: item[key]
                for key in ("instrument_id", "code", "effective_date", "title_variants")
            } | {
                "discovery_status": "official_not_found",
                "metadata_url": "",
                "metadata_path": metadata_relpath(item["code"], item["effective_date"]),
                "attachments": [],
                "secondary_urls": item.get("secondary_urls", []),
            }
        instruments.append(item)
    registry["instruments"] = instruments
    unresolved = [
        item for item in registry["instruments"]
        if item["discovery_status"] == "official_not_found"
    ]
    local = threading.local()

    def recover(item):
        if not hasattr(local, "search"):
            local.search = GazetteSearch(timeout=timeout)
        record = {
            key: item[key]
            for key in ("instrument_id", "code", "effective_date", "title_variants")
        }
        result = discover_gazette_instrument(
            record,
            search=local.search,
            secondary_urls=item.get("secondary_urls", []),
        )
        return item, result

    replacements = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(recover, item): item for item in unresolved}
        for completed, future in enumerate(as_completed(futures), start=1):
            original, result = future.result()
            if result is not None:
                replacements[result["instrument_id"]] = result
            print(
                f"  {completed:>3}/{len(unresolved)} "
                f"{'verified_gazette_match' if result else 'gazette_not_found':<29} "
                f"{original['instrument_id']}"
            )
    instruments = [
        replacements.get(item["instrument_id"], item)
        for item in registry["instruments"]
    ]
    registry["instruments"] = instruments
    registry["summary"] = _registry_summary(instruments)
    write_registry(registry, path)
    return registry


def _registry_summary(instruments: list[dict]) -> dict:
    statuses: dict[str, int] = {}
    for item in instruments:
        statuses[item["discovery_status"]] = statuses.get(item["discovery_status"], 0) + 1
    return {
        "instruments": len(instruments),
        "status_counts": dict(sorted(statuses.items())),
        "official_matches": sum(
            item["discovery_status"] in {
                "reused_existing_2025_pair", "verified_official_match",
            }
            for item in instruments
        ),
        "official_attachments": sum(len(item["attachments"]) for item in instruments),
        "preserved_artifacts": sum(
            1 + len(item["attachments"])
            for item in instruments
            if item["discovery_status"] in {
                "reused_existing_2025_pair", "verified_official_match",
            }
        ),
        "official_code_differences": sum(
            item.get("code_match_status") == "official_code_differs"
            for item in instruments
        ),
        "index_date_anomalies": sum(
            item.get("date_match_status") == "index_date_anomaly"
            for item in instruments
        ),
        "secondary_tvpl_urls": sum(len(item["secondary_urls"]) for item in instruments),
    }


def normalize_registry_metadata(registry: dict) -> dict:
    """Fill validation metadata for rows discovered by older resumable passes."""
    secondary = _secondary_url_map()
    for item in registry["instruments"]:
        item["secondary_urls"] = sorted(set(
            item.get("secondary_urls", []) + secondary.get(item["code"], [])
        ))
        if item["discovery_status"] not in {
                "reused_existing_2025_pair", "verified_official_match"}:
            continue
        item.setdefault("official_code", item["code"])
        item.setdefault("code_match_status", "exact")
        gap = (
            date.fromisoformat(item["effective_date"])
            - date.fromisoformat(item["issued_date"])
        ).days
        item.setdefault("effective_gap_days", gap)
        item.setdefault(
            "date_match_status",
            "plausible_effective_lag" if gap <= 366 else "index_date_anomaly",
        )
    registry["summary"] = _registry_summary(registry["instruments"])
    registry["input_fingerprints"] = _input_fingerprints()
    return registry


def serialize_registry(registry: dict) -> str:
    return json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_registry(registry: dict, path: Path = REGISTRY) -> None:
    registry = normalize_registry_metadata(registry)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(serialize_registry(registry), encoding="utf-8")
    temporary.replace(path)


def _validate_attachment(content: bytes, media_type: str, label: str) -> str:
    if len(content) < 100:
        raise ValueError(f"official attachment is unexpectedly short: {label}")
    if content.startswith(b"%PDF-"):
        detected = "pdf"
    elif content.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        detected = "doc"
    elif content.startswith(b"{\\rtf"):
        detected = "rtf"
    elif content.startswith(b"PK\x03\x04"):
        detected = "zip"
    elif content.lstrip().lower().startswith((b"<html", b"<!doctype html")):
        _decode_html(content, label)
        detected = "html"
    else:
        detected = "unknown"

    accepted = {
        "doc": {"doc", "html", "rtf"},
        "docx": {"zip"},
        "pdf": {"pdf"},
        "rtf": {"doc", "rtf"},
        "zip": {"zip"},
    }
    if media_type in accepted and detected not in accepted[media_type]:
        raise ValueError(f"official attachment signature is not {media_type}: {label}")
    if media_type in {"html", "htm"}:
        _decode_html(content, label)
        detected = "html"
    return detected


def _get(session, url: str, *, timeout: int):
    _require_official_url(url)
    last_error = None
    for attempt in range(1, 4):
        try:
            response = session.get(url, timeout=timeout)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(attempt)
    assert last_error is not None
    raise last_error


def fetch_registry(*, registry_path: Path = REGISTRY, timeout: int = 120,
                   session=None) -> list[dict]:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    session = session or requests.Session()
    results = []
    for item in registry["instruments"]:
        if item["discovery_status"] == "reused_existing_2025_pair":
            paths = [item["metadata_path"], *[a["path"] for a in item["attachments"]]]
            if not all(rawcache.raw_is_verified(path) for path in paths):
                raise ValueError(f"reused 2025 source pair failed verification: {item['instrument_id']}")
            results.append({"instrument_id": item["instrument_id"], "status": "reused"})
            continue
        if item["discovery_status"] != "verified_official_match":
            results.append({"instrument_id": item["instrument_id"], "status": "unresolved"})
            continue

        metadata_status = "cached"
        if not rawcache.raw_is_verified(item["metadata_path"]):
            response = _get(session, item["metadata_url"], timeout=timeout)
            is_gazette = item.get("source_provider") == "government_gazette"
            detail = (
                parse_gazette_detail(response.content, item["metadata_url"])
                if is_gazette
                else parse_official_detail(response.content, item["metadata_url"])
            )
            candidate = {**detail, "metadata_url": item["metadata_url"]}
            validation_item = {**item, "code": item.get("official_code", item["code"])}
            _validate_candidate(validation_item, candidate)
            expected_urls = [attachment["url"] for attachment in item["attachments"]]
            if detail["attachment_urls"] != expected_urls:
                raise ValueError(
                    f"official attachments drifted for {item['instrument_id']}: "
                    f"expected {expected_urls}, got {detail['attachment_urls']}"
                )
            rawcache.save_raw(item["metadata_path"], response.content, {
                "source_url": item["metadata_url"],
                "source_class": "official",
                "source_role": "legal_metadata",
                "method": (
                    "official Government Gazette metadata HTML"
                    if is_gazette
                    else "official Government legal metadata HTML"
                ),
                "source_provider": item.get("source_provider", "government_legal_portal"),
                "document_code": item["code"],
                "official_document_code": item.get("official_code", item["code"]),
                "issued_date": item["issued_date"],
                "effective_date": item["effective_date"],
                "title": item["title_variants"][0],
                "attachment_urls": expected_urls,
                "secondary_urls": item["secondary_urls"],
            })
            metadata_status = "fetched"

        attachment_statuses = []
        for attachment in item["attachments"]:
            if rawcache.raw_is_verified(attachment["path"]):
                attachment_statuses.append("cached")
                continue
            response = _get(session, attachment["url"], timeout=timeout)
            detected_media_type = _validate_attachment(
                response.content, attachment["media_type"], attachment["url"],
            )
            rawcache.save_raw(attachment["path"], response.content, {
                "source_url": attachment["url"],
                "source_class": "official",
                "source_role": "legal_original_attachment",
                "method": (
                    "official Government Gazette publication PDF"
                    if item.get("source_provider") == "government_gazette"
                    else "official Government legal original attachment"
                ),
                "source_provider": item.get("source_provider", "government_legal_portal"),
                "document_code": item["code"],
                "official_document_code": item.get("official_code", item["code"]),
                "issued_date": item["issued_date"],
                "effective_date": item["effective_date"],
                "title": item["title_variants"][0],
                "metadata_path": item["metadata_path"],
                "metadata_url": item["metadata_url"],
                "secondary_urls": item["secondary_urls"],
                "declared_media_type": attachment["media_type"],
                "detected_media_type": detected_media_type,
            })
            attachment_statuses.append("fetched")
        results.append({
            "instrument_id": item["instrument_id"],
            "status": "verified",
            "metadata_status": metadata_status,
            "attachment_statuses": attachment_statuses,
        })
        print(
            f"  {item['instrument_id']}: metadata {metadata_status}, "
            f"attachments {','.join(attachment_statuses) or 'none'}"
        )
    return results


def fetch_supplemental_sources(*, overrides_path: Path = LEGAL_LINKAGE_OVERRIDES,
                               timeout: int = 120, session=None) -> list[dict]:
    """Archive official artifacts for canonical instruments absent from the index."""
    overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
    session = session or requests.Session()
    results = []
    for item in overrides["supplemental_instruments"]:
        source_url = item.get("source_url")
        source_path = item.get("source_path") or (
            f"{cache_base(item['code'], item['effective_date'])}.supplemental.doc"
        )
        if not source_url:
            continue
        if rawcache.raw_is_verified(source_path):
            results.append({"instrument_id": item["instrument_id"], "status": "cached"})
            continue
        response = _get(session, source_url, timeout=timeout)
        detected_media_type = _validate_attachment(response.content, "doc", source_url)
        rawcache.save_raw(source_path, response.content, {
            "source_url": source_url,
            "source_class": "official",
            "source_role": "legal_original_attachment",
            "method": "official provincial government legal original attachment",
            "source_provider": "dong_nai_provincial_legal_portal",
            "document_code": item["code"],
            "official_document_code": item["code"],
            "issued_date": item["issued_date"],
            "effective_date": item["effective_date"],
            "title": item["title"],
            "declared_media_type": "doc",
            "detected_media_type": detected_media_type,
        })
        results.append({"instrument_id": item["instrument_id"], "status": "fetched"})
        print(f"  {item['instrument_id']}: supplemental artifact fetched")
    return results


def check_registry(path: Path = REGISTRY) -> dict:
    registry = json.loads(path.read_text(encoding="utf-8"))
    instruments = registry.get("instruments", [])
    if len(instruments) != EXPECTED_INSTRUMENTS:
        raise ValueError(
            f"legal registry denominator drifted: expected {EXPECTED_INSTRUMENTS}, "
            f"got {len(instruments)}"
        )
    if registry.get("summary") != _registry_summary(instruments):
        raise ValueError("legal registry summary is stale")
    if registry.get("input_fingerprints") != _input_fingerprints():
        raise ValueError("legal registry input fingerprints are stale")
    unexpected_statuses = sorted({
        item["discovery_status"] for item in instruments
    } - {
        "official_not_found", "reused_existing_2025_pair", "verified_official_match",
    })
    if unexpected_statuses:
        raise ValueError(f"legal registry contains unresolved errors: {unexpected_statuses}")
    expected_ids = {record["instrument_id"] for record in _instrument_records()}
    actual_ids = {item["instrument_id"] for item in instruments}
    if actual_ids != expected_ids or len(actual_ids) != len(instruments):
        raise ValueError("legal registry instrument IDs do not match the pinned legal index")
    reused = [item for item in instruments if item["discovery_status"] == "reused_existing_2025_pair"]
    if len(reused) != EXPECTED_REUSED_2025:
        raise ValueError(
            f"reused 2025 pair count drifted: expected {EXPECTED_REUSED_2025}, got {len(reused)}"
        )
    failures = []
    for item in instruments:
        for url in item.get("secondary_urls", []):
            parsed = urlparse(url)
            if parsed.scheme != "https" or not (
                    (parsed.hostname or "").lower() == "thuvienphapluat.vn"
                    or (parsed.hostname or "").lower().endswith(".thuvienphapluat.vn")):
                raise ValueError(f"invalid secondary legal URL: {url}")
        if item["discovery_status"] not in {
                "reused_existing_2025_pair", "verified_official_match"}:
            if item["attachments"] or item["metadata_url"]:
                raise ValueError(
                    f"unresolved legal row has accepted official sources: {item['instrument_id']}"
                )
            continue
        required = {
            "official_code", "code_match_status", "issued_date",
            "effective_gap_days", "date_match_status",
        }
        missing = sorted(required - item.keys())
        if missing:
            raise ValueError(
                f"verified legal row is missing validation metadata: "
                f"{item['instrument_id']} {missing}"
            )
        gap = (
            date.fromisoformat(item["effective_date"])
            - date.fromisoformat(item["issued_date"])
        ).days
        expected_date_status = (
            "plausible_effective_lag" if gap <= 366 else "index_date_anomaly"
        )
        if (
            item["effective_gap_days"] != gap
            or item["date_match_status"] != expected_date_status
            or gap < 0
            or gap > 730
            or not item["attachments"]
        ):
            raise ValueError(f"verified legal metadata is inconsistent: {item['instrument_id']}")
        code_status_is_valid = (
            item["code_match_status"] == "exact"
            and item["official_code"] == item["code"]
        ) or (
            item["code_match_status"] == "official_code_differs"
            and item["official_code"] != item["code"]
        )
        if not code_status_is_valid:
            raise ValueError(f"verified legal code metadata is inconsistent: {item['instrument_id']}")
        if item["discovery_status"] == "verified_official_match":
            _require_official_url(item["metadata_url"])
        for attachment in item["attachments"]:
            _require_official_url(attachment["url"])
        paths = [item["metadata_path"], *[a["path"] for a in item["attachments"]]]
        failures.extend(path for path in paths if not rawcache.raw_is_verified(path))
    if failures:
        raise ValueError(f"official legal artifacts failed verification: {failures}")
    return registry["summary"]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Preserve historical ward legal sources.")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--discover", action="store_true")
    actions.add_argument("--gazette-recover", action="store_true")
    actions.add_argument("--fetch-supplemental", action="store_true")
    actions.add_argument("--retry", action="store_true")
    actions.add_argument("--fetch", action="store_true")
    actions.add_argument("--check", action="store_true")
    actions.add_argument("--normalize", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    args = parser.parse_args(argv)

    if args.discover:
        registry = discover_registry(workers=args.workers, timeout=args.timeout)
        write_registry(registry, args.registry)
        print(f"wrote {args.registry}: {registry['summary']}")
    elif args.gazette_recover:
        registry = recover_registry_from_gazette(
            path=args.registry, workers=args.workers, timeout=args.timeout,
        )
        print(f"updated {args.registry}: {registry['summary']}")
    elif args.fetch_supplemental:
        results = fetch_supplemental_sources(timeout=args.timeout)
        counts = {
            status: sum(row["status"] == status for row in results)
            for status in sorted({row["status"] for row in results})
        }
        print(f"supplemental fetch complete: {counts}")
    elif args.retry:
        registry = retry_registry(
            path=args.registry, workers=args.workers, timeout=args.timeout,
        )
        print(f"updated {args.registry}: {registry['summary']}")
    elif args.fetch:
        results = fetch_registry(registry_path=args.registry, timeout=args.timeout)
        counts = {
            status: sum(row["status"] == status for row in results)
            for status in sorted({row["status"] for row in results})
        }
        print(f"fetch complete: {counts}")
    elif args.normalize:
        registry = normalize_registry_metadata(
            json.loads(args.registry.read_text(encoding="utf-8"))
        )
        write_registry(registry, args.registry)
        print(f"normalized {args.registry}: {registry['summary']}")
    else:
        summary = check_registry(args.registry)
        print(f"verified {args.registry}: {summary}")


if __name__ == "__main__":
    main()
