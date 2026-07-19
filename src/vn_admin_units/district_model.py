"""District tier (huyện / quận / thị xã / thành phố thuộc tỉnh) assembly, 2004→2025.

Purely historical: the tier existed 2002→2025 and was abolished 2025-07-01 by the
two-tier reform. Builds one continuous Entity per district (rename/retype/re-parent
are same-entity relabels) + the lineage edges the yearly Đối Chiếu windows expose,
then applies the universal 2025 abolition. See docs/DESIGN-phase2.md."""
from __future__ import annotations

import glob
import json
import logging
import os
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from vn_admin_units.core import Entity, LineageEdge
from vn_admin_units.crosscheck_decrees import decree_code
from vn_admin_units.crosswalk import read_district_crosswalk
from vn_admin_units.ghichu import parse_district_ghichu
from vn_admin_units.names import fold_district_name

log = logging.getLogger("vn_admin_units.district_model")

ABOLITION_DATE = "2025-07-01"       # two-tier reform; districts' event date
ABOLITION_VALID_TO = "2025-06-30"   # last in-force day (inclusive)
DISTRICT_TYPES = {"Huyện", "Quận", "Thị xã", "Thành phố"}

_TIERS = ("Thành phố", "Thị xã", "Huyện", "Quận")   # longest-first so "Thị xã" wins


def unit_tier(name: str) -> str:
    for t in _TIERS:
        if name.startswith(t):
            return t
    return ""


def classify_change(row: dict) -> str:
    """Candidate event kind from structured columns. 'reparent' is checked before
    name/tier diffs because a Hà Tây→Hà Nội row keeps the same code+name and only
    the province differs. 'retype_rename' (tier AND name changed) is a candidate the
    D6 resolver may promote to a split (Từ Liêm)."""
    b, s = row["base_ma"], row["succ_ma"]
    if not b and s:
        return "create"
    if b and not s:
        return "dissolve"
    if row["base_tinh"] != row["succ_tinh"]:
        return "reparent"
    tier_diff = unit_tier(row["base_ten"]) != unit_tier(row["succ_ten"])
    name_diff = fold_district_name(row["base_ten"]) != fold_district_name(row["succ_ten"])
    if tier_diff and name_diff:
        return "retype_rename"
    if tier_diff:
        return "retype"
    if name_diff:
        return "rename"
    return "unchanged"


def window_events(rows: list) -> list:
    """Changed rows of one yearly window as classified event dicts (kind !=
    unchanged). Carries both codes/names/provinces, the compare-side effective date
    + decree, and Ghi Chú for the D6 resolver."""
    out = []
    for r in rows:
        kind = classify_change(r)
        if kind == "unchanged":
            continue
        out.append({
            "kind": kind,
            "code_from": r["base_ma"], "code_to": r["succ_ma"],
            "name_from": r["base_ten"], "name_to": r["succ_ten"],
            "tinh_from": r["base_tinh"], "tinh_to": r["succ_tinh"],
            "eff_date": r["succ_hieu_luc"] or r["base_hieu_luc"],
            "decree_raw": r["succ_nghi_dinh"] or r["base_nghi_dinh"],
            "ghi_chu": r["ghi_chu"],
        })
    return out


def crossvalidate_window(rows: list) -> dict:
    """A window's changed events must exactly account for its create/dissolve delta
    (design §Graph assembly). Returns {created, dissolved, events, ok} for a build assertion."""
    created = sum(1 for r in rows if not r["base_ma"] and r["succ_ma"])
    dissolved = sum(1 for r in rows if r["base_ma"] and not r["succ_ma"])
    ev = window_events(rows)
    ec = sum(1 for e in ev if e["kind"] == "create")
    ed = sum(1 for e in ev if e["kind"] == "dissolve")
    return {"created": created, "dissolved": dissolved,
            "event_creates": ec, "event_dissolves": ed,
            "ok": created == ec and dissolved == ed}


