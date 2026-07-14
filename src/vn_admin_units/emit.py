REFERENCE_URL = "https://danhmuchanhchinh.nso.gov.vn/"


def _date(d: str) -> str:
    """Wikidata date literal (day precision). Defensively takes the date part in
    case a source ever passes a datetime string like '2025-07-01 00:00:00'."""
    d = str(d).strip().split(" ")[0].split("T")[0]
    return f"+{d}T00:00:00Z/11"


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

NSO_SOURCE_URL = "https://danhmuchanhchinh.nso.gov.vn/"
# WD item QIDs for the two admin-unit types (CONFIRM via constraints.describe_items).
P31_PROVINCE = "Q13079705"       # province of Vietnam
P31_CITY_TW = "Q3623867"         # centrally-run city of Vietnam


def _ref(url: str) -> str:
    return f'S854\t"{url}"'


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
        # Only retyped entities have >1 span. The terminal span's `to` is the entity's
        # valid_to (reform/dissolution, handled by P576), NOT a type-change end -> no P582.
        n = len(e.type_spans)
        for i, span in enumerate(e.type_spans):
            target = P31_CITY_TW if span["loai_hinh"].startswith("Thành phố") else P31_PROVINCE
            ref = _ref(span.get("reference_url") or default_ref_url)
            if i < n - 1:                               # an earlier type ended via retype
                if span.get("to"):
                    add(f"{e.wikidata_qid}\tP31\t{target}\tP582\t{_date(span['to'])}\t{ref}")
            elif span.get("from"):                      # the terminal type started via retype
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
