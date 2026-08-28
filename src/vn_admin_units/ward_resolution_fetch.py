"""Preserve the official 2025 provincial ward-arrangement resolutions.

The 34 instruments numbered 1654–1687/NQ-UBTVQH15 cover the provinces/cities
that arranged commune-level units for the 2025 two-tier reform. The official
signed PDFs are the authoritative artifacts, while the Government Newspaper's
matching full-text HTML pages provide a machine-readable transcription.
"""
from __future__ import annotations

import argparse
import json
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from lxml import html

from vn_admin_units import rawcache


LEGAL_INDEX = Path("data/raw/nghidinh.json")
PDF_URL_TEMPLATE = "https://datafiles.chinhphu.vn/cpp/files/vbpq/2025/6/{number}-nq.signed.pdf"
PDF_PATH_TEMPLATE = "resolutions/ward-2025/{number}-nq-ubtvqh15.pdf"
ARTICLE_ROOT = "https://xaydungchinhsach.chinhphu.vn"
SEARCH_URL = f"{ARTICLE_ROOT}/tim-kiem.htm"
HTML_PATH_TEMPLATE = "resolutions/ward-2025/{number}-nq-ubtvqh15.html"


def resolution_records(path: Path = LEGAL_INDEX) -> list[dict]:
    records = json.loads(path.read_text(encoding="utf-8"))
    selected = []
    for record in records:
        match = re.fullmatch(r"(\d+)/NQ-UBTVQH15", str(record.get("code", "")))
        if match and 1654 <= int(match.group(1)) <= 1687:
            selected.append({**record, "number": int(match.group(1))})
    selected.sort(key=lambda record: record["number"])
    if [record["number"] for record in selected] != list(range(1654, 1688)):
        raise ValueError("legal index does not contain the complete 1654–1687 resolution run")
    return selected


def pdf_cache_relpath(number: int) -> str:
    return PDF_PATH_TEMPLATE.format(number=number)


def html_cache_relpath(number: int) -> str:
    return HTML_PATH_TEMPLATE.format(number=number)


def pdf_source_url(number: int) -> str:
    return PDF_URL_TEMPLATE.format(number=number)


def _decode_utf8(content: bytes, label: str) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} is not UTF-8") from exc


def _fold_text(value: str) -> str:
    value = unicodedata.normalize("NFD", value.casefold()).replace("đ", "d")
    value = "".join(char for char in value if unicodedata.category(char) != "Mn")
    return " ".join(value.split())