def dist_local_id(code: str, valid_from) -> str:
    """Entity-anchored id: code + generation. `gen` = valid_from ('base' for the
    2004 baseline root). The bare code is never a key — codes are inherited across
    splits (Từ Liêm 019 → Nam Từ Liêm 019) and reassigned (Đạ Tẻh→Đạ Huoai 682)."""
    return f"d-{code}-{valid_from or 'base'}"


def District(code: str, valid_from, valid_to, name_vi: str, loai_hinh: str,
             parent_spans=None, aliases=None, gso_codes=None,
             wikidata_qid=None, qid_status=None, type_spans=None) -> Entity:
    """Construct a district as a core.Entity (era stays None; districts use
    parent_spans for dated P131). gso_codes defaults to [code]; type_spans defaults
    to a single span so a genuine retype (>1 span) is distinguishable."""
    return Entity(
        local_id=dist_local_id(code, valid_from),
        gso_codes=gso_codes or [code],
        name_vi=name_vi, loai_hinh=loai_hinh,
        type_spans=type_spans or [{"loai_hinh": loai_hinh, "from": valid_from, "to": valid_to}],
        aliases=aliases or [],
        valid_from=valid_from, valid_to=valid_to,
        wikidata_qid=wikidata_qid, qid_status=qid_status,
        parent_spans=parent_spans or [])


def group_by_event(events: list) -> dict:
    """{(effective_date, province): [events]} — candidate operation buckets. A
    single bucket may still hold several independent operations (2020 Cao Bằng), so
    callers pair predecessors to successors within it via prose/discriminator."""
    g = defaultdict(list)
    for e in events:
        prov = e.get("tinh_to") or e.get("tinh_from")
        g[(e["eff_date"], prov)].append(e)
    return dict(g)


def source_survives(source_name: str, roster_next_folds: set) -> bool:
    """Carve-out vs. split discriminator (design §5): does the named source district
    survive into the next window's roster? Survives → carve-out (parent persists,
    P807). Gone → division/merger (predecessor ends, P576/P1365)."""
    return fold_district_name(source_name) in roster_next_folds


def resolve_merge_target(event: dict, code_by_fold: dict) -> str | None:
    """CODE of the district a dissolved unit folds into (the caller resolves the code
    to an Entity). Uses the Ghi Chú 'vào <huyện Y>' target; `code_by_fold` maps folded
    unit names — built from BOTH base and successor names by the caller, so a 'vào
    <old name>' target still resolves after the survivor was renamed. Returns None
    when unresolvable (→ manual residue)."""
    parsed = parse_district_ghichu(event.get("ghi_chu", ""))
    if parsed["event"] == "merge" and parsed["target"]:
        return code_by_fold.get(fold_district_name(parsed["target"]))
    return None


def detect_collisions(entities: list) -> list:
    """local_ids appearing more than once (a code+gen clash the assembly must
    disambiguate). Logged, returned sorted; never silent."""
    from collections import Counter
    dups = sorted(k for k, n in Counter(e.local_id for e in entities).items() if n > 1)
    for d in dups:
        log.warning("local_id collision: %s", d)
    return dups


# ---------------------------------------------------------------------------
# D7 — assembly (Execution corrections 2026-07-17..18 authoritative):
#   (1) dissolve/merge DATE from the SURVIVOR crosswalk row (succ_hieu_luc);
#       decree from the dissolved row's own nghi_dinh cell; NOT decrees_naming.
#   (4) 621/TCTK code-only re-codes classify "unchanged" (no name/type/province
#       change) so window_events drops them — asserted in build (no TCTK event).
#   (5) reference URL keyed by (code, effective_date) for ambiguous bare codes,
#       else bare code.
# ---------------------------------------------------------------------------

def _minus_one_day(iso: str) -> str:
    y, m, d = (int(x) for x in iso.split("-"))
    return (date(y, m, d) - timedelta(days=1)).isoformat()


