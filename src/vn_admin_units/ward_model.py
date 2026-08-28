"""Verified 2025 ward-boundary observations and structured lineage evidence.

This is intentionally narrower than the eventual ward history graph. It builds
the source-backed observation spine and preserves the old→new crosswalk's
unambiguous primary links, while keeping the 6,719 absorbed predecessors as
explicit composition residue. See docs/plans/2026-08-28-phase3-ward-2025-boundary.md.
"""
from __future__ import annotations

import io
import json
import re
import unicodedata
from pathlib import Path

from vn_admin_units.crosswalk import read_ward_crosswalk
from vn_admin_units.rawcache import manifest_entry, raw_is_verified, read_raw
from vn_admin_units.soap import TIERS, parse_rows


EFFECTIVE_DATE = "2025-07-01"
PRE_DATE = "2025-06-30"
POST_DATE = "2025-07-01"
PRE_SNAPSHOT = f"soap/DanhMucPhuongXa_{PRE_DATE}.xml.gz"
POST_SNAPSHOT = f"soap/DanhMucPhuongXa_{POST_DATE}.xml.gz"
PRIMARY_CROSSWALK = "crosswalk/ward_2025-06-30_2025-07-01.xls"
COMPOSITION_CROSSWALK = "crosswalk/ward_2025-07-01_2026-08-27.xls"

WARD_FIELDS = tuple(TIERS["ward"][1])
IDENTITY_FIELDS = ("MaTinh", "MaQuanHuyen", "MaPhuongXa")
_NOTE_SUFFIX = ". Bỏ cấp huyện"


def normalize_text(value: str) -> str:
    """NFC-normalize and collapse source whitespace without folding diacritics."""
    return unicodedata.normalize("NFC", re.sub(r"\s+", " ", str(value))).strip()


def _normalized_row(row: dict) -> dict:
    return {field: normalize_text(row.get(field, "")) for field in WARD_FIELDS}


def normalize_snapshot(rows: list[dict]) -> tuple[list[dict], dict]:
    """Normalize and exact-dedupe one SOAP roster; reject identity conflicts.

    NSO sometimes repeats an identical ``TABLE`` row. Those repetitions carry no
    new observation and are collapsed. Two different normalized rows for the
    same province/district/ward key are not guessed through: the caller gets a
    hard failure with the conflicting key.
    """
    by_identity: dict[tuple[str, str, str], dict] = {}
    duplicate_rows = 0
    for source_row in rows:
        row = _normalized_row(source_row)
        key = tuple(row[field] for field in IDENTITY_FIELDS)
        if not all(key):
            raise ValueError(f"ward snapshot has an incomplete identity key: {key}")
        previous = by_identity.get(key)
        if previous is None:
            by_identity[key] = row
        elif previous == row:
            duplicate_rows += 1
        else:
            changed = [field for field in WARD_FIELDS if previous[field] != row[field]]
            raise ValueError(
                f"conflicting ward snapshot rows for {key}; differing fields: {changed}"
            )

    normalized = sorted(by_identity.values(), key=lambda row: tuple(row[f] for f in IDENTITY_FIELDS))
    metrics = {
        "source_rows": len(rows),
        "normalized_rows": len(normalized),
        "exact_duplicate_rows_collapsed": duplicate_rows,
        "distinct_codes": len({row["MaPhuongXa"] for row in normalized}),
        "missing_district_codes": sum(not row["MaQuanHuyen"] for row in normalized),
    }
    return normalized, metrics


def _verified_source(relpath: str) -> bytes:
    if not raw_is_verified(relpath):
        raise ValueError(f"required raw source is missing or failed verification: {relpath}")
    return read_raw(relpath)


def load_snapshot(relpath: str) -> tuple[list[dict], dict]:
    source = _verified_source(relpath).decode("utf-8")
    return normalize_snapshot(parse_rows(source, list(WARD_FIELDS)))


def load_crosswalk(relpath: str) -> list[dict]:
    return read_ward_crosswalk(io.BytesIO(_verified_source(relpath)))


def _source_descriptor(relpath: str) -> dict:
    entry = manifest_entry(relpath)
    if entry is None or not raw_is_verified(relpath):
        raise ValueError(f"required raw source is missing or failed verification: {relpath}")
    return {
        "path": relpath,
        "sha256": entry["sha256"],
        "content_sha256": entry.get("content_sha256", entry["sha256"]),
        "params": entry.get("params", {}),
        "rows": entry.get("rows"),
    }


