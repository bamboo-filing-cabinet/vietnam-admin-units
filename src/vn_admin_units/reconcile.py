import csv
import json
import urllib.parse
import urllib.request
from pathlib import Path

from vn_admin_units.model import Entity


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
        "type": "item", "format": "json", "limit": 5})
    req = urllib.request.Request(u, headers={"User-Agent": "vn-admin-units/0.1 (research)"})
    data = json.load(urllib.request.urlopen(req, timeout=timeout))
    return [{"id": x["id"], "label": x.get("label", ""), "description": x.get("description", "")}
            for x in data["search"]]
