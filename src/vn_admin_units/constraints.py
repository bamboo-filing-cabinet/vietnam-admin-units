"""Check a Wikidata property's *allowed-qualifiers* constraint — the pre-upload
gate for our batch (we saw this bite with P1107 on P39, journal .07).

Wikidata constraints are advisory (QuickStatements still applies violating
statements), but emitting statements that violate a property's allowed-qualifiers
constraint is bad citizenship and produces violation reports. This tool reports,
per property, which qualifier properties are allowed and whether the ones we use
(notably P585 point-in-time) are among them.

Run: uv run python -m vn_admin_units.constraints         # defaults to our batch's props
     uv run python -m vn_admin_units.constraints P1365 P7888
"""
import sys
import urllib.parse

from vn_admin_units.reconcile import _get_json  # canonical, backoff-aware

ALLOWED_QUALIFIERS = "Q21510851"   # "allowed qualifiers constraint"
PROPERTY_CONSTRAINT = "P2302"
QUALIFIER_PROPERTY = "P2306"       # "property" qualifier listing the allowed qualifier

# properties our province batch emits, and the qualifier we attach
BATCH_PROPS = ["P576", "P571", "P7888", "P1366", "P1365"]
OUR_QUALIFIER = "P585"             # point in time


def _allowed_from_claims(claims: list) -> set | None:
    """Allowed qualifier P-ids from a property's P2302 claims.
    None = no allowed-qualifiers constraint declared (⇒ any qualifier is fine)."""
    declared = False
    allowed: set[str] = set()
    for c in claims:
        val = c.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if not (isinstance(val, dict) and val.get("id") == ALLOWED_QUALIFIERS):
            continue
        declared = True
        for q in c.get("qualifiers", {}).get(QUALIFIER_PROPERTY, []):
            dv = q.get("datavalue", {}).get("value", {})
            if isinstance(dv, dict) and dv.get("id"):
                allowed.add(dv["id"])
    return allowed if declared else None


def allowed_qualifiers(pid: str, timeout: int = 30) -> set | None:
    u = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode({
        "action": "wbgetentities", "ids": pid, "props": "claims", "format": "json"})
    claims = _get_json(u, timeout)["entities"][pid].get("claims", {}).get(PROPERTY_CONSTRAINT, [])
    return _allowed_from_claims(claims)


def main(argv: list[str] | None = None) -> None:
    pids = (argv if argv is not None else sys.argv[1:]) or BATCH_PROPS
    print(f"Checking allowed-qualifiers for {pids}; our qualifier = {OUR_QUALIFIER}\n")
    for pid in pids:
        aq = allowed_qualifiers(pid)
        if aq is None:
            verdict = "OK (no allowed-qualifiers constraint → any qualifier fine)"
        elif OUR_QUALIFIER in aq:
            verdict = f"OK ({OUR_QUALIFIER} is allowed)"
        else:
            verdict = f"VIOLATION ({OUR_QUALIFIER} NOT in allowed set)"
        print(f"  {pid}: {verdict}")
        if aq is not None:
            print(f"       allowed: {sorted(aq)}")


if __name__ == "__main__":
    main()
