import json

import pytest

from vn_admin_units import rawcache
from vn_admin_units import ward_legal_fetch as fetcher


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


class FakeSearch:
    def __init__(self, candidate):
        self.candidate = candidate
        self.queries = []

    def search(self, code, query=None):
        self.queries.append((code, query))
        return [] if query is None else [self.candidate]


class FakeGazetteSearch:
    def __init__(self, candidates):
        self.candidates = candidates

    def search(self, record):
        return self.candidates


def _search_result_html():
    return """
      <table id="ctrl_191017_163_grvDocument">
        <tr><th>code</th><th>date</th><th>title</th></tr>
        <tr>
          <td><a href="/?pageid=27160&amp;docid=217876&amp;classid=2">
            <span class="code">237/NQ-UBTVQH16</span></a></td>
          <td><span class="issued-date">14/04/2026</span></td>
          <td><a href="/?pageid=27160&amp;docid=217876&amp;classid=2">
            <span class="substract">Về việc thành lập 10 phường thuộc tỉnh Đồng Nai</span></a>
            <div class="bl-doc-file"><a download
              href="https://datafiles.chinhphu.vn/cpp/files/vbpq/2026/4/nq-237.pdf">file</a></div>
          </td>
        </tr>
      </table>
    """.encode()


def _detail_html():
    return """
      <html><body><table>
        <tr><td class="col1">Số ký hiệu</td><td>237/NQ-UBTVQH16</td></tr>
        <tr><td class="col1">Ngày ban hành</td><td>14-04-2026</td></tr>
        <tr><td class="col1">Trích yếu</td>
          <td>Về việc thành lập 10 phường thuộc tỉnh Đồng Nai</td></tr>
        <tr><td class="col1">Tài liệu đính kèm</td><td>
          <a class="view-file" href="https://datafiles.chinhphu.vn/cpp/files/vbpq/2026/4/nq-237.pdf">nq-237.pdf</a>
        </td></tr>
      </table></body></html>
    """.encode()


def _curated_government_portal_html():
    return """
      <html><body><table>
        <tr><td>Số ký hiệu</td><td>39/NQ-CP</td></tr>
        <tr><td>Ngày ban hành</td><td>24-08-2009</td></tr>
        <tr><td>Trích yếu</td><td>Về việc điều chỉnh địa giới hành chính xã,
          thành lập thị trấn Cửa Tùng thuộc huyện Vĩnh Linh, tỉnh Quảng Trị</td></tr>
        <tr><td>Tài liệu đính kèm</td><td>
          <a class="view-file"
             href="https://datafiles.chinhphu.vn/cpp/files/vbpq/2009/08/93875_nq39cp2.doc">2</a>
          <a class="view-file"
             href="https://datafiles.chinhphu.vn/cpp/files/vbpq/2009/08/93874_nq39cp1.doc">1</a>
        </td></tr>
      </table>
      <div>Hà Nội, ngày 27 tháng 8 năm 2009</div>
      </body></html>
    """.encode()


def _provincial_archive_html():
    return """
      <html><body>
        <p>Năm 2015, phường Yên Bình được thành lập thuộc thị xã Tam Điệp,
          thị xã Tam Điệp lên thành phố Tam Điệp theo Nghị quyết số
          904/NQ-UBTVQH13 ngày 10/4/2015 của Ủy ban Thường vụ Quốc hội khóa XIII.</p>
        <p>
          <img src="https://luutru.ninhbinh.gov.vn/uploads/TamDiep/
            6-_NQ_904-NQ-UBTVQH13_(HSNT_2015_026_002)_Page1.png" />
          <img src="https://luutru.ninhbinh.gov.vn/uploads/TamDiep/
            6-2_NQ_904-NQ-UBTVQH13_(HSNT_2015_026_002)_Page2.png" />
        </p>
      </body></html>
    """.replace("/\n            ", "/").encode()


