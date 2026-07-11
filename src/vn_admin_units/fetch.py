"""Reliable, reusable CLI to fetch raw admin-unit data at any tier/date.

Use this instead of ad-hoc scripts — it goes through the one canonical
parser (soap.parse_rows, DocumentElement-scoped) so counts are consistent.

Examples:
  uv run python -m vn_admin_units.fetch --tier ward --date 01/01/2019 --stats
  uv run python -m vn_admin_units.fetch --tier province --date 10/07/2026 --json
"""
import argparse
import json
from collections import Counter

from vn_admin_units.soap import TIERS, fetch_units


def code_stats(rows: list[dict], tier: str) -> dict:
    """Row/distinct/duplicate counts for a tier's code field."""
    code_field = TIERS[tier][2]
    codes = [r[code_field] for r in rows]
    dup_codes = {c: n for c, n in Counter(codes).items() if n > 1}
    return {"rows": len(rows), "distinct": len(set(codes)),
            "duplicates": len(codes) - len(set(codes)), "dup_codes": dup_codes}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Fetch raw admin-unit data (any tier/date).")
    ap.add_argument("--tier", choices=list(TIERS), required=True)
    ap.add_argument("--date", required=True, help="as-of date, dd/mm/yyyy")
    ap.add_argument("--tinh", default="", help="province code (district/ward tiers; empty = all)")
    ap.add_argument("--quan-huyen", default="", help="district code (ward tier; empty = all)")
    ap.add_argument("--json", action="store_true", help="print rows as JSON")
    ap.add_argument("--stats", action="store_true", help="also list duplicate codes")
    a = ap.parse_args(argv)
    rows = fetch_units(a.tier, a.date, a.tinh, a.quan_huyen)
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    st = code_stats(rows, a.tier)
    print(f"{a.tier} @ {a.date}: rows={st['rows']} distinct_codes={st['distinct']} "
          f"duplicates={st['duplicates']}")
    if a.stats and st["dup_codes"]:
        cf = TIERS[a.tier][2]
        for code in list(st["dup_codes"])[:15]:
            names = [r.get("TenPhuongXa") or r.get("TenQuanHuyen") or r.get("TenTinh")
                     for r in rows if r[cf] == code]
            print(f"  dup {code}: {names}")


if __name__ == "__main__":
    main()
