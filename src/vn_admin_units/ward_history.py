"""Build the deterministic 2002-present canonical ward observation graph.

The builder consumes the already reviewed source ledger and never re-scrapes.
It treats a repeated national code as continuity only when the observed-change
and crosswalk artifacts support that interpretation. The 27 proven code-reuse
components mint new entities, and the 2025 two-tier reform always separates
pre- and post-reform entities even when a national code is inherited.

Historical additions and removals without a structured old-to-new pair remain
explicit topology residue. The complete 2025 legal composition is converted to
``core.LineageEdge`` records with its clause-level provenance intact.

Usage:
  uv run python -m vn_admin_units.ward_history
  uv run python -m vn_admin_units.ward_history --check --audit
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from vn_admin_units import rawcache
from vn_admin_units.core import Entity, LineageEdge
from vn_admin_units.soap import parse_rows
from vn_admin_units.ward_composition import bare_ward_name
from vn_admin_units.ward_model import WARD_FIELDS
from vn_admin_units.ward_observed_changes import normalize_snapshot_variants


SOURCE_FLOOR = "2002-01-01"
AS_OF = "2026-08-27"
REFORM_DATE = "2025-07-01"
REFORM_VALID_TO = "2025-06-30"

OBSERVED_CHANGES = Path("data/ward-observed-changes.json")
RECONCILIATION = Path("data/ward-crosswalk-reconciliation.json")
COVERAGE = Path("data/ward-source-coverage.json")
BOUNDARY_2025 = Path("data/ward-2025-boundary.json")
COMPOSITION_2025 = Path("data/ward-2025-composition.json")
OVERRIDES = Path("data/ward-history-overrides.json")
OUTPUT = Path("data/ward-history.json")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _minus_one_day(value: str) -> str:
    return (date.fromisoformat(value) - timedelta(days=1)).isoformat()


def ward_local_id(code: str, valid_from: str | None) -> str:
    return f"w-{code}-{valid_from or 'base'}"


def _source_observation(row: dict) -> dict:
    return {
        "province_code_echo": row["MaTinh"],
        "province_name_echo": row["TenTinh"],
        "district_code": row["MaQuanHuyen"],
        "district_name_vi": row["TenQuanHuyen"],
        "code": row["MaPhuongXa"],
        "name_vi": row["TenPhuongXa"],
        "loai_hinh": row["LoaiHinh"],
    }


def _boundary_observation(row: dict) -> dict:
    return {
        "province_code_echo": row["soap_province_code_echo"],
        "province_name_echo": row["soap_province_name_echo"],
        "district_code": row["parent_code"],
        "district_name_vi": row["parent_name_vi"],
        "code": row["code"],
        "name_vi": row["name_vi"],
        "loai_hinh": row["loai_hinh"],
    }


def _load_snapshot(relpath: str) -> tuple[dict[str, dict], set[str]]:
    if not rawcache.raw_is_verified(relpath):
        raise ValueError(f"ward snapshot is missing or unverified: {relpath}")
    rows = parse_rows(rawcache.read_raw(relpath).decode("utf-8"), list(WARD_FIELDS))
    state, _ = normalize_snapshot_variants(rows)
    resolved = {
        code: _source_observation(row)
        for code, row in state["resolved_by_code"].items()
    }
    return resolved, set(state["anomalies_by_code"])


def _span(value: dict, start: str | None, evidence: dict) -> dict:
    return {**value, "from": start, "to": None, "evidence": evidence}


@dataclass
class _WardNode:
    entity: Entity
    current: dict
    name_spans: list[dict] = field(default_factory=list)
    province_echo_spans: list[dict] = field(default_factory=list)
    creation_evidence: dict = field(default_factory=dict)
    dissolution_evidence: dict = field(default_factory=dict)
    observed_from: str = SOURCE_FLOOR
    observed_to: str | None = None

    def to_dict(self) -> dict:
        return {
            **self.entity.to_dict(),
            "name_spans": self.name_spans,
            "province_echo_spans": self.province_echo_spans,
            "creation_evidence": self.creation_evidence,
            "dissolution_evidence": self.dissolution_evidence,
            "observed_from": self.observed_from,
            "observed_to": self.observed_to,
        }


def _new_node(observation: dict, valid_from: str | None, evidence: dict,
              *, parent_tier: str = "district") -> _WardNode:
    code = observation["code"]
    entity = Entity(
        local_id=ward_local_id(code, valid_from),
        gso_codes=[code],
        name_vi=observation["name_vi"],
        loai_hinh=observation["loai_hinh"],
        type_spans=[_span(
            {"loai_hinh": observation["loai_hinh"]}, valid_from, evidence,
        )],
        aliases=[],
        valid_from=valid_from,
        valid_to=None,
        parent_spans=[_span({
            "tier": parent_tier,
            "code": observation["district_code"],
            "name_vi": observation["district_name_vi"],
            "qid": None,
        }, valid_from, evidence)],
    )
    return _WardNode(
        entity=entity,
        current=observation,
        name_spans=[_span({"name_vi": observation["name_vi"]}, valid_from, evidence)],
        province_echo_spans=[_span({
            "code": observation["province_code_echo"],
            "name_vi": observation["province_name_echo"],
        }, valid_from, evidence)],
        creation_evidence=evidence,
        observed_from=valid_from or SOURCE_FLOOR,
    )


def _close_span(spans: list[dict], effective_date: str) -> None:
    if not spans or spans[-1]["to"] is not None:
        raise ValueError("cannot close a missing or already closed ward span")
    spans[-1]["to"] = _minus_one_day(effective_date)


def _append_alias(entity: Entity, value: str) -> None:
    value = str(value or "").strip()
    if value and value not in entity.aliases:
        entity.aliases.append(value)


def _apply_observation(node: _WardNode, observation: dict, effective_date: str,
                       evidence: dict, *, parent_tier: str = "district") -> None:
    previous = node.current
    if previous["name_vi"] != observation["name_vi"]:
        _close_span(node.name_spans, effective_date)
        _append_alias(node.entity, previous["name_vi"])
        node.name_spans.append(_span(
            {"name_vi": observation["name_vi"]}, effective_date, evidence,
        ))
        node.entity.name_vi = observation["name_vi"]

    if previous["loai_hinh"] != observation["loai_hinh"]:
        _close_span(node.entity.type_spans, effective_date)
        node.entity.type_spans.append(_span(
            {"loai_hinh": observation["loai_hinh"]}, effective_date, evidence,
        ))
        node.entity.loai_hinh = observation["loai_hinh"]

    old_parent = (previous["district_code"], previous["district_name_vi"])
    new_parent = (observation["district_code"], observation["district_name_vi"])
    current_parent_tier = node.entity.parent_spans[-1]["tier"]
    if old_parent != new_parent or current_parent_tier != parent_tier:
        _close_span(node.entity.parent_spans, effective_date)
        node.entity.parent_spans.append(_span({
            "tier": parent_tier,
            "code": observation["district_code"],
            "name_vi": observation["district_name_vi"],
            "qid": None,
        }, effective_date, evidence))

    old_province = (
        previous["province_code_echo"], previous["province_name_echo"],
    )
    new_province = (
        observation["province_code_echo"], observation["province_name_echo"],
    )
    if old_province != new_province:
        _close_span(node.province_echo_spans, effective_date)
        node.province_echo_spans.append(_span({
            "code": observation["province_code_echo"],
            "name_vi": observation["province_name_echo"],
        }, effective_date, evidence))
    node.current = observation


def _end_node(node: _WardNode, effective_date: str, evidence: dict) -> None:
    valid_to = _minus_one_day(effective_date)
    node.entity.valid_to = valid_to
    node.observed_to = valid_to
    for spans in (
        node.name_spans,
        node.entity.type_spans,
        node.entity.parent_spans,
        node.province_echo_spans,
    ):
        if spans[-1]["to"] is None:
            spans[-1]["to"] = valid_to
    node.dissolution_evidence = evidence


def _compact_instrument(instrument: dict) -> dict:
    return {
        "instrument_id": instrument["instrument_id"],
        "source_status": instrument["source_status"],
        "primary_sources": [
            {
                "path": source["path"],
                "source_url": source["source_url"],
                "sha256": source["sha256"],
            }
            for source in instrument["primary_sources"]
        ],
        "secondary_sources": [
            {"source_url": source["source_url"]}
            for source in instrument["secondary_sources"]
            if source.get("source_url")
        ],
    }


def _component_instrument_ids(event: dict, component: dict) -> list[str]:
    row_ids = set(component.get("evidence_row_ids", []))
    linked = {
        link["instrument_id"]
        for link in event.get("legal_evidence", {}).get("instrument_links", [])
        if row_ids & set(link.get("crosswalk_row_ids", []))
    }
    if linked:
        return sorted(linked)

    decree_codes = set(
        component.get("evidence_signals", {}).get("decree_codes_raw", [])
    )
    cited = [
        instrument_id for instrument_id in event.get("legal_instrument_ids", [])
        if instrument_id.split("@", 1)[0] in decree_codes
    ]
    return cited or event.get("legal_instrument_ids", [])


def _component_evidence(event: dict, component: dict, effective_date: str) -> dict:
    return {
        "event_id": event["event_id"],
        "component_id": component["component_id"],
        "effective_date": effective_date,
        "instrument_ids": _component_instrument_ids(event, component),
        "crosswalk_row_ids": component.get("evidence_row_ids", []),
        "crosswalk_status": component.get("status", ""),
    }


def _component_date(component: dict, event: dict, rows_by_id: dict[str, dict]) -> str:
    candidates = set()
    for row_id in component.get("evidence_row_ids", []):
        row = rows_by_id[row_id]
        if component["kind"] == "removal" and row.get("succ_ma"):
            value = row.get("succ_hieu_luc")
        elif component["kind"] in {"addition", "same_code"}:
            value = row.get("succ_hieu_luc")
        else:
            value = ""
        if value and event["before_date"] < value <= event["after_date"]:
            candidates.add(value)
    return max(candidates) if candidates else event["after_date"]


def _load_overrides(path: Path) -> tuple[dict[str, dict], dict[str, dict]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported ward-history override schema")
    rows = payload.get("code_transition_pairs", [])
    indexed = {row["old_code"]: row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError("ward-history overrides contain duplicate old codes")
    if len({row["new_code"] for row in rows}) != len(rows):
        raise ValueError("ward-history overrides contain duplicate new codes")
    unmapped_rows = payload.get("unmapped_predecessors", [])
    unmapped = {row["old_code"]: row for row in unmapped_rows}
    if len(unmapped) != len(unmapped_rows):
        raise ValueError("ward-history overrides contain duplicate unmapped codes")
    if set(indexed) & set(unmapped):
        raise ValueError("ward-history override cannot map and omit the same code")
    return indexed, unmapped


def _recode_mapping(event: dict, live: dict[str, _WardNode],
                    addition_observations: dict[str, dict],
                    rows_by_id: dict[str, dict],
                    overrides: dict[str, dict],
                    unmapped_overrides: dict[str, dict]) -> tuple[dict, dict]:
    addition_components = {
        component["code"]: component
        for component in event["components"]
        if component["kind"] == "addition"
    }
    removals = [
        component for component in event["components"]
        if component["kind"] == "removal"
    ]
    mapping = {}
    evidence = {}
    for component in removals:
        old_code = component["code"]
        candidates: dict[str, set[str]] = defaultdict(set)
        for row_id in component.get("evidence_row_ids", []):
            row = rows_by_id[row_id]
            if row["base_ma"] == old_code and row["succ_ma"] in addition_components:
                candidates[row["succ_ma"]].add(row_id)
        if len(candidates) > 1:
            old_name = bare_ward_name(live[old_code].current["name_vi"])
            name_matches = [
                code for code in candidates
                if bare_ward_name(addition_observations[code]["name_vi"]) == old_name
            ]
            if len(name_matches) == 1:
                candidates = {name_matches[0]: candidates[name_matches[0]]}
        if not candidates:
            override = overrides.get(old_code)
            if old_code in unmapped_overrides:
                continue
            if override is None or override["new_code"] not in addition_components:
                raise ValueError(f"2004 code transition lacks mapping for {old_code}")
            mapping[old_code] = override["new_code"]
            evidence[old_code] = {
                "override": override,
                "crosswalk_row_ids": [],
            }
        elif len(candidates) == 1:
            new_code, row_ids = next(iter(candidates.items()))
            mapping[old_code] = new_code
            evidence[old_code] = {
                "crosswalk_row_ids": sorted(row_ids),
            }
        else:
            raise ValueError(
                f"2004 code transition is ambiguous for {old_code}: {sorted(candidates)}"
            )
    removal_codes = {component["code"] for component in removals}
    classified = set(mapping) | set(unmapped_overrides)
    if classified != removal_codes:
        raise ValueError(
            "2004 code transition does not classify every removed code: "
            f"missing={sorted(removal_codes - classified)}, "
            f"extra={sorted(classified - removal_codes)}"
        )
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("2004 code transition maps multiple live wards to one code")
    if set(overrides) != {code for code, item in evidence.items() if "override" in item}:
        raise ValueError("ward-history code-transition overrides are stale")
    return mapping, evidence


def _strongest_reference(instrument_ids: list[str], instruments: dict[str, dict]) -> str:
    for instrument_id in instrument_ids:
        instrument = instruments.get(instrument_id)
        if not instrument:
            continue
        primary = instrument.get("primary_sources", [])
        if primary:
            preferred = sorted(
                primary,
                key=lambda source: (
                    source.get("media_type") != "pdf", source.get("path", ""),
                ),
            )[0]
            return preferred.get("source_url", "")
    for instrument_id in instrument_ids:
        instrument = instruments.get(instrument_id)
        if not instrument:
            continue
        secondary = instrument.get("secondary_sources", [])
        if secondary:
            return secondary[0].get("source_url", "")
    return ""


def _historical_pair_edges(event: dict, removals: list[dict],
                           live: dict[str, _WardNode], ended: dict[str, _WardNode],
                           rows_by_id: dict[str, dict], instruments: dict[str, dict]) -> tuple[list[dict], set[str]]:
    proposed: dict[tuple[str, str], dict] = {}
    for component in removals:
        predecessor = ended[component["code"]]
        for row_id in component.get("evidence_row_ids", []):
            row = rows_by_id[row_id]
            successor_code = row.get("succ_ma", "")
            if row.get("base_ma") != component["code"] or successor_code not in live:
                continue
            successor = live[successor_code]
            if predecessor.entity.local_id == successor.entity.local_id:
                continue
            key = (predecessor.entity.local_id, successor.entity.local_id)
            item = proposed.setdefault(key, {
                "predecessor": predecessor,
                "successor": successor,
                "component": component,
                "row_ids": set(),
                "decree_codes": set(),
            })
            item["row_ids"].add(row_id)
            item["decree_codes"].update(
                component.get("evidence_signals", {}).get("decree_codes_raw", [])
            )

    outgoing = Counter(key[0] for key in proposed)
    incoming = Counter(key[1] for key in proposed)
    edge_rows = []
    linked_removals = set()
    for key, item in sorted(proposed.items()):
        predecessor = item["predecessor"]
        successor = item["successor"]
        component = item["component"]
        effective_date = _component_date(component, event, rows_by_id)
        if outgoing[key[0]] > 1:
            relation = "split"
        elif incoming[key[1]] > 1:
            relation = "merged_into"
        else:
            relation = "replaces"
        decree_codes = sorted(item["decree_codes"])
        instrument_ids = _component_instrument_ids(event, component)
        decree = (
            instrument_ids[0].split("@", 1)[0]
            if len(instrument_ids) == 1
            else decree_codes[0] if len(decree_codes) == 1 else ""
        )
        edge = LineageEdge(
            predecessor=predecessor.entity.local_id,
            successor=successor.entity.local_id,
            relation=relation,
            share="partial" if outgoing[key[0]] > 1 else "whole",
            primary=False,
            decree=decree,
            effective_date=effective_date,
            reference_url=_strongest_reference(instrument_ids, instruments),
        ).to_dict()
        edge["provenance"] = {
            "event_id": event["event_id"],
            "component_id": component["component_id"],
            "instrument_ids": instrument_ids,
            "crosswalk_row_ids": sorted(item["row_ids"]),
        }
        edge_rows.append(edge)
        linked_removals.add(component["component_id"])
    return edge_rows, linked_removals


def _composition_edges(composition: dict, old_by_code: dict[str, _WardNode],
                       new_by_code: dict[str, _WardNode], boundary: dict,
                       instruments: dict[str, dict]) -> list[dict]:
    outgoing = Counter(edge["predecessor_code"] for edge in composition["edges"])
    incoming = Counter(edge["successor_code"] for edge in composition["edges"])
    province_by_successor = {
        row["code"]: row["province_code"]
        for row in boundary["observations"]["post"]
    }
    resolution_by_province: dict[str, set[str]] = defaultdict(set)
    for clause in composition["clauses"]:
        resolution_by_province[clause["successor_province_code"]].add(
            clause["resolution_code"]
        )

    rows = []
    for source in composition["edges"]:
        predecessor = old_by_code[source["predecessor_code"]]
        successor = new_by_code[source["successor_code"]]
        resolution_codes = sorted({
            evidence["resolution_code"]
            for evidence in source["evidence"]
            if evidence.get("resolution_code")
        })
        if not resolution_codes:
            province = province_by_successor[source["successor_code"]]
            resolution_codes = sorted(resolution_by_province[province])
        if len(resolution_codes) != 1:
            raise ValueError(
                "2025 composition edge has ambiguous resolution scope: "
                f"{source['predecessor_code']}->{source['successor_code']} "
                f"{resolution_codes}"
            )
        resolution = resolution_codes[0]
        instrument_ids = [f"{resolution}@{REFORM_DATE}"]
        if outgoing[source["predecessor_code"]] > 1:
            relation = "split"
        elif incoming[source["successor_code"]] > 1:
            relation = "merged_into"
        else:
            relation = "replaces"
        edge = LineageEdge(
            predecessor=predecessor.entity.local_id,
            successor=successor.entity.local_id,
            relation=relation,
            share=source["share"],
            primary=source["primary"],
            decree=resolution,
            effective_date=REFORM_DATE,
            reference_url=_strongest_reference(instrument_ids, instruments),
        ).to_dict()
        edge["provenance"] = {
            "event_id": "soap:2025-06-30->2025-07-01",
            "instrument_ids": instrument_ids,
            "composition_evidence": source["evidence"],
        }
        rows.append(edge)
    return rows


def _assert_current_roster(live: dict[str, _WardNode]) -> None:
    expected, anomalies = _load_snapshot(
        f"soap/DanhMucPhuongXa_{AS_OF}.xml.gz"
    )
    if anomalies:
        raise ValueError(f"current ward snapshot retains source anomalies: {anomalies}")
    if set(live) != set(expected):
        raise ValueError("historical graph live codes differ from the current SOAP roster")
    fields = (
        "province_code_echo", "province_name_echo", "district_code",
        "district_name_vi", "code", "name_vi", "loai_hinh",
    )
    mismatches = [
        code for code in sorted(expected)
        if any(
            live[code].current[field] != expected[code][field]
            for field in fields
            if expected[code][field]
        )
    ]
    if mismatches:
        first = mismatches[0]
        raise ValueError(
            "historical graph current observations drifted: "
            f"{mismatches[:10]}; first={first}, "
            f"graph={live[first].current}, expected={expected[first]}"
        )


def build_ward_history() -> dict:
    observed = json.loads(OBSERVED_CHANGES.read_text(encoding="utf-8"))
    reconciliation = json.loads(RECONCILIATION.read_text(encoding="utf-8"))
    coverage = json.loads(COVERAGE.read_text(encoding="utf-8"))
    boundary = json.loads(BOUNDARY_2025.read_text(encoding="utf-8"))
    composition = json.loads(COMPOSITION_2025.read_text(encoding="utf-8"))
    overrides, unmapped_overrides = _load_overrides(OVERRIDES)

    if coverage["scope"]["source_gate_status"] != "accepted_bounded_residue":
        raise ValueError("ward source gate has not accepted its bounded residue")
    if coverage["scope"]["next_task"] != 8:
        raise ValueError("ward source ledger does not authorize Task 8")
    if composition["lineage_completeness"] != "complete":
        raise ValueError("2025 composition is not complete")

    rows_by_id = {
        row["row_id"]: row for row in reconciliation["crosswalk_evidence_rows"]
    }
    reconciled_events = {
        event["event_id"]: event for event in reconciliation["events"]
    }
    coverage_events = {event["event_id"]: event for event in coverage["events"]}
    instruments = {
        instrument["instrument_id"]: instrument
        for instrument in coverage["legal_instruments"]
    }
    compact_instruments = [
        _compact_instrument(instruments[instrument_id])
        for instrument_id in sorted(instruments)
    ]

    baseline_path = f"soap/DanhMucPhuongXa_{SOURCE_FLOOR}.xml.gz"
    baseline, baseline_anomalies = _load_snapshot(baseline_path)
    baseline_evidence = {
        "kind": "source_floor_observation",
        "source_path": baseline_path,
        "as_of": SOURCE_FLOOR,
    }
    live = {
        code: _new_node(observation, None, baseline_evidence)
        for code, observation in sorted(baseline.items())
    }
    all_nodes = list(live.values())
    lineage_edges = []
    anomaly_codes = set(baseline_anomalies)
    code_reuse = []
    predecessorless_additions = []
    successorless_removals = []
    transition_additions = []
    transition_unmapped_predecessors = []
    structured_edge_failures = []
    pre_reform_nodes = None

    audits_by_date = {
        item["date"]: item for item in observed["snapshot_audits"]
    }
    for interval in observed["intervals"]:
        event_id = interval["event_id"]
        for transition in interval["source_anomaly_transitions"]:
            before_status = transition["before"]["status"]
            after_status = transition["after"]["status"]
            if before_status == "resolved" and after_status == "source_anomaly":
                anomaly_codes.add(transition["code"])
            elif before_status == "source_anomaly" and after_status == "resolved":
                anomaly_codes.discard(transition["code"])
                if transition["code"] in live:
                    live[transition["code"]].current = transition["after"]["observation"]
            elif before_status == "source_anomaly" and after_status == "absent":
                anomaly_codes.discard(transition["code"])

        if not interval["normalized_changed"]:
            continue
        event = coverage_events[event_id]
        reconciled = reconciled_events[event_id]
        components = {
            component["component_id"]: component
            for component in reconciled["components"]
        }

        if event_id == "soap:2004-01-01->2004-07-01":
            additions = {
                change["code"]: change for change in interval["additions"]
            }
            mapping, mapping_evidence = _recode_mapping(
                reconciled, live, additions, rows_by_id, overrides,
                unmapped_overrides,
            )
            removed_codes = {
                component["code"] for component in components.values()
                if component["kind"] == "removal"
            }
            new_live = {
                code: node for code, node in live.items()
                if code not in removed_codes
            }
            for old_code, new_code in sorted(mapping.items()):
                node = live[old_code]
                component_id = f"{event_id}#addition:{new_code}"
                component = components[component_id]
                effective_date = _component_date(component, event, rows_by_id)
                evidence = _component_evidence(event, component, effective_date)
                evidence["code_transition"] = mapping_evidence[old_code]
                _append_alias(node.entity, old_code)
                if node.entity.gso_codes[-1] != new_code:
                    node.entity.gso_codes.append(new_code)
                _apply_observation(
                    node, additions[new_code], effective_date, evidence,
                )
                new_live[new_code] = node
            for old_code, override in sorted(unmapped_overrides.items()):
                component = components[f"{event_id}#removal:{old_code}"]
                effective_date = _component_date(component, event, rows_by_id)
                evidence = _component_evidence(event, component, effective_date)
                node = live[old_code]
                _end_node(node, effective_date, evidence)
                transition_unmapped_predecessors.append({
                    "entity_id": node.entity.local_id,
                    **evidence,
                    "override": override,
                })
            for new_code, observation in sorted(additions.items()):
                if new_code in new_live:
                    continue
                component = components[f"{event_id}#addition:{new_code}"]
                effective_date = _component_date(component, event, rows_by_id)
                evidence = _component_evidence(event, component, effective_date)
                node = _new_node(observation, effective_date, evidence)
                new_live[new_code] = node
                all_nodes.append(node)
                transition_additions.append({
                    "entity_id": node.entity.local_id,
                    **evidence,
                })
            live = new_live
        elif event_id == "soap:2025-06-30->2025-07-01":
            expected_pre = {
                row["code"]: _boundary_observation(row)
                for row in boundary["observations"]["pre"]
            }
            if set(live) != set(expected_pre):
                raise ValueError("pre-reform live roster differs from boundary artifact")
            mismatches = [
                code for code in sorted(expected_pre)
                if live[code].current["name_vi"] != expected_pre[code]["name_vi"]
                or live[code].current["loai_hinh"] != expected_pre[code]["loai_hinh"]
                or live[code].current["district_code"] != expected_pre[code]["district_code"]
            ]
            if mismatches:
                raise ValueError(f"pre-reform live observations drifted: {mismatches[:10]}")
            pre_reform_nodes = dict(live)
            reform_evidence = {
                "event_id": event_id,
                "effective_date": REFORM_DATE,
                "instrument_ids": event["legal_instrument_ids"],
                "composition_path": COMPOSITION_2025.as_posix(),
            }
            for node in pre_reform_nodes.values():
                _end_node(node, REFORM_DATE, reform_evidence)
            live = {}
            post_observations = {
                change["code"]: change["after"]
                for change in interval["same_code_changes"]
            }
            post_observations.update({
                change["code"]: change for change in interval["additions"]
            })
            if set(post_observations) != {
                row["code"] for row in boundary["observations"]["post"]
            }:
                raise ValueError(
                    "post-reform change observations differ from boundary artifact"
                )
            for row in boundary["observations"]["post"]:
                observation = dict(post_observations[row["code"]])
                if not observation["name_vi"] and row["name_vi"]:
                    observation["name_vi"] = row["name_vi"]
                province = row["province_code"]
                resolution_codes = sorted({
                    clause["resolution_code"]
                    for clause in composition["clauses"]
                    if clause["successor_province_code"] == province
                })
                evidence = {
                    **reform_evidence,
                    "instrument_ids": [f"{code}@{REFORM_DATE}" for code in resolution_codes],
                }
                node = _new_node(
                    observation, REFORM_DATE, evidence, parent_tier="province",
                )
                live[observation["code"]] = node
                all_nodes.append(node)
            lineage_edges.extend(_composition_edges(
                composition, pre_reform_nodes, live, boundary, instruments,
            ))
        else:
            same_changes = {
                change["code"]: change for change in interval["same_code_changes"]
            }
            additions = {
                change["code"]: change for change in interval["additions"]
            }
            removals = {
                change["code"]: change for change in interval["removals"]
            }
            ended = {}
            removal_components = []

            for code, change in sorted(same_changes.items()):
                component = components[f"{event_id}#same_code:{code}"]
                effective_date = _component_date(component, event, rows_by_id)
                evidence = _component_evidence(event, component, effective_date)
                if component["status"] == "supported_code_reuse":
                    old = live.pop(code)
                    _end_node(old, effective_date, evidence)
                    node = _new_node(
                        change["after"], effective_date, evidence,
                        parent_tier="province" if effective_date >= REFORM_DATE else "district",
                    )
                    live[code] = node
                    all_nodes.append(node)
                    code_reuse.append({
                        "code": code,
                        "predecessor_entity_id": old.entity.local_id,
                        "successor_entity_id": node.entity.local_id,
                        **evidence,
                    })
                else:
                    if code not in live:
                        raise ValueError(f"same-code component has no live ward: {component['component_id']}")
                    _apply_observation(
                        live[code], change["after"], effective_date, evidence,
                        parent_tier="province" if effective_date >= REFORM_DATE else "district",
                    )

            for code in sorted(removals):
                component = components[f"{event_id}#removal:{code}"]
                effective_date = _component_date(component, event, rows_by_id)
                evidence = _component_evidence(event, component, effective_date)
                node = live.pop(code, None)
                if node is None:
                    raise ValueError(f"removal component has no live ward: {component['component_id']}")
                _end_node(node, effective_date, evidence)
                ended[code] = node
                removal_components.append(component)

            for code, observation in sorted(additions.items()):
                if code in live:
                    raise ValueError(f"addition reuses a live ward code without classification: {code}")
                component = components[f"{event_id}#addition:{code}"]
                effective_date = _component_date(component, event, rows_by_id)
                evidence = _component_evidence(event, component, effective_date)
                node = _new_node(
                    observation, effective_date, evidence,
                    parent_tier="province" if effective_date >= REFORM_DATE else "district",
                )
                live[code] = node
                all_nodes.append(node)
                predecessorless_additions.append({
                    "entity_id": node.entity.local_id,
                    **evidence,
                    "reason": "no structured predecessor pair in retained crosswalk evidence",
                })

            new_edges, linked_removals = _historical_pair_edges(
                event, removal_components, live, ended, rows_by_id, instruments,
            )
            lineage_edges.extend(new_edges)
            for component in removal_components:
                if component["component_id"] not in linked_removals:
                    successorless_removals.append({
                        "entity_id": ended[component["code"]].entity.local_id,
                        **_component_evidence(
                            event, component,
                            _component_date(component, event, rows_by_id),
                        ),
                        "reason": "no structured successor pair in retained crosswalk evidence",
                    })

        after_audit = audits_by_date[interval["after_date"]]
        resolved_live = set(live) - anomaly_codes
        if len(resolved_live) != after_audit["resolved_codes"]:
            raise ValueError(
                f"live roster count drift at {interval['after_date']}: "
                f"{len(resolved_live)} != {after_audit['resolved_codes']}"
            )

    if pre_reform_nodes is None:
        raise ValueError("historical graph did not process the 2025 reform")
    _assert_current_roster(live)

    entity_rows = sorted(
        (node.to_dict() for node in all_nodes), key=lambda row: row["local_id"],
    )
    edge_rows = sorted(
        lineage_edges,
        key=lambda row: (row["effective_date"], row["predecessor"], row["successor"]),
    )
    entity_ids = {row["local_id"] for row in entity_rows}
    dangling = [
        edge for edge in edge_rows
        if edge["predecessor"] not in entity_ids or edge["successor"] not in entity_ids
    ]
    duplicate_edges = [
        key for key, count in Counter(
            (edge["predecessor"], edge["successor"], edge["effective_date"])
            for edge in edge_rows
        ).items() if count > 1
    ]
    self_edges = [
        edge for edge in edge_rows if edge["predecessor"] == edge["successor"]
    ]
    if dangling or duplicate_edges or self_edges or structured_edge_failures:
        raise ValueError(
            "ward graph integrity failure: "
            f"dangling={len(dangling)}, duplicates={len(duplicate_edges)}, "
            f"self={len(self_edges)}, structured={len(structured_edge_failures)}"
        )

    relation_counts = Counter(edge["relation"] for edge in edge_rows)
    share_counts = Counter(edge["share"] for edge in edge_rows)
    return {
        "schema_version": 1,
        "scope": {
            "tier": "ward",
            "source_floor": SOURCE_FLOOR,
            "as_of": AS_OF,
            "status": "canonical_observation_graph_complete_with_explicit_topology_residue",
            "source_gate_status": coverage["scope"]["source_gate_status"],
            "wikidata_status": "not_reconciled_or_emitted",
        },
        "input_fingerprints": {
            path.as_posix(): _sha256(path)
            for path in (
                OBSERVED_CHANGES, RECONCILIATION, COVERAGE, BOUNDARY_2025,
                COMPOSITION_2025, OVERRIDES,
            )
        },
        "audit": {
            "entities": len(entity_rows),
            "baseline_entities": len(baseline),
            "current_entities": len(live),
            "pre_reform_entities": len(pre_reform_nodes),
            "post_reform_entities": len(boundary["observations"]["post"]),
            "lineage_edges": len(edge_rows),
            "relation_counts": dict(sorted(relation_counts.items())),
            "share_counts": dict(sorted(share_counts.items())),
            "composition_edges_2025": composition["audit"]["composition_edges"],
            "code_reuse_breaks": len(code_reuse),
            "code_transition_overrides": len(overrides),
            "code_transition_unmapped_predecessors": len(
                transition_unmapped_predecessors
            ),
            "transition_additions": len(transition_additions),
            "predecessorless_historical_additions": len(predecessorless_additions),
            "successorless_historical_removals": len(successorless_removals),
            "source_anomaly_codes_at_floor": len(baseline_anomalies),
            "dangling_edges": len(dangling),
            "duplicate_edges": len(duplicate_edges),
            "self_edges": len(self_edges),
        },
        "provenance": {
            "source_coverage_path": COVERAGE.as_posix(),
            "accepted_source_residue_instrument_ids": coverage["residue"][
                "accepted_source_residue_instrument_ids"
            ],
            "legal_instruments": compact_instruments,
        },
        "entities": entity_rows,
        "lineage_edges": edge_rows,
        "residue": {
            "baseline_source_anomaly_codes": sorted(baseline_anomalies),
            "code_reuse_breaks": code_reuse,
            "transition_additions_without_baseline_identity": transition_additions,
            "transition_unmapped_predecessors": transition_unmapped_predecessors,
            "predecessorless_historical_additions": predecessorless_additions,
            "successorless_historical_removals": successorless_removals,
        },
    }


def serialize_ward_history(artifact: dict) -> str:
    return json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_ward_history(path: Path = OUTPUT) -> Path:
    artifact = build_ward_history()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(serialize_ward_history(artifact), encoding="utf-8")
    temporary.replace(path)
    return path


def format_audit(artifact: dict) -> str:
    audit = artifact["audit"]
    return (
        f"ward history graph: {audit['entities']} entities, "
        f"{audit['lineage_edges']} lineage edges, "
        f"{audit['current_entities']} current; "
        f"{audit['predecessorless_historical_additions']} predecessorless additions, "
        f"{audit['successorless_historical_removals']} successorless removals"
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the historical ward graph")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--audit", action="store_true")
    args = parser.parse_args(argv)

    artifact = build_ward_history()
    rendered = serialize_ward_history(artifact)
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != rendered:
            raise SystemExit(f"ward history artifact is missing or stale: {args.output}")
        action = "verified"
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_name(f".{args.output.name}.tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(args.output)
        action = "wrote"
    if args.audit:
        print(f"{action} {args.output}\n{format_audit(artifact)}")
    else:
        print(f"{action} {args.output}: {artifact['audit']['entities']} entities")


if __name__ == "__main__":
    main()