def _gazette_detail_html():
    return """
      <html><body>
        <div data-contentvanban="loadtep">
          <a data-href="https://congbaocdn.chinhphu.vn/CongBaoCP/1192.pdf">issue</a>
        </div>
        <div class="table">
          <div class="row"><span class="name">Số, ký hiệu</span>
            <div class="value"><span class="child-value">1192/NQ-UBTVQH15</span></div></div>
          <div class="row"><span class="name">Ngày ban hành</span>
            <div class="value"><span class="child-value">28/09/2024</span></div></div>
          <div class="row"><span class="name">Trích yếu</span>
            <div class="value"><span class="child-value">về việc sắp xếp đơn vị hành chính
              cấp xã của thành phố Cần Thơ giai đoạn 2023 - 2025.</span></div></div>
        </div>
      </body></html>
    """.encode()


def _national_assembly_full_text_html():
    return """
      <html><head>
        <meta name="description" content="Thay mặt Uỷ ban Thường vụ Quốc hội,
          ngày 13/02/2023, Chủ tịch Quốc hội đã ký ban hành Nghị quyết số
          728/NQ-UBTVQH15 về việc điều chỉnh địa giới đơn vị hành chính giữa
          xã Long Khánh và xã Ngũ Lạc thuộc huyện Duyên Hải, tỉnh Trà Vinh." />
      </head><body>
        <h1>NGHỊ QUYẾT SỐ 728/NQ-UBTVQH15 CỦA UBTVQH VỀ ĐIỀU CHỈNH ĐỊA GIỚI</h1>
        <div>Số: 728/NQ-UBTVQH15</div>
        <div>QUYẾT NGHỊ:</div>
        <div>Nghị quyết này có hiệu lực thi hành từ ngày 1 tháng 3 năm 2023.</div>
      </body></html>
    """.encode()


def _record():
    return {
        "instrument_id": "237/NQ-UBTVQH16@2026-04-30",
        "code": "237/NQ-UBTVQH16",
        "effective_date": "2026-04-30",
        "title_variants": ["Nghị quyết về việc thành lập 10 phường thuộc tỉnh Đồng Nai"],
    }


def test_paths_are_deterministic_from_code_and_effective_date():
    assert fetcher.code_slug("237/NQ-UBTVQH16") == "237-nq-ubtvqh16"
    assert fetcher.metadata_relpath("237/NQ-UBTVQH16", "30/04/2026") == (
        "legal/ward/2026-04-30/237-nq-ubtvqh16.metadata.html"
    )
    assert fetcher.attachment_relpaths(
        "237/NQ-UBTVQH16", "2026-04-30", ["https://official.test/nq-237.pdf"],
    ) == ["legal/ward/2026-04-30/237-nq-ubtvqh16.original.pdf"]


def test_search_and_detail_parsers_validate_the_2026_acceptance_case():
    assert fetcher.parse_search_results(_search_result_html()) == [{
        "code": "237/NQ-UBTVQH16",
        "issued_date": "2026-04-14",
        "title": "Về việc thành lập 10 phường thuộc tỉnh Đồng Nai",
        "metadata_url": "https://chinhphu.vn/?pageid=27160&docid=217876&classid=2",
        "attachment_urls": [
            "https://datafiles.chinhphu.vn/cpp/files/vbpq/2026/4/nq-237.pdf",
        ],
    }]
    detail = fetcher.parse_official_detail(
        _detail_html(),
        "https://chinhphu.vn/?pageid=27160&docid=217876&classid=2",
    )
    assert detail["code"] == "237/NQ-UBTVQH16"
    assert detail["issued_date"] == "2026-04-14"
    assert detail["attachment_urls"] == [
        "https://datafiles.chinhphu.vn/cpp/files/vbpq/2026/4/nq-237.pdf",
    ]
    assert fetcher._validate_candidate(_record(), detail) > 0.85


