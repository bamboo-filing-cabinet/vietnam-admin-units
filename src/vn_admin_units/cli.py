import json
from pathlib import Path

from vn_admin_units.soap import fetch_provinces_raw, parse_province_diffgram
from vn_admin_units.rawcache import save_raw
from vn_admin_units.crosswalk import read_province_crosswalk
from vn_admin_units.model import build_entities, build_lineage
from vn_admin_units.reconcile import load_seed, apply_seed
from vn_admin_units.emit import emit_quickstatements

BOUNDARY_DATES = {"2025-06-30": "30/06/2025", "2026-07-10": "10/07/2026"}
SOAP_URL = "https://danhmuchanhchinh.nso.gov.vn/DMDVHC.asmx"
DATA = Path("data")
CROSSWALK = "data/raw/crosswalk/DoiChieu_Tinh_2025.xls"


def cache_snapshots() -> None:
    DATA.mkdir(exist_ok=True)
    for iso, ddmmyyyy in BOUNDARY_DATES.items():
        xml = fetch_provinces_raw(ddmmyyyy)
        rows = parse_province_diffgram(xml)
        save_raw(f"soap/DanhMucTinh_{iso}.xml", xml.encode("utf-8"),
                 {"source_url": SOAP_URL, "method": "DanhMucTinh",
                  "params": {"DenNgay": ddmmyyyy}, "rows": len(rows)})
        (DATA / f"provinces-{iso}.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"cached {len(rows)} provinces @ {iso}")


def history_snapshot_dates() -> list[tuple[str, str]]:
    """(iso, dd/mm/yyyy) yearly 01/01 snapshots 2002..2025 + the event boundaries
    that a 01/01 grid would straddle (2004 renumber service-date, 2008 Hà Tây,
    2025 pre-reform). Terminal boundary = the 2025 reform; 2026 is out of scope."""
    pairs = [(f"{y}-01-01", f"01/01/{y}") for y in range(2002, 2026)]
    pairs += [("2004-07-01", "01/07/2004"),   # just after the 30/06/2004 renumber+carve-outs
              ("2008-09-01", "01/09/2008"),   # just after 2008-08-01 Hà Tây
              ("2025-06-30", "30/06/2025")]   # 1a pre-reform boundary (already cached by 1a)
    seen, out = set(), []
    for iso, ddmm in pairs:
        if iso not in seen:
            seen.add(iso)
            out.append((iso, ddmm))
    return sorted(out)


def cache_history_snapshots() -> None:
    """Yearly SOAP DanhMucTinh walk 2002→2025 (event-discovery backbone). Reuses
    fetch_provinces_raw; caches verbatim + manifest + derived JSON, like
    cache_snapshots but over the historical date set (cache_snapshots hardcodes only
    the two 2025-reform boundary dates)."""
    DATA.mkdir(exist_ok=True)
    for iso, ddmmyyyy in history_snapshot_dates():
        xml = fetch_provinces_raw(ddmmyyyy)
        rows = parse_province_diffgram(xml)
        save_raw(f"soap/DanhMucTinh_{iso}.xml", xml.encode("utf-8"),
                 {"source_url": SOAP_URL, "method": "DanhMucTinh",
                  "params": {"DenNgay": ddmmyyyy}, "rows": len(rows)})
        (DATA / f"provinces-{iso}.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"cached {len(rows)} provinces @ {iso}")


def _load(iso):
    return json.loads((DATA / f"provinces-{iso}.json").read_text(encoding="utf-8"))


def build_all() -> None:
    pre, post = _load("2025-06-30"), _load("2026-07-10")
    ents = apply_seed(build_entities(pre, post), load_seed("mappings/provinces-qid.csv"))
    edges = build_lineage(ents, read_province_crosswalk(CROSSWALK))
    DATA.mkdir(exist_ok=True)
    (DATA / "entities.json").write_text(
        json.dumps([e.to_dict() for e in ents], ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA / "lineage.json").write_text(
        json.dumps([e.to_dict() for e in edges], ensure_ascii=False, indent=2), encoding="utf-8")
    Path("statements").mkdir(exist_ok=True)
    Path("statements/na-provinces-2025.qs").write_text(
        emit_quickstatements(ents, edges), encoding="utf-8")
    print(f"built {len(ents)} entities, {len(edges)} lineage edges")


def build_province_history_all() -> None:
    from vn_admin_units.province_history import build_province_history
    from vn_admin_units.reconcile import (reuse_1a_qids, load_history_seed,
                                          apply_history_seed, write_history_mapping)
    from vn_admin_units.emit import emit_history_quickstatements, NSO_SOURCE_URL
    ents, edges = build_province_history("data", "data/raw/crosswalk",
                                         "data/decrees/2004-splits.json",
                                         "mappings/provinces-qid.csv")
    ents = reuse_1a_qids(ents, "mappings/provinces-qid.csv")
    # Preserve the hand-verified Hà Tây QID (manual step) across rebuilds BEFORE emit,
    # so the 2008 absorption edge isn't skipped for a missing QID.
    ents = apply_history_seed(ents, load_history_seed())
    write_history_mapping(ents)
    DATA.mkdir(exist_ok=True)
    (DATA / "provinces-history.json").write_text(
        json.dumps([e.to_dict() for e in ents], ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA / "province-history-lineage.json").write_text(
        json.dumps([e.to_dict() for e in edges], ensure_ascii=False, indent=2), encoding="utf-8")
    Path("statements").mkdir(exist_ok=True)
    # Per-statement references come from each edge/span/decree; NSO is the fallback.
    Path("statements/na-provinces-history.qs").write_text(
        emit_history_quickstatements(ents, edges, default_ref_url=NSO_SOURCE_URL), encoding="utf-8")
    print(f"built {len(ents)} entities, {len(edges)} lineage edges")


# ── Phase 2: district pipeline ──

# Live reconciliation (networked) — a MANUAL/audit command, NOT run by the test suite.
def reconcile_districts_live() -> None:
    """LIVE Wikidata reconciliation: bulk SPARQL + per-item wbsearchentities fallback →
    writes mappings/districts-qid.csv. Networked; run manually to refresh the mapping. The
    offline build_districts_all and the test suite NEVER call it."""
    from vn_admin_units.district_model import build_districts
    from vn_admin_units.reconcile import (match_districts, sparql_vn_districts, attach_parent_codes,
                                          load_district_seed, apply_district_seed,
                                          write_district_mapping, wd_search, wd_claims_ids)
    ents, _ = build_districts("data/raw/crosswalk")
    code_qid, qid_code = _province_qid_maps("mappings/provinces-history-qid.csv",
                                            "mappings/provinces-qid.csv")
    _fill_parent_qids(ents, code_qid)                    # so province is a real weak tiebreak
    cands = attach_parent_codes(sparql_vn_districts(), qid_code)   # candidate parent_qid → GSO code
    # verify_fn returns each candidate's P31 so the fallback enforces DISTRICT-tier (not just P17=VN)
    ents = match_districts(ents, cands, search_fn=wd_search,
                           verify_fn=lambda ids: wd_claims_ids(ids, "P31"))   # fallback before 'new'
    ents = apply_district_seed(ents, load_district_seed())
    write_district_mapping(ents)
    print(f"reconciled {sum(1 for e in ents if e.wikidata_qid)}/{len(ents)} -> mappings/districts-qid.csv")


# Offline assemble + emit — safe as a regression gate (no network).
def build_districts_all() -> None:
    """OFFLINE: assemble the graph from the cached crosswalk + cached Nghị định records, apply
    QIDs from the COMMITTED mappings/districts-qid.csv (reconcile_districts_live refreshes it),
    then write the artifacts + QuickStatements. No network — runs in the test suite."""
    from vn_admin_units.district_model import build_districts
    from vn_admin_units.reconcile import (load_district_mapping, apply_district_seed,
                                          write_district_mapping, load_acknowledged_gaps)
    from vn_admin_units.emit import emit_district_quickstatements, NSO_SOURCE_URL

    # The reform resolution that abolished the district tier on 2025-07-01. Design §Emit requires
    # the abolition P576 reference THIS instrument, NOT the NSO root — so it starts empty and the
    # build hard-fails until the confirmed URL is set (F2). ~696 abolition statements ride on it.
    # Luật Tổ chức chính quyền địa phương số 72/2025/QH15 (passed 16/6/2025), Điều 51 khoản 3:
    # "Kể từ ngày 01/7/2025, không tổ chức chính quyền địa phương ở cấp huyện" — the instrument
    # that abolished the district tier on 2025-07-01. Sourced + confirmed 2026-07-19.
    ABOLITION_REF = ("https://thuvienphapluat.vn/van-ban/Bo-may-hanh-chinh/"
                     "Luat-To-chuc-chinh-quyen-dia-phuong-2025-so-72-2025-QH15-649675.aspx")
    if not ABOLITION_REF or ABOLITION_REF == NSO_SOURCE_URL or not ABOLITION_REF.startswith("http"):
        raise SystemExit("ABOLITION_REF unset/placeholder: set it to the confirmed two-tier-reform "
                         "resolution URL (design §Emit — never the NSO root) before emitting.")

    ents, edges = build_districts("data/raw/crosswalk")
    residue = getattr(build_districts, "residue", [])
    blocking = [r for r in residue if r[0] == "dissolve-date-unrecovered"]
    if blocking:
        raise SystemExit(f"DISSOLVE-DATE GATE: {len(blocking)} dissolves have no recovered date "
                         f"(never guessed). Recover it via the survivor row / curate merge targets, "
                         f"then rebuild. First: {blocking[0][1].get('name_from')}")
    unlinked = [r for r in residue if r[0] == "merge-target-unresolved"]
    if unlinked:
        raise SystemExit(f"MERGE-TARGET GATE: {len(unlinked)} dissolutions have no resolved "
                         f"successor. Add {{dissolved_local_id: successor_local_id}} entries to "
                         f"data/district-merge-targets.json, then rebuild. "
                         f"First: {unlinked[0][1]['local_id']} ({unlinked[0][1]['name_from']})")
    code_qid, _ = _province_qid_maps("mappings/provinces-history-qid.csv", "mappings/provinces-qid.csv")
    _fill_parent_qids(ents, code_qid)                        # P131 province QIDs (dependency §1)
    ents = apply_district_seed(ents, load_district_mapping())
    ack = load_acknowledged_gaps()
    gaps = [e for e in ents if not e.wikidata_qid]
    unresolved = [e for e in gaps if e.local_id not in ack]
    DATA.mkdir(exist_ok=True)                                 # always refresh (write [] when none) so it can't go stale
    (DATA / "district-gaps.json").write_text(
        json.dumps([e.to_dict() for e in gaps], ensure_ascii=False, indent=2), encoding="utf-8")
    if unresolved:
        raise SystemExit(f"COMPLETENESS GATE: {len(unresolved)} districts have no QID and are not "
                         f"acknowledged gaps (match_status='gap') — they would emit NOTHING and drop "
                         f"their lineage. Run reconcile_districts_live, or mark genuine no-item gaps "
                         f"'gap' in mappings/districts-qid.csv. See data/district-gaps.json. "
                         f"First: {unresolved[0].name_vi}")
    # Tier-C create-new succession (see docs/journals/2026-07-19.02): {local_id: {successor, reference_url}}
    # for the 5 former districts whose WD items were hand-created (no former item existed, only the successor).
    cn_path = DATA / "district-create-new.json"
    create_new = json.loads(cn_path.read_text(encoding="utf-8")) if cn_path.exists() else {}
    # Tier-B P31 fixups (see docs/journals/2026-07-19.01): former-district stubs with a generic P31.
    pa_path = DATA / "district-p31-assert.json"
    p31_assert = {k for k in json.loads(pa_path.read_text(encoding="utf-8")) if not k.startswith("_")} \
        if pa_path.exists() else set()
    qs = emit_district_quickstatements(ents, edges, default_ref_url=NSO_SOURCE_URL,
                                       abolition_ref=ABOLITION_REF, create_new=create_new,
                                       p31_assert=p31_assert)
    missing = event_statements_missing_reference(qs, NSO_SOURCE_URL)
    if missing:
        raise SystemExit(f"REFERENCE GATE: {len(missing)} event statements lack a real decree URL "
                         f"(missing / 'nan' / NSO root). Add their decrees to data/decree-urls.json, "
                         f"then rebuild. First offenders:\n  " + "\n  ".join(missing[:10]))
    write_district_mapping(ents)                             # refresh names/spans; preserve verified/manual
    DATA.mkdir(exist_ok=True)
    (DATA / "districts.json").write_text(
        json.dumps([e.to_dict() for e in ents], ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA / "district-lineage.json").write_text(
        json.dumps([e.to_dict() for e in edges], ensure_ascii=False, indent=2), encoding="utf-8")
    Path("statements").mkdir(exist_ok=True)
    Path("statements/na-districts.qs").write_text(qs, encoding="utf-8")
    print(f"built {len(ents)} districts, {len(edges)} lineage edges")


def event_statements_missing_reference(qs: str, root_url: str) -> list:
    """Every EVENT-DRIVEN statement that must cite its establishing resolution (design §3) whose
    S854 reference is NOT a real URL. Covered: succession/separation (P7888/P1366/P1365/P807), ALL
    dissolution incl. the universal 2025 abolition (P576 — the reform resolution, NOT the NSO root),
    inception (P571), and any DATED P131/P31 span (P580/P582). A reference is bad if missing, empty,
    the literal 'nan', the generic root_url, or not http(s). EXEMPT only: a bare baseline P131 (no
    date qualifier — the NSO source is legitimate for pre-floor province membership)."""
    import re
    bad = []
    for line in qs.splitlines():
        p = line.split("\t")
        if len(p) < 2:
            continue
        prop = p[1]
        dated = ("P580" in p) or ("P582" in p)
        needs_ref = (
            prop in {"P7888", "P1366", "P1365", "P807", "P571", "P576"}
            or (prop in {"P131", "P31"} and dated)
        )
        if not needs_ref:
            continue
        m = re.search(r'S854\t"([^"]*)"', line)
        ref = (m.group(1).strip() if m else "")
        if (not ref) or ref == root_url or ref.lower() in ("nan", "none") \
                or not ref.lower().startswith(("http://", "https://")):
            bad.append(line)
    return bad


def _province_qid_maps(history_csv, seed_csv):
    """(code→qid, qid→code) from the reconciled province mappings — 1a (2025-era,
    keyed by `gso_code`) + 1b (historical, keyed by `terminal_code`)."""
    import csv as _csv
    from pathlib import Path as _P
    code_qid = {}
    for path, code_col in ((seed_csv, "gso_code"), (history_csv, "terminal_code")):
        p = _P(path)
        if not p.exists():
            continue
        for row in _csv.DictReader(p.read_text(encoding="utf-8").splitlines()):
            if row.get("wikidata_qid"):
                code_qid.setdefault(row[code_col], row["wikidata_qid"])
    qid_code = {q: c for c, q in code_qid.items()}
    return code_qid, qid_code


def _fill_parent_qids(ents, code_qid) -> None:
    """Set each parent_span's province QID from code_qid; a span with no QID stays
    None and its P131 is skipped + logged by emit (dependency §1)."""
    missing = set()
    for e in ents:
        for sp in e.parent_spans:
            sp["qid"] = code_qid.get(sp["code"])
            if not sp["qid"]:
                missing.add(sp["code"])
    if missing:
        print(f"  WARNING: {len(missing)} province codes lack a QID (P131 skipped): {sorted(missing)}")


if __name__ == "__main__":
    cache_snapshots()
