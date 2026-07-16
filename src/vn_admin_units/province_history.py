"""Phase 1b — province-tier history 2002→2025 (entity + lineage assembly).

Continuous-entity model: one Entity per province across recode/retype; carve-out
children and the ended Hà Tây are their own entities. Kept separate from the 1a
`model.py` (which hardcodes the 2025 eras); the shared shape is a Phase-2 refactor
target, not an import. See docs/DESIGN-phase1b.md.
"""
import json
from pathlib import Path
from typing import Optional

from vn_admin_units.core import Entity, LineageEdge
from vn_admin_units.names import fold_name
from vn_admin_units.crosswalk import read_province_history_crosswalk

# Curated province retypes (province -> centrally-run city): SAME entity, dated P31.
# The effective date + decree aren't in the terminal snapshot, so name them here.
# Covers Cần Thơ (2004, NQ22 LEGAL date) and Huế (2025, also a rename).
RETYPES = [
    {"code": "92", "old_name": "Tỉnh Cần Thơ", "date": "2004-01-01",
     "decree": "Số: 22/2003/QH11; Ngày: 26/11/2003",
     "reference_url": "https://thuvienphapluat.vn/van-ban/Bo-may-hanh-chinh/Nghi-quyet-22-2003-QH11-chia-va-dieu-chinh-dia-gioi-hanh-chinh-tinh-51694.aspx"},
    {"code": "46", "old_name": "Tỉnh Thừa Thiên Huế", "date": "2025-01-01",
     "decree": "Số: 175/2024/QH15; Ngày: 30/11/2024",
     "reference_url": "https://thuvienphapluat.vn/van-ban/Bo-may-hanh-chinh/Nghi-quyet-175-2024-QH15-thanh-lap-thanh-pho-Hue-truc-thuoc-trung-uong-634162.aspx"},
]

# The 2008 Hà Tây absorption resolution (verified 2026-07-14 via web search).
HA_TAY_2008 = {
    "decree": "Số: 15/2008/QH12; Ngày: 29/05/2008",
    "reference_url": "https://thuvienphapluat.vn/van-ban/Bat-dong-san/Nghi-quyet-15-2008-QH12-dieu-chinh-dia-gioi-hanh-chinh-thanh-pho-Ha-Noi-va-mot-so-tinh-co-lien-quan-68076.aspx",
}


def diff_roster(before: list, after: list) -> dict:
    """Code-keyed diff of two ADJACENT-year province snapshots (same code-era, so
    codes are stable). Same code + changed type = retype; same code + changed folded
    name = rename — both SAME entity (catches Huế: Thừa Thiên Huế→Huế, code 46), NOT
    dissolve+create. 'Hoà'/'Hòa' orthography folds equal → no event. NOT valid across
    the 2004 renumber (codes change there — that boundary is handled by the Đối Chiếu
    remap window + carve-out decree, not this diff)."""
    b = {r["ma"]: r for r in before}
    a = {r["ma"]: r for r in after}
    created = sorted(a[k]["ten"] for k in a.keys() - b.keys())
    dissolved = sorted(b[k]["ten"] for k in b.keys() - a.keys())
    retyped, renamed = [], []
    for k in a.keys() & b.keys():
        if b[k]["loai_hinh"] != a[k]["loai_hinh"]:
            retyped.append({"from": b[k]["ten"], "to": a[k]["ten"],
                            "loai_hinh_from": b[k]["loai_hinh"], "loai_hinh_to": a[k]["loai_hinh"]})
        elif fold_name(b[k]["ten"]) != fold_name(a[k]["ten"]):
            renamed.append({"from": b[k]["ten"], "to": a[k]["ten"]})
    return {"created": created, "dissolved": dissolved, "retyped": retyped, "renamed": renamed}


