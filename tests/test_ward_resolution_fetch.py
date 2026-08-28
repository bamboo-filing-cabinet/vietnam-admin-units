import pytest

from vn_admin_units import rawcache
from vn_admin_units import ward_resolution_fetch as fetcher


class FakeResponse:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self):
        return None


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.responses.pop(0))


def _search_html(number=1656):
    return f"""
        <html><body>
          <a href="https://example.test/wrong">{number}/NQ-UBTVQH15</a>
          <a href="/toan-van-{number}.htm">Nghị quyết {number}/NQ-UBTVQH15</a>
        </body></html>
    """.encode()


def _article_html(number=1656):
    return f"""
        <html><body>
          <div class="detail-content article" data-role="content">
            Số: {number}/NQ-UBTVQH15
            <h4>Điều 1. Sắp xếp các đơn vị hành chính</h4>
          </div>
        </body></html>
    """.encode()


def test_find_article_url_uses_utf8_and_rejects_external_results():
    session = FakeSession([_search_html()])

    assert fetcher.find_article_url(1656, session=session) == (
        "https://xaydungchinhsach.chinhphu.vn/toan-van-1656.htm"
    )
    assert session.calls[0][1]["params"] == {"keywords": "1656/NQ-UBTVQH15"}


def test_validate_article_requires_one_matching_full_text_body():
    fetcher._validate_article(_article_html(), 1656)

    with pytest.raises(ValueError, match="article bodies"):
        fetcher._validate_article(b"<html><body>1656/NQ-UBTVQH15</body></html>", 1656)


def test_fetch_resolution_pair_is_offline_after_first_verified_cache(
        tmp_path, monkeypatch):
    monkeypatch.setattr(rawcache, "RAW", tmp_path)
    monkeypatch.setattr(rawcache, "MANIFEST", tmp_path / "manifest.jsonl")
    monkeypatch.setattr(fetcher, "resolution_records", lambda: [{
        "number": 1656,
        "code": "1656/NQ-UBTVQH15",
        "hieu_luc": "2025-06-16",
        "noi_dung": "Hà Nội",
    }])
    session = FakeSession([b"%PDF-1.7 signed", _search_html(), _article_html()])

    first = fetcher.fetch_resolutions(session=session, sleeper=lambda _: None)

    assert first[0]["pdf_status"] == "fetched"
    assert first[0]["html_status"] == "fetched"
    assert rawcache.raw_is_verified(fetcher.pdf_cache_relpath(1656))
    assert rawcache.raw_is_verified(fetcher.html_cache_relpath(1656))
    html_entry = rawcache.manifest_entry(fetcher.html_cache_relpath(1656))
    assert html_entry["document_code"] == "1656/NQ-UBTVQH15"
    assert html_entry["signed_pdf_path"] == fetcher.pdf_cache_relpath(1656)

    second = fetcher.fetch_resolutions(
        session=FakeSession([]), sleeper=lambda _: None,
    )
    assert second[0]["pdf_status"] == "cached"
    assert second[0]["html_status"] == "cached"


def test_real_legal_index_has_complete_resolution_run():
    assert [row["number"] for row in fetcher.resolution_records()] == list(range(1654, 1688))
