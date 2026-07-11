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


def _strip_prefix(name: str) -> str:
    return re.sub(r"^(Tỉnh|Thành phố)\s+", "", name).strip()


def wd_lookup(name: str, timeout: int = 30) -> dict:
    """Best Wikidata item for a VN province name: search, then prefer a candidate
    whose P17 = Vietnam (Q881). Returns {qid, label, desc, confidence}."""
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
    build_province_qid_csv()


if __name__ == "__main__":
    main()