def test_curated_government_portal_recovery_preserves_index_and_rendered_date_anomalies(
        tmp_path, monkeypatch):
    instrument_id = "39/NQ-CP@2009-08-15"
    source_url = "https://chinhphu.vn/default.aspx?pageid=27160&docid=90252"
    item = {
        "instrument_id": instrument_id,
        "code": "39/NQ-CP",
        "effective_date": "2009-08-15",
        "title_variants": [
            "Điều chỉnh địa giới hành chính xã, thành lập thị trấn Cửa Tùng "
            "thuộc huyện Vĩnh Linh, tỉnh Quảng Trị"
        ],
        "discovery_status": "official_not_found",
        "metadata_url": "",
        "metadata_path": "legal/ward/2009-08-15/39-nq-cp.metadata.html",
        "attachments": [],
        "secondary_urls": [],
    }
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps({"instruments": [item]}), encoding="utf-8",
    )
    monkeypatch.setattr(fetcher, "CURATED_GOVERNMENT_LEGAL_PAGES", {
        instrument_id: {
            "source_url": source_url,
            "official_effective_date": "2009-08-24",
        },
    })

    detail = fetcher.parse_official_detail(
        _curated_government_portal_html(), source_url,
    )
    with pytest.raises(ValueError, match="dates are inconsistent"):
        fetcher._validate_candidate(item, detail)
    assert fetcher._validate_candidate(
        item, detail, allow_index_date_precedes_issue=True,
    ) > 0.85

    registry = fetcher.recover_registry_from_government_portal(
        path=registry_path,
        session=FakeSession([_curated_government_portal_html()]),
    )

    recovered = registry["instruments"][0]
    assert recovered["discovery_status"] == "verified_official_match"
    assert recovered["source_provider"] == "government_legal_portal"
    assert recovered["issued_date"] == "2009-08-24"
    assert recovered["official_effective_date"] == "2009-08-24"
    assert recovered["effective_gap_days"] == -9
    assert recovered["date_match_status"] == "index_date_precedes_official_issue"
    assert recovered["effective_date_match_status"] == "index_effective_date_differs"
    assert recovered["rendered_full_text_date"] == "2009-08-27"
    assert recovered["rendered_full_text_date_match_status"] == (
        "differs_from_official_issue_date"
    )
    assert len(recovered["attachments"]) == 2


def test_provincial_archive_recovery_preserves_complete_signed_scan(
        tmp_path, monkeypatch):
    monkeypatch.setattr(rawcache, "RAW", tmp_path / "raw")
    monkeypatch.setattr(rawcache, "MANIFEST", tmp_path / "raw" / "manifest.jsonl")
    instrument_id = "904/NQ-UBTVQH13@2015-04-11"
    source_url = (
        "https://luutru.ninhbinh.gov.vn/gioi-thieu-tai-lieu-luu-tru/"
        "lich-su-dia-gioi-hanh-chinh-thanh-pho-tam-diep-qua-tai-lieu-luu-tru-213.html"
    )
    item = {
        "instrument_id": instrument_id,
        "code": "904/NQ-UBTVQH13",
        "effective_date": "2015-04-11",
        "title_variants": [
            "thành lập phường Yên Bình thuộc thị xã Tam Điệp và thành lập "
            "thành phố Tam Điệp, tỉnh Ninh Bình"
        ],
        "discovery_status": "official_not_found",
        "metadata_url": "",
        "metadata_path": "legal/ward/2015-04-11/904-nq-ubtvqh13.metadata.html",
        "attachments": [],
        "secondary_urls": [],
    }
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps({"instruments": [item]}), encoding="utf-8",
    )
    source = {
        "source_url": source_url,
        "archive_id": "HSNT_2015_026_002",
        "official_effective_date": "2015-04-10",
    }
    monkeypatch.setattr(
        fetcher, "PROVINCIAL_HISTORICAL_ARCHIVE_PAGES", {instrument_id: source},
    )

    detail = fetcher.parse_provincial_historical_archive(
        _provincial_archive_html(),
        source_url,
        code=item["code"],
        archive_id=source["archive_id"],
    )
    assert detail["issued_date"] == "2015-04-10"
    assert detail["archive_id"] == "HSNT_2015_026_002"
    assert [url.rsplit("/", 1)[-1] for url in detail["attachment_urls"]] == [
        "6-_NQ_904-NQ-UBTVQH13_(HSNT_2015_026_002)_Page1.png",
        "6-2_NQ_904-NQ-UBTVQH13_(HSNT_2015_026_002)_Page2.png",
    ]
    assert fetcher._validate_candidate(item, detail) > 0.65

    registry = fetcher.recover_registry_from_provincial_archive(
        path=registry_path,
        session=FakeSession([_provincial_archive_html()]),
    )
    recovered = registry["instruments"][0]
    assert recovered["source_provider"] == "provincial_historical_archive"
    assert recovered["official_effective_date"] == "2015-04-10"
    assert recovered["effective_date_match_status"] == "index_effective_date_differs"
    assert recovered["effective_gap_days"] == 1
    assert recovered["date_match_status"] == "plausible_effective_lag"
    assert [row["media_type"] for row in recovered["attachments"]] == ["png", "png"]

    png = b"\x89PNG\r\n\x1a\n" + b"scan" * 30
    results = fetcher.fetch_registry(
        registry_path=registry_path,
        session=FakeSession([_provincial_archive_html(), png, png]),
    )
    assert results[0]["metadata_status"] == "fetched"
    assert results[0]["attachment_statuses"] == ["fetched", "fetched"]
    metadata_entry = rawcache.manifest_entry(recovered["metadata_path"])
    assert metadata_entry["source_role"] == "legal_archive_index"
    assert metadata_entry["archive_id"] == "HSNT_2015_026_002"
    scan_entry = rawcache.manifest_entry(recovered["attachments"][0]["path"])
    assert scan_entry["source_role"] == "legal_original_scan"
    assert scan_entry["detected_media_type"] == "png"


