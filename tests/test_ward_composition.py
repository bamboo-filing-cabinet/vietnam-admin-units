from collections import defaultdict

import pytest

from vn_admin_units import rawcache
from vn_admin_units.ward_composition import (
    build_2025_compositions,
    write_2025_compositions,
)
from vn_admin_units.ward_model import build_2025_boundary


@pytest.fixture(scope="module")
def boundary():
    return build_2025_boundary()


@pytest.fixture(scope="module")
def artifact(boundary):
    return build_2025_compositions(boundary)


def _indexes(artifact):
    by_predecessor = defaultdict(set)
    by_successor = defaultdict(set)
    for edge in artifact["edges"]:
        by_predecessor[edge["predecessor_code"]].add(edge["successor_code"])
        by_successor[edge["successor_code"]].add(edge["predecessor_code"])
    return by_predecessor, by_successor


def test_real_composition_counts_and_sources_are_locked(artifact):
    assert artifact["lineage_completeness"] == "complete"
    assert artifact["audit"] == {
        "resolution_pairs": 34,
        "arrangement_clauses": 3194,
        "unchanged_successors": 127,
        "composition_edges": 10586,
        "resolved_predecessors": 10035,
        "unresolved_predecessors": 0,
        "successors_without_ward_predecessor": 5,
        "split_predecessors": 459,
        "whole_edges": 9576,
        "partial_edges": 1010,
        "curated_predecessors": 192,
        "curated_edges": 195,
        "ambiguous_mentions": 382,
        "missing_primary_clause_mentions": 98,
    }
    assert len(artifact["sources"]) == 72
    assert all(rawcache.raw_is_verified(source["path"]) for source in artifact["sources"])


def test_every_predecessor_and_primary_link_is_represented(artifact, boundary):
    by_predecessor, by_successor = _indexes(artifact)
    assert set(by_predecessor) == {
        row["code"] for row in boundary["observations"]["pre"]
    }
    assert all(
        row["predecessor_code"] in by_successor[row["successor_code"]]
        for row in boundary["structured_primary_links"]
    )
    creation_codes = {
        row["code"] for row in boundary["observations"]["post"]
    } - {
        row["successor_code"] for row in boundary["structured_primary_links"]
    }
    assert creation_codes == {
        "11948", "19742", "20333", "21548", "26732",
    }
    assert creation_codes.isdisjoint(by_successor)


def test_edge_shares_are_derived_from_predecessor_outdegree(artifact):
    by_predecessor, _ = _indexes(artifact)
    for edge in artifact["edges"]:
        expected = (
            "partial"
            if len(by_predecessor[edge["predecessor_code"]]) > 1
            else "whole"
        )
        assert edge["share"] == expected
        assert edge["evidence"]
    assert (
        artifact["audit"]["composition_edges"]
        - artifact["audit"]["resolved_predecessors"]
        == artifact["audit"]["partial_edges"]
        - artifact["audit"]["split_predecessors"]
    )


def test_known_whole_district_numeric_and_split_ground_truths(artifact):
    by_predecessor, by_successor = _indexes(artifact)
    assert len(by_successor["06994"]) == 12  # đặc khu Vân Đồn
    assert by_predecessor["00040"] == {"00004", "00070"}  # Đồng Xuân
    assert by_predecessor["06799"] == {"06799", "06886"}  # Hải Hòa
    assert by_predecessor["06886"] == {"06799", "06886", "06970"}  # Hải Lạng
    assert by_predecessor["10798"] == {"10804", "10843"}  # Hòa Bình
    assert by_predecessor["22228"] == {"22207", "22222"}  # EaBia
    assert "25462" in by_successor["25459"]  # Phường IV/Phường 4 → Tân Ninh


def test_result_names_and_legal_vocabulary_do_not_create_false_edges(artifact):
    by_predecessor, _ = _indexes(artifact)
    assert by_predecessor["04426"] == {"04441"}  # Yên Hợp, not “Yên, hợp nhất”
    assert by_predecessor["04825"] == {"04792"}  # old Hòa Bình, not result names
    assert by_predecessor["08014"] == {"07969"}  # Hợp Nhất, not the verb
    assert by_predecessor["10219"] == {"10237"}  # Tự Nhiên, not “diện tích tự nhiên”
    assert by_predecessor["27247"] == {"27238"}  # Phường 1, not “1 phần”


def test_write_composition_is_deterministic(tmp_path):
    path = tmp_path / "ward-composition.json"
    write_2025_compositions(path)
    first = path.read_bytes()
    write_2025_compositions(path)
    assert path.read_bytes() == first
