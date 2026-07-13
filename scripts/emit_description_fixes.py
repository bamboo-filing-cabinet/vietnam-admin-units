"""Generate QuickStatements to normalize Wikidata descriptions for Vietnam provinces.

Reads:
  - mappings/provinces-qid.csv  (which QIDs are pre2025-only = dissolved)
  - data/province-descriptions.csv  (current descriptions from Wikidata)

Outputs:
  - statements/description-fixes.qs  (QuickStatements V1 commands)

Rules:
  - Dissolved provinces (appear in pre2025 but NOT post2025): "former province of Vietnam"
  - Surviving provinces: "province of Vietnam"
  - Municipalities (thành phố): left alone (already varied: "capital", "largest city", etc.)
  - Only emits a statement if the current description differs from the target.

Usage:
    uv run python scripts/emit_description_fixes.py
"""

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAPPING = ROOT / "mappings" / "provinces-qid.csv"
DESCRIPTIONS = ROOT / "data" / "province-descriptions.csv"
OUTPUT = ROOT / "statements" / "description-fixes.qs"


def load_mapping() -> tuple[set[str], set[str], dict[str, str]]:
    """Returns (dissolved_qids, survivor_qids, qid_to_name_vi).

    qid_to_name uses the post2025 name if available (reflects current status),
    falling back to pre2025.
    """
    rows = list(csv.DictReader(MAPPING.read_text(encoding="utf-8").splitlines()))

    pre_qids = {r["wikidata_qid"] for r in rows if r["era"] == "pre2025"}
    post_qids = {r["wikidata_qid"] for r in rows if r["era"] == "post2025"}
    dissolved = pre_qids - post_qids
    survivors = pre_qids & post_qids

    qid_to_name = {}
    for r in rows:
        # post2025 name takes precedence (reflects current administrative status)
        if r["era"] == "post2025" or r["wikidata_qid"] not in qid_to_name:
            qid_to_name[r["wikidata_qid"]] = r["name_vi"]

    return dissolved, survivors, qid_to_name


def load_descriptions() -> dict[str, dict]:
    """QID -> {description_en, description_vi, name_vi, era}. Deduped to one per QID."""
    rows = list(csv.DictReader(DESCRIPTIONS.read_text(encoding="utf-8").splitlines()))
    by_qid = {}
    for r in rows:
        # prefer pre2025 row (that's the one whose description might be wrong)
        if r["wikidata_qid"] not in by_qid or r["era"] == "pre2025":
            by_qid[r["wikidata_qid"]] = r
    return by_qid


def is_municipality(name_vi: str) -> bool:
    return name_vi.startswith("Thành phố")


def target_description_en(qid: str, dissolved: set, survivors: set, name_vi: str) -> str | None:
    """Return the target English description, or None to skip (no change needed)."""
    if is_municipality(name_vi):
        return None  # municipalities have varied descriptions, leave alone
    if qid in dissolved:
        return "former province of Vietnam"
    if qid in survivors:
        return "province of Vietnam"
    return None


def needs_fix(current: str, target: str) -> bool:
    """True if current doesn't match target (case-sensitive, exact match)."""
    return current.strip() != target


def main():
    dissolved, survivors, qid_to_name = load_mapping()
    descriptions = load_descriptions()

    lines = []
    fixes = []

    for qid, desc_row in sorted(descriptions.items()):
        name_vi = qid_to_name.get(qid, desc_row.get("name_vi", ""))
        current_en = desc_row["description_en"]

        target_en = target_description_en(qid, dissolved, survivors, name_vi)
        if target_en is None:
            continue
        if not needs_fix(current_en, target_en):
            continue

        # QuickStatements V1: Dlang"value"
        lines.append(f'{qid}\tDen\t"{target_en}"')
        fixes.append((qid, name_vi, current_en, target_en))

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    if lines:
        OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        OUTPUT.write_text("", encoding="utf-8")

    print(f"Generated {len(lines)} description fixes -> {OUTPUT}")
    print()
    if fixes:
        print(f"{'QID':<12} {'Name':<30} {'Current':<50} → Target")
        print("-" * 120)
        for qid, name, current, target in fixes:
            print(f"{qid:<12} {name:<30} {current:<50} → {target}")
    else:
        print("All descriptions already match. Nothing to fix.")


if __name__ == "__main__":
    main()