def _observation(row: dict, as_of: str, parent_tier: str,
                 province_code: str | None = None,
                 province_name: str | None = None) -> dict:
    province_code = province_code or row["MaTinh"]
    province_name = province_name or row["TenTinh"]
    parent_code = row["MaQuanHuyen"] if parent_tier == "district" else row["MaTinh"]
    parent_name = row["TenQuanHuyen"] if parent_tier == "district" else row["TenTinh"]
    return {
        "as_of": as_of,
        "code": row["MaPhuongXa"],
        "name_vi": row["TenPhuongXa"],
        "loai_hinh": row["LoaiHinh"],
        "province_code": province_code,
        "province_name_vi": province_name,
        # DanhMucPhuongXa historically echoes the current province row into old
        # snapshots. Preserve that raw observation while using the date-correct
        # crosswalk province above (999 code and 159 label differences here).
        "soap_province_code_echo": row["MaTinh"],
        "soap_province_name_echo": row["TenTinh"],
        "parent_tier": parent_tier,
        "parent_code": parent_code,
        "parent_name_vi": parent_name,
    }


def _note_hit_source_limit(note: str) -> bool:
    """Whether the narrative portion hit the export's observed 255-char cap."""
    core = note[:-len(_NOTE_SUFFIX)] if note.endswith(_NOTE_SUFFIX) else note
    return len(core) == 255


def _require_unique_codes(rows: list[dict], label: str) -> dict[str, dict]:
    out = {}
    for row in rows:
        code = row["MaPhuongXa"]
        if code in out:
            raise ValueError(f"{label} contains duplicate national ward code {code}")
        out[code] = row
    return out


