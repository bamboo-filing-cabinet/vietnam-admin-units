import io
import zipfile

from vn_admin_units.ward_reconcile_predecessors_geonames import (
    build_artifact,
    parse_geonames_dump,
)


def _archive(*rows):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("VN.txt", "\n".join(rows) + "\n")
    return output.getvalue()


def _record(*, admin2="249", admin3="08938"):
    return {
        "geonames_id": "8609096",
        "name": "Xã Trung Mỹ",
        "alternate_names": "Xa Trung My,Xã Trung Mỹ",
        "latitude": 21.38562,
        "longitude": 105.69132,
        "feature_class": "A",
        "feature_code": "ADM3",
        "country_code": "VN",
        "admin1_code": "25",
        "admin2_code": admin2,
        "admin3_code": admin3,
    }


def _inputs():
    history = {
        "entities": [
            {
                "local_id": "w-old",
                "gso_codes": ["1040603", "08938"],
                "name_vi": "Xã Trung Mỹ",
                "loai_hinh": "Xã",
                "province_echo_spans": [{"code": "26"}],
            },
            {
                "local_id": "w-new",
                "gso_codes": ["08944"],
                "name_vi": "Xã Bình Tuyền",
                "loai_hinh": "Xã",
                "province_echo_spans": [{"code": "25"}],
            },
        ],
        "lineage_edges": [{
            "predecessor": "w-old",
            "successor": "w-new",
            "effective_date": "2025-07-01",
        }],
    }
    article = {"action_api_verification": {"entities": [{
        "qid": "Q1",
        "geonames_ids": ["8609096"],
        "p625": [{"latitude": 21.385555555556, "longitude": 105.69138888889}],
    }]}}
    context = {"review": [{
        "local_id": "w-old",
        "terminal_code": "08938",
        "name_vi": "Xã Trung Mỹ",
        "loai_hinh": "Xã",
        "parent_code": "249",
        "parent_codes": ["249"],
        "same_name_successor": False,
        "verified_candidate_qids": ["Q1"],
        "auto_candidate_qids": [],
    }]}
    mapping = [{"local_id": "w-old", "wikidata_qid": ""}]
    return history, article, context, mapping


def test_geonames_dump_parser_preserves_zero_padded_gso_code():
    row = (
        "8609096\tXã Trung Mỹ\tXa Trung My\tXa Trung My,Xã Trung Mỹ\t"
        "21.38562\t105.69132\tA\tADM3\tVN\t\t25\t249\t08938\t"
    )

    parsed = parse_geonames_dump(_archive(row))["8609096"]

    assert parsed["admin2_code"] == "249"
    assert parsed["admin3_code"] == "08938"


def test_exact_geonames_gso_and_coordinate_evidence_recovers_candidate():
    history, article, context, mapping = _inputs()

    row = build_artifact(
        history, article, context, {"8609096": _record()}, mapping,
    )["review"][0]

    assert row["geonames_candidate_qids"] == ["Q1"]
    assert row["auto_candidate_qids"] == ["Q1"]
    assert row["classification"] == "verified-unique"


def test_wrong_geonames_parent_code_is_not_accepted():
    history, article, context, mapping = _inputs()

    row = build_artifact(
        history, article, context,
        {"8609096": _record(admin2="999")}, mapping,
    )["review"][0]

    assert row["geonames_candidate_qids"] == []
    assert row["classification"] == "no-exact-geonames-gso-code"


def test_missing_geonames_hierarchy_uses_unique_name_and_province():
    history, article, context, mapping = _inputs()
    record = _record(admin2="", admin3="8609096")
    record["admin1_code"] = "25"
    province_entities = [
        {"local_id": "p-old", "gso_codes": ["26"]},
        {"local_id": "p-new", "gso_codes": ["25"]},
    ]
    province_lineage = [{
        "predecessor": "p-old",
        "successor": "p-new",
        "effective_date": "2025-07-01",
    }]

    row = build_artifact(
        history, article, context, {"8609096": record}, mapping,
        province_entities=province_entities,
        province_lineage=province_lineage,
    )["review"][0]

    evidence = row["geonames_evidence"]["Q1"][0]
    assert row["auto_candidate_qids"] == ["Q1"]
    assert evidence["match_basis"] == (
        "unique-name-tier+province-code+missing-geonames-hierarchy"
    )