def load_carve_outs(path: str = "data/decrees/2004-splits.json") -> dict:
    """The curated 2004 carve-out pairings + decree/reference (parentage the GSO
    Đối Chiếu omits below the 2004 floor)."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def hist_local_id(first_code: str, valid_from: Optional[str]) -> str:
    """Entity-anchored id: first-known code + inception ('base' if pre-2004 root).
    Codes reuse across reforms and the scheme changes at 2004 (journal .15), so the
    bare code is never a key; valid_from disambiguates reused codes."""
    return f"ph-{first_code}-{valid_from or 'base'}"


def _load_json(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_province_history(snapshot_dir: str, window_dir: str,
                           carve_outs_path: str, seed_1a: str):
    """Assemble the 2002→2025 province entity+lineage graph.

    Spine = the 1a pre-reform (2025-06-30) roster: one continuous Entity per
    surviving/absorbed province. Enrich each with earlier codes (2004 renumber →
    alias), retype spans, and valid_from; add the ended Hà Tây; attach the 2004
    carve-out edges from the decree and the 2008 absorption from the window."""
    terminal = _load_json(f"{snapshot_dir}/provinces-2025-06-30.json")      # 63 rows
    co = load_carve_outs(carve_outs_path)
    carve_child_codes = {c["child_code"] for c in co["carve_outs"]}

    # 2004 renumber map: old 3-digit -> new 2-digit, by folded name, from the window
    # whose COMPARE date is post-30/06/2004 (base 2004-01-01 → compare 2005-01-01;
    # a 2002→2004 window is pre-switch and shows no renumber).
    renumber = {}   # folded name -> {"old": code3, "new": code2}
    for row in read_province_history_crosswalk(f"{window_dir}/province_2004-01-01_2005-01-01.xls"):
        if row["base_ma"] and row["succ_ma"] and row["base_ma"] != row["succ_ma"]:
            renumber[fold_name(row["base_ten"])] = {"old": row["base_ma"], "new": row["succ_ma"]}

    retype_by_code = {rt["code"]: rt for rt in RETYPES}
    ents: list[Entity] = []
    by_code: dict[str, Entity] = {}
    for r in terminal:
        code2 = r["ma"]
        fn = fold_name(r["ten"])
        old3 = renumber.get(fn, {}).get("old")
        # Renamed retype (Huế): the renumber map is keyed by the OLD name, so the
        # terminal-name lookup misses. Recover the pre-2004 code via old_name HERE,
        # before the Entity is built, so gso_codes AND local_id use the first-known code.
        rt = retype_by_code.get(code2)
        if old3 is None and rt and fold_name(rt["old_name"]) != fn:
            old3 = renumber.get(fold_name(rt["old_name"]), {}).get("old")
        gso_codes = [old3, code2] if old3 else [code2]
        aliases = [old3] if old3 else []
        is_child = code2 in carve_child_codes
        vf = co["effective_date"] if is_child else None
        e = Entity(local_id=hist_local_id(gso_codes[0], vf), gso_codes=gso_codes,
                   name_vi=r["ten"], loai_hinh=r["loai_hinh"],
                   type_spans=[{"loai_hinh": r["loai_hinh"], "from": vf, "to": "2025-06-30"}],
                   aliases=aliases, valid_from=vf, valid_to="2025-06-30",
                   wikidata_qid=None, qid_status=None)
        ents.append(e)
        by_code[code2] = e

    edges: list[LineageEdge] = []

    # 2004 carve-outs: child (already in ents) carved_from parent; both from decree.
    for c in co["carve_outs"]:
        child, parent = by_code.get(c["child_code"]), by_code.get(c["parent_code"])
        if child and parent:
            edges.append(LineageEdge(parent.local_id, child.local_id, "carved_from",
                                     decree=co["decree"], effective_date=co["effective_date"],
                                     reference_url=co["reference_url"]))

    # Retypes (province -> centrally-run city): SAME entity, dated P31. Setting the
    # terminal span's `from` to the retype date is what makes the dated P31 emit.
    for rt in RETYPES:
        e = by_code.get(rt["code"])
        if not e:
            continue
        e.type_spans[-1]["from"] = rt["date"]
        e.type_spans[-1]["decree"] = rt["decree"]
        e.type_spans[-1]["reference_url"] = rt["reference_url"]
        # the prior province span ENDS (P582) at the retype date; same decree bounds both.
        e.type_spans = [{"loai_hinh": "Tỉnh", "from": None, "to": rt["date"],
                         "decree": rt["decree"], "reference_url": rt["reference_url"]}] + e.type_spans
        # former name -> alias. Compare LITERALLY (NFC), not by folded bare-place name:
        # "Tỉnh Cần Thơ" and "Thành phố Cần Thơ" fold equal but are distinct former names.
        if rt["old_name"] != e.name_vi:
            e.aliases.append(rt["old_name"])

    # 2008 Hà Tây absorption: Hà Tây is NOT in the 2025 roster -> add it, ended.
    ht_window = read_province_history_crosswalk(f"{window_dir}/province_2008-01-01_2009-01-01.xls")
    ht = next((r for r in ht_window if fold_name(r["base_ten"]) == "ha tay"), None)
    if ht:
        ht_e = Entity(local_id=hist_local_id(ht["base_ma"], None), gso_codes=[ht["base_ma"]],
                      name_vi=ht["base_ten"], loai_hinh="Tỉnh",
                      type_spans=[{"loai_hinh": "Tỉnh", "from": None, "to": "2008-07-31"}],
                      aliases=[], valid_from=None, valid_to="2008-07-31",
                      wikidata_qid=None, qid_status=None)
        ents.append(ht_e)
        ha_noi = by_code.get("01")
        if ha_noi:
            edges.append(LineageEdge(ht_e.local_id, ha_noi.local_id, "absorbed_into",
                                     decree=HA_TAY_2008["decree"], effective_date="2008-08-01",
                                     reference_url=HA_TAY_2008["reference_url"]))

    return ents, edges