def _same_official_site(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.netloc == urlparse(ARTICLE_ROOT).netloc


def find_article_url(number: int, *, timeout: int = 120, session=requests) -> str:
    """Find the Government Newspaper's full-text page for one resolution."""
    code = f"{number}/NQ-UBTVQH15"
    response = session.get(SEARCH_URL, params={"keywords": code}, timeout=timeout)
    response.raise_for_status()
    document = html.fromstring(_decode_utf8(response.content, f"search response for {code}"))
    matches = []
    for anchor in document.xpath("//a[@href]"):
        label = " ".join(" ".join(anchor.itertext()).split())
        title = " ".join(str(anchor.get("title", "")).split())
        if code.casefold() not in f"{label} {title}".casefold():
            continue
        url = urljoin(ARTICLE_ROOT, anchor.get("href"))
        if _same_official_site(url):
            matches.append(url)
    matches = list(dict.fromkeys(matches))
    if not matches:
        raise ValueError(f"official search returned no full-text page for {code}")
    return matches[0]


def _validate_article(content: bytes, number: int) -> None:
    code = f"{number}/NQ-UBTVQH15"
    document = html.fromstring(_decode_utf8(content, f"full-text page for {code}"))
    bodies = document.xpath(
        '//div[contains(concat(" ", normalize-space(@class), " "), '
        '" detail-content ") and @data-role="content"]'
    )
    if len(bodies) != 1:
        raise ValueError(f"official full-text page for {code} has {len(bodies)} article bodies")
    page_text = _fold_text(" ".join(document.itertext()))
    body_text = _fold_text(" ".join(bodies[0].itertext()))
    missing = []
    if _fold_text(code) not in page_text:
        missing.append(code)
    missing.extend(value for value in ("dieu 1", "sap xep") if value not in body_text)
    if missing:
        raise ValueError(f"official full-text page for {code} is missing {missing}")


def _fetch_with_retries(fetch, *, number: int, kind: str, max_attempts: int,
                        sleeper=time.sleep):
    error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fetch()
        except Exception as exc:
            error = exc
            if attempt < max_attempts:
                sleeper(2 ** (attempt - 1))
    raise RuntimeError(
        f"failed to preserve resolution {number} {kind} after {max_attempts} attempts: {error}"
    ) from error


def fetch_resolutions(*, timeout: int = 120, max_attempts: int = 3,
                      sleeper=time.sleep, session=requests) -> list[dict]:
    results = []
    for record in resolution_records():
        number = record["number"]
        pdf_relpath = pdf_cache_relpath(number)
        html_relpath = html_cache_relpath(number)

        if rawcache.raw_is_verified(pdf_relpath):
            pdf_status = "cached"
            print(f"  VERIFIED {number} PDF:  {pdf_relpath}")
        else:
            def fetch_pdf():
                response = session.get(pdf_source_url(number), timeout=timeout)
                response.raise_for_status()
                if not response.content.startswith(b"%PDF-"):
                    raise ValueError(
                        f"official response is not a PDF ({len(response.content)} bytes)"
                    )
                return response.content

            content = _fetch_with_retries(
                fetch_pdf, number=number, kind="PDF", max_attempts=max_attempts,
                sleeper=sleeper,
            )
            rawcache.save_raw(pdf_relpath, content, {
                "source_url": pdf_source_url(number),
                "method": "official signed resolution PDF",
                "document_code": record["code"],
                "effective_date": record.get("hieu_luc", ""),
                "title": record.get("noi_dung", ""),
            })
            pdf_status = "fetched"
            print(f"  FETCHED  {number} PDF:  {len(content)} bytes")

        if rawcache.raw_is_verified(html_relpath):
            html_status = "cached"
            print(f"  VERIFIED {number} HTML: {html_relpath}")
        else:
            article_url = _fetch_with_retries(
                lambda: find_article_url(number, timeout=timeout, session=session),
                number=number,
                kind="article discovery",
                max_attempts=max_attempts,
                sleeper=sleeper,
            )

            def fetch_html():
                response = session.get(article_url, timeout=timeout)
                response.raise_for_status()
                _validate_article(response.content, number)
                return response.content

            content = _fetch_with_retries(
                fetch_html, number=number, kind="HTML", max_attempts=max_attempts,
                sleeper=sleeper,
            )
            rawcache.save_raw(html_relpath, content, {
                "source_url": article_url,
                "method": "official full-text resolution HTML",
                "document_code": record["code"],
                "effective_date": record.get("hieu_luc", ""),
                "title": record.get("noi_dung", ""),
                "signed_pdf_path": pdf_relpath,
                "signed_pdf_url": pdf_source_url(number),
            })
            html_status = "fetched"
            print(f"  FETCHED  {number} HTML: {len(content)} bytes")

        results.append({
            "number": number,
            "pdf_status": pdf_status,
            "html_status": html_status,
            "pdf_path": pdf_relpath,
            "html_path": html_relpath,
        })
    return results


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Cache official 2025 ward resolutions.")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--max-attempts", type=int, default=3)
    args = parser.parse_args(argv)
    results = fetch_resolutions(timeout=args.timeout, max_attempts=args.max_attempts)
    pdf_fetched = sum(row["pdf_status"] == "fetched" for row in results)
    html_fetched = sum(row["html_status"] == "fetched" for row in results)
    print(
        f"Done: {len(results)} resolution pairs verified "
        f"({pdf_fetched} PDFs and {html_fetched} HTML pages fetched)"
    )


if __name__ == "__main__":
    main()