def test_gazette_parsers_retain_direct_publication_pdf_and_validate_metadata():
    payload = {
        "success": True,
        "data": [{
            "id_van_ban": 42858,
            "so_ky_hieu": "1192/NQ-UBTVQH15",
            "ngay_ban_hanh": "2024-09-28T00:00:00",
            "trich_yeu": "về việc sắp xếp đơn vị hành chính cấp xã của thành phố Cần Thơ",
            "loai_van_ban": "Nghị quyết",
            "danh_sach_tep_van_ban": [
                {
                    "duong_dan": "https://congbaocdn.chinhphu.vn/CongBaoCP/1192.pdf",
                    "file_extension": "pdf",
                },
                {
                    "duong_dan": "https://congbaocdn.chinhphu.vn/CongBaoCP/1192.doc",
                    "file_extension": "doc",
                },
            ],
        }],
    }
    assert fetcher.parse_gazette_results(payload) == [{
        "code": "1192/NQ-UBTVQH15",
        "issued_date": "2024-09-28",
        "title": "về việc sắp xếp đơn vị hành chính cấp xã của thành phố Cần Thơ",
        "metadata_url": (
            "https://congbao.chinhphu.vn/van-ban/"
            "nghi-quyet-so-1192-nq-ubtvqh15-42858.htm"
        ),
        "attachment_urls": [
            "https://congbaocdn.chinhphu.vn/CongBaoCP/1192.pdf",
        ],
        "gazette_record_id": 42858,
    }]
    detail = fetcher.parse_gazette_detail(
        _gazette_detail_html(), payload["data"][0]["danh_sach_tep_van_ban"][0]["duong_dan"],
    )
    assert detail["code"] == "1192/NQ-UBTVQH15"
    assert detail["issued_date"] == "2024-09-28"
    assert detail["attachment_urls"] == [
        "https://congbaocdn.chinhphu.vn/CongBaoCP/1192.pdf",
    ]


def test_national_assembly_parser_validates_full_text_and_effective_date():
    source_url = (
        "https://quochoi.vn/tintuc/Pages/"
        "tin-hoat-dong-cua-quoc-hoi.aspx?ItemID=73340"
    )
    detail = fetcher.parse_national_assembly_full_text(
        _national_assembly_full_text_html(), source_url,
    )
    assert detail == {
        "code": "728/NQ-UBTVQH15",
        "issued_date": "2023-02-13",
        "official_effective_date": "2023-03-01",
        "title": (
            "Về việc điều chỉnh địa giới đơn vị hành chính giữa xã Long Khánh "
            "và xã Ngũ Lạc thuộc huyện Duyên Hải, tỉnh Trà Vinh."
        ),
        "attachment_urls": [],
    }
    record = {
        "instrument_id": "728/NQ-UBTVQH15@2023-04-10",
        "code": "728/NQ-UBTVQH15",
        "effective_date": "2023-04-10",
        "title_variants": [
            "Nghị quyết về việc điều chỉnh địa giới đơn vị hành chính giữa xã "
            "Long Khánh và xã Ngũ Lạc thuộc huyện Duyên Hải, tỉnh Trà Vinh"
        ],
    }
    assert fetcher._validate_candidate(record, detail) > 0.9