def _recode_aliases(window_dir: str) -> dict:
    """succ code -> pre-2004 code (alias), from the 2004→2005 recode window."""
    p = os.path.join(window_dir, "district_2004-01-01_2005-01-01.xls")
    out = {}
    if os.path.exists(p):
        for r in read_district_crosswalk(p):
            if r["succ_ma"] and r["base_ma"] and r["succ_ma"] != r["base_ma"]:
                out[r["succ_ma"]] = r["base_ma"]
    return out


def _yearly_paths(window_dir: str) -> list:
    """Ordered (base_year, path) for the event windows 2005→… + the 2025 tail.
    The 2004→2005 recode window is excluded (alias source only)."""
    out = []
    for p in sorted(glob.glob(os.path.join(window_dir, "district_20*-01-01_20*-01-01.xls"))):
        y = int(os.path.basename(p).split("_")[1][:4])
        if y >= 2005:
            out.append((y, p))
    tail = os.path.join(window_dir, "district_2025-01-01_2025-06-30.xls")
    if os.path.exists(tail):
        out.append((2025, tail))
    return out


def _load_merge_targets(path: str = "data/district-merge-targets.json") -> dict:
    """Curated {dissolved_local_id: successor_local_id} overrides for merges with no
    Ghi Chú 'vào Y' prose (Nông Sơn→Quế Sơn). Missing file -> {}."""
    return json.loads(Path(path).read_text(encoding="utf-8")) if os.path.exists(path) else {}


def _load_dated_urls(path: str = "data/decree-urls-residue-2026-07-18.json") -> dict:
    """{(code, effective_date): url} for the genuinely-ambiguous bare codes (correction 5;
    residue_c_date_qualified). Missing file -> {}."""
    if not os.path.exists(path):
        return {}
    blob = json.loads(Path(path).read_text(encoding="utf-8")).get("residue_c_date_qualified", {})
    out = {}
    for code, bydate in blob.items():
        if not isinstance(bydate, dict):
            continue
        for eff, entry in bydate.items():
            if isinstance(entry, dict) and entry.get("url"):
                out[(code, eff)] = entry["url"]
    return out


def _mint(code, eff, name, tinh, aliases=None, ref_url=""):
    """A district minted mid-era (valid_from=eff): split product, carve child, or plain
    creation. `ref_url` stamps both the founding type span (P571) and the initial parent
    span (dated P131/P580)."""
    return District(code=code, valid_from=eff, valid_to=ABOLITION_VALID_TO,
                    name_vi=name, loai_hinh=unit_tier(name), aliases=aliases or [],
                    type_spans=[{"loai_hinh": unit_tier(name), "from": eff,
                                 "to": ABOLITION_VALID_TO, "reference_url": ref_url}],
                    parent_spans=[{"code": tinh, "qid": None, "from": eff,
                                   "to": ABOLITION_VALID_TO, "reference_url": ref_url}])


def _apply_reparent(ev, ents, residue, ref):
    e = ents.get(ev["code_from"])
    if not e:
        residue.append(("reparent-miss", ev)); return
    eff = ev["eff_date"]
    url = ref(decree_code(ev["decree_raw"]), eff)
    e.parent_spans[-1]["to"] = _minus_one_day(eff)
    e.parent_spans[-1]["reference_url"] = url
    e.parent_spans.append({"code": ev["tinh_to"], "qid": None, "from": eff,
                           "to": ABOLITION_VALID_TO, "reference_url": url})
    if ev["code_to"] and ev["code_to"] != ev["code_from"]:      # rare: province+code both change
        ents.pop(ev["code_from"], None); ents[ev["code_to"]] = e
        e.gso_codes.append(ev["code_to"])


def _apply_rename(ev, ents, residue):
    e = ents.get(ev["code_from"])
    if not e:
        residue.append(("rename-miss", ev)); return
    if ev["name_from"] not in e.aliases:
        e.aliases.append(ev["name_from"])
    e.name_vi = ev["name_to"]


def _apply_retype(ev, eff, ents, residue, ref):
    """Same-entity type change (+ possible rename): end the current type span, open a new
    one, keep the old name as an alias if it actually changed."""
    e = ents.get(ev["code_from"])
    if not e:
        residue.append(("retype-miss", ev)); return
    url = ref(decree_code(ev["decree_raw"]), eff)
    e.type_spans[-1]["to"] = _minus_one_day(eff)
    e.type_spans[-1]["reference_url"] = url
    e.type_spans.append({"loai_hinh": unit_tier(ev["name_to"]), "from": eff,
                         "to": ABOLITION_VALID_TO, "reference_url": url})
    if fold_district_name(ev["name_from"]) != fold_district_name(ev["name_to"]) \
            and ev["name_from"] not in e.aliases:
        e.aliases.append(ev["name_from"])
    e.name_vi, e.loai_hinh = ev["name_to"], unit_tier(ev["name_to"])


def _apply_split(ev, eff, ents, all_ents, edges, bucket_creates, ref):
    """Từ Liêm case: the code-inheriting retype_rename row ends the old entity and mints a
    NEW same-code product; every create in this bucket is another product. Returns the set
    of create codes consumed (so they aren't also minted as plain new)."""
    old = ents.get(ev["code_from"])
    if not old:
        return set()
    old.valid_to = _minus_one_day(eff)
    code = decree_code(ev["decree_raw"])
    url = ref(code, eff)
    products = [_mint(ev["code_to"], eff, ev["name_to"], ev["tinh_to"], ref_url=url)]  # inherits old code
    ents[ev["code_to"]] = products[0]
    consumed = set()
    for c in bucket_creates:
        if c["code_to"] and c["code_to"] != ev["code_to"]:
            sib = _mint(c["code_to"], eff, c["name_to"], c["tinh_to"], ref_url=url)
            ents[c["code_to"]] = sib; products.append(sib); consumed.add(c["code_to"])
    for p in products:
        all_ents.append(p)
        edges.append(LineageEdge(old.local_id, p.local_id, "split", share="partial",
                                 decree=code or ev["decree_raw"], effective_date=eff,
                                 reference_url=url))
    return consumed


def _apply_create(ev, eff, ents, all_ents, edges, residue, roster_next, ref):
    """Materialize a newly-created district (blank base). If Ghi Chú names a source it was
    carved 'trên cơ sở'/'chia tách từ' AND that source SURVIVES, add a carved_from edge to
    the persisting parent (P807 at emit); otherwise a plain new entity (P571)."""
    parsed = parse_district_ghichu(ev["ghi_chu"])
    src = parsed.get("source")
    code = decree_code(ev["decree_raw"])
    url = ref(code, eff)
    child = _mint(ev["code_to"], eff, ev["name_to"], ev["tinh_to"], ref_url=url)
    ents[ev["code_to"]] = child
    all_ents.append(child)
    if src and source_survives(src, roster_next):
        fs = fold_district_name(src)
        parent = next((e for e in ents.values()
                       if fold_district_name(e.name_vi) == fs
                       or fs in {fold_district_name(a) for a in e.aliases}), None)
        if parent and parent.local_id != child.local_id:
            edges.append(LineageEdge(parent.local_id, child.local_id, "carved_from",
                                     share="partial", decree=code or ev["decree_raw"],
                                     effective_date=eff, reference_url=url))


def _is_division(gc: str) -> bool:
    """A dissolve whose predecessor was DIVIDED to establish new units (Ayun Pa →
    thị xã Ayun Pa + huyện Phú Thiện), vs. absorbed into a survivor ('nhập … vào Y')."""
    return any(k in (gc or "") for k in ("chia cắt", "chia tách", "chia ra"))


def _resolve_dissolve(ev, ents, edges, residue, code_by_fold, survivor_eff,
                      manual_targets, ref, window_create_ents):
    """End a dissolved district. Two shapes:
      • DIVISION ('chia cắt/tách … để thành lập X và Y'): predecessor SPLIT into this
        window's new products (dated from their create rows) → `split` edges. The
        blank-successor row's stale date is ignored; the products carry the real date.
      • MERGE ('nhập/sát nhập … vào Y'): folded into a persisting/absorbing target,
        dated from the SURVIVOR's crosswalk row (`succ_hieu_luc`, correction 1); the
        decree sits on the dissolved row's own nghi_dinh cell. Target via Ghi-Chú 'vào
        Y' prose, else the curated manual_targets override (by local_id).
    Unresolved target OR unrecovered date → residue (both hard-gated in build)."""
    e = ents.get(ev["code_from"])
    if not e:
        residue.append(("dissolve-miss", ev)); return
    code = decree_code(ev["decree_raw"])

    if _is_division(ev.get("ghi_chu", "")):
        prods = [p for p in window_create_ents
                 if p.parent_spans and p.parent_spans[0]["code"] == ev["tinh_from"]
                 and not any(x.successor == p.local_id for x in edges)]
        if prods:
            eff = min(p.valid_from for p in prods)
            e.valid_to = _minus_one_day(eff)
            url = ref(code, eff)
            for p in prods:
                edges.append(LineageEdge(e.local_id, p.local_id, "split", share="partial",
                                         decree=code, effective_date=eff, reference_url=url))
            ents.pop(ev["code_from"], None)
            return

    tgt_code = resolve_merge_target(ev, code_by_fold)
    tgt = ents.get(tgt_code) if tgt_code else None
    if not tgt and manual_targets.get(e.local_id):
        succ_local = manual_targets[e.local_id]
        tgt = next((x for x in ents.values() if x.local_id == succ_local), None)
        tgt_code = tgt.terminal_code if tgt else None
    eff = survivor_eff.get(tgt_code) if tgt_code else None
    if not eff:
        # NEVER guess a date (F2). Flag BLOCKING and emit nothing: valid_to=None so the
        # abolition pass + emitter both SKIP it (else it masquerades as a 2025 abolition).
        residue.append(("dissolve-date-unrecovered", ev))
        e.valid_to = None
        ents.pop(ev["code_from"], None)
        return
    e.valid_to = _minus_one_day(eff)
    url = ref(code, eff)
    if tgt and tgt.local_id != e.local_id:
        edges.append(LineageEdge(e.local_id, tgt.local_id, "merged_into", share="whole",
                                 decree=code, effective_date=eff, reference_url=url))
    else:
        e.dissolution = (eff, url)
        residue.append(("merge-target-unresolved",
                        {"local_id": e.local_id, "name_from": ev["name_from"], "eff": eff}))
    ents.pop(ev["code_from"], None)


def _resolve_bucket(bucket, eff, ents, all_ents, edges, residue, roster_next, ref):
    """Pair predecessors/successors within one (effective_date, province) bucket
    (dissolves are resolved separately, at window level, so a division can reach its
    products in another bucket):
      1. retype_rename whose source vanished + creates present → SPLIT (consumes creates);
         otherwise a same-entity retype.
      2. plain retype (tier change only) → same entity.
      3. remaining creates → carve-out child (source survives) or plain new entity."""
    creates = [e for e in bucket if e["kind"] == "create"]
    consumed = set()
    for ev in bucket:
        if ev["kind"] == "retype_rename":
            if not source_survives(ev["name_from"], roster_next) and creates:
                consumed |= _apply_split(ev, eff, ents, all_ents, edges, creates, ref)
            else:
                _apply_retype(ev, eff, ents, residue, ref)
        elif ev["kind"] == "retype":
            _apply_retype(ev, eff, ents, residue, ref)
    for ev in creates:
        if ev["code_to"] not in consumed:
            _apply_create(ev, eff, ents, all_ents, edges, residue, roster_next, ref)


def build_districts(window_dir: str):
    """Assemble the district entity + lineage graph 2004→2025 + the 2025 abolition.

    Spine: the 2005-01-01 roster as roots (valid_from=None). Walk each yearly window in
    order, keyed by CURRENT district code; apply reparent / rename / retype / create /
    dissolve, resolving split/carve/merge buckets via the D6 discriminator; finally end
    every surviving entity at the 2025 abolition. Dates + references come from the crosswalk
    rows (survivor row for dissolves — correction 1). Returns (entities, edges); residue is
    exposed on build_districts.residue."""
    from vn_admin_units.crosscheck_decrees import load_decree_urls
    recode = _recode_aliases(window_dir)
    flat_urls = load_decree_urls()
    dated_urls = _load_dated_urls()
    manual_targets = _load_merge_targets()

    def ref(code, eff):
        return dated_urls.get((code, eff)) or flat_urls.get(code, "")

    ents = {}          # current code -> Entity
    all_ents = []      # every entity ever created (incl. ended)
    edges = []
    residue = []

    # seed roots from the 2005-01-01 roster (base side of the 2005→2006 window)
    for r in read_district_crosswalk(os.path.join(window_dir, "district_2005-01-01_2006-01-01.xls")):
        code = r["base_ma"]
        if not code or code in ents:
            continue
        e = District(code=code, valid_from=None, valid_to=ABOLITION_VALID_TO,
                     name_vi=r["base_ten"], loai_hinh=unit_tier(r["base_ten"]),
                     aliases=[recode[code]] if code in recode else [],
                     parent_spans=[{"code": r["base_tinh"], "qid": None,
                                    "from": None, "to": ABOLITION_VALID_TO, "reference_url": ""}])
        ents[code] = e
        all_ents.append(e)

    for year, path in _yearly_paths(window_dir):
        rows = read_district_crosswalk(path)
        events = window_events(rows)
        roster_next = {fold_district_name(r["succ_ten"]) for r in rows if r["succ_ma"]}
        survivor_eff = {r["succ_ma"]: r["succ_hieu_luc"]
                        for r in rows if r["succ_ma"] and r["succ_hieu_luc"]}

        # correction 4: pure 621/TCTK code-only re-codes (base_ma≠succ_ma, name/type/province
        # unchanged) classify as "unchanged" and are dropped by window_events — verified by a
        # classify_change unit test, not asserted here (a REAL event, e.g. huyện→thị xã Kỳ Anh,
        # can carry a stale TCTK decree *cell* — the unreliable-decree-column problem, journal
        # 2026-07-13.02 — which is a D11 reference-gate concern, not an assembly halt).

        # Pass 1 — same-entity relabels (reparent/rename) BEFORE bucket pairing so renamed
        # survivors are in place when dissolves resolve their target.
        for ev in events:
            if ev["kind"] == "reparent":
                _apply_reparent(ev, ents, residue, ref)
            elif ev["kind"] == "rename":
                _apply_rename(ev, ents, residue)

        # Pass 2 — create/retype/split buckets (mint this window's new units).
        for (eff, prov), bucket in group_by_event(events).items():
            _resolve_bucket(bucket, eff, ents, all_ents, edges, residue, roster_next, ref)

        # merge-target lookup: folded name/alias -> CURRENT code, from ALL live entities
        # (built AFTER buckets so a target renamed/minted this window is included; the
        # absorber is often unchanged this window and has no row of its own).
        code_by_fold = {}
        for e in ents.values():
            code_by_fold.setdefault(fold_district_name(e.name_vi), e.terminal_code)
            for a in e.aliases:
                code_by_fold.setdefault(fold_district_name(a), e.terminal_code)

        # Pass 3 — dissolves at window level (a division reaches its products in any bucket).
        window_create_ents = [ents[ev["code_to"]] for ev in events
                              if ev["kind"] == "create" and ev["code_to"] in ents]
        for ev in events:
            if ev["kind"] == "dissolve":
                _resolve_dissolve(ev, ents, edges, residue, code_by_fold, survivor_eff,
                                  manual_targets, ref, window_create_ents)

    # universal 2025 abolition: every entity still in force at 2025-06-30 ends there.
    for e in all_ents:
        if e.valid_to == ABOLITION_VALID_TO:
            e.abolished = True

    detect_collisions(all_ents)
    build_districts.residue = residue
    return all_ents, edges
