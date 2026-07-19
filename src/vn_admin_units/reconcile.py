import csv
import json
import logging
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from vn_admin_units.model import Entity

log = logging.getLogger("vn_admin_units.reconcile")
HEADER = ["gso_code", "era", "name_vi", "wikidata_qid", "qid_status", "match_status"]
REUSE = {"verified", "manual"}   # match_status values trusted on resume (skip re-lookup)

VIETNAM = "Q881"
UA = {"User-Agent": "vn-admin-units/0.1 (research; contact via github.com/bamboo-filing-cabinet)"}


def _get_json(url: str, timeout: int = 30, retries: int = 5) -> dict:
    """GET JSON with exponential backoff on 429/5xx (Wikidata throttling)."""
    delay = 2.0
    for attempt in range(retries):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < retries - 1:
                time.sleep(delay); delay *= 2
                continue
            raise


def load_seed(path: str) -> dict:
    """(gso_code, era) -> {'qid', 'qid_status'} from the curated CSV."""
    seed = {}
    for row in csv.DictReader(Path(path).read_text(encoding="utf-8").splitlines()):
        seed[(row["gso_code"], row["era"])] = {
            "qid": row["wikidata_qid"], "qid_status": row.get("qid_status", "existing")}
    return seed


def apply_seed(entities: list[Entity], seed: dict) -> list[Entity]:
    for e in entities:
        hit = seed.get((e.gso_code, e.era))
        if hit:
            e.wikidata_qid = hit["qid"]
            e.qid_status = hit["qid_status"]
    return entities


def wd_search(name: str, timeout: int = 30) -> list[dict]:
    """wbsearchentities by Vietnamese label; returns [{id,label,description}]."""
    u = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode({
        "action": "wbsearchentities", "search": name, "language": "vi",
        "type": "item", "format": "json", "limit": 6})
    data = _get_json(u, timeout)
    return [{"id": x["id"], "label": x.get("label", ""), "description": x.get("description", "")}
            for x in data["search"]]


def wd_country(ids: list[str], timeout: int = 30) -> dict:
    """{qid: country QID (P17)} for the given items (batched wbgetentities)."""
    if not ids:
        return {}
    u = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode({
        "action": "wbgetentities", "ids": "|".join(ids), "props": "claims",
        "format": "json"})
    ents = _get_json(u, timeout)["entities"]
    out = {}
    for qid, e in ents.items():
        vals = []
        for c in e.get("claims", {}).get("P17", []):
            dv = c.get("mainsnak", {}).get("datavalue", {}).get("value", {})
            if isinstance(dv, dict) and dv.get("id"):
                vals.append(dv["id"])
        out[qid] = vals
    return out


def wd_claims_ids(ids: list[str], prop: str, timeout: int = 30) -> dict:
    """{qid: [target QIDs]} for an item-valued property, batched (<=50/call)."""
    out: dict[str, list[str]] = {}
    for i in range(0, len(ids), 50):
        u = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode({
            "action": "wbgetentities", "ids": "|".join(ids[i:i + 50]),
            "props": "claims", "format": "json"})
        for qid, e in _get_json(u, timeout)["entities"].items():
            vals = []
            for c in e.get("claims", {}).get(prop, []):
                dv = c.get("mainsnak", {}).get("datavalue", {}).get("value", {})
                if isinstance(dv, dict) and dv.get("id"):
                    vals.append(dv["id"])
            out[qid] = vals
        time.sleep(1)
    return out


def wd_labels(ids: list[str], langs: tuple = ("en", "vi"), timeout: int = 30) -> dict:
    """{qid: label in the first available of `langs`} batched."""
    out: dict[str, str] = {}
    for i in range(0, len(ids), 50):
        u = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode({
            "action": "wbgetentities", "ids": "|".join(ids[i:i + 50]),
            "props": "labels", "languages": "|".join(langs), "format": "json"})
        for qid, e in _get_json(u, timeout)["entities"].items():
            labs = e.get("labels", {})
            val = next((labs[l]["value"] for l in langs if l in labs), "")
            out[qid] = val
        time.sleep(1)
    return out


