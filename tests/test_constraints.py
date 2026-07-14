from vn_admin_units.constraints import _allowed_from_claims


def _constraint(constraint_qid, qualifier_pids):
    return {
        "mainsnak": {"datavalue": {"value": {"id": constraint_qid}}},
        "qualifiers": {"P2306": [
            {"datavalue": {"value": {"id": p}}} for p in qualifier_pids]},
    }


def test_none_when_no_allowed_qualifiers_constraint():
    # only some other constraint present -> None (unconstrained)
    assert _allowed_from_claims([_constraint("Q21510865", [])]) is None


def test_extracts_allowed_qualifier_pids():
    claims = [_constraint("Q21510851", ["P585", "P1319"])]
    assert _allowed_from_claims(claims) == {"P585", "P1319"}


def test_empty_allowed_set_is_not_none():
    # allowed-qualifiers constraint declared but lists nothing -> empty set (all disallowed)
    assert _allowed_from_claims([_constraint("Q21510851", [])]) == set()


def test_check_qualifier_membership_helper():
    from vn_admin_units.constraints import qualifier_allowed
    assert qualifier_allowed({"P580", "P582"}, "P580") is True
    assert qualifier_allowed({"P585"}, "P580") is False
    assert qualifier_allowed(None, "P580") is True      # no constraint declared => allowed
