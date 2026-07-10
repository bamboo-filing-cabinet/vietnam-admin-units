import json
from pathlib import Path
from vn_admin_units.cli import build_all


def test_build_all_produces_artifacts():
    """Integration test: runs the full build against the committed data/ and
    data/raw/ inputs, writing the real data/ + statements/ artifacts. Requires
    Task 2/3 inputs to exist. (No tmp isolation — build_all uses repo-relative
    paths; this is an end-to-end check, not a unit test.)"""
    build_all()
    ents = json.loads(Path("data/entities.json").read_text(encoding="utf-8"))
    assert len([e for e in ents if e["era"] == "post2025"]) == 34
    qs = Path("statements/na-provinces-2025.qs").read_text(encoding="utf-8")
    assert "P576" in qs and "P1365" in qs
    # end-to-end safety net (guards review findings #1/#2 against regression):
    for line in qs.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[1] in {"P7888", "P1366", "P1365"}:
            assert parts[0] != parts[2], f"self-referential statement leaked: {line}"
    assert "P571" not in qs, "no province item should get a (false) 2025 inception"
    assert "S854" in qs, "every statement must be referenced"
    assert "+2025-07-01T00:00:00Z/11" in qs, "reform date must be present"
    assert " 00:00:00T" not in qs and "2004" not in qs, "no malformed/base-history dates"