def test_national_assembly_reload_cookie_is_extracted_strictly():
    challenge = (
        b'<script>document.cookie="D1N=ce11f8ea3e8479cff0198dc31f4fd711"+'
        b'"; expires=Fri, 31 Dec 2099 23:59:59 GMT; path=/";</script>'
    )
    assert fetcher._national_assembly_reload_cookie(challenge) == (
        "ce11f8ea3e8479cff0198dc31f4fd711"
    )
    assert fetcher._national_assembly_reload_cookie(b"<html>normal</html>") is None


def test_gazette_recovery_records_confirmed_index_code_correction():
    record = {
        "instrument_id": "1192/NQ-UBTVQH@2024-11-01",
        "code": "1192/NQ-UBTVQH",
        "effective_date": "2024-11-01",
        "title_variants": [
            "Nghị quyết về việc sắp xếp đơn vị hành chính cấp xã của thành phố "
            "Cần Thơ giai đoạn 2023-2025"
        ],
    }
    candidate = {
        "code": "1192/NQ-UBTVQH15",
        "issued_date": "2024-09-28",
        "title": (
            "về việc sắp xếp đơn vị hành chính cấp xã của thành phố Cần Thơ "
            "giai đoạn 2023 - 2025."
        ),
        "metadata_url": (
            "https://congbao.chinhphu.vn/van-ban/"
            "nghi-quyet-so-1192-nq-ubtvqh15-42858.htm"
        ),
        "attachment_urls": [
            "https://congbaocdn.chinhphu.vn/CongBaoCP/1192.pdf",
        ],
        "gazette_record_id": 42858,
    }
    recovered = fetcher.discover_gazette_instrument(
        record, search=FakeGazetteSearch([candidate]),
    )
    assert recovered["source_provider"] == "government_gazette"
    assert recovered["official_code"] == "1192/NQ-UBTVQH15"
    assert recovered["code_match_status"] == "official_code_differs"
    assert recovered["attachments"][0]["path"].endswith(".gazette.pdf")


def test_gazette_recovery_rejects_similar_boilerplate_with_different_number():
    record = {
        "instrument_id": "820/NQ-UBTVQH14@2020-01-01",
        "code": "820/NQ-UBTVQH14",
        "effective_date": "2020-01-01",
        "title_variants": [
            "Sắp xếp các đơn vị hành chính cấp xã thuộc tỉnh Bình Thuận"
        ],
    }
    candidate = {
        "code": "786/NQ-UBTVQH14",
        "issued_date": "2019-10-16",
        "title": "về việc sắp xếp các đơn vị hành chính cấp xã thuộc tỉnh Thanh Hóa.",
        "metadata_url": (
            "https://congbao.chinhphu.vn/van-ban/"
            "nghi-quyet-so-786-nq-ubtvqh14-30046.htm"
        ),
        "attachment_urls": [
            "https://congbaocdn.chinhphu.vn/CongBaoCP/786.pdf",
        ],
        "gazette_record_id": 30046,
    }
    recovered = fetcher.discover_gazette_instrument(
        record, search=FakeGazetteSearch([candidate]),
    )
    assert recovered is None


def test_attachment_validation_checks_real_file_signatures():
    assert fetcher._validate_attachment(
        b"%PDF-1.7" + b"x" * 100, "pdf", "signed.pdf",
    ) == "pdf"
    assert fetcher._validate_attachment(
        b"{\\rtf1" + b"x" * 100, "rtf", "original.rtf",
    ) == "rtf"
    assert fetcher._validate_attachment(
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"x" * 100,
        "rtf",
        "legacy-mislabeled.rtf",
    ) == "doc"
    assert fetcher._validate_attachment(
        b"\x89PNG\r\n\x1a\n" + b"x" * 100, "png", "official-scan.png",
    ) == "png"
    assert fetcher._validate_attachment(
        b'<html xmlns:w="urn:word"><body>' + b"x" * 100 + b"</body></html>",
        "doc",
        "word-html.doc",
    ) == "html"
    with pytest.raises(ValueError, match="signature"):
        fetcher._validate_attachment(b"<html>" + b"x" * 100, "pdf", "wrong.pdf")


