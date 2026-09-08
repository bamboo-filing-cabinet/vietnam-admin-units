from vn_admin_units.ward_reconcile_predecessors_context import build_artifact


def _article(*entities, same_name_successor=False):
    return {
        "action_api_verification": {"entities": list(entities)},
        "review": [{
            "local_id": "w-old",
            "terminal_code": "00001",
            "name_vi": "Xã Hòa Bình",
            "loai_hinh": "Xã",
            "parent_code": "001",
            "parent_codes": ["001"],
            "parent_names_vi": ["Huyện Cũ"],
            "province_names_vi": ["Tỉnh Ví Dụ"],
            "successor_names_vi": [
                "Xã Hòa Bình" if same_name_successor else "Xã Mới"
            ],
            "successor_qids": ["Q9"],
            "same_name_successor": same_name_successor,
            "candidate_qids": [entity["qid"] for entity in entities],
            "auto_candidate_qids": [],
        }],
    }


def _entity(
    qid="Q1", *, name="Hòa Bình", description="", p131=None,
):
    return {
        "qid": qid,
        "missing": False,
        "labels": {"vi": name},
        "aliases": [],
        "descriptions": {"vi": description} if description else {},
        "p31": ["Q2389082"],
        "p131": p131 or [],
    }


def _mapping():
    return [
        {"local_id": "w-old", "wikidata_qid": ""},
        {"local_id": "w-new", "wikidata_qid": "Q9"},
    ]


def test_historical_parent_description_selects_one_exact_name_candidate():
    entity = _entity(description="xã cũ thuộc huyện Cũ")

    row = build_artifact(_article(entity), _mapping())["review"][0]

    assert row["context_support_flags"] == {
        "Q1": ["historical-parent-in-description"],
    }
    assert row["auto_candidate_qids"] == ["Q1"]


def test_successor_p131_is_accepted_as_explicit_context():
    entity = _entity(p131=["Q9"])

    row = build_artifact(_article(entity), _mapping())["review"][0]

    assert row["context_support_flags"] == {"Q1": ["successor-p131"]}
    assert row["auto_candidate_qids"] == ["Q1"]


def test_same_name_successor_blocks_context_only_assignment():
    entity = _entity(description="xã cũ thuộc huyện Cũ")

    row = build_artifact(
        _article(entity, same_name_successor=True), _mapping(),
    )["review"][0]

    assert row["auto_candidate_qids"] == []
    assert row["classification"] == "same-name-successor-risk"


def test_folded_homophone_is_not_an_exact_vietnamese_name():
    entity = _entity(name="Hoằng Bình", description="xã cũ thuộc huyện Cũ")

    row = build_artifact(_article(entity), _mapping())["review"][0]

    assert row["verified_candidate_qids"] == []
    assert row["classification"] == "no-exact-vietnamese-name-candidate"