def audit_province_qids(path: str = "mappings/provinces-qid.csv") -> list[str]:
    """Pre-upload correctness audit: completeness, pre-QID distinctness, post⊆pre,
    and instance-of sanity (each QID is a VN province/city/territorial entity)."""
    rows = list(csv.DictReader(Path(path).read_text(encoding="utf-8").splitlines()))
    pre = [r for r in rows if r["era"] == "pre2025"]
    post = [r for r in rows if r["era"] == "post2025"]
    issues: list[str] = []
    from collections import Counter
    for r in rows:
        if not r["wikidata_qid"]:
            issues.append(f"UNRESOLVED {r['era']} {r['gso_code']} {r['name_vi']}")
    prec = Counter(r["wikidata_qid"] for r in pre if r["wikidata_qid"])
    for q, n in prec.items():
        if n > 1:
            issues.append(f"DUP pre QID {q} x{n}")
    preqids = set(prec)
    for r in post:
        if r["wikidata_qid"] and r["wikidata_qid"] not in preqids:
            issues.append(f"POST-NOT-IN-PRE {r['name_vi']} {r['wikidata_qid']}")

    qids = sorted({r["wikidata_qid"] for r in rows if r["wikidata_qid"]})
    inst = wd_claims_ids(qids, "P31")
    tl = wd_labels(sorted({t for v in inst.values() for t in v}))
    item_lbl = wd_labels(qids, langs=("vi", "en"))   # the province items' own labels (identity check)

    import unicodedata

    def _bare(s: str) -> str:
        """Strip tier prefix, lowercase, and fold Vietnamese diacritics so tone-mark
        placement variants match (GSO 'Hoà Bình' == Wikidata 'Hòa Bình')."""
        s = re.sub(r"^(tỉnh|thành phố)\s+", "", s.strip().lower())
        s = "".join(c for c in unicodedata.normalize("NFD", s)
                    if unicodedata.category(c) != "Mn")
        return s.replace("đ", "d")

    log.info("=== per pre-reform province: type + label-match ===")
    for r in pre:
        labels = [tl.get(t, t) for t in inst.get(r["wikidata_qid"], [])]
        low = [l.lower() for l in labels]
        want_city = r["name_vi"].startswith("Thành phố")
        type_ok = any(("city" in l or "municipal" in l) for l in low) if want_city \
            else any("province" in l for l in low)
        lbl = item_lbl.get(r["wikidata_qid"], "")
        name_ok = _bare(r["name_vi"]) in _bare(lbl) or _bare(lbl) in _bare(r["name_vi"])
        flag = "" if (type_ok and name_ok) else \
            f"   <-- REVIEW ({'type' if not type_ok else ''}{',' if not type_ok and not name_ok else ''}{'label' if not name_ok else ''})"
        log.info("  %s %-24s %s  label=%-22s type=%s%s",
                 r["gso_code"], r["name_vi"], r["wikidata_qid"], lbl, labels, flag)
        if not type_ok:
            issues.append(f"TYPE-MISMATCH {r['gso_code']} {r['name_vi']} {r['wikidata_qid']} {labels}")
        if not name_ok:
            issues.append(f"LABEL-MISMATCH {r['gso_code']} {r['name_vi']} {r['wikidata_qid']} label={lbl!r}")
    log.info("audit: pre=%d (distinct %d), post=%d, issues=%d",
             len(pre), len(preqids), len(post), len(issues))
    for i in issues:
        log.warning(i)
    return issues


def _strip_prefix(name: str) -> str:
    return re.sub(r"^(Tỉnh|Thành phố)\s+", "", name).strip()


def wd_lookup(name: str, timeout: int = 30) -> dict:
    """Best Wikidata item for a VN province name: search, then prefer a candidate
    whose P17 = Vietnam (Q881). Returns {qid, label, desc, confidence}.

    CAVEAT: search can return a same-named entity of the wrong type (e.g. the
    provincial *capital city* instead of the *province* — this happened for Cà
    Mau: city Q25262 vs province Q33354). P17=Vietnam alone does not disambiguate
    type. The `--audit` step (audit_province_qids, name-aware instance-of check)
    is REQUIRED to catch these; fix flagged rows manually with match_status=manual."""
    hits = wd_search(_strip_prefix(name), timeout)
    if not hits:
        return {"qid": "", "label": "", "desc": "", "confidence": "none"}
    p17 = wd_country([h["id"] for h in hits], timeout)
    for h in hits:
        if VIETNAM in p17.get(h["id"], []):
            return {"qid": h["id"], "label": h["label"], "desc": h["description"],
                    "confidence": "verified"}
    return {"qid": hits[0]["id"], "label": hits[0]["label"], "desc": hits[0]["description"],
            "confidence": "unverified"}


def _write_csv(out_path: str, rows: list[list[str]]) -> None:
    """Rewrite the whole CSV (small; called after each pre row for crash-safety)."""
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(rows)


def _load_existing(out_path: str) -> dict:
    """{(gso_code, era): match_status→qid} from a prior run, for resume."""
    p = Path(out_path)
    if not p.exists():
        return {}
    return {(r["gso_code"], r["era"]): r
            for r in csv.DictReader(p.read_text(encoding="utf-8").splitlines())}


def build_province_qid_csv(out_path: str = "mappings/provinces-qid.csv", pause: float = 5.0) -> None:
    """Reconcile all 63 pre-reform provinces to Wikidata QIDs (verified by P17=VN),
    derive the 34 post-reform QIDs from the primary-predecessor lineage (edit-in-
    place survivors), and write the full mapping CSV.

    Incremental (writes after every province) + resumable (rows already
    `verified`/`manual` in the CSV are reused, not re-looked-up) + logs progress
    to stdout. Run: python -m vn_admin_units.reconcile"""
    from vn_admin_units.model import build_entities, build_lineage
    from vn_admin_units.crosswalk import read_province_crosswalk
    pre = json.loads(Path("data/provinces-2025-06-30.json").read_text(encoding="utf-8"))
    post = json.loads(Path("data/provinces-2026-07-10.json").read_text(encoding="utf-8"))
    existing = _load_existing(out_path)

    pre_qid: dict[str, str] = {}
    rows: list[list[str]] = []
    n = len(pre)
    t0 = time.monotonic()
    log.info("reconciling %d pre-reform provinces (resume: %d rows on disk)", n, len(existing))
    for i, r in enumerate(pre, 1):
        ex = existing.get((r["ma"], "pre2025"))
        if ex and ex.get("wikidata_qid") and ex.get("match_status") in REUSE:
            qid, conf = ex["wikidata_qid"], ex["match_status"]
            log.info("[%d/%d] pre %s %-28s = %s (cached: %s)", i, n, r["ma"], r["ten"], qid, conf)
        else:
            try:
                hit = wd_lookup(r["ten"])
            except Exception as e:
                hit = {"qid": "", "desc": str(e)[:50], "confidence": "error"}
            time.sleep(pause)
            qid, conf = hit["qid"], hit["confidence"]
            log.info("[%d/%d] pre %s %-28s -> %s (%s) %s",
                     i, n, r["ma"], r["ten"], qid or "(none)", conf, hit.get("desc", "")[:34])
        pre_qid[r["ma"]] = qid
        rows.append([r["ma"], "pre2025", r["ten"], qid, "existing", conf])
        _write_csv(out_path, rows)   # crash-safe: latest state always on disk

    log.info("deriving 34 post-reform QIDs from primary-predecessor lineage")
    ents = build_entities(pre, post)
    edges = build_lineage(ents, read_province_crosswalk("data/raw/crosswalk/DoiChieu_Tinh_2025.xls"))
    primary = {e.successor: e.predecessor for e in edges if e.primary}
    for r in post:
        pred = primary.get(f"p-{r['ma']}-post2025")
        pred_code = pred.split("-")[1] if pred else None
        qid = pre_qid.get(pred_code, "") if pred_code else ""
        rows.append([r["ma"], "post2025", r["ten"], qid, "existing", "derived-primary"])
        log.info("post %s %-28s = %s (from pre %s)", r["ma"], r["ten"], qid or "(none)", pred_code)
    _write_csv(out_path, rows)

    resolved = sum(1 for x in rows if x[3])
    review = [x for x in rows if not x[3] or x[5] in ("error", "unverified")]
    log.info("DONE in %.0fs: %d rows, %d resolved, %d need review -> %s",
             time.monotonic() - t0, len(rows), resolved, len(review), out_path)
    for x in review:
        log.warning("REVIEW: code=%s era=%s name=%s qid=%r status=%s", x[0], x[1], x[2], x[3], x[5])


# ── Phase 1b: province history reconciliation (separate local_id-keyed mapping) ──

HISTORY_HEADER = ["local_id", "terminal_code", "name_vi", "wikidata_qid", "qid_status", "match_status"]


def reuse_1a_qids(entities: list, seed_1a_path: str = "mappings/provinces-qid.csv") -> list:
    """Fill wikidata_qid/qid_status from 1a's (gso_code, era='pre2025') mapping by
    terminal_code. Entities absent from 1a (e.g. Hà Tây, dissolved 2008) stay None
    for fresh reconciliation."""
    seed = {}
    for row in csv.DictReader(Path(seed_1a_path).read_text(encoding="utf-8").splitlines()):
        if row["era"] == "pre2025":
            seed[row["gso_code"]] = (row["wikidata_qid"], row.get("qid_status", "existing"))
    for e in entities:
        hit = seed.get(e.terminal_code)
        if hit:
            e.wikidata_qid, e.qid_status = hit
    return entities


def load_history_seed(path: str = "mappings/provinces-history-qid.csv") -> dict:
    """{local_id: (qid, qid_status)} for rows a human has verified/manually fixed
    (match_status in {verified, manual}). Lets the pipeline preserve the hand-filled
    Hà Tây QID across rebuilds (reuse_1a_qids can't supply it — Hà Tây isn't in 1a)."""
    p = Path(path)
    if not p.exists():
        return {}
    out = {}
    for row in csv.DictReader(p.read_text(encoding="utf-8").splitlines()):
        if row.get("wikidata_qid") and row.get("match_status") in {"verified", "manual"}:
            out[row["local_id"]] = (row["wikidata_qid"], row.get("qid_status") or "existing")
    return out


def apply_history_seed(entities: list, seed: dict) -> list:
    """Apply the trusted history seed (verified/manual rows). **Overrides** an
    already-set QID — a human 'manual' correction must beat a reused-but-wrong 1a QID
    (the pipeline runs reuse_1a_qids first, then this)."""
    for e in entities:
        if e.local_id in seed:
            e.wikidata_qid, e.qid_status = seed[e.local_id]
    return entities


def write_history_mapping(entities: list, out_path: str = "mappings/provinces-history-qid.csv") -> None:
    """Write the local_id-keyed history mapping (separate file — never mutates
    provinces-qid.csv). Preserves the match_status of rows a human verified/fixed, so a
    rebuild never downgrades a hand-filled QID (e.g. Hà Tây) back to needs-lookup."""
    prior = {}
    p = Path(out_path)
    if p.exists():
        for row in csv.DictReader(p.read_text(encoding="utf-8").splitlines()):
            if row.get("match_status") in {"verified", "manual"}:
                prior[row["local_id"]] = row["match_status"]
    lines = [",".join(HISTORY_HEADER)]
    for e in entities:
        status = prior.get(e.local_id) or ("reused" if e.wikidata_qid else "needs-lookup")
        lines.append(",".join([e.local_id, e.terminal_code, e.name_vi,
                               e.wikidata_qid or "", e.qid_status or "", status]))
    Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def audit_history_qids(mapping_path: str = "mappings/provinces-history-qid.csv") -> list:
    """Pre-upload audit over ALL history entities (1a's audit only checks era==pre2025).
    Flags unresolved QIDs, the instance-of TYPE check, AND a NAME/label match — so a
    same-type but WRONG item (e.g. a Hà Tây QID pointing at a different province) is
    caught, not just a wrong type. Reuses fold_name for the label match."""
    from vn_admin_units.names import fold_name
    rows = list(csv.DictReader(Path(mapping_path).read_text(encoding="utf-8").splitlines()))
    issues = [f"UNRESOLVED {r['local_id']} {r['name_vi']}" for r in rows if not r["wikidata_qid"]]
    qids = sorted({r["wikidata_qid"] for r in rows if r["wikidata_qid"]})
    inst = wd_claims_ids(qids, "P31")
    tl = wd_labels(sorted({t for v in inst.values() for t in v}))
    item_lbl = wd_labels(qids, langs=("vi", "en"))
    for r in rows:
        if not r["wikidata_qid"]:
            continue
        labels = [tl.get(t, t).lower() for t in inst.get(r["wikidata_qid"], [])]
        want_city = r["name_vi"].startswith("Thành phố")
        type_ok = any(("city" in l or "municipal" in l) for l in labels) if want_city \
            else any("province" in l for l in labels)
        if not type_ok:
            issues.append(f"TYPE {r['local_id']} {r['name_vi']} {r['wikidata_qid']} -> {labels}")
        lbl = item_lbl.get(r["wikidata_qid"], "")
        if not (fold_name(r["name_vi"]) in fold_name(lbl) or fold_name(lbl) in fold_name(r["name_vi"])):
            issues.append(f"LABEL {r['local_id']} {r['name_vi']} != {r['wikidata_qid']} ({lbl})")
    return issues


# ── Phase 2: district reconciliation (separate local_id-keyed mapping) ──

DISTRICT_HEADER = ["local_id", "terminal_code", "name_vi", "parent_code",
                   "wikidata_qid", "qid_status", "match_status"]

_WDQS = "https://query.wikidata.org/sparql"


def sparql_vn_districts(timeout: int = 90) -> list:
    """All Vietnamese district-level items (incl. abolished): {qid, label, aliases, parent_qid}.
    One pull instead of ~700 wbsearchentities calls. `aliases` are the vi/en altLabels — a
    near-empty item frequently holds the GSO name only as an ALIAS (its main label being an
    English or stale form), so matching must include them (design §Reconciliation). parent_qid
    is the WD P131 target (may be stale — a WEAK tiebreak only, after attach_parent_codes maps
    it to a GSO province code)."""
    q = """SELECT ?item ?itemLabel ?parent
             (GROUP_CONCAT(DISTINCT ?alias; separator="|") AS ?aliases) WHERE {
      ?item wdt:P31/wdt:P279* wd:Q13221722 .        # district-level admin unit
      ?item wdt:P17 wd:Q881 .                        # country = Vietnam
      OPTIONAL { ?item wdt:P131 ?parent . }
      OPTIONAL { ?item skos:altLabel ?alias . FILTER(LANG(?alias) IN ("vi", "en")) }
      SERVICE wikibase:label { bd:serviceParam wikibase:language "vi,en". }
    } GROUP BY ?item ?itemLabel ?parent"""
    u = _WDQS + "?" + urllib.parse.urlencode({"query": q, "format": "json"})
    data = _get_json(u, timeout)
    out = []
    for b in data["results"]["bindings"]:
        parent = b.get("parent", {}).get("value", "")
        aliases = [a for a in b.get("aliases", {}).get("value", "").split("|") if a]
        out.append({"qid": b["item"]["value"].rsplit("/", 1)[-1],
                    "label": b.get("itemLabel", {}).get("value", ""),
                    "aliases": aliases,
                    "parent_qid": parent.rsplit("/", 1)[-1] if parent else None,
                    "parent_code": None})     # filled by attach_parent_codes
    return out


def attach_parent_codes(candidates: list, prov_qid_to_code: dict) -> list:
    """Map each candidate's parent_qid → GSO province code (via the reconciled province
    mappings) so match_districts can use province as a weak tiebreak. A candidate whose
    parent_qid isn't in the map keeps parent_code=None (name-only)."""
    for c in candidates:
        c["parent_code"] = prov_qid_to_code.get(c.get("parent_qid"))
    return candidates


def match_districts(entities: list, candidates: list, search_fn=None, verify_fn=None) -> list:
    """Match each district Entity to a WD candidate by FOLDED NAME — indexing candidate
    LABELS **and aliases**, and testing the entity's OWN aliases too (a near-empty item often
    holds the GSO name only as an alias). Parent province is a WEAK tiebreak among same-name
    hits; a lone name hit is accepted even if its P131 disagrees (WD P131 is stale — design §4).

    A bulk miss is NOT immediately 'new': when `search_fn` (wbsearchentities) is supplied, fall
    back to a per-item search verified by `verify_fn` (P17=Vietnam) before conceding a gap. Only
    a *verified* no-hit becomes qid_status='new'. Both fns are injected so the unit tests stay
    offline; the pipeline (D11) passes the live `wd_search`/`wd_country`."""
    from collections import defaultdict
    from vn_admin_units.names import fold_district_name
    by_name = defaultdict(list)
    for c in candidates:
        for nm in (c.get("label", ""), *c.get("aliases", [])):
            if nm:
                by_name[fold_district_name(nm)].append(c)

    def bulk_hit(e):
        for k in (e.name_vi, *getattr(e, "aliases", [])):
            hits = by_name.get(fold_district_name(k))
            if hits:
                return hits
        return []

    for e in entities:
        hits = bulk_hit(e)
        if hits:
            prov = e.parent_spans[-1]["code"] if e.parent_spans else None
            best = next((h for h in hits if h.get("parent_code") == prov), hits[0])
            e.wikidata_qid, e.qid_status = best["qid"], "existing"
            continue
        found = _district_search_fallback(e, search_fn, verify_fn) if search_fn else ""
        if found:
            e.wikidata_qid, e.qid_status = found, "existing"
        else:
            e.qid_status = "new"
    return entities


def _district_search_fallback(e, search_fn, verify_fn=None) -> str:
    """Per-item wbsearchentities for a bulk-SPARQL miss (design §Reconciliation fallback).
    Returns a QID whose label folds to the entity name AND (when verify_fn is given) whose
    P17 = Vietnam; else '' (a genuine gap)."""
    from vn_admin_units.names import fold_district_name
    want = fold_district_name(e.name_vi)
    hits = search_fn(re.sub(r"^(Huyện|Quận|Thị xã|Thành phố)\s+", "", e.name_vi, flags=re.I))
    ids = [h["id"] for h in hits]
    vn = verify_fn(ids) if (verify_fn and ids) else {}
    for h in hits:
        name_ok = fold_district_name(h.get("label", "")) == want
        vn_ok = (VIETNAM in vn.get(h["id"], [])) if verify_fn else True
        if name_ok and vn_ok:
            return h["id"]
    return ""


def load_district_seed(path: str = "mappings/districts-qid.csv") -> dict:
    """{local_id: (qid, qid_status)} for HUMAN-LOCKED rows only (verified/manual). Used by the
    live step to let a hand-fix beat a fresh auto-match. NOT what the offline build reads —
    see load_district_mapping (auto `matched` rows must survive to emit)."""
    p = Path(path)
    if not p.exists():
        return {}
    out = {}
    for row in csv.DictReader(p.read_text(encoding="utf-8").splitlines()):
        if row.get("wikidata_qid") and row.get("match_status") in {"verified", "manual"}:
            out[row["local_id"]] = (row["wikidata_qid"], row.get("qid_status") or "existing")
    return out


def load_district_mapping(path: str = "mappings/districts-qid.csv") -> dict:
    """{local_id: (qid, qid_status)} for EVERY row that has a QID, regardless of match_status
    (matched / verified / manual). This is what the OFFLINE build applies so the QIDs that
    `reconcile_districts_live` wrote as `matched` reach the emitter instead of being dropped
    (F1). Upload stays gated on the audit — `matched` is auto-but-usable, not human-approved."""
    p = Path(path)
    if not p.exists():
        return {}
    out = {}
    for row in csv.DictReader(p.read_text(encoding="utf-8").splitlines()):
        if row.get("wikidata_qid"):
            out[row["local_id"]] = (row["wikidata_qid"], row.get("qid_status") or "existing")
    return out


def apply_district_seed(entities: list, seed: dict) -> list:
    for e in entities:
        if e.local_id in seed:
            e.wikidata_qid, e.qid_status = seed[e.local_id]
    return entities


def load_acknowledged_gaps(path: str = "mappings/districts-qid.csv") -> set:
    """local_ids a human has marked `match_status == "gap"` — a district with genuinely no WD
    item, acknowledged as create-later (design §Reconciliation, e.g. Bắc Từ Liêm). The pre-emit
    completeness gate (F1) lets these pass (they emit nothing NOW, by design) but fails on any
    un-triaged `needs-lookup` row, so a silently-incomplete artifact can't ship."""
    p = Path(path)
    if not p.exists():
        return set()
    return {row["local_id"] for row in csv.DictReader(p.read_text(encoding="utf-8").splitlines())
            if row.get("match_status") == "gap"}


def write_district_mapping(entities: list, out_path: str = "mappings/districts-qid.csv") -> None:
    """Write the local_id-keyed district mapping (separate file). Preserves the prior
    match_status of ANY resolved row (matched/verified/manual) so a rebuild never downgrades a
    QID-bearing row to needs-lookup (F1) — only a genuinely QID-less entity gets needs-lookup."""
    prior = {}
    p = Path(out_path)
    if p.exists():
        for row in csv.DictReader(p.read_text(encoding="utf-8").splitlines()):
            if row.get("match_status"):
                prior[row["local_id"]] = row["match_status"]
    lines = [",".join(DISTRICT_HEADER)]
    for e in entities:
        prov = e.parent_spans[-1]["code"] if e.parent_spans else ""
        if not e.wikidata_qid:
            # a QID-less row keeps a human 'gap' acknowledgment (create-later); else needs-lookup.
            status = "gap" if prior.get(e.local_id) == "gap" else "needs-lookup"
        else:
            # a resolved row keeps only a resolved prior status; a former 'gap' that now HAS a QID
            # (e.g. later found by reconcile) must NOT stay 'gap' — it becomes 'matched' (F2).
            prev = prior.get(e.local_id)
            status = prev if prev in {"verified", "manual", "matched"} else "matched"
        lines.append(",".join([e.local_id, e.terminal_code, e.name_vi, prov,
                               e.wikidata_qid or "", e.qid_status or "", status]))
    Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def audit_district_qids(mapping_path: str = "mappings/districts-qid.csv") -> list:
    """Pre-upload audit: unresolved rows, instance-of TYPE check (district-level), and a
    NAME/label match (so a same-type but WRONG item is caught). Province half stays weak.

    A QID-less row marked `match_status="gap"` is a REVIEWED create-later gap (consistent with the
    completeness gate) — reported as an informational `GAP …` line, NOT an `UNRESOLVED` issue, so
    the "resolve all issues" audit can go clean while acknowledged gaps remain. Only un-triaged
    QID-less rows are `UNRESOLVED`."""
    from vn_admin_units.names import fold_district_name
    rows = list(csv.DictReader(Path(mapping_path).read_text(encoding="utf-8").splitlines()))
    issues = [f"UNRESOLVED {r['local_id']} {r['name_vi']}"
              for r in rows if not r["wikidata_qid"] and r.get("match_status") != "gap"]
    gaps = [f"GAP {r['local_id']} {r['name_vi']}"
            for r in rows if not r["wikidata_qid"] and r.get("match_status") == "gap"]
    for g in gaps:
        log.info("acknowledged %s", g)               # informational — a reviewed create-later gap
    qids = sorted({r["wikidata_qid"] for r in rows if r["wikidata_qid"]})
    if not qids:
        return issues
    inst = wd_claims_ids(qids, "P31")
    tl = wd_labels(sorted({t for v in inst.values() for t in v}))
    item_lbl = wd_labels(qids, langs=("vi", "en"))
    for r in rows:
        if not r["wikidata_qid"]:
            continue
        labels = [tl.get(t, t).lower() for t in inst.get(r["wikidata_qid"], [])]
        # District-tier types only: district (huyện/quận), town (thị xã), city (thành phố
        # thuộc tỉnh). "ward" is a LOWER tier (phường/xã) — a ward-typed item matched to a
        # district is a wrong match (names overlap across tiers), so it must NOT pass (F3).
        if not any(("district" in l or "town" in l or "city" in l) for l in labels):
            issues.append(f"TYPE {r['local_id']} {r['name_vi']} {r['wikidata_qid']} -> {labels}")
        lbl = item_lbl.get(r["wikidata_qid"], "")
        if not (fold_district_name(r["name_vi"]) in fold_district_name(lbl)
                or fold_district_name(lbl) in fold_district_name(r["name_vi"])):
            issues.append(f"LABEL {r['local_id']} {r['name_vi']} != {r['wikidata_qid']} ({lbl})")
    return issues


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stdout)
    if "--audit" in sys.argv:
        audit_province_qids()
    else:
        build_province_qid_csv()


if __name__ == "__main__":
    main()