def test_title_fallback_records_source_code_and_index_date_anomaly():
    record = {
        "instrument_id": "112/2002/NĐ-CP@2004-01-15",
        "code": "112/2002/NĐ-CP",
        "effective_date": "2004-01-15",
        "title_variants": [
            "Thành lập xã thuộc các huyện Lâm Hà, Đạ Huoai, Đạ Tẻ, "
            "Cát Tiên, tỉnh Lâm Đồng"
        ],
    }
    candidate = {
        "code": "112/2002/NĐ-CP",
        "issued_date": "2002-12-31",
        "title": record["title_variants"][0],
        "metadata_url": "https://chinhphu.vn/?pageid=27160&docid=12000",
        "attachment_urls": [
            "https://datafiles.chinhphu.vn/cpp/files/vbpq/2002/12/112.rtf"
        ],
    }
    search = FakeSearch(candidate)

    discovered = fetcher.discover_instrument(record, search=search)

    assert search.queries[0] == (record["code"], None)
    assert search.queries[1][1]
    assert discovered["discovery_status"] == "verified_official_match"
    assert discovered["official_code"] == candidate["code"]
    assert discovered["effective_gap_days"] == 380
    assert discovered["date_match_status"] == "index_date_anomaly"


def test_fetch_is_offline_after_verified_metadata_and_attachment(tmp_path, monkeypatch):
    monkeypatch.setattr(rawcache, "RAW", tmp_path / "raw")
    monkeypatch.setattr(rawcache, "MANIFEST", tmp_path / "raw" / "manifest.jsonl")
    registry_path = tmp_path / "registry.json"
    item = {
        **_record(),
        "discovery_status": "verified_official_match",
        "issued_date": "2026-04-14",
        "metadata_url": "https://chinhphu.vn/?pageid=27160&docid=217876&classid=2",
        "metadata_path": "legal/ward/2026-04-30/237-nq-ubtvqh16.metadata.html",
        "attachments": [{
            "url": "https://datafiles.chinhphu.vn/cpp/files/vbpq/2026/4/nq-237.pdf",
            "path": "legal/ward/2026-04-30/237-nq-ubtvqh16.original.pdf",
            "media_type": "pdf",
        }],
        "secondary_urls": ["https://thuvienphapluat.vn/van-ban/example.aspx"],
    }
    registry_path.write_text(json.dumps({"instruments": [item]}), encoding="utf-8")
    session = FakeSession([_detail_html(), b"%PDF-1.7" + b"signed" * 40])

    first = fetcher.fetch_registry(registry_path=registry_path, session=session)

    assert first[0]["status"] == "verified"
    assert first[0]["metadata_status"] == "fetched"
    assert first[0]["attachment_statuses"] == ["fetched"]
    assert rawcache.raw_is_verified(item["metadata_path"])
    assert rawcache.raw_is_verified(item["attachments"][0]["path"])
    metadata_entry = rawcache.manifest_entry(item["metadata_path"])
    assert metadata_entry["source_class"] == "official"
    assert metadata_entry["secondary_urls"] == item["secondary_urls"]

    second = fetcher.fetch_registry(
        registry_path=registry_path, session=FakeSession([]),
    )
    assert second[0]["metadata_status"] == "cached"
    assert second[0]["attachment_statuses"] == ["cached"]


def test_fetch_accepts_archived_national_assembly_full_text_without_attachment(
        tmp_path, monkeypatch):
    monkeypatch.setattr(rawcache, "RAW", tmp_path / "raw")
    monkeypatch.setattr(rawcache, "MANIFEST", tmp_path / "raw" / "manifest.jsonl")
    registry_path = tmp_path / "registry.json"
    item = {
        "instrument_id": "728/NQ-UBTVQH15@2023-04-10",
        "code": "728/NQ-UBTVQH15",
        "effective_date": "2023-04-10",
        "title_variants": [
            "Nghị quyết về việc điều chỉnh địa giới đơn vị hành chính giữa xã "
            "Long Khánh và xã Ngũ Lạc thuộc huyện Duyên Hải, tỉnh Trà Vinh"
        ],
        "discovery_status": "verified_official_match",
        "source_provider": "national_assembly_full_text",
        "issued_date": "2023-02-13",
        "official_effective_date": "2023-03-01",
        "effective_date_match_status": "index_effective_date_differs",
        "metadata_url": (
            "https://quochoi.vn/tintuc/Pages/"
            "tin-hoat-dong-cua-quoc-hoi.aspx?ItemID=73340"
        ),
        "metadata_path": (
            "legal/ward/2023-04-10/728-nq-ubtvqh15.fulltext.html"
        ),
        "attachments": [],
        "secondary_urls": [],
    }
    registry_path.write_text(json.dumps({"instruments": [item]}), encoding="utf-8")

    first = fetcher.fetch_registry(
        registry_path=registry_path,
        session=FakeSession([_national_assembly_full_text_html()]),
    )

    assert first[0]["metadata_status"] == "fetched"
    assert first[0]["attachment_statuses"] == []
    entry = rawcache.manifest_entry(item["metadata_path"])
    assert entry["source_role"] == "legal_full_text"
    assert entry["source_provider"] == "national_assembly_full_text"
    assert entry["official_effective_date"] == "2023-03-01"
    assert entry["effective_date_match_status"] == "index_effective_date_differs"

    second = fetcher.fetch_registry(
        registry_path=registry_path, session=FakeSession([]),
    )
    assert second[0]["metadata_status"] == "cached"


