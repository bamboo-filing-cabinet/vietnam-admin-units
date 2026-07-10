REFERENCE_URL = "https://danhmuchanhchinh.nso.gov.vn/"


def _date(d: str) -> str:
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
