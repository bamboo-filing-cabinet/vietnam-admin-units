"""Classify ward legal records and link them to observed SOAP events.

The legal index is a high-recall discovery source, not an event log.  This
module therefore requires temporal and textual corroboration in addition to a
document-code match, preserves same-date ambiguity as event context, and keeps
the two known 2008 index corrections explicit in a small reviewed override.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path


OVERRIDES = Path("data/ward-legal-linkage-overrides.json")
COMPOSITION_2025 = Path("data/ward-2025-composition.json")

_LINEAGE_TERMS = (
    "sap xep",
    "thanh lap",
    "sat nhap",
    "sap nhap",
    "hop nhat",
    "giai the",
    "chia xa",
    "chia tach",
    "tach xa",
)
_RENAME_TERMS = (
    "doi ten",
    "chuyen xa thanh phuong",
    "chuyen thi tran thanh phuong",
    "chuyen phuong thanh",
    "chuyen thanh",
)
_BOUNDARY_TERMS = (
    "dieu chinh dia gioi",
    "phan vach dia gioi",
    "mo rong dia gioi",
)
_TYPE_PREFIXES = (
    "thanh pho ",
    "tinh ",
    "thi xa ",
    "huyen ",
    "quan ",
    "phuong ",
    "thi tran ",
    "xa ",
)


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", str(value or "").lower()).replace("đ", "d")
    ascii_text = "".join(
        character
        for character in decomposed
        if unicodedata.category(character) != "Mn"
    )
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_text).split())


def _bare_name(value: str) -> str:
    folded = _fold(value)
    for prefix in _TYPE_PREFIXES:
        if folded.startswith(prefix):
            return folded[len(prefix):]
    return folded


def _phrase_in_title(value: str, title: str) -> bool:
    phrase = _bare_name(value)
    return len(phrase) >= 4 and phrase in _fold(title)


def classify_instrument_title(title: str) -> tuple[str, list[str]]:
    """Return the reviewed structural class and the phrases supporting it."""
    folded = _fold(title)
    for classification, terms in (
        ("lineage", _LINEAGE_TERMS),
        ("rename_or_retype", _RENAME_TERMS),
        ("parent_or_boundary_only", _BOUNDARY_TERMS),
    ):
        matched = [term for term in terms if term in folded]
        if matched:
            return classification, matched
    return "unresolved", []


def _code_aliases(value: str) -> set[str]:
    folded = _fold(value)
    return {
        folded,
        folded.replace("nq ubtvqh", "ubtvqh"),
        folded.replace("nd cp", "cp"),
    }


def _observations_by_component(interval: dict) -> dict[str, list[dict]]:
    event_id = interval["event_id"]
    observations = {}
    for kind, key in (("removal", "removals"), ("addition", "additions")):
        for observation in interval[key]:
            observations[f"{event_id}#{kind}:{observation['code']}"] = [observation]
    for change in interval["same_code_changes"]:
        observations[f"{event_id}#same_code:{change['code']}"] = [
            change["before"],
            change["after"],
        ]
    return observations


def _component_classification(component: dict) -> str:
    if component["kind"] in {"addition", "removal"}:
        return "lineage"
    changes = set(component.get("change_types", []))
    if changes & {"name", "type"}:
        return "rename_or_retype"
    if changes & {
        "district_parent_code",
        "district_parent_label",
        "province_echo_code",
        "province_echo_label",
    }:
        return "parent_or_boundary_only"
    return "no_observable_roster_change"


def _instrument_source_paths(instrument: dict) -> list[str]:
    return sorted(source["path"] for source in instrument["primary_sources"])


def _source_only_reason(instrument: dict) -> str | None:
    effective_date = instrument["effective_date"]
    if effective_date <= "2003-12-31":
        return "source_only_before_first_reliable_national_code_transition"
    if effective_date <= "2004-07-01":
        return "source_only_inside_2004_code_scheme_transition"
    if instrument["instrument_id"] == "212/2004/NĐ-CP@2005-01-08":
        return "source_only_normalized_quiet_soap_interval"
    return None


def _generic_event_review(event: dict, reconciled: dict, interval: dict,
                          eligible: list[dict], evidence_by_id: dict[str, dict]) -> dict:
    observations = _observations_by_component(interval)
    assignments: dict[str, str] = {}
    methods: dict[str, set[str]] = defaultdict(set)
    context_only = []

    for component in reconciled["components"]:
        component_id = component["component_id"]
        component_observations = observations[component_id]
        direct = []
        title_matches = []
        territory_matches = []
        named_unit_matches = []
        cited_codes = component.get("evidence_signals", {}).get("decree_codes_raw", [])
        cited_aliases = set().union(*(_code_aliases(code) for code in cited_codes)) if cited_codes else set()
        for instrument in eligible:
            title = " ".join(instrument["title_variants"])
            if _code_aliases(instrument["code"]) & cited_aliases:
                direct.append(instrument["instrument_id"])
            territory = any(
                _phrase_in_title(observation.get("province_name_echo", ""), title)
                for observation in component_observations
            )
            named_unit = any(
                _phrase_in_title(observation.get(key, ""), title)
                for observation in component_observations
                for key in ("name_vi", "district_name_vi")
            )
            crosswalk_territory = any(
                _phrase_in_title(row.get(key, ""), title)
                for row_id in component["evidence_row_ids"]
                for row in [evidence_by_id[row_id]]
                for key in ("base_tinh_ten", "succ_tinh_ten")
            )
            crosswalk_named_unit = any(
                _phrase_in_title(row.get(key, ""), title)
                for row_id in component["evidence_row_ids"]
                for row in [evidence_by_id[row_id]]
                for key in ("base_ten", "succ_ten")
            )
            if territory or crosswalk_territory:
                territory_matches.append(instrument["instrument_id"])
            if named_unit or crosswalk_named_unit:
                named_unit_matches.append(instrument["instrument_id"])
            if territory or named_unit or crosswalk_territory or crosswalk_named_unit:
                title_matches.append(instrument["instrument_id"])

        corroborated = sorted(set(direct) & set(title_matches))
        if len(corroborated) == 1:
            selected = corroborated[0]
            assignments[component_id] = selected
            methods[component_id].update({
                "crosswalk_document_code",
                "effective_date_inside_observation_interval",
                "title_territory_or_named_unit",
            })
        elif (
            len(named_unit_matches) == 1
            and direct
            and direct[0] != named_unit_matches[0]
        ):
            selected = named_unit_matches[0]
            assignments[component_id] = selected
            methods[component_id].update({
                "crosswalk_code_conflict_overridden_by_title_named_unit",
                "effective_date_inside_observation_interval",
                "title_territory_or_named_unit",
            })
        elif len(direct) == 1:
            selected = direct[0]
            assignments[component_id] = selected
            methods[component_id].update({
                "crosswalk_document_code",
                "effective_date_inside_observation_interval",
                "structural_title_review",
            })
            if selected in title_matches:
                methods[component_id].add("title_territory_or_named_unit")
        elif len(title_matches) == 1:
            assignments[component_id] = title_matches[0]
            methods[component_id].update({
                "effective_date_inside_observation_interval",
                (
                    "title_named_unit"
                    if title_matches[0] in named_unit_matches
                    else "title_territory"
                ),
            })
        elif len(eligible) == 1:
            assignments[component_id] = eligible[0]["instrument_id"]
            methods[component_id].update({
                "effective_date_inside_observation_interval",
                "sole_structural_instrument_in_interval",
            })
        else:
            context_only.append(component_id)

    by_instrument: dict[str, list[dict]] = defaultdict(list)
    for component in reconciled["components"]:
        instrument_id = assignments.get(component["component_id"])
        if instrument_id:
            by_instrument[instrument_id].append(component)

    links = []
    for instrument in eligible:
        instrument_id = instrument["instrument_id"]
        components = by_instrument[instrument_id]
        row_ids = sorted({
            row_id
            for component in components
            for row_id in component["evidence_row_ids"]
        })
        factors = sorted({
            factor
            for component in components
            for factor in methods[component["component_id"]]
        })
        links.append({
            "instrument_id": instrument_id,
            "classification": instrument["classification"],
            "link_status": (
                "topology_components_linked"
                if components else "no_observable_roster_change"
            ),
            "component_count": len(components),
            "component_classifications": dict(sorted(Counter(
                _component_classification(component) for component in components
            ).items())),
            "matching_factors": factors or [
                "effective_date_inside_observation_interval",
                "structural_title_review",
                "no_matching_soap_component",
            ],
            "crosswalk_row_ids": row_ids,
            "primary_source_paths": _instrument_source_paths(instrument),
            "source_status": instrument["source_status"],
        })

    assignment_counts = Counter(
        "component_linked_to_instrument" if component["component_id"] in assignments
        else "same_date_legal_context_only"
        for component in reconciled["components"]
    )
    return {
        "classification": "mixed_structural_event",
        "status": "legal_context_classified" if context_only else "legal_topology_linked",
        "legal_instrument_ids": [instrument["instrument_id"] for instrument in eligible],
        "instrument_links": links,
        "component_assignment_counts": dict(sorted(assignment_counts.items())),
        "component_classification_counts": dict(sorted(Counter(
            _component_classification(component) for component in reconciled["components"]
        ).items())),
        "context_only_component_ids": context_only,
        "context_only_explanation": (
            "The crosswalk omits a unique decree citation and the same observation "
            "interval contains multiple structural instruments; the component is "
            "linked to the reviewed event-level legal context without inventing a "
            "one-instrument assignment."
            if context_only else ""
        ),
    }


def _scheme_transition_review(reconciled: dict, override: dict,
                              source_only_ids: list[str]) -> dict:
    exceptions = sorted(
        component["component_id"]
        for component in reconciled["components"]
        if component["status"] == "unmatched"
    )
    return {
        "classification": override["classification"],
        "status": "explicitly_classified_non_legal_transition",
        "legal_instrument_ids": [],
        "instrument_links": [],
        "component_assignment_counts": {
            "code_scheme_transition": len(reconciled["components"]),
        },
        "component_classification_counts": {
            "code_only": len(reconciled["components"]),
        },
        "context_only_component_ids": [],
        "crosswalk_omission_component_ids": exceptions,
        "source_only_instrument_ids": source_only_ids,
        "review_note": override["review_note"],
    }


def _review_2008_boundary(reconciled: dict, override: dict,
                          supplemental: dict[str, dict]) -> dict:
    tan_duc_id = override["tan_duc_component_id"]
    links = []
    for instrument_id in override["legal_instrument_ids"]:
        if instrument_id.startswith("14/"):
            components = [
                component for component in reconciled["components"]
                if component["component_id"] == tan_duc_id
            ]
            factors = [
                "canonical_index_correction",
                "effective_date_precedes_delayed_soap_observation",
                "title_named_unit_xa_tan_duc",
            ]
        else:
            components = [
                component for component in reconciled["components"]
                if component["kind"] == "same_code"
                and component["component_id"] != tan_duc_id
            ]
            factors = [
                "effective_date_inside_observation_interval",
                "crosswalk_document_code_15_2008_qh12",
                "title_territory_ha_noi",
            ]
        item = supplemental[instrument_id]
        links.append({
            "instrument_id": instrument_id,
            "classification": item["classification"],
            "link_status": "topology_components_linked",
            "component_count": len(components),
            "component_classifications": {
                "parent_or_boundary_only": len(components),
            },
            "matching_factors": factors,
            "crosswalk_row_ids": sorted({
                row_id for component in components
                for row_id in component["evidence_row_ids"]
            }),
            "primary_source_paths": item["primary_source_paths"],
            "source_status": item["source_status"],
        })
    stale_removals = sorted(
        component["component_id"]
        for component in reconciled["components"]
        if component["kind"] == "removal"
    )
    return {
        "classification": override["classification"],
        "status": "legal_topology_linked_with_source_cleanup",
        "legal_instrument_ids": override["legal_instrument_ids"],
        "instrument_links": links,
        "component_assignment_counts": {
            "component_linked_to_instrument": sum(link["component_count"] for link in links),
            "stale_source_record_retired_at_parent_boundary": len(stale_removals),
        },
        "component_classification_counts": {
            "parent_or_boundary_only": sum(link["component_count"] for link in links),
            "source_cleanup": len(stale_removals),
        },
        "context_only_component_ids": [],
        "source_cleanup_component_ids": stale_removals,
        "review_note": override["review_note"],
    }


def _review_2025_boundary(reconciled: dict, composition: dict,
                          instruments: dict[str, dict]) -> dict:
    predecessor_resolution = {}
    for edge in composition["edges"]:
        codes = {
            evidence["resolution_code"]
            for evidence in edge["evidence"]
            if evidence.get("resolution_code")
        }
        if len(codes) == 1:
            predecessor_resolution[edge["predecessor_code"]] = next(iter(codes))
    successor_resolution = {
        clause["successor_code"]: clause["resolution_code"]
        for clause in composition["clauses"]
    }
    province_resolution: dict[str, set[str]] = defaultdict(set)
    for clause in composition["clauses"]:
        province_resolution[clause["successor_province_code"]].add(
            clause["resolution_code"]
        )
    unchanged = {
        item["successor_code"]: item["successor_province_code"]
        for item in composition["unchanged_successors"]
    }

    assigned: dict[str, str] = {}
    unchanged_ids = []
    for component in reconciled["components"]:
        code = component["code"]
        if component["kind"] == "removal":
            resolution = predecessor_resolution.get(code)
        else:
            resolution = successor_resolution.get(code)
        if resolution is None and code in unchanged:
            candidates = province_resolution[unchanged[code]]
            if len(candidates) != 1:
                raise ValueError(f"ambiguous 2025 unchanged-successor scope for {code}: {candidates}")
            resolution = next(iter(candidates))
            unchanged_ids.append(component["component_id"])
        if resolution is None:
            raise ValueError(f"2025 component lacks resolution evidence: {component['component_id']}")
        assigned[component["component_id"]] = f"{resolution}@2025-07-01"

    by_instrument: dict[str, list[dict]] = defaultdict(list)
    for component in reconciled["components"]:
        by_instrument[assigned[component["component_id"]]].append(component)
    clauses_by_instrument: dict[str, list[dict]] = defaultdict(list)
    for clause in composition["clauses"]:
        clauses_by_instrument[f"{clause['resolution_code']}@2025-07-01"].append({
            "clause_number": clause["clause_number"],
            "successor_code": clause["successor_code"],
            "source_path": clause["source_path"],
        })

    links = []
    for instrument_id in sorted(by_instrument):
        instrument = instruments[instrument_id]
        components = by_instrument[instrument_id]
        unchanged_count = sum(
            component["component_id"] in unchanged_ids for component in components
        )
        classifications = Counter({"lineage": len(components) - unchanged_count})
        if unchanged_count:
            classifications["parent_or_boundary_only"] = unchanged_count
        links.append({
            "instrument_id": instrument_id,
            "classification": "lineage",
            "link_status": "resolution_clauses_linked",
            "component_count": len(components),
            "component_classifications": dict(sorted(classifications.items())),
            "matching_factors": [
                "effective_date_inside_observation_interval",
                "resolution_clause_named_predecessor_or_successor",
                "resolution_province_scope",
            ],
            "resolution_clauses": clauses_by_instrument[instrument_id],
            "primary_source_paths": _instrument_source_paths(instrument),
            "source_status": instrument["source_status"],
        })
    return {
        "classification": "lineage",
        "status": "legal_topology_linked",
        "legal_instrument_ids": sorted(by_instrument),
        "instrument_links": links,
        "component_assignment_counts": {
            "resolution_clause_or_edge": len(reconciled["components"]) - len(unchanged_ids),
            "unchanged_successor_province_scope": len(unchanged_ids),
        },
        "component_classification_counts": {
            "lineage": len(reconciled["components"]) - len(unchanged_ids),
            "parent_or_boundary_only": len(unchanged_ids),
        },
        "context_only_component_ids": [],
        "composition_evidence": {
            "path": COMPOSITION_2025.as_posix(),
            "lineage_completeness": composition["lineage_completeness"],
            "arrangement_clauses": composition["audit"]["arrangement_clauses"],
            "composition_edges": composition["audit"]["composition_edges"],
            "unresolved_predecessors": len(composition["residue"]["unresolved_predecessors"]),
        },
    }


def build_legal_linkage(instruments: list[dict], events: list[dict],
                        reconciliation: dict, observed: dict, source_index: dict,
                        *, overrides_path: Path = OVERRIDES,
                        composition_path: Path = COMPOSITION_2025) -> dict:
    """Return complete instrument reviews and event-level legal linkage."""
    overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
    composition = json.loads(composition_path.read_text(encoding="utf-8"))
    corrections = overrides["instrument_corrections"]

    reviews = {}
    for instrument in instruments:
        instrument_id = instrument["instrument_id"]
        if instrument_id in corrections:
            correction = corrections[instrument_id]
            reviews[instrument_id] = {
                "classification": correction["classification"],
                "review_status": "reviewed_index_correction",
                "classification_evidence": {
                    "canonical_instrument_id": correction["canonical_instrument_id"],
                    "review_note": correction["review_note"],
                },
                "observation_status": "superseded_by_canonical_correction",
                "event_ids": [],
            }
            continue
        title = " | ".join(instrument["title_variants"])
        classification, terms = classify_instrument_title(title)
        reviews[instrument_id] = {
            "classification": classification,
            "review_status": "reviewed_title_and_source_scope",
            "classification_evidence": {
                "matched_title_terms": terms,
                "title_variants": instrument["title_variants"],
            },
            "observation_status": _source_only_reason(instrument) or "pending_event_linkage",
            "event_ids": [],
        }

    unresolved = sorted(
        instrument_id for instrument_id, review in reviews.items()
        if review["classification"] == "unresolved"
    )
    if unresolved:
        raise ValueError(f"legal title classification remains unresolved: {unresolved}")

    supplemental = {}
    for item in overrides["supplemental_instruments"]:
        code, effective_date = item["instrument_id"].split("@", 1)
        sources = source_index.get((code, effective_date), [])
        primary = [source for source in sources if source["source_class"] == "official"]
        source_status = (
            "verified_official_artifact" if primary else item["source_status"]
        )
        supplemental[item["instrument_id"]] = {
            **item,
            "source_status": source_status,
            "primary_source_paths": sorted(source["path"] for source in primary),
            "primary_sources": primary,
        }

    reconciled_by_id = {event["event_id"]: event for event in reconciliation["events"]}
    evidence_by_id = {
        row["row_id"]: row for row in reconciliation["crosswalk_evidence_rows"]
    }
    observed_by_id = {interval["event_id"]: interval for interval in observed["intervals"]}
    reviewed_instruments = {
        instrument["instrument_id"]: {
            **instrument,
            "classification": reviews[instrument["instrument_id"]]["classification"],
        }
        for instrument in instruments
    }
    event_reviews = {}
    for event in events:
        event_id = event["event_id"]
        reconciled = reconciled_by_id[event_id]
        if event_id == "soap:2004-01-01->2004-07-01":
            source_only_ids = sorted(
                instrument_id for instrument_id, review in reviews.items()
                if review["observation_status"] == "source_only_inside_2004_code_scheme_transition"
            )
            review = _scheme_transition_review(
                reconciled, overrides["event_overrides"][event_id], source_only_ids,
            )
        elif event_id == "soap:2008-07-02->2008-08-03":
            review = _review_2008_boundary(
                reconciled, overrides["event_overrides"][event_id], supplemental,
            )
        elif event_id == "soap:2025-06-30->2025-07-01":
            review = _review_2025_boundary(reconciled, composition, reviewed_instruments)
        else:
            eligible = [
                reviewed_instruments[instrument["instrument_id"]]
                for instrument in instruments
                if event["before_date"] < instrument["effective_date"] <= event["after_date"]
                and instrument["instrument_id"] not in corrections
                and _source_only_reason(instrument) is None
            ]
            if not eligible:
                raise ValueError(f"event lacks legal context: {event_id}")
            review = _generic_event_review(
                event, reconciled, observed_by_id[event_id], eligible, evidence_by_id,
            )
        event_reviews[event_id] = review
        for link in review["instrument_links"]:
            instrument_id = link["instrument_id"]
            if instrument_id not in reviews:
                continue
            reviews[instrument_id]["event_ids"].append(event_id)
            reviews[instrument_id]["observation_status"] = link["link_status"]

    for review in reviews.values():
        review["event_ids"].sort()

    instrument_classifications = Counter(
        review["classification"] for review in reviews.values()
    )
    observation_statuses = Counter(
        review["observation_status"] for review in reviews.values()
    )
    component_assignment_counts = Counter()
    for review in event_reviews.values():
        component_assignment_counts.update(review["component_assignment_counts"])
    return {
        "instrument_reviews": reviews,
        "event_reviews": event_reviews,
        "supplemental_instruments": [supplemental[key] for key in sorted(supplemental)],
        "summary": {
            "classified_instruments": len(reviews),
            "classified_legal_index_rows": sum(
                instrument["index_occurrences"] for instrument in instruments
            ),
            "instrument_classifications": dict(sorted(instrument_classifications.items())),
            "instrument_observation_statuses": dict(sorted(observation_statuses.items())),
            "events_reviewed": len(event_reviews),
            "event_statuses": dict(sorted(Counter(
                review["status"] for review in event_reviews.values()
            ).items())),
            "component_assignment_counts": dict(sorted(component_assignment_counts.items())),
            "context_only_components": sum(
                len(review["context_only_component_ids"])
                for review in event_reviews.values()
            ),
        },
    }