def test_supplemental_fetch_archives_canonical_official_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(rawcache, "RAW", tmp_path / "raw")
    monkeypatch.setattr(rawcache, "MANIFEST", tmp_path / "raw" / "manifest.jsonl")
    overrides_path = tmp_path / "overrides.json"
    item = {
        "instrument_id": "14/2008/QH12@2008-07-01",
        "code": "14/2008/QH12",
        "effective_date": "2008-07-01",
        "issued_date": "2008-05-29",
        "title": "Điều chỉnh địa giới hành chính giữa tỉnh Hà Tây và tỉnh Phú Thọ",
        "source_url": (
            "https://ttptquydat.stnmt.dongnai.gov.vn/VN/Vanbanphapquy/"
            "DownloadFile?fileName=14_2008_QH12.doc"
        ),
    }
    overrides_path.write_text(
        json.dumps({"supplemental_instruments": [item]}), encoding="utf-8",
    )
    session = FakeSession([b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"legal" * 40])

    result = fetcher.fetch_supplemental_sources(
        overrides_path=overrides_path, session=session,
    )

    path = "legal/ward/2008-07-01/14-2008-qh12.supplemental.doc"
    assert result == [{"instrument_id": item["instrument_id"], "status": "fetched"}]
    assert rawcache.raw_is_verified(path)
    assert rawcache.manifest_entry(path)["source_class"] == "official"


def test_real_legal_index_includes_2026_acceptance_and_reuses_34_pairs():
    records = fetcher._instrument_records()
    secondary = fetcher._secondary_url_map()
    assert len(records) == 449
    assert sum(fetcher._is_reused_2025(record) for record in records) == 34
    assert _record() in records
    assert secondary["1656/NQ-UBTVQH15"] == [
        "https://thuvienphapluat.vn/van-ban/EN/Bo-may-hanh-chinh/"
        "Resolution-1656-NQ-UBTVQH15-2025-the-arrangement-of-commune-level-"
        "administrative-divisions-of-Hanoi-city/662762/tieng-anh.aspx"
    ]
    assert set(fetcher.NATIONAL_ASSEMBLY_FULL_TEXT) == {
        f"{number}/NQ-UBTVQH15@2023-04-10"
        for number in (721, 722, 723, 724, 726, 727, 728, 729, 730)
    }
    assert fetcher.CURATED_GOVERNMENT_LEGAL_PAGES == {
        "39/NQ-CP@2009-08-15": {
            "source_url": (
                "https://chinhphu.vn/default.aspx?pageid=27160&docid=90252"
            ),
            "official_effective_date": "2009-08-24",
        },
    }
    assert fetcher.PROVINCIAL_HISTORICAL_ARCHIVE_PAGES == {
        "904/NQ-UBTVQH13@2015-04-11": {
            "source_url": (
                "https://luutru.ninhbinh.gov.vn/gioi-thieu-tai-lieu-luu-tru/"
                "lich-su-dia-gioi-hanh-chinh-thanh-pho-tam-diep-qua-tai-lieu-"
                "luu-tru-213.html"
            ),
            "archive_id": "HSNT_2015_026_002",
            "official_effective_date": "2015-04-10",
        },
    }
