"""Fetch current Wikidata descriptions (en + vi) for all provinces in the QID mapping.

Usage:
    uv run python scripts/fetch_descriptions.py

Outputs: data/province-descriptions.csv
"""

import csv
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAPPING = ROOT / "mappings" / "provinces-qid.csv"
OUTPUT = ROOT / "data" / "province-descriptions.csv"

UA = {"User-Agent": "vn-admin-units/0.1 (research; contact via github.com/bamboo-filing-cabinet)"}
WD_API = "https://www.wikidata.org/w/api.php"


def _get_json(url: str, timeout: int = 30, retries: int = 5) -> dict:
    delay = 2.0
    for attempt in range(retries):
        try:
            return json.load(
                urllib.request.urlopen(
                    urllib.request.Request(url, headers=UA), timeout=timeout
                )
            )
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise


def fetch_descriptions(qids: list[str]) -> dict[str, dict]:
    """Batch-fetch descriptions from Wikidata (max 50 per request)."""
    results = {}
    for i in range(0, len(qids), 50):
        batch = qids[i : i + 50]
        params = urllib.parse.urlencode({
            "action": "wbgetentities",
            "ids": "|".join(batch),
            "props": "descriptions",
            "languages": "en|vi",
            "format": "json",
        })
        url = f"{WD_API}?{params}"
        data = _get_json(url)
        for qid, entity in data.get("entities", {}).items():
            descs = entity.get("descriptions", {})
            results[qid] = {
                "description_en": descs.get("en", {}).get("value", ""),
                "description_vi": descs.get("vi", {}).get("value", ""),
            }
        if i + 50 < len(qids):
            time.sleep(1)  # polite pause between batches
    return results


def main():
    # Read mapping
    rows = list(csv.DictReader(MAPPING.read_text(encoding="utf-8").splitlines()))

    # Deduplicate QIDs (same QID appears in pre2025 + post2025)
    qid_set = sorted({row["wikidata_qid"] for row in rows})
    print(f"Fetching descriptions for {len(qid_set)} unique QIDs...")

    descriptions = fetch_descriptions(qid_set)

    # Write output: one row per mapping row, enriched with descriptions
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "gso_code", "era", "name_vi", "wikidata_qid",
            "description_en", "description_vi",
        ])
        for row in rows:
            qid = row["wikidata_qid"]
            desc = descriptions.get(qid, {})
            writer.writerow([
                row["gso_code"],
                row["era"],
                row["name_vi"],
                qid,
                desc.get("description_en", ""),
                desc.get("description_vi", ""),
            ])

    print(f"Written: {OUTPUT} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
