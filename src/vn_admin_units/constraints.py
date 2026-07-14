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


# ── Phase 1b additions ──

PHASE1B_CHECKS = [("P31", "P580"), ("P31", "P582"), ("P7888", "P585"),
                  ("P1365", "P585"), ("P1366", "P585")]


def qualifier_allowed(allowed: set | None, qualifier_pid: str) -> bool:
    """True if `qualifier_pid` is permitted: None = no allowed-qualifiers constraint
    declared (anything allowed); otherwise membership in the allowed set."""
    return True if allowed is None else qualifier_pid in allowed


def describe_items(qids: list, timeout: int = 30) -> None:
    """Print vi/en labels + en description of item QIDs, for MANUAL confirmation of
    emit's P31 TARGET items (Q13079705 / Q3623867). The qualifier check does NOT
    validate these — a wrong target QID would emit a wrong P31 while all tests pass."""
    u = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode({
        "action": "wbgetentities", "ids": "|".join(qids),
        "props": "labels|descriptions", "languages": "vi|en", "format": "json"})
    ents = _get_json(u, timeout).get("entities", {})
    for q in qids:
        lab = ents.get(q, {}).get("labels", {})
        desc = ents.get(q, {}).get("descriptions", {})
        print(f"  {q}: en='{lab.get('en',{}).get('value','?')}' "
              f"vi='{lab.get('vi',{}).get('value','?')}' — {desc.get('en',{}).get('value','')}")


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

    print("\n=== Phase-1b qualifier checks ===")
    for pid, qual in PHASE1B_CHECKS:
        aq = allowed_qualifiers(pid)
        print(f"  {pid} + {qual}: {'OK' if qualifier_allowed(aq, qual) else 'DISALLOWED'}")
    print("  P807 value-type: inspect https://www.wikidata.org/wiki/Property:P807 "
          "for 'administrative territorial entity' in the value-type constraint (manual).")
    print("\n=== Phase-1b P31 target items — CONFIRM before emit ===")
    describe_items(["Q2824648", "Q1381899"])   # expect 'province of Vietnam' / 'centrally-controlled city of Vietnam'


if __name__ == "__main__":
    main()