def build_2025_boundary() -> dict:
    """Build deterministic observations + primary-link evidence for the reform."""
    pre_rows, pre_metrics = load_snapshot(PRE_SNAPSHOT)
    post_rows, post_metrics = load_snapshot(POST_SNAPSHOT)
    boundary_rows = load_crosswalk(PRIMARY_CROSSWALK)
    composition_rows = load_crosswalk(COMPOSITION_CROSSWALK)

    pre_by_code = _require_unique_codes(pre_rows, PRE_DATE)
    post_by_code = _require_unique_codes(post_rows, POST_DATE)

    boundary_by_base = {row["base_ma"]: row for row in boundary_rows if row["base_ma"]}
    if len(boundary_by_base) != len(pre_by_code) or set(boundary_by_base) != set(pre_by_code):
        raise ValueError("boundary crosswalk does not provide one base row per pre SOAP code")

    if any(row["MaQuanHuyen"] != row["MaTinh"] for row in post_rows):
        raise ValueError("post-reform SOAP has a ward pseudo-parent code unlike its province code")

    composition_by_code = {}
    composition_notes = []
    for row in composition_rows:
        code = row["base_ma"]
        if not code or code in composition_by_code:
            raise ValueError(f"composition crosswalk has missing/duplicate base code: {code!r}")
        note = normalize_text(row["ghi_chu"])
        if not note:
            raise ValueError(f"composition crosswalk has an empty note for {code}")
        composition_by_code[code] = row
        composition_notes.append({
            "successor_code": code,
            "successor_name_vi": normalize_text(row["base_ten"]),
            "successor_province_code": row["base_tinh"],
            "decree_raw": normalize_text(row["base_nghi_dinh"]),
            "effective_date": row["base_hieu_luc"],
            "note": note,
            "source_text_at_255_char_limit": _note_hit_source_limit(row["ghi_chu"]),
        })

    if set(composition_by_code) != set(post_by_code):
        missing = sorted(set(post_by_code) - set(composition_by_code))
        extra = sorted(set(composition_by_code) - set(post_by_code))
        raise ValueError(f"composition/POST code mismatch; missing={missing[:5]}, extra={extra[:5]}")

    corrections = []
    for code, row in post_by_code.items():
        if row["TenPhuongXa"]:
            continue
        replacement = normalize_text(composition_by_code[code]["base_ten"])
        if not replacement:
            raise ValueError(f"post-reform ward {code} has no name in SOAP or crosswalk")
        row["TenPhuongXa"] = replacement
        corrections.append({
            "code": code,
            "field": "TenPhuongXa",
            "reason": "blank in post-reform SOAP; filled from official NSO composition crosswalk",
            "source_path": COMPOSITION_CROSSWALK,
            "source_value": replacement,
        })

    primary_links = []
    creations = []
    absorbed_without_target = []
    seen_base = set()
    seen_successor = set()
    for row in boundary_rows:
        base_code, successor_code = row["base_ma"], row["succ_ma"]
        if base_code:
            if base_code in seen_base:
                raise ValueError(f"boundary crosswalk repeats base code {base_code}")
            seen_base.add(base_code)
            predecessor = pre_by_code.get(base_code)
            if predecessor is None:
                raise ValueError(f"boundary predecessor {base_code} is absent from pre SOAP")
        else:
            predecessor = None

        if successor_code:
            if successor_code in seen_successor:
                raise ValueError(f"boundary crosswalk repeats successor code {successor_code}")
            seen_successor.add(successor_code)
            successor = post_by_code.get(successor_code)
            if successor is None:
                raise ValueError(f"boundary successor {successor_code} is absent from post SOAP")
            if successor["MaTinh"] != row["succ_tinh"]:
                raise ValueError(f"boundary successor province mismatch for {successor_code}")
            if row["succ_hieu_luc"] != EFFECTIVE_DATE:
                raise ValueError(
                    f"boundary successor {successor_code} has effective date {row['succ_hieu_luc']!r}"
                )
        else:
            successor = None

        if predecessor and successor:
            primary_links.append({
                "predecessor_code": base_code,
                "predecessor_name_vi": predecessor["TenPhuongXa"],
                "predecessor_province_code": row["base_tinh"],
                "predecessor_district_code": predecessor["MaQuanHuyen"],
                "successor_code": successor_code,
                "successor_name_vi": successor["TenPhuongXa"],
                "successor_province_code": successor["MaTinh"],
                "effective_date": EFFECTIVE_DATE,
                "decree_raw": normalize_text(row["succ_nghi_dinh"]),
                "evidence": "structured Xã DC link",
            })
        elif successor:
            creations.append({
                "successor_code": successor_code,
                "successor_name_vi": successor["TenPhuongXa"],
                "successor_province_code": successor["MaTinh"],
                "effective_date": EFFECTIVE_DATE,
                "decree_raw": normalize_text(row["succ_nghi_dinh"]),
                "evidence": "blank base side in ward crosswalk",
            })
        elif predecessor:
            absorbed_without_target.append({
                "predecessor_code": base_code,
                "predecessor_name_vi": predecessor["TenPhuongXa"],
                "predecessor_province_code": row["base_tinh"],
                "predecessor_district_code": predecessor["MaQuanHuyen"],
                "predecessor_district_name_vi": predecessor["TenQuanHuyen"],
                "status": "target requires composition-note resolution",
            })
        else:
            raise ValueError("boundary crosswalk row has neither a base nor successor code")

    if seen_base != set(pre_by_code) or seen_successor != set(post_by_code):
        raise ValueError("boundary crosswalk does not cover the complete pre/post SOAP code sets")

    composition_notes.sort(key=lambda row: row["successor_code"])
    primary_links.sort(key=lambda row: row["predecessor_code"])
    creations.sort(key=lambda row: row["successor_code"])
    absorbed_without_target.sort(key=lambda row: row["predecessor_code"])
    pre_observations = [
        _observation(
            row,
            PRE_DATE,
            "district",
            province_code=boundary_by_base[row["MaPhuongXa"]]["base_tinh"],
            province_name=normalize_text(boundary_by_base[row["MaPhuongXa"]]["base_tinh_ten"]),
        )
        for row in pre_rows
    ]
    post_observations = [_observation(row, POST_DATE, "province") for row in post_rows]

    audit = {
        "pre": pre_metrics,
        "post": post_metrics,
        "boundary_crosswalk_rows": len(boundary_rows),
        "composition_crosswalk_rows": len(composition_rows),
        "structured_primary_links": len(primary_links),
        "blank_base_creations": len(creations),
        "absorbed_without_structured_target": len(absorbed_without_target),
        "composition_notes": len(composition_notes),
        "composition_notes_at_255_char_source_limit": sum(
            row["source_text_at_255_char_limit"] for row in composition_notes
        ),
        "source_backed_corrections": len(corrections),
        "pre_soap_province_echo_code_mismatches": sum(
            row["MaTinh"] != boundary_by_base[row["MaPhuongXa"]]["base_tinh"]
            for row in pre_rows
        ),
        "pre_soap_province_echo_name_mismatches": sum(
            row["TenTinh"]
            != normalize_text(boundary_by_base[row["MaPhuongXa"]]["base_tinh_ten"])
            for row in pre_rows
        ),
    }
    expected = {
        "pre_rows": 10035,
        "post_rows": 3321,
        "boundary_rows": 10040,
        "primary_links": 3316,
        "creations": 5,
        "absorbed": 6719,
        "composition_notes": 3321,
    }
    actual = {
        "pre_rows": len(pre_rows),
        "post_rows": len(post_rows),
        "boundary_rows": len(boundary_rows),
        "primary_links": len(primary_links),
        "creations": len(creations),
        "absorbed": len(absorbed_without_target),
        "composition_notes": len(composition_notes),
    }
    if actual != expected:
        raise ValueError(f"2025 ward boundary count gate failed: actual={actual}, expected={expected}")

    return {
        "schema_version": 1,
        "scope": "Vietnam ward boundary 2025-06-30 to 2025-07-01",
        "effective_date": EFFECTIVE_DATE,
        "lineage_completeness": "structured primary links only; composition resolution pending",
        "sources": [
            _source_descriptor(path)
            for path in (PRE_SNAPSHOT, POST_SNAPSHOT, PRIMARY_CROSSWALK, COMPOSITION_CROSSWALK)
        ],
        "audit": audit,
        "corrections": corrections,
        "observations": {"pre": pre_observations, "post": post_observations},
        "structured_primary_links": primary_links,
        "post_units_without_ward_predecessor": creations,
        "composition_notes": composition_notes,
        "composition_residue": {
            "absorbed_predecessors_without_structured_target": absorbed_without_target,
        },
    }


def write_2025_boundary(path: str | Path = "data/ward-2025-boundary.json") -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(build_2025_boundary(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination
