from vn_admin_units.core import wd_date as _date, ref_s854 as _ref, REFERENCE_URL
from vn_admin_units.core import wd_date, ref_s854, p31_target, predecessor_ends

NSO_SOURCE_URL = REFERENCE_URL
# WD item QIDs for the two admin-unit types (confirmed via constraints.describe_items
# 2026-07-14: the placeholder QIDs were wrong — Myanmar settlement / Benin arrondissement).
P31_PROVINCE = "Q2824648"        # "province of Vietnam"
P31_CITY_TW = "Q1381899"         # "centrally-controlled city of Vietnam"


def emit_quickstatements(entities: list, edges: list) -> str:
    """QuickStatements v2 for the reform. Rules (DESIGN §Identity):
    1. skip same-QID edges (survivor edited in place);
    2. P571 only when successor.qid_status == "new";
    3. reference every statement (S854) + P585 on lineage;
    4. skip edges with an unreconciled endpoint."""
    by_id = {e.local_id: e for e in entities}
    lines: list[str] = []
    p571_done: set[str] = set()
    ref = f'S854\t"{REFERENCE_URL}"'
    for e in edges:
        pre, post = by_id[e.predecessor], by_id[e.successor]
        if not (pre.wikidata_qid and post.wikidata_qid):
            continue                              # rule 4
        if pre.wikidata_qid == post.wikidata_qid:
            continue                              # rule 1
        eff = _date(e.effective_date)
        lines.append(f"{pre.wikidata_qid}\tP576\t{eff}\t{ref}")
        lines.append(f"{pre.wikidata_qid}\tP7888\t{post.wikidata_qid}\tP585\t{eff}\t{ref}")
        lines.append(f"{pre.wikidata_qid}\tP1366\t{post.wikidata_qid}\tP585\t{eff}\t{ref}")
        lines.append(f"{post.wikidata_qid}\tP1365\t{pre.wikidata_qid}\tP585\t{eff}\t{ref}")
        if post.qid_status == "new" and post.wikidata_qid not in p571_done:
            lines.append(f"{post.wikidata_qid}\tP571\t{eff}\t{ref}")
            p571_done.add(post.wikidata_qid)
    seen, out = set(), []
    for ln in lines:
        if ln not in seen:
            seen.add(ln)
            out.append(ln)
    return ("\n".join(out) + "\n") if out else ""


# ── Phase 1b: relation-aware history emitter ──


def emit_history_quickstatements(entities: list, edges: list, default_ref_url: str) -> str:
    """Relation-aware QuickStatements for the 2002→2025 province history. Each statement
    is referenced to ITS OWN event source: carve-out P571/P807 → the carve-out decree;
    absorption → the 2008 resolution; retype P31 → the retype decree; anything without a
    specific source → default_ref_url (NSO). See DESIGN-phase1b.md §Emit."""
    by_id = {e.local_id: e for e in entities}
    carve_edge = {ed.successor: ed for ed in edges if ed.relation == "carved_from"}   # child -> its edge
    out: list = []
    seen: set = set()

    def add(line: str) -> None:
        if line not in seen:
            seen.add(line)
            out.append(line)

    for e in entities:
        if not e.wikidata_qid:
            continue
        # P571 gated on known valid_from (NOT qid_status); referenced to the founding
        # event (the carve-out decree for a carve-out child). Audit existing claims first.
        if e.valid_from:
            ce = carve_edge.get(e.local_id)
            ref = _ref(ce.reference_url if ce and ce.reference_url else default_ref_url)
            add(f"{e.wikidata_qid}\tP571\t{_date(e.valid_from)}\t{ref}")
        # retype: bound BOTH the old type (P582 end) and the new type (P580 start).
        # ONLY for entities that GENUINELY retyped (>1 type span). A single-span entity
        # did not change type — its existing WD P31 is correct, so don't restate it
        # (that would add a redundant/competing P31, e.g. on the carve-out children).
        # The terminal span's `to` is the entity's valid_to (reform/dissolution, handled
        # by P576), NOT a type-change end -> no P582.
        n = len(e.type_spans)
        if n > 1:
            for i, span in enumerate(e.type_spans):
                target = P31_CITY_TW if span["loai_hinh"].startswith("Thành phố") else P31_PROVINCE
                ref = _ref(span.get("reference_url") or default_ref_url)
                if i < n - 1:                           # an earlier type ended via retype
                    if span.get("to"):
                        add(f"{e.wikidata_qid}\tP31\t{target}\tP582\t{_date(span['to'])}\t{ref}")
                elif span.get("from"):                  # the terminal type started via retype
                    add(f"{e.wikidata_qid}\tP31\t{target}\tP580\t{_date(span['from'])}\t{ref}")

    for ed in edges:
        pre, post = by_id[ed.predecessor], by_id[ed.successor]
        if not (pre.wikidata_qid and post.wikidata_qid):
            continue
        if pre.wikidata_qid == post.wikidata_qid:
            continue                                    # same-QID survivor edited in place
        eff = _date(ed.effective_date)
        ref = _ref(ed.reference_url or default_ref_url)
        if ed.relation == "carved_from":
            # predecessor is the PARENT (persists); successor is the new CHILD.
            add(f"{post.wikidata_qid}\tP807\t{pre.wikidata_qid}\t{ref}")
        elif ed.relation == "absorbed_into":
            add(f"{pre.wikidata_qid}\tP576\t{eff}\t{ref}")
            add(f"{pre.wikidata_qid}\tP7888\t{post.wikidata_qid}\tP585\t{eff}\t{ref}")
            add(f"{pre.wikidata_qid}\tP1366\t{post.wikidata_qid}\tP585\t{eff}\t{ref}")
            add(f"{post.wikidata_qid}\tP1365\t{pre.wikidata_qid}\tP585\t{eff}\t{ref}")
    return ("\n".join(out) + "\n") if out else ""


# ── Phase 2: relation-aware district emitter (built on core primitives) ──

ABOLITION_DATE = "2025-07-01"        # two-tier reform; districts' P576 event date
ABOLITION_VALID_TO = "2025-06-30"


def emit_district_quickstatements(entities: list, edges: list, default_ref_url: str,
                                  abolition_ref: str, create_new: dict | None = None,
                                  p31_assert: set | None = None) -> str:
    """Relation-aware QuickStatements for the district tier + the 2025 abolition.
    P576 fires only on entities that end: from a lineage edge's effective_date for a
    pre-abolition end, or ABOLITION_DATE for a survivor. carved_from parents never get
    P576. See docs/DESIGN-phase2.md §Emit."""
    by_id = {e.local_id: e for e in entities}
    ends_at = {}                     # local_id -> (P576 date, reference) from ending edges
    founding_ref = {}                # successor local_id -> its creating event's reference
    # Only relations that actually MINT the successor supply its P571 founding reference. A
    # merged_into / absorbed_into successor PERSISTS (it's the absorber, not newly founded), so
    # its edge decree is a later merger — it must NOT become that district's inception ref (F3).
    _MINTS_SUCCESSOR = {"split", "carved_from"}
    for ed in edges:
        if ed.reference_url and ed.relation in _MINTS_SUCCESSOR:
            founding_ref[ed.successor] = ed.reference_url
        if predecessor_ends(ed.relation):
            ends_at[ed.predecessor] = (ed.effective_date, ed.reference_url or default_ref_url)
    out, seen = [], set()

    def add(line):
        if line not in seen:
            seen.add(line); out.append(line)

    for e in entities:
        if not e.wikidata_qid:
            continue
        # P571 inception (known valid_from; not gated on qid_status). Referenced to the creating
        # event: the edge's decree if one exists (carve/split), else the founding reference the
        # assembly stamped on type_spans[0] (plain creation / split product), else the default.
        if e.valid_from:
            founding = (founding_ref.get(e.local_id)
                        or (e.type_spans[0].get("reference_url") if e.type_spans else ""))
            ref = ref_s854(founding or default_ref_url)
            add(f"{e.wikidata_qid}\tP571\t{wd_date(e.valid_from)}\t{ref}")
        # P131 per dated parent span — skip unresolved province QIDs (dependency §1). A dated span
        # (re-parenting / creation) references the decree the assembly stamped on the span; a bare
        # baseline span (from=None, not end-dated) legitimately references the default NSO source.
        n_p = len(e.parent_spans)
        for i, sp in enumerate(e.parent_spans):
            if not sp.get("qid"):
                continue
            ref = ref_s854(sp.get("reference_url") or default_ref_url)
            quals = ""
            if sp.get("from"):
                quals += f"\tP580\t{wd_date(sp['from'])}"
            if i < n_p - 1 and sp.get("to"):        # a superseded parent span is end-dated
                quals += f"\tP582\t{wd_date(sp['to'])}"
            add(f"{e.wikidata_qid}\tP131\t{sp['qid']}{quals}\t{ref}")
        # P31 retype (only genuine retypes: >1 type span), dated.
        n_t = len(e.type_spans)
        if n_t > 1:
            for i, sp in enumerate(e.type_spans):
                target = p31_target(sp["loai_hinh"])
                if not target:
                    continue
                ref = ref_s854(sp.get("reference_url") or default_ref_url)
                if i < n_t - 1 and sp.get("to"):
                    add(f"{e.wikidata_qid}\tP31\t{target}\tP582\t{wd_date(sp['to'])}\t{ref}")
                elif i == n_t - 1 and sp.get("from"):
                    add(f"{e.wikidata_qid}\tP31\t{target}\tP580\t{wd_date(sp['from'])}\t{ref}")
        elif p31_assert and e.local_id in p31_assert:
            # Tier-B: the matched WD item is a former-district STUB with a generic P31 (Q56061). A
            # single-span entity normally emits no P31 (WD's is trusted) — here we stamp the correct
            # district-tier P31 so the item is properly typed. Bare (no date), NSO-referenced.
            target = p31_target(e.loai_hinh)
            if target:
                add(f"{e.wikidata_qid}\tP31\t{target}\t{ref_s854(default_ref_url)}")
        # P576: pre-abolition end (from an edge, referenced to its own decree) OR a dissolution
        # with no resolved successor (entity-stamped e.dissolution — the district DID dissolve on
        # the recovered date even if its merge target is manual-curation residue, F2) OR the
        # universal abolition. Never on a carve-out parent (it persists).
        if e.local_id in ends_at:
            end_date, end_ref = ends_at[e.local_id]
            add(f"{e.wikidata_qid}\tP576\t{wd_date(end_date)}\t{ref_s854(end_ref)}")
        elif getattr(e, "dissolution", None):
            diss_date, diss_ref = e.dissolution
            add(f"{e.wikidata_qid}\tP576\t{wd_date(diss_date)}\t{ref_s854(diss_ref)}")
        elif e.valid_to == ABOLITION_VALID_TO:
            add(f"{e.wikidata_qid}\tP576\t{wd_date(ABOLITION_DATE)}\t{ref_s854(abolition_ref)}")

    for ed in edges:
        pre, post = by_id.get(ed.predecessor), by_id.get(ed.successor)
        if not (pre and post and pre.wikidata_qid and post.wikidata_qid):
            continue
        if pre.wikidata_qid == post.wikidata_qid:
            continue                                # same-QID survivor edited in place
        eff = wd_date(ed.effective_date)
        ref = ref_s854(ed.reference_url or default_ref_url)
        if ed.relation == "carved_from":
            add(f"{post.wikidata_qid}\tP807\t{pre.wikidata_qid}\t{ref}")     # parent persists
        elif predecessor_ends(ed.relation):
            add(f"{pre.wikidata_qid}\tP7888\t{post.wikidata_qid}\tP585\t{eff}\t{ref}")
            add(f"{pre.wikidata_qid}\tP1366\t{post.wikidata_qid}\tP585\t{eff}\t{ref}")
            add(f"{post.wikidata_qid}\tP1365\t{pre.wikidata_qid}\tP585\t{eff}\t{ref}")

    # Tier-C create-new succession: these former districts have no lineage edge to their 2025
    # successor (the đặc-khu/phường is a commune-tier unit, out of our graph), so wire it from a
    # curated {local_id: {successor, reference_url}} map. BOTH directions, referenced to the province
    # arrangement resolution that created the successor, P585 = the abolition date. Not a merger →
    # no P7888. (Rides in na-districts.qs because the manual CREATE batch's `<successor> P1365 LAST`
    # back-link errored — QuickStatements can't use LAST as a value on another item.)
    for e in entities:
        info = (create_new or {}).get(e.local_id)
        if not (info and e.wikidata_qid):
            continue
        succ, ref = info["successor"], ref_s854(info.get("reference_url") or default_ref_url)
        eff = wd_date(ABOLITION_DATE)
        add(f"{e.wikidata_qid}\tP1366\t{succ}\tP585\t{eff}\t{ref}")
        add(f"{succ}\tP1365\t{e.wikidata_qid}\tP585\t{eff}\t{ref}")
    return ("\n".join(out) + "\n") if out else ""
