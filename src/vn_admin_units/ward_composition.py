"""Build the source-backed 2025 ward-composition topology.

The official provincial resolutions are the primary composition source. Their
signed PDFs are preserved for authority and their matching Government Newspaper
HTML transcriptions provide the parseable legal clauses. The NSO composition
notes remain an independent cross-check and identify the unchanged-unit
complement; parser-resistant clause identities live in explicit curation.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from lxml import html

from vn_admin_units.rawcache import manifest_entry, raw_is_verified, read_raw
from vn_admin_units.ward_model import build_2025_boundary
from vn_admin_units.ward_resolution_fetch import (
    html_cache_relpath,
    pdf_cache_relpath,
    resolution_records,
)


_TIER_PREFIX = re.compile(r"^(?:xa|phuong|thi tran|dac khu)\s+")
_CLAUSE = re.compile(r"^(\d+)\.\s*(.*)$", re.DOTALL)
_ARTICLE_BODY_XPATH = (
    '//div[contains(concat(" ", normalize-space(@class), " "), '
    '" detail-content ") and @data-role="content"]'
)
_ARTICLE_ELEMENTS_XPATH = (
    ".//*[self::p or self::h1 or self::h2 or self::h3 or self::h4 or self::h5]"
)
CURATION_PATH = Path("data/ward-2025-composition-overrides.json")
_TONE_PLACEMENT = {
    "oà": "òa", "oá": "óa", "oả": "ỏa", "oã": "õa", "oạ": "ọa",
    "oè": "òe", "oé": "óe", "oẻ": "ỏe", "oẽ": "õe", "oẹ": "ọe",
    "uỳ": "ùy", "uý": "úy", "uỷ": "ủy", "uỹ": "ũy", "uỵ": "ụy",
}


def fold_words(value: str) -> str:
    """Return accent-insensitive lowercase words for source matching."""
    value = unicodedata.normalize("NFD", str(value).casefold()).replace("đ", "d")
    value = "".join(char for char in value if unicodedata.category(char) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def literal_words(value: str) -> str:
    """Return NFC lowercase words retaining Vietnamese diacritics."""
    value = unicodedata.normalize("NFC", str(value).casefold())
    return re.sub(r"[^0-9a-zà-ỹđ]+", " ", value).strip()


def canonical_literal_words(value: str) -> str:
    value = literal_words(value)
    for old, new in _TONE_PLACEMENT.items():
        value = value.replace(old, new)
    return value


def compact_literal(value: str) -> str:
    """Ignore source layout spaces while preserving letters and diacritics."""
    value = unicodedata.normalize("NFC", "".join(str(value).split()).casefold())
    return "".join(char for char in value if char.isalnum())


def compact_folded(value: str) -> str:
    return "".join(fold_words(value).split())


def bare_ward_name(value: str) -> str:
    return _TIER_PREFIX.sub("", fold_words(value), count=1)


def literal_bare_ward_name(value: str) -> str:
    return re.sub(
        r"^(?:xã|phường|thị trấn|đặc khu)\s+", "", literal_words(value), count=1
    )


def _candidate_tier(value: str) -> str:
    folded = fold_words(value)
    for tier in ("thi tran", "phuong", "xa", "dac khu"):
        if folded == tier or folded.startswith(f"{tier} "):
            return tier
    return ""


def _normalize_source_text(value: str) -> str:
    return unicodedata.normalize("NFC", re.sub(r"\s+", " ", value)).strip()


def _source_descriptor(relpath: str) -> dict:
    entry = manifest_entry(relpath)
    if entry is None or not raw_is_verified(relpath):
        raise ValueError(f"required raw resolution is missing or unverified: {relpath}")
    return {
        "path": relpath,
        "sha256": entry["sha256"],
        "source_url": entry["source_url"],
        "document_code": entry["document_code"],
    }


def _successor_indexes(boundary: dict) -> tuple[dict[int, str], dict[str, list[dict]]]:
    provinces_by_resolution: dict[int, set[str]] = defaultdict(set)
    for note in boundary["composition_notes"]:
        match = re.search(r"(\d+)/NQ-UBTVQH15", note["decree_raw"])
        if not match:
            raise ValueError(f"composition note has no resolution code: {note['decree_raw']!r}")
        provinces_by_resolution[int(match.group(1))].add(note["successor_province_code"])

    number_to_province = {}
    for record in resolution_records():
        number = record["number"]
        provinces = provinces_by_resolution.get(number, set())
        if len(provinces) != 1:
            raise ValueError(f"resolution {number} maps to successor provinces {sorted(provinces)}")
        number_to_province[number] = next(iter(provinces))

    post_by_province: dict[str, list[dict]] = defaultdict(list)
    for row in boundary["observations"]["post"]:
        post_by_province[row["province_code"]].append(row)
    return number_to_province, post_by_province


def _article_text_rows(number: int) -> list[str]:
    relpath = html_cache_relpath(number)
    document = html.fromstring(read_raw(relpath).decode("utf-8"))
    bodies = document.xpath(_ARTICLE_BODY_XPATH)
    if len(bodies) != 1:
        raise ValueError(f"resolution {number} has {len(bodies)} article bodies")
    rows = []
    for element in bodies[0].xpath(_ARTICLE_ELEMENTS_XPATH):
        text = _normalize_source_text(" ".join(element.itertext()))
        if text:
            rows.append(text)
    return rows


def _target_fragment(clause_text: str) -> str:
    literal = literal_words(clause_text)
    if "có tên gọi là" in literal:
        return literal.rsplit("có tên gọi là", 1)[1]
    if " thành " in f" {literal} ":
        return literal.rsplit(" thành ", 1)[1]
    raise ValueError(f"arrangement clause has no result marker: {clause_text!r}")


def _resolve_clause_target(clause_text: str, candidates: list[dict]) -> dict:
    fragment = _target_fragment(clause_text)
    literal_key = compact_literal(fragment)
    matches = [row for row in candidates if compact_literal(row["name_vi"]) == literal_key]
    if not matches:
        folded_key = compact_folded(fragment)
        matches = [row for row in candidates if compact_folded(row["name_vi"]) == folded_key]
    if len(matches) != 1:
        raise ValueError(
            f"clause target {fragment!r} resolved to "
            f"{[(row['code'], row['name_vi']) for row in matches]}"
        )
    return matches[0]


def extract_resolution_clauses(boundary: dict) -> tuple[list[dict], list[dict]]:
    """Extract Article 1 clauses and map every legal result to one post unit."""
    number_to_province, post_by_province = _successor_indexes(boundary)
    clauses = []
    targeted_codes = set()
    for record in resolution_records():
        number = record["number"]
        rows = _article_text_rows(number)
        article_two = next(
            (index for index, text in enumerate(rows) if fold_words(text).startswith("dieu 2")),
            None,
        )
        if article_two is None:
            raise ValueError(f"resolution {number} has no Article 2 boundary")
        for text in rows[:article_two]:
            match = _CLAUSE.match(text)
            if not match or fold_words(match.group(2)).startswith("sau khi sap xep"):
                continue
            target = _resolve_clause_target(text, post_by_province[number_to_province[number]])
            if target["code"] in targeted_codes:
                raise ValueError(f"multiple resolution clauses target {target['code']}")
            targeted_codes.add(target["code"])
            clauses.append({
                "resolution_code": record["code"],
                "resolution_number": number,
                "clause_number": int(match.group(1)),
                "successor_code": target["code"],
                "successor_name_vi": target["name_vi"],
                "successor_province_code": target["province_code"],
                "source_path": html_cache_relpath(number),
                "text": text,
            })

    notes_by_code = {row["successor_code"]: row for row in boundary["composition_notes"]}
    unchanged = []
    for row in boundary["observations"]["post"]:
        if row["code"] in targeted_codes:
            continue
        note = notes_by_code[row["code"]]
        folded_note = fold_words(note["note"])
        if "giu nguyen" not in folded_note or "khong" not in folded_note:
            raise ValueError(
                f"post unit {row['code']} has neither a legal clause nor an unchanged note"
            )
        unchanged.append({
            "successor_code": row["code"],
            "successor_name_vi": row["name_vi"],
            "successor_province_code": row["province_code"],
            "note": note["note"],
        })

    clauses.sort(key=lambda row: (row["resolution_number"], row["clause_number"]))
    unchanged.sort(key=lambda row: row["successor_code"])
    if len(clauses) != 3194 or len(unchanged) != 127:
        raise ValueError(
            f"resolution target gate failed: {len(clauses)} clauses, {len(unchanged)} unchanged"
        )
    return clauses, unchanged


def _token_phrase_hits(tokens: list[str], phrases: set[str]) -> list[tuple[int, int, str]]:
    hits = []
    for phrase in phrases:
        phrase_tokens = phrase.split()
        size = len(phrase_tokens)
        for start in range(len(tokens) - size + 1):
            if tokens[start:start + size] == phrase_tokens:
                hits.append((start, start + size, phrase))
    return hits


def _immediate_tier_tokens(folded: list[str], literal: list[str], start: int) -> str:
    if start >= 2 and literal[start - 2:start] == ["thị", "trấn"]:
        return "thi tran"
    if start and literal[start - 1] in {"xã", "phường"}:
        return folded[start - 1]
    return ""


def _in_district_context(literal: list[str], start: int) -> bool:
    if start and literal[start - 1] in {"huyện", "quận"}:
        return True
    return start >= 2 and literal[start - 2:start] in (
        ["thị", "xã"], ["thành", "phố"],
    )


def _active_tier_tokens(folded: list[str], literal: list[str], start: int) -> str:
    immediate = _immediate_tier_tokens(folded, literal, start)
    if immediate:
        return immediate
    for index in range(start - 1, -1, -1):
        if literal[index] in {"xã", "phường"}:
            return folded[index]
        if index and literal[index - 1:index + 1] == ["thị", "trấn"]:
            return "thi tran"
    return ""


def _source_portion(value: str, *, legal_clause: bool = False) -> tuple[str, str]:
    if legal_clause:
        value = re.sub(
            r"\s*thành\s*(?=(?:xã|phường|thị\s*trấn|đặc\s*khu))",
            " thành ",
            value,
            flags=re.IGNORECASE,
        )
    folded = fold_words(value)
    literal = literal_words(value)
    if legal_clause:
        folded_tokens = folded.split()
        literal_tokens = literal.split()
        if len(folded_tokens) != len(literal_tokens):
            raise ValueError(f"folded/literal source token counts diverged: {value!r}")
        result_starts = []
        for index, token in enumerate(literal_tokens[:-1]):
            if token != "thành":
                continue
            following = literal_tokens[index + 1:index + 3]
            if following[:1] in (["xã"], ["phường"]):
                result_starts.append(index)
            elif following in (["thị", "trấn"], ["đặc", "khu"]):
                result_starts.append(index)
        if not result_starts:
            raise ValueError(f"cannot isolate legal-clause result: {value!r}")
        result_start = result_starts[-1]
        folded = " ".join(folded_tokens[:result_start])
        literal = " ".join(literal_tokens[:result_start])
    return folded, literal


def _candidate_rows(boundary: dict) -> dict[str, list[dict]]:
    old_provinces_by_successor: dict[str, set[str]] = defaultdict(set)
    for row in boundary["structured_primary_links"]:
        old_provinces_by_successor[row["successor_province_code"]].add(
            row["predecessor_province_code"]
        )

    candidates_by_old_province: dict[str, list[dict]] = defaultdict(list)
    for row in boundary["observations"]["pre"]:
        candidates_by_old_province[row["province_code"]].append({
            **row,
            "folded_name": bare_ward_name(row["name_vi"]),
            "literal_name": literal_bare_ward_name(row["name_vi"]),
            "canonical_literal_name": canonical_literal_words(
                literal_bare_ward_name(row["name_vi"])
            ),
            "folded_tier": _candidate_tier(row["name_vi"]),
            "folded_parent": fold_words(row["parent_name_vi"]),
            "literal_parent": literal_words(row["parent_name_vi"]),
            "canonical_literal_parent": canonical_literal_words(row["parent_name_vi"]),
            "compact_literal_parent": compact_literal(
                canonical_literal_words(row["parent_name_vi"])
            ),
        })

    candidates_by_successor: dict[str, list[dict]] = {}
    for successor_province, old_provinces in old_provinces_by_successor.items():
        candidates_by_successor[successor_province] = [
            row
            for province in old_provinces
            for row in candidates_by_old_province[province]
        ]
    return candidates_by_successor


def _match_source_phrases(text: str, candidates: list[dict], *,
                          primary: dict | None = None,
                          legal_clause: bool = False) -> tuple[list[dict], list[dict]]:
    folded, literal = _source_portion(text, legal_clause=legal_clause)
    folded_tokens = folded.split()
    literal_tokens = literal.split()
    if len(folded_tokens) != len(literal_tokens):
        raise ValueError(f"folded/literal source token counts diverged: {text!r}")
    by_phrase: dict[str, list[dict]] = defaultdict(list)
    for candidate in candidates:
        by_phrase[candidate["folded_name"]].append(candidate)

    proposals = []
    for start, end, phrase in _token_phrase_hits(folded_tokens, set(by_phrase)):
        if _in_district_context(literal_tokens, start):
            continue
        if phrase == "tu nhien" and folded_tokens[max(0, start - 2):start] == [
            "dien", "tich",
        ]:
            continue
        options = by_phrase[phrase]
        immediate_tier = _immediate_tier_tokens(folded_tokens, literal_tokens, start)
        tier = _active_tier_tokens(folded_tokens, literal_tokens, start)
        tier_size = 2 if tier == "thi tran" else int(bool(tier))
        if (
            not legal_clause
            and tier_size
            and start > tier_size
            and folded_tokens[start - tier_size - 1] == "thanh"
        ):
            continue
        if phrase.isdigit() and not immediate_tier:
            continue
        if phrase in {"hop nhat", "sap nhap", "thanh lap"} and not immediate_tier:
            continue
        if (
            end < len(folded_tokens)
            and phrase.split()[-1] in {"hop", "sap", "thanh"}
            and folded_tokens[end] in {"nhat", "nhap", "lap"}
        ):
            continue
        if tier:
            tier_options = [row for row in options if row["folded_tier"] == tier]
            if tier_options:
                options = tier_options
        source_literal = " ".join(literal_tokens[start:end])
        canonical_source_literal = canonical_literal_words(source_literal)
        literal_options = [
            row for row in options
            if row["canonical_literal_name"] == canonical_source_literal
        ]
        if literal_options:
            options = literal_options
        else:
            proposals.append((start, end, phrase, [], "literal mismatch"))
            continue
        if len(options) > 1:
            compact_source_literal = compact_literal(canonical_literal_words(literal))
            parent_options = [
                row for row in options
                if f" {row['literal_parent']} " in f" {literal} "
                or f" {row['canonical_literal_parent']} "
                in f" {canonical_literal_words(literal)} "
                or row["compact_literal_parent"] in compact_source_literal
                or f" {row['folded_parent']} " in f" {folded} "
            ]
            if len(parent_options) == 1:
                options = parent_options
        if len(options) > 1 and primary:
            primary_options = [
                row for row in options if row["code"] == primary["predecessor_code"]
            ]
            if len(primary_options) == 1:
                options = primary_options

        if len(options) == 1:
            proposals.append((start, end, phrase, options, ""))
        else:
            proposals.append((start, end, phrase, options, "multiple candidates"))

    selected = []
    occupied: list[tuple[int, int]] = []
    for proposal in sorted(
        proposals,
        key=lambda row: (not bool(row[3]), -(row[1] - row[0]), row[0], row[2]),
    ):
        start, end = proposal[:2]
        if any(start < used_end and used_start < end for used_start, used_end in occupied):
            continue
        occupied.append((start, end))
        selected.append(proposal)

    resolved = []
    ambiguous = []
    for start, end, phrase, options, reason in sorted(selected):
        if len(options) == 1:
            resolved.append({
                "candidate": options[0],
                "matched_phrase": phrase,
                "source_token_span": [start, end],
            })
        else:
            ambiguous.append({
                "phrase": phrase,
                "source_token_span": [start, end],
                "candidate_codes": sorted(row["code"] for row in options),
                "reason": reason,
            })
    return resolved, ambiguous


def resolve_compositions(boundary: dict) -> dict:
    """Resolve legal clauses, unchanged notes, and curation into ward edges."""
    clauses, unchanged = extract_resolution_clauses(boundary)
    candidates_by_successor = _candidate_rows(boundary)
    primary_by_successor = {
        row["successor_code"]: row for row in boundary["structured_primary_links"]
    }
    pre_by_code = {row["code"]: row for row in boundary["observations"]["pre"]}

    edges: dict[tuple[str, str], dict] = {}
    ambiguous_mentions = []
    missing_primary_clause_mentions = []

    def add_edge(candidate: dict, successor_code: str, evidence: str,
                 clause: dict | None, match: dict | None = None) -> None:
        key = (candidate["code"], successor_code)
        row = edges.get(key)
        if row is None:
            row = {
                "predecessor_code": candidate["code"],
                "predecessor_name_vi": candidate["name_vi"],
                "successor_code": successor_code,
                "share": "pending topology audit",
                "primary": bool(
                    primary_by_successor.get(successor_code, {}).get("predecessor_code")
                    == candidate["code"]
                ),
                "evidence": [],
            }
            edges[key] = row
        evidence_row = {"kind": evidence}
        if clause:
            evidence_row.update({
                "resolution_code": clause["resolution_code"],
                "clause_number": clause["clause_number"],
                "source_path": clause["source_path"],
            })
        if match:
            evidence_row.update({
                "matched_phrase": match["matched_phrase"],
                "source_token_span": match["source_token_span"],
            })
        if evidence_row not in row["evidence"]:
            row["evidence"].append(evidence_row)

    for clause in clauses:
        successor = clause["successor_code"]
        primary = primary_by_successor.get(successor)
        candidates = candidates_by_successor[clause["successor_province_code"]]
        matches, ambiguous = _match_source_phrases(
            clause["text"], candidates, primary=primary, legal_clause=True,
        )
        for match in matches:
            add_edge(match["candidate"], successor, "resolution clause phrase", clause, match)
        ambiguous_mentions.extend({
            "successor_code": successor,
            "resolution_code": clause["resolution_code"],
            "clause_number": clause["clause_number"],
            **row,
        } for row in ambiguous)

        if (
            primary
            and primary["predecessor_code"] not in {match["candidate"]["code"] for match in matches}
        ):
            missing_primary_clause_mentions.append({
                "successor_code": successor,
                "predecessor_code": primary["predecessor_code"],
                "resolution_code": clause["resolution_code"],
                "clause_number": clause["clause_number"],
            })

        folded = fold_words(clause["text"])
        if "toan bo" in folded and "thuoc huyen" in folded and primary:
            district_rows = [
                row for row in candidates if row["parent_code"] == primary["predecessor_district_code"]
            ]
            for candidate in district_rows:
                add_edge(candidate, successor, "whole former district clause", clause)

    for row in unchanged:
        primary = primary_by_successor.get(row["successor_code"])
        if primary is None:
            raise ValueError(f"unchanged successor {row['successor_code']} has no primary link")
        add_edge(
            pre_by_code[primary["predecessor_code"]],
            row["successor_code"],
            "NSO unchanged-unit note",
            None,
        )

    for successor, primary in primary_by_successor.items():
        add_edge(
            pre_by_code[primary["predecessor_code"]],
            successor,
            "structured Xã DC link",
            None,
        )

    resolved_before_curation = {predecessor for predecessor, _ in edges}
    unresolved_before_curation = set(pre_by_code) - resolved_before_curation
    curation = json.loads(CURATION_PATH.read_text(encoding="utf-8"))
    if curation.get("schema_version") != 1:
        raise ValueError("unsupported ward-composition curation schema")
    mappings = curation.get("mappings", {})
    supplemental_mappings = curation.get("supplemental_mappings", {})
    if set(mappings) != unresolved_before_curation:
        missing = sorted(unresolved_before_curation - set(mappings))
        extra = sorted(set(mappings) - unresolved_before_curation)
        raise ValueError(
            f"composition curation drift; missing={missing}, extra={extra}"
        )
    if set(mappings) & set(supplemental_mappings):
        raise ValueError("curation predecessor cannot be both unresolved and supplemental")
    for predecessor, successors in supplemental_mappings.items():
        if predecessor not in resolved_before_curation:
            raise ValueError(
                f"supplemental predecessor {predecessor} was not already resolved"
            )
        if any((predecessor, successor) in edges for successor in successors):
            raise ValueError(f"supplemental curation for {predecessor} is redundant")
    clauses_by_successor = {row["successor_code"]: row for row in clauses}
    curated_edges = 0
    curated = {**mappings, **supplemental_mappings}
    for predecessor, successors in sorted(curated.items()):
        if not successors or len(successors) != len(set(successors)):
            raise ValueError(f"invalid curated successors for {predecessor}: {successors}")
        for successor in successors:
            clause = clauses_by_successor.get(successor)
            if clause is None:
                raise ValueError(f"curated successor {successor} has no resolution clause")
            allowed_codes = {
                row["code"] for row in candidates_by_successor[clause["successor_province_code"]]
            }
            if predecessor not in allowed_codes:
                raise ValueError(
                    f"curated edge {predecessor}→{successor} crosses resolution province scope"
                )
            add_edge(
                pre_by_code[predecessor], successor,
                "curated resolution-clause identity", clause,
            )
            curated_edges += 1

    successors_by_predecessor: dict[str, set[str]] = defaultdict(set)
    for predecessor, successor in edges:
        successors_by_predecessor[predecessor].add(successor)
    for (predecessor, _), row in edges.items():
        row["share"] = (
            "partial" if len(successors_by_predecessor[predecessor]) > 1 else "whole"
        )
        row["evidence"].sort(key=lambda item: (
            item["kind"], item.get("resolution_code", ""), item.get("clause_number", 0)
        ))

    unresolved_predecessors = [
        {
            "predecessor_code": code,
            "predecessor_name_vi": row["name_vi"],
            "predecessor_province_code": row["province_code"],
            "predecessor_district_code": row["parent_code"],
            "predecessor_district_name_vi": row["parent_name_vi"],
        }
        for code, row in sorted(pre_by_code.items())
        if code not in successors_by_predecessor
    ]
    edge_rows = sorted(
        edges.values(), key=lambda row: (row["predecessor_code"], row["successor_code"])
    )
    edge_keys = {
        (row["predecessor_code"], row["successor_code"]) for row in edge_rows
    }
    missing_primary_edges = [
        (row["predecessor_code"], row["successor_code"])
        for row in primary_by_successor.values()
        if (row["predecessor_code"], row["successor_code"]) not in edge_keys
    ]
    if missing_primary_edges:
        raise ValueError(f"composition omits primary links: {missing_primary_edges}")
    post_codes = {row["code"] for row in boundary["observations"]["post"]}
    creation_codes = post_codes - set(primary_by_successor)
    incoming_successors = {successor for _, successor in edge_keys}
    unlinked_successors = post_codes - incoming_successors
    if unlinked_successors != creation_codes:
        raise ValueError(
            "successors without ward predecessors differ from blank-base creations: "
            f"unlinked={sorted(unlinked_successors)}, creations={sorted(creation_codes)}"
        )
    if any(not row["evidence"] for row in edge_rows):
        raise ValueError("composition contains an edge without source evidence")
    share_counts = Counter(row["share"] for row in edge_rows)
    return {
        "audit": {
            "resolution_pairs": len(resolution_records()),
            "arrangement_clauses": len(clauses),
            "unchanged_successors": len(unchanged),
            "composition_edges": len(edge_rows),
            "resolved_predecessors": len(successors_by_predecessor),
            "unresolved_predecessors": len(unresolved_predecessors),
            "successors_without_ward_predecessor": len(unlinked_successors),
            "split_predecessors": sum(
                len(successors) > 1 for successors in successors_by_predecessor.values()
            ),
            "whole_edges": share_counts["whole"],
            "partial_edges": share_counts["partial"],
            "curated_predecessors": len(curated),
            "curated_edges": curated_edges,
            "ambiguous_mentions": len(ambiguous_mentions),
            "missing_primary_clause_mentions": len(missing_primary_clause_mentions),
        },
        "clauses": clauses,
        "unchanged_successors": unchanged,
        "edges": edge_rows,
        "residue": {
            "unresolved_predecessors": unresolved_predecessors,
        },
        "parser_diagnostics": {
            "ambiguous_mentions": ambiguous_mentions,
            "missing_primary_clause_mentions": missing_primary_clause_mentions,
        },
    }


def build_2025_compositions(boundary: dict | None = None) -> dict:
    boundary = boundary or build_2025_boundary()
    resolved = resolve_compositions(boundary)
    sources = list(boundary["sources"])
    for record in resolution_records():
        sources.extend((
            _source_descriptor(pdf_cache_relpath(record["number"])),
            _source_descriptor(html_cache_relpath(record["number"])),
        ))
    return {
        "schema_version": 1,
        "scope": "Vietnam ward composition at the 2025-07-01 boundary",
        "effective_date": "2025-07-01",
        "lineage_completeness": (
            "complete" if not resolved["residue"]["unresolved_predecessors"]
            else "explicit predecessor-resolution residue remains"
        ),
        "sources": sources,
        "curation": {
            "path": CURATION_PATH.as_posix(),
            "sha256": hashlib.sha256(CURATION_PATH.read_bytes()).hexdigest(),
        },
        **resolved,
    }


def write_2025_compositions(
        path: str | Path = "data/ward-2025-composition.json") -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(build_2025_compositions(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination
