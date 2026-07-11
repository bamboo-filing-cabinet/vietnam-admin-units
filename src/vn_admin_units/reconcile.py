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


def wd_labels(ids: list[str], timeout: int = 30) -> dict:
    """{qid: english (or vi) label} batched."""
    out: dict[str, str] = {}
    for i in range(0, len(ids), 50):
        u = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode({
            "action": "wbgetentities", "ids": "|".join(ids[i:i + 50]),
            "props": "labels", "languages": "en|vi", "format": "json"})
        for qid, e in _get_json(u, timeout)["entities"].items():
            labs = e.get("labels", {})
            out[qid] = (labs.get("en") or labs.get("vi") or {}).get("value", "")
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
    log.info("=== instance-of per pre-reform province (name-aware) ===")
    for r in pre:
        labels = [tl.get(t, t) for t in inst.get(r["wikidata_qid"], [])]
        low = [l.lower() for l in labels]
        if r["name_vi"].startswith("Thành phố"):     # centrally-run city
            ok = any("city" in l or "municipal" in l for l in low)
        else:                                          # Tỉnh -> province (incl. "former provinces")
            ok = any("province" in l for l in low)
        log.info("  %s %-26s %s : %s%s", r["gso_code"], r["name_vi"], r["wikidata_qid"],
                 labels, "" if ok else "   <-- REVIEW (expected " +
                 ("city" if r["name_vi"].startswith("Thành phố") else "province") + ")")
        if not ok:
            issues.append(f"TYPE-MISMATCH {r['gso_code']} {r['name_vi']} {r['wikidata_qid']} {labels}")
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
