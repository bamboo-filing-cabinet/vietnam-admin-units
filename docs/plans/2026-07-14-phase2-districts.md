# Phase 2 — District tier 2004→2025 (Wikidata Goal B) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the district tier (huyện / quận / thị xã / thành phố thuộc tỉnh) as a continuous-entity lineage graph 2004→2025 — every create / dissolve / merge / split / carve-out / rename / type-upgrade / **re-parenting** the yearly Đối Chiếu windows expose, plus the universal **2025-07-01 abolition** — reconcile ~700 districts to Wikidata QIDs, and emit a referenced, relation-aware QuickStatements batch. This drives Goal B (Wikidata district corrections) and lays the parent layer Phase 3 wards need for historical `P131`.

**Architecture:** Two movements. **(A) Tier-neutral core refactor first** (design §2 recommendation): extract a shared `Entity` / `LineageEdge` / emit-primitive core out of `model.py` (1a), `province_history.py` (1b), and `emit.py`, keeping 1a + 1b behavior identical (the 62-test suite is the regression gate). **(B) District build** on that core: a district-template `Ghi Chú` sibling parser, event discovery from the 23 cached yearly windows (structured-column classification, `Ghi Chú` supplementary), event-log chaining into one continuous entity per district (code-inheritance-aware `local_id`, dated parent-province spans), province-aware reconciliation via a bulk SPARQL pull, a relation-aware emitter that only dissolves entities that actually end, and the universal 2025 abolition.

**Tech Stack:** Python 3.11+, `uv`; `pandas`+`xlrd` (`.xls`); Playwright (`ingest` group — only for re-fetching windows, all 23 already cached); stdlib `urllib` (WD API + SPARQL); `requests`+`lxml` (Nghị định list); `pytest`.

**Read first:** `docs/DESIGN-phase2.md` (the spec — decisions, model, lineage resolution, emit rules, dependencies & risks). Grounding journals: `2026-07-13.01` (source scouting — Đối Chiếu is the district goldmine; Lịch Sử is inventory-only), `2026-07-13.02` (yearly-window validation, extraction mechanism, decree cross-check: 147 structural decrees, no real miss), `2026-07-10.10` (change taxonomy). The Phase-1b plan `docs/plans/2026-07-14-phase1b-province-history.md` is the template this mirrors. Existing code this plan refactors/extends: `src/vn_admin_units/{model,province_history,emit,crosswalk,ghichu,names,reconcile,constraints,crosscheck_decrees,cli}.py`.

**Scope discipline (from the design's Out-of-scope §):** Event floor at **2004** — pre-2004 ancestry is Phase 4 (the Đối Chiếu tool returns the 2002→2004 code-remap, not diffs, below the floor). Boundary-only adjustments ("điều chỉnh địa giới … để mở rộng …" with no identity change) are **not** lineage events. Goal A (district-composed NA11–NA15 exports) is a later build on this graph. Ward re-parenting at the 2025 abolition is Phase 3. **The Phase-1a reference backfill (design §3) is deferred to its own follow-up plan — not in scope here.** Upload is a separate reviewed step after the audit + constraints gates pass (personal WD account).

## Execution corrections (2026-07-17) — supersede D4/D6.5/D7 where they conflict

Discovered while executing against the real cached data; these OVERRIDE the as-written date/reference mechanism in D4/D6.5/D7:

1. **Dissolve/merge DATE comes from the crosswalk *survivor* row, NOT the Nghị định list.** D6.5's `decrees_naming(unit_name, …)` finds **nothing** on real data — the Nghị định *list titles* name the **province** ("sắp xếp … tỉnh Cao Bằng"), not the dissolved district. But the merger's real per-unit effective date **and** decree code sit on the **absorbing survivor's** crosswalk row (`succ_hieu_luc` + `succ_nghi_dinh`), reachable via the dissolved row's Ghi Chú "vào Y" target (or the `district-merge-targets.json` override when there's no prose). So `_apply_dissolve` recovers date+decree from the survivor row; `decrees_naming`/`nghidinh.json` are retained only for the existing cross-check. The dissolved row's own `base_hieu_luc` (stale 2004 date) is never used.
2. **Ground-truth dates corrected (per-unit, from real survivor rows):** Từ Liêm split `2013-12-28` (`132/NQ-CP`); **Thông Nông→Hà Quảng `2020-02-01` (`864/NQ-UBTVQH14`)** — NOT 2020-03-01; Trà Lĩnh→Trùng Khánh & Phục Hoà→Quảng Uyên(→Quảng Hòa) `2020-03-01` (`897/NQ-UBTVQH14`); **Nông Sơn→Quế Sơn `2025-01-01` (`1241/NQ-UBTVQH15`)** — no Ghi Chú target, so a curated `district-merge-targets.json` entry. (The plan's "three Cao Bằng mergers all at 2020-03-01 / decree 897" was wrong.)
3. **Reference URLs come from thuvienphapluat via WebSearch, cached in `data/decree-urls.json`.** thuvienphapluat blocks direct fetch (Cloudflare 403), and the NSO `nghidinh.json` has no per-row URL column — so the D4 "fetch_decrees url extension via lxml" does **not** apply. Instead: WebSearch `<decree code>` restricted to `thuvienphapluat.vn`, take the confirmed `van-ban/…` result, cache `{code: url}`. This is proven (4/4 canonical decrees resolved). The cited reference set is **~150 distinct decrees** (measured: all 157 changed-row codes tie to real events; only 7 are garbled typos) — a large batch resolved incrementally, with garbled/unindexed codes as the manual residue.

---

## File Structure

**Movement A — tier-neutral core (refactor, behavior-preserving):**

- Create `src/vn_admin_units/core.py` — the shared tier-neutral layer. (1) Emit primitives: `wd_date()` (was `emit._date`), `ref_s854()` (was `emit._ref`), `REFERENCE_URL`, the `P31_TARGETS` type→QID map + `p31_target()`. (2) The relation vocabulary + `predecessor_ends()` — the single source of truth for "which relations end the predecessor (⇒ `P576`)". (3) Superset `Entity` / `LineageEdge` dataclasses that all three tiers construct. One responsibility: the tier-neutral shape + Wikidata literal helpers.
- Modify `src/vn_admin_units/emit.py` — import the primitives from `core`; leave both emitters' *rules* untouched (pure de-duplication).
- Modify `src/vn_admin_units/model.py` (1a) — import `Entity`/`LineageEdge` from `core`; `build_entities` constructs the superset (`gso_codes=[ma]`, `era=…`). Reads via the `gso_code`/`era` back-compat accessors.
- Modify `src/vn_admin_units/province_history.py` (1b) — import `Entity`/`LineageEdge` from `core`; drop its private dataclasses; keep `hist_local_id` + assembly.

**Movement B — district build:**

- Create `src/vn_admin_units/district_model.py` — district entity+lineage assembly. `dist_local_id`, entity/edge construction on `core`, event discovery, layered lineage resolution, the carve-out-vs-split discriminator, the universal 2025 abolition, and the roster-delta cross-validation assertion. Largest new module.
- Modify `src/vn_admin_units/ghichu.py` — add the district-template parser `parse_district_ghichu()` (sibling to the province `parse_ghichu`; shares only `_norm`).
- Modify `src/vn_admin_units/names.py` — add `fold_district_name()` (strips all four district prefixes: huyện/quận/thị xã/thành phố). Leave `fold_name` (province) untouched.
- Modify `src/vn_admin_units/crosscheck_decrees.py` — add `decree_index()` + `decree_for(unit_name, effective_date, aliases)` → `(code, url)` (source/alias-aware; the crosswalk decree column is unreliable — journal `2026-07-13.02`), `decrees_naming()` (name-based recovery of a dissolve's true date + reference, D6.5), `load_decree_urls()` + `cache_decrees()` (curated/cached decree URLs). Extend `fetch_decrees` to carry a `url` column.
- Modify `src/vn_admin_units/reconcile.py` — add `sparql_vn_districts()` (bulk pull incl. `altLabel` aliases), `match_districts(…, search_fn, verify_fn)` (folded name + alias index + parent-province weak-disambiguator + verified `wbsearchentities` fallback before `new`), `load_district_mapping()` (ALL QID rows → offline emit), `load_acknowledged_gaps()` (`match_status='gap'` → completeness gate), `write_district_mapping()`, `audit_district_qids()`. Do **not** touch 1a/1b functions.
- Modify `src/vn_admin_units/constraints.py` — add the `P131`+`P580`/`P582` qualifier checks + the district `P31` target items to the `describe_items` confirmation.
- Modify `src/vn_admin_units/emit.py` — add `emit_district_quickstatements()` (relation-aware; `P576` only on ended entities, `P807` for carve-outs, per-span dated `P131`, `P571`, succession, universal 2025 abolition). Built on `core`.
- Modify `src/vn_admin_units/cli.py` — add offline `build_districts_all()` + `event_statements_missing_reference()` (emit ref gate — hard-fails on any event statement whose reference is missing/`nan`/non-URL/the NSO root), and the networked `reconcile_districts_live()` (manual — kept out of the suite).
- Produce: `data/districts.json`, `data/district-lineage.json`, `data/district-residue.json` (logged unresolvable residue), `data/district-gaps.json` (districts with no QID — completeness-gate report), `data/raw/nghidinh.json` (cached decrees), `data/decree-urls.json` (curated decree-URL overrides), `data/district-merge-targets.json` (curated `{dissolved_local_id: successor_local_id}` — merge-target-gate escape), `mappings/districts-qid.csv`, `statements/na-districts.qs`.
- Tests: `tests/test_core.py`, `tests/test_district_ghichu.py`, `tests/test_names.py` (add), `tests/test_district_model.py`, `tests/test_district_events.py`, `tests/test_district_groundtruth.py`, `tests/test_district_reconcile.py`, `tests/test_district_emit.py`, `tests/test_crosscheck_decrees.py` (add), `tests/test_constraints.py` (add), `tests/test_pipeline.py` (add). Update refactor fallout in `tests/{test_emit,test_reconcile,test_model,test_history_emit,test_history_model}.py`.

**Core model shape (defined once in `core.py`, used by all tiers).**
`core.Entity`: `local_id: str`, `gso_codes: list` (chronological; `[-1]` = terminal/reconcile code), `name_vi: str`, `loai_hinh: str`, `valid_from: Optional[str]`, `valid_to: Optional[str]`, `wikidata_qid: Optional[str]`, `qid_status: Optional[str] = None`, `era: Optional[str] = None` (1a's pre/post label), `type_spans: list = []` (`{loai_hinh, from, to, …}`), `aliases: list = []`, `parent_spans: list = []` (`{code, qid, from, to}` — the dated `P131` parent-province spans; districts/wards). Accessors: `gso_code` and `terminal_code` both → `gso_codes[-1]`.
`core.LineageEdge`: `predecessor: str`, `successor: str`, `relation: str`, `decree: str = ""`, `effective_date: str = ""`, `share: str = "whole"`, `primary: bool = False`, `reference_url: str = ""`.

**Relation vocabulary (design §LineageEdge — the predecessor-ends distinction drives `P576`).**
Ends the predecessor (⇒ `P576`): `consolidated`, `merged_into`, `split`, `absorbed_into`, `replaces` (1a). Predecessor persists (no `P576`): `carved_from`, `renamed_to`, `retyped`. `renamed_to`/`retyped` are same-entity relabels recorded as aliases/`P31` spans, not emitted edges.

---

## Task R0: Branch + baseline green suite

**Files:** none (verification only).

- [ ] **Step 1: Branch off main**

Consult the branch-naming convention, then:
Run: `git -C /Users/viett/personal/bamboo-filing-cabinet/vietnam-admin-units checkout -b docs/phase2-districts`
Expected: switched to a new branch; tree clean (git status shows nothing).

- [ ] **Step 2: Confirm the 23 district windows + the full suite are green**

Run: `ls data/raw/crosswalk/district_*.xls | wc -l && uv run pytest -q 2>&1 | tail -3`
Expected: `23` windows; `62 passed`. This is the regression baseline the refactor must preserve.

- [ ] **Step 3: No commit** (verification only).

---

## Task R1: Extract emit primitives + relation vocabulary into `core.py`

**Files:**
- Create: `src/vn_admin_units/core.py`
- Modify: `src/vn_admin_units/emit.py`
- Test: `tests/test_core.py`

Pure move — no dataclass change yet, so 1a/1b emit output is byte-identical. Safest first step.

- [ ] **Step 1: Write the failing test** (`tests/test_core.py`)

```python
from vn_admin_units.core import (wd_date, ref_s854, p31_target, predecessor_ends,
                                 P31_TARGETS, REFERENCE_URL)

def test_wd_date_is_day_precision_and_defensive():
    assert wd_date("2025-07-01") == "+2025-07-01T00:00:00Z/11"
    assert wd_date("2013-12-28 00:00:00") == "+2013-12-28T00:00:00Z/11"   # datetime tail stripped

def test_ref_is_s854():
    assert ref_s854("https://x") == 'S854\t"https://x"'

def test_p31_target_maps_by_loai_hinh():
    assert p31_target("Tỉnh") == P31_TARGETS["Tỉnh"]
    assert p31_target("Thành phố Trung ương") == P31_TARGETS["Thành phố Trung ương"]

def test_predecessor_ends_only_for_ending_relations():
    assert predecessor_ends("merged_into") and predecessor_ends("split")
    assert predecessor_ends("absorbed_into") and predecessor_ends("replaces")
    assert not predecessor_ends("carved_from")      # parent persists
    assert not predecessor_ends("renamed_to") and not predecessor_ends("retyped")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core.py -q`
Expected: FAIL — `vn_admin_units.core` does not exist.

- [ ] **Step 3: Create `core.py` (primitives + vocabulary only — dataclasses come in R2)**

```python
"""Tier-neutral core shared by the province (1a/1b), district (Phase 2), and
future ward (Phase 3) pipelines. Two concerns live here: the Wikidata emit
primitives (date literal, reference, P31 type-target resolution) and the lineage
relation vocabulary (which relations END the predecessor -> P576). The Entity /
LineageEdge dataclasses (added in R2) are supersets every tier constructs."""
from __future__ import annotations

REFERENCE_URL = "https://danhmuchanhchinh.nso.gov.vn/"

# Wikidata item QIDs for admin-unit types (P31 targets). Province types were confirmed via
# constraints.describe_items 2026-07-14. The four district types are registered here as
# PLACEHOLDERS so the district emitter (D9) resolves a target in its shape tests; their QIDs are
# CONFIRMED/corrected via constraints.describe_items in Task D10 before any real district emit —
# a wrong QID passes shape tests but emits a wrong P31 (this bit Phase 1b).
P31_TARGETS = {
    "Tỉnh": "Q2824648",                       # province of Vietnam
    "Thành phố Trung ương": "Q1381899",       # centrally-controlled city of Vietnam
    # District tier (longest-key-first resolution: "Thành phố Trung ương" above wins over the
    # provincial-city "Thành phố" here). PLACEHOLDERS — CONFIRM in D10.
    "Huyện": "Q5057368",                      # rural district of Vietnam — CONFIRM (D10)
    "Quận": "Q5124547",                       # urban district of Vietnam — CONFIRM (D10)
    "Thị xã": "Q7973736",                     # district-level town (thị xã) — CONFIRM (D10)
    "Thành phố": "Q20124469",                 # provincial city (thành phố thuộc tỉnh) — CONFIRM (D10)
}


def wd_date(d: str) -> str:
    """Wikidata date literal (day precision). Defensively takes the date part in
    case a source passes a datetime string like '2025-07-01 00:00:00'."""
    d = str(d).strip().split(" ")[0].split("T")[0]
    return f"+{d}T00:00:00Z/11"


def ref_s854(url: str) -> str:
    return f'S854\t"{url}"'


def p31_target(loai_hinh: str) -> str:
    """QID for a unit type's P31 target. Longest-key-first so 'Thành phố Trung
    ương' wins over a bare 'Thành phố' prefix match."""
    for key in sorted(P31_TARGETS, key=len, reverse=True):
        if loai_hinh.startswith(key):
            return P31_TARGETS[key]
    return ""


# Relations where the predecessor ENDS (gets P576). Everything else persists.
PREDECESSOR_ENDS = {"consolidated", "merged_into", "split", "absorbed_into", "replaces"}


def predecessor_ends(relation: str) -> bool:
    return relation in PREDECESSOR_ENDS
```

- [ ] **Step 4: Repoint `emit.py` at the primitives** (keep the module-level names as re-export aliases so nothing else breaks)

Replace the top of `emit.py` (lines 1–8 and the `_ref` helper at 52–53) so `_date`/`_ref`/`REFERENCE_URL`/`NSO_SOURCE_URL` are the `core` functions. The emitter bodies keep calling `_date(...)`/`_ref(...)` unchanged:

```python
from vn_admin_units.core import wd_date as _date, ref_s854 as _ref, REFERENCE_URL

NSO_SOURCE_URL = REFERENCE_URL
# WD item QIDs for the two admin-unit types (confirmed via constraints.describe_items
# 2026-07-14: the placeholder QIDs were wrong — Myanmar settlement / Benin arrondissement).
P31_PROVINCE = "Q2824648"        # "province of Vietnam"
P31_CITY_TW = "Q1381899"         # "centrally-controlled city of Vietnam"
```

Delete the old `REFERENCE_URL = …` line, the old `def _date(...)` block, the old `NSO_SOURCE_URL = …` line, and the old `def _ref(...)` block. Leave `emit_quickstatements` and `emit_history_quickstatements` bodies exactly as they are (they call `_date`/`_ref`, now the aliases).

- [ ] **Step 5: Run the full suite (regression gate)**

Run: `uv run pytest -q 2>&1 | tail -3`
Expected: `66 passed` (62 prior + 4 new core tests). 1a/1b emit output is unchanged (same primitives).

- [ ] **Step 6: Commit**

```bash
git add src/vn_admin_units/core.py src/vn_admin_units/emit.py tests/test_core.py
git commit -m "refactor(phase2): extract emit primitives + relation vocabulary into core"
```

---

## Task R2: Add the superset `Entity` / `LineageEdge` to `core.py`

**Files:**
- Modify: `src/vn_admin_units/core.py`
- Test: `tests/test_core.py` (add)

The 1a and 1b positional signatures are incompatible (position 2 is `gso_code` scalar vs `gso_codes` list), so one shared dataclass must win. Chosen: `Entity` keeps **1b field order** (so all 1b constructions stay valid), `LineageEdge` keeps **1a field order** (so all 1a edge constructions stay valid); the diverging side migrates to keyword args in R3/R4.

- [ ] **Step 1: Write the failing test** (append to `tests/test_core.py`)

Positional order below is 1b's: `(local_id, gso_codes, name_vi, loai_hinh, type_spans, aliases, valid_from, valid_to, wikidata_qid, qid_status)` — exactly `province_history.Entity`'s current order, so R3 needs no 1b entity-constructor edits.

```python
from vn_admin_units.core import Entity, LineageEdge

def test_entity_terminal_and_gso_code_accessors():
    e = Entity("d-019-base", ["019"], "Huyện Từ Liêm", "Huyện", [], [], None, "2013-12-27")
    assert e.terminal_code == "019" and e.gso_code == "019"
    assert e.era is None and e.type_spans == [] and e.parent_spans == []

def test_entity_1a_style_via_kwargs_and_1b_style_positional():
    prov = Entity(local_id="p-15-post2025", gso_codes=["15"], name_vi="Tỉnh Lào Cai",
                  loai_hinh="Tỉnh", valid_from="2025-07-01", valid_to=None,
                  wikidata_qid="Q36446", qid_status="existing", era="post2025")
    assert prov.gso_code == "15" and prov.era == "post2025"
    hist = Entity("ph-28-base", ["28"], "Tỉnh Hà Tây", "Tỉnh",
                  [{"loai_hinh": "Tỉnh", "from": None, "to": "2008-07-31"}], [],
                  None, "2008-07-31", None, None)   # 1b positional order preserved
    assert hist.terminal_code == "28" and hist.type_spans[0]["to"] == "2008-07-31"

def test_lineage_edge_1a_positional_preserved():
    ed = LineageEdge("p-10-pre2025", "p-15-post2025", "replaces", "whole", True,
                     "Số: 1685", "2025-07-01")
    assert ed.share == "whole" and ed.primary is True and ed.effective_date == "2025-07-01"
    d = LineageEdge("a", "b", "carved_from", decree="Số: 22", effective_date="2004-01-01",
                    reference_url="https://x")
    assert d.reference_url == "https://x" and d.share == "whole"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core.py -q`
Expected: FAIL — `Entity`/`LineageEdge` not importable from `core`.

- [ ] **Step 3: Add the dataclasses to `core.py`** (append)

```python
from dataclasses import dataclass, asdict, field
from typing import Optional


@dataclass
class Entity:
    """Tier-neutral admin-unit entity. Field ORDER matches 1b's province_history
    (gso_codes list, type_spans, aliases) so 1b constructions stay positional; the
    trailing era/parent_spans are defaulted so 1a/2 add them by keyword.

    - gso_codes: chronological codes; [-1] = terminal/reconcile code.
    - type_spans: [{loai_hinh, from, to, decree?, reference_url?}] — >1 span => retype.
    - aliases: former names + former codes (-> WD aliases).
    - era: 1a's "pre2025"/"post2025" label (None for history/districts).
    - parent_spans: [{code, qid, from, to}] dated P131 parent-province spans (districts/wards).
    """
    local_id: str
    gso_codes: list
    name_vi: str
    loai_hinh: str
    type_spans: list = field(default_factory=list)
    aliases: list = field(default_factory=list)
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    wikidata_qid: Optional[str] = None
    qid_status: Optional[str] = None
    era: Optional[str] = None
    parent_spans: list = field(default_factory=list)

    @property
    def terminal_code(self) -> str:
        return self.gso_codes[-1] if self.gso_codes else ""

    @property
    def gso_code(self) -> str:          # 1a back-compat accessor
        return self.gso_codes[-1] if self.gso_codes else ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LineageEdge:
    """Tier-neutral lineage edge. Field ORDER matches 1a's model.LineageEdge
    (share, primary before decree) so 1a edges stay positional; 1b/2 use keywords
    for decree/effective_date/reference_url."""
    predecessor: str
    successor: str
    relation: str
    share: str = "whole"
    primary: bool = False
    decree: str = ""
    effective_date: str = ""
    reference_url: str = ""

    def to_dict(self) -> dict:
        return asdict(self)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_core.py -q`
Expected: PASS (7 tests). The full suite is still `66 passed` (nothing imports the new dataclasses yet).

- [ ] **Step 5: Commit**

```bash
git add src/vn_admin_units/core.py tests/test_core.py
git commit -m "refactor(phase2): superset Entity/LineageEdge dataclasses in core"
```

---

## Task R3: Migrate `province_history.py` (1b) onto `core`

**Files:**
- Modify: `src/vn_admin_units/province_history.py`
- Test: `tests/test_history_emit.py`, `tests/test_history_model.py` (edge constructions → kwargs)

`province_history.Entity` field order already equals `core.Entity`'s first ten fields, so entity constructions are untouched. Only `LineageEdge` constructions (whose 1b positional order `(pred, succ, relation, decree, effective_date, reference_url)` clashes with `core`'s `(pred, succ, relation, share, primary, decree, …)`) must switch to keywords.

- [ ] **Step 1: Replace the private dataclasses with a `core` import**

In `province_history.py`, delete the `@dataclass class Entity` and `@dataclass class LineageEdge` blocks (and the now-unused `from dataclasses import dataclass, asdict, field`). Add at the top:

```python
from vn_admin_units.core import Entity, LineageEdge
```

Keep `hist_local_id`, `load_carve_outs`, `diff_roster`, `build_province_history`, and the `RETYPES`/`HA_TAY_2008` constants exactly as they are.

- [ ] **Step 2: Convert the two `LineageEdge(...)` calls in `build_province_history` to keywords**

Find (carve-out, ~line 158) and rewrite:

```python
            edges.append(LineageEdge(parent.local_id, child.local_id, "carved_from",
                                     decree=co["decree"], effective_date=co["effective_date"],
                                     reference_url=co["reference_url"]))
```

Find (absorption, ~line 190) and rewrite:

```python
            edges.append(LineageEdge(ht_e.local_id, ha_noi.local_id, "absorbed_into",
                                     decree=HA_TAY_2008["decree"], effective_date="2008-08-01",
                                     reference_url=HA_TAY_2008["reference_url"]))
```

- [ ] **Step 3: Convert the `LineageEdge(...)` calls in the 1b tests to keywords**

`tests/test_history_emit.py` (~line 13, 27) and `tests/test_history_model.py` (~line 22): change each `LineageEdge(pred, succ, "carved_from", "Số…", "date", "url")` to `LineageEdge(pred, succ, "carved_from", decree="Số…", effective_date="date", reference_url="url")` (same for `absorbed_into`). The assertions are unchanged.

- [ ] **Step 4: Run the full suite (regression gate)**

Run: `uv run pytest -q 2>&1 | tail -3`
Expected: `66 passed`. 1b entity/edge behavior identical.

> Note: `data/province-history-lineage.json` will now also carry `share`/`primary` keys (defaults) — a benign shape widening of a derived artifact, not a claim change. Regenerating it is optional here; do it in Task D11's full rebuild if desired.

- [ ] **Step 5: Commit**

```bash
git add src/vn_admin_units/province_history.py tests/test_history_emit.py tests/test_history_model.py
git commit -m "refactor(phase2): province_history builds on core Entity/LineageEdge"
```

---

## Task R4: Migrate `model.py` (1a) onto `core`

**Files:**
- Modify: `src/vn_admin_units/model.py`
- Test: `tests/test_emit.py`, `tests/test_reconcile.py`, `tests/test_model.py` (entity constructions → new shape)

1a's `LineageEdge` order equals `core`'s, so edges are untouched. Its `Entity(local_id, gso_code, era, …)` order clashes (`gso_code` scalar + `era` at positions 2–3), so entity constructions migrate to `gso_codes=[…]` + `era=…` keywords.

- [ ] **Step 1: Replace 1a's dataclasses + `build_entities` construction with `core`**

In `model.py`: delete the `@dataclass class Entity` and `@dataclass class LineageEdge` blocks and the `from dataclasses import dataclass, asdict` import. Add:

```python
from vn_admin_units.core import Entity, LineageEdge
```

Rewrite the two `Entity(...)` constructions in `build_entities`:

```python
    for r in pre_rows:
        ents.append(Entity(
            local_id=local_id(r["ma"], "pre2025"), gso_codes=[r["ma"]], era="pre2025",
            name_vi=r["ten"], loai_hinh=r["loai_hinh"],
            valid_from=None, valid_to="2025-06-30", wikidata_qid=None))
    for r in post_rows:
        ents.append(Entity(
            local_id=local_id(r["ma"], "post2025"), gso_codes=[r["ma"]], era="post2025",
            name_vi=r["ten"], loai_hinh=r["loai_hinh"],
            valid_from="2025-07-01", valid_to=None, wikidata_qid=None))
```

`build_lineage` reads `e.gso_code`/`e.era` — both work via the accessor/field. The `LineageEdge(pre.local_id, succ.local_id, "replaces", "whole", True, decree, succ.valid_from)` calls are positional in `core`'s order → unchanged.

- [ ] **Step 2: Update 1a Entity constructions in tests to the new shape**

`tests/test_emit.py` — each `Entity("p-15-post2025", "15", "post2025", "Tỉnh Lào Cai", "Tỉnh", "2025-07-01", None, "Q36446", "existing")` becomes keyword form so the scalar code + era land correctly:

```python
    Entity(local_id="p-15-post2025", gso_codes=["15"], era="post2025",
           name_vi="Tỉnh Lào Cai", loai_hinh="Tỉnh", valid_from="2025-07-01",
           valid_to=None, wikidata_qid="Q36446", qid_status="existing"),
```

Apply the same rewrite to all five `Entity(...)` calls in `test_emit.py` (provinces + the two ward-shaped ones — keep their codes/QIDs/loai_hinh/era values, just move to keyword form). `tests/test_reconcile.py` (~line 7): `Entity(local_id="p-15-pre2025", gso_codes=["15"], era="pre2025", name_vi="Tỉnh Yên Bái", loai_hinh="Tỉnh", valid_from=None, valid_to="2025-06-30", wikidata_qid=None)`. `tests/test_model.py` (~line 11) is already keyword form — change `gso_code="15"` to `gso_codes=["15"]`. Assertions (`.gso_code`, `.era`) are unchanged and pass via the accessor/field.

- [ ] **Step 3: Run the full suite (regression gate)**

Run: `uv run pytest -q 2>&1 | tail -3`
Expected: `66 passed`.

- [ ] **Step 4: Confirm the 1a mapping is byte-stable (the artifact that matters)**

Run: `uv run python -c "from vn_admin_units.cli import build_all; build_all()" && git diff --stat mappings/`
Expected: `build_all` prints `built … entities … edges`; **no diff in `mappings/`** (the QID CSV is unchanged). `data/entities.json`/`data/lineage.json` shape widens (`gso_codes`/`type_spans`/`parent_spans` keys) — expected and benign; stage them.

- [ ] **Step 5: Commit**

```bash
git add src/vn_admin_units/model.py tests/test_emit.py tests/test_reconcile.py tests/test_model.py data/entities.json data/lineage.json
git commit -m "refactor(phase2): province 1a builds on core Entity/LineageEdge (behavior identical)"
```

> **End of Movement A.** 1a + 1b now share `core`; the suite is `66 passed` with 1a's mapping byte-stable. Movement B builds districts on `core`.

---

## Task D1: District `Ghi Chú` sibling parser

**Files:**
- Modify: `src/vn_admin_units/ghichu.py`
- Test: `tests/test_district_ghichu.py`

`Ghi Chú` is **supplementary** (design §Lineage resolution) — often blank on changed rows (the Từ Liêm split rows carry no prose). This parser confirms/overrides the structured-column inference when prose is present. It shares only `_norm` with the province `parse_ghichu`; the templates are a sibling. Test strings are the real cached prose (verified 2026-07-14 against the windows).

- [ ] **Step 1: Write the failing test** (`tests/test_district_ghichu.py`)

```python
from vn_admin_units.ghichu import parse_district_ghichu

def test_merge_names_source_and_target():
    p = parse_district_ghichu(
        "Nhập toàn bộ 357,38 km2 diện tích tự nhiên, 24.441 người của huyện Thông Nông  vào huyện Hà Quảng")
    assert p["event"] == "merge" and p["source"] == "Thông Nông" and p["target"] == "Hà Quảng"

def test_merge_target_only_when_no_source_clause():
    p = parse_district_ghichu("nhập vào huyện Quảng Uyên, thành lập huyện Quảng Hòa")
    assert p["event"] == "merge" and p["target"] == "Quảng Uyên"

def test_carve_names_source_stripping_cu():
    p = parse_district_ghichu("Chia tách từ huyện Quảng Trạch cũ")
    assert p["event"] == "carve" and p["source"] == "Quảng Trạch"

def test_establish_and_retype_and_rename():
    assert parse_district_ghichu(
        "thành lập thị xã Lai Châu trên cơ sở tự nhiên và dân số của thị trấn Phong Thổ")["event"] == "establish"
    assert parse_district_ghichu("Thay đổi loại hình")["event"] == "retype"
    assert parse_district_ghichu("Đổi tên huyện")["event"] == "rename"

def test_blank_is_none():
    assert parse_district_ghichu("")["event"] == "none"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_district_ghichu.py -q`
Expected: FAIL — `parse_district_ghichu` not defined.

- [ ] **Step 3: Add the parser to `ghichu.py`** (reuse the existing `_norm`)

```python
# ── District templates (Phase 2). Sibling to parse_ghichu; shares only _norm. ──
_DTYPE = r"(?:huyện|quận|thị xã|thành phố)"
_D_MERGE_TARGET = re.compile(rf"\bvào\s+{_DTYPE}\s+(?P<target>[^,.;]+)", re.IGNORECASE)
_D_MERGE_SOURCE = re.compile(rf"\bcủa\s+{_DTYPE}\s+(?P<source>.+?)\s+vào\b", re.IGNORECASE)
_D_CARVE = re.compile(rf"chia tách từ\s+{_DTYPE}\s+(?P<source>.+?)\s*\(?\s*cũ", re.IGNORECASE)
_D_RENAME = re.compile(
    rf"đổi tên\s+{_DTYPE}\s+(?P<old>.+?)\s+thành\s+{_DTYPE}\s+(?P<new>[^,.;]+)", re.IGNORECASE)


def parse_district_ghichu(text: str) -> dict:
    """Classify a district Ghi Chú and extract the merge/carve/rename constituents.

    Returns {event, source, target}. event in
    {none, merge, carve, establish, rename, retype, other}. `source`/`target` are
    bare unit names (no tier prefix) when the prose names them, else None. Never
    required — the structured-column classifier (district_model) is primary; this
    confirms/overrides when prose is present (design §Lineage resolution)."""
    t = _norm(text)
    if not t:
        return {"event": "none", "source": None, "target": None}
    low = t.lower()
    if low.startswith("đổi tên"):
        m = _D_RENAME.search(t)
        return {"event": "rename",
                "source": m.group("old").strip() if m else None,
                "target": m.group("new").strip() if m else None}
    if "loại hình" in low or low.startswith("chuyển"):
        return {"event": "retype", "source": None, "target": None}
    if low.startswith("chia tách từ"):
        m = _D_CARVE.search(t)
        return {"event": "carve", "source": m.group("source").strip() if m else None, "target": None}
    if low.startswith("thành lập"):
        return {"event": "establish", "source": None, "target": None}
    if any(k in low for k in ("nhập", "sáp nhập", "sát nhập")):
        ms, mt = _D_MERGE_SOURCE.search(t), _D_MERGE_TARGET.search(t)
        return {"event": "merge",
                "source": ms.group("source").strip() if ms else None,
                "target": mt.group("target").strip() if mt else None}
    return {"event": "other", "source": None, "target": None}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_district_ghichu.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/vn_admin_units/ghichu.py tests/test_district_ghichu.py
git commit -m "feat(phase2): district Ghi Chú sibling parser (merge/carve/rename/retype)"
```

---

## Task D2: District name folding

**Files:**
- Modify: `src/vn_admin_units/names.py`
- Test: `tests/test_names.py` (add)

`fold_name` strips only the province prefixes (`tỉnh|thành phố`). Districts need all four tier prefixes stripped (`huyện|quận|thị xã|thành phố`) so `Huyện Hà Quảng` folds to `ha quang` and matches `Hà Quảng` in prose/WD. Keep `fold_name` untouched (provinces rely on its narrower prefix set).

- [ ] **Step 1: Write the failing test** (append to `tests/test_names.py`)

```python
from vn_admin_units.names import fold_district_name

def test_strips_all_four_district_prefixes():
    assert fold_district_name("Huyện Hà Quảng") == "ha quang"
    assert fold_district_name("Quận Nam Từ Liêm") == "nam tu liem"
    assert fold_district_name("Thị xã Ba Đồn") == "ba don"
    assert fold_district_name("Thành phố Lai Châu") == "lai chau"

def test_folds_tone_and_case_and_keeps_distinct():
    assert fold_district_name("Huyện Hoà Bình") == fold_district_name("huyện  hòa bình")
    assert fold_district_name("Huyện Đạ Tẻh") != fold_district_name("Huyện Đạ Huoai")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_names.py -q`
Expected: FAIL — `fold_district_name` not defined.

- [ ] **Step 3: Add `fold_district_name` to `names.py`**

```python
def fold_district_name(s: str) -> str:
    """Fold a district name for comparison: strip any of the four tier prefixes
    (huyện/quận/thị xã/thành phố), lowercase, collapse whitespace, drop combining
    tone marks (NFD) so 'Hoà'=='Hòa'; đ→d. Wider prefix set than fold_name (which
    is province-only)."""
    s = re.sub(r"^(huyện|quận|thị xã|thành phố)\s+", "", s.strip(), flags=re.IGNORECASE).lower()
    s = re.sub(r"\s+", " ", s)
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").strip()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_names.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vn_admin_units/names.py tests/test_names.py
git commit -m "feat(phase2): district name folding (all four tier prefixes)"
```

---

## Task D3: `district_model` types (`dist_local_id` + collision guard)

**Files:**
- Create: `src/vn_admin_units/district_model.py`
- Test: `tests/test_district_model.py`

The 3-digit code is **not** a unique key: split/merge mint new entities that inherit a predecessor's code across an event boundary (Từ Liêm `019` → new Nam Từ Liêm `019`), and codes get reassigned (Đạ Tẻh→Đạ Huoai `682`). `local_id = d-{code}-{gen}` where `gen` = `valid_from` (or `base` for the 2004 baseline root). Collisions (same `local_id`) are detected + logged, never silent.

- [ ] **Step 1: Write the failing test** (`tests/test_district_model.py`)

```python
from vn_admin_units.district_model import dist_local_id, District, detect_collisions
from vn_admin_units.core import Entity

def test_local_id_gen_disambiguates_inherited_code():
    assert dist_local_id("019", None) == "d-019-base"                 # baseline root
    assert dist_local_id("019", "2013-12-28") == "d-019-2013-12-28"   # new Nam Từ Liêm
    assert dist_local_id("019", None) != dist_local_id("019", "2013-12-28")

def test_district_is_core_entity_with_parent_spans():
    d = District(code="271", valid_from=None, valid_to="2025-06-30",
                 name_vi="Huyện Ba Vì", loai_hinh="Huyện",
                 parent_spans=[{"code": "28", "qid": None, "from": None, "to": "2008-07-31"},
                               {"code": "01", "qid": None, "from": "2008-08-01", "to": "2025-06-30"}])
    assert isinstance(d, Entity)
    assert d.local_id == "d-271-base" and d.terminal_code == "271"
    assert len(d.parent_spans) == 2 and d.parent_spans[-1]["code"] == "01"

def test_detect_collisions_flags_dup_local_id():
    a = District(code="019", valid_from=None, valid_to="2013-12-27", name_vi="Huyện Từ Liêm", loai_hinh="Huyện")
    b = District(code="019", valid_from=None, valid_to=None, name_vi="X", loai_hinh="Huyện")  # same id
    c = District(code="019", valid_from="2013-12-28", valid_to="2025-06-30", name_vi="Quận Nam Từ Liêm", loai_hinh="Quận")
    assert detect_collisions([a, b, c]) == ["d-019-base"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_district_model.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the types in `district_model.py`**

```python
"""District tier (huyện / quận / thị xã / thành phố thuộc tỉnh) assembly, 2004→2025.

Purely historical: the tier existed 2002→2025 and was abolished 2025-07-01 by the
two-tier reform. Builds one continuous Entity per district (rename/retype/re-parent
are same-entity relabels) + the lineage edges the yearly Đối Chiếu windows expose,
then applies the universal 2025 abolition. See docs/DESIGN-phase2.md."""
from __future__ import annotations

import logging

from vn_admin_units.core import Entity, LineageEdge

log = logging.getLogger("vn_admin_units.district_model")

ABOLITION_DATE = "2025-07-01"       # two-tier reform; districts' event date
ABOLITION_VALID_TO = "2025-06-30"   # last in-force day (inclusive)
DISTRICT_TYPES = {"Huyện", "Quận", "Thị xã", "Thành phố"}


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


def detect_collisions(entities: list) -> list:
    """local_ids appearing more than once (a code+gen clash the assembly must
    disambiguate). Logged, returned sorted; never silent."""
    from collections import Counter
    dups = sorted(k for k, n in Counter(e.local_id for e in entities).items() if n > 1)
    for d in dups:
        log.warning("local_id collision: %s", d)
    return dups
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_district_model.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/vn_admin_units/district_model.py tests/test_district_model.py
git commit -m "feat(phase2): district_model types (dist_local_id, District, collision guard)"
```

---

## Task D4: Authoritative decree lookup from the Nghị định list

**Files:**
- Modify: `src/vn_admin_units/crosscheck_decrees.py`
- Test: `tests/test_crosscheck_decrees.py` (add)

The crosswalk's own decree column is **unreliable** (blank, or a later "last-touching" decree — verified: Nông Sơn tagged with the 2024 decree that dissolved it; journal `2026-07-13.02`). Decree numbers come from the Nghị định list, matched by **unit + effective date**.

Two properties this lookup must have (surfaced in the 2026-07-15 plan review):
1. **Match on source/alias names, not just the successor label.** A split product is named in the decree prose only as its *source* (`132/NQ-CP` says "…huyện **Từ Liêm**…", never "Nam Từ Liêm"), so `decree_for` takes the entity's former names/aliases and matches on any of them. Matching the successor label alone silently misses the decree whenever the effective date carries more than one decree (the real multi-op case) — falling back to date-only only rescues the accidental single-candidate date.
2. **Return the establishing-resolution reference, not just the code** (design §3 / §Emit — every statement referenced to *its own* source, not the generic NSO root, which was the Phase-1a shortcut). `decree_for` returns `(code, url)`; the `url` is the decree's source link (from the Nghị định list when it exposes a per-row link, else a curated override — `load_decree_urls`). Edges carry it into `reference_url` (D7); the emit gate (D11) fails any lineage statement left on the bare root.

- [ ] **Step 1: Write the failing test** (append to `tests/test_crosscheck_decrees.py`)

```python
from vn_admin_units.crosscheck_decrees import decree_index, decree_for

_RECORDS = [
    {"code": "897/NQ-UBTVQH14", "hieu_luc": "01/03/2020", "url": "https://vb/897",
     "noi_dung": "sắp xếp các đơn vị hành chính cấp huyện; nhập huyện Thông Nông vào huyện Hà Quảng"},
    # TWO decrees share 2013-12-28 so the date-only fallback is AMBIGUOUS — the split
    # product must resolve via its source name 'Từ Liêm', which only 132/NQ-CP names.
    {"code": "132/NQ-CP", "hieu_luc": "28/12/2013", "url": "https://vb/132",
     "noi_dung": "điều chỉnh địa giới hành chính huyện Từ Liêm để thành lập 02 quận"},
    {"code": "999/NQ-CP", "hieu_luc": "28/12/2013", "url": "https://vb/999",
     "noi_dung": "thành lập thị xã khác, không liên quan"},
    {"code": "133/NQ-CP", "hieu_luc": "30/12/2013", "url": "https://vb/133",
     "noi_dung": "thành lập thị xã Ngã Năm thuộc tỉnh Sóc Trăng"},
]

def test_decree_for_matches_source_name_via_alias_on_ambiguous_date():
    idx = decree_index(_RECORDS)
    # 'Quận Nam Từ Liêm' is NOT in any decree prose; its source alias 'Huyện Từ Liêm' is.
    # Two decrees bear 2013-12-28, so date-only can't disambiguate — the alias must.
    assert decree_for(idx, "Quận Nam Từ Liêm", "2013-12-28",
                      aliases=["Huyện Từ Liêm"]) == ("132/NQ-CP", "https://vb/132")

def test_decree_for_matches_by_own_name_and_returns_url():
    idx = decree_index(_RECORDS)
    assert decree_for(idx, "Huyện Hà Quảng", "2020-03-01") == ("897/NQ-UBTVQH14", "https://vb/897")

def test_decree_for_single_candidate_falls_back_to_date_only():
    idx = decree_index(_RECORDS)
    assert decree_for(idx, "Thị xã Ngã Năm", "2013-12-30") == ("133/NQ-CP", "https://vb/133")

def test_decree_for_returns_empty_pair_when_ambiguous_and_no_name_hit():
    idx = decree_index(_RECORDS)
    # 2013-12-28 has two decrees and neither names this unit (and no alias given) -> ("","")
    assert decree_for(idx, "Huyện Không Có", "2013-12-28") == ("", "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_crosscheck_decrees.py -q`
Expected: FAIL — `decree_index`/`decree_for` not defined.

- [ ] **Step 3: Add the lookup to `crosscheck_decrees.py`**

```python
import json
import os

from vn_admin_units.names import fold_district_name


def _iso_from_dmy(s: str) -> str:
    """'28/12/2013' -> '2013-12-28'; pass through anything already ISO or unparseable."""
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})", s or "")
    return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}" if m else (s or "")


def _clean_url(v) -> str:
    """Normalize a URL cell to "" for the empties pandas leaves behind — a missing cell that
    `fetch_decrees().astype(str)` stringified to the literal 'nan'/'none', or blanks. Without
    this a 'nan' url is truthy: it blocks the curated-override merge AND ships as S854 "nan"."""
    s = str(v or "").strip()
    return "" if s.lower() in ("", "nan", "none", "<na>") else s


def decree_index(records) -> dict:
    """{iso_effective_date: [{code, url, noi_dung}]} from Nghị định records
    (each {code, hieu_luc, noi_dung, url?}). Accepts the fetch_decrees DataFrame rows
    or plain dicts. `url` is the decree's per-row source link when the list exposes one
    (see fetch_decrees extension below), else "" (via _clean_url) — a curated override fills the rest."""
    idx: dict[str, list] = {}
    for r in records:
        iso = _iso_from_dmy(str(r["hieu_luc"]))
        idx.setdefault(iso, []).append(
            {"code": r["code"], "url": _clean_url(r.get("url")), "noi_dung": str(r["noi_dung"])})
    return idx


def index_from_df(dec) -> dict:
    """decree_index over a fetch_decrees() DataFrame."""
    return decree_index(dec.to_dict("records"))


def load_decree_urls(path: str = "data/decree-urls.json") -> dict:
    """Curated {decree_code: source_url} overrides for decrees whose per-row link the
    Nghị định list doesn't expose (same discipline as 1b's cached Hà Tây/Huế decrees).
    Merged over any url fetch_decrees scraped; the emit gate (D11) lists any structural
    decree still lacking a url so the residue is never silent."""
    return json.loads(open(path, encoding="utf-8").read()) if os.path.exists(path) else {}


def decree_for(idx: dict, unit_name: str, effective_date: str, aliases=()) -> tuple:
    """Authoritative (decree code, source url) for a (unit, effective-date) change.

    Matches the decree whose noi_dung names the unit BY ANY OF ITS NAMES — the current
    name AND its former names/aliases — because a split product (`Quận Nam Từ Liêm`) is
    named in the decree only as its source (`huyện Từ Liêm`). Matching the successor
    label alone misses it whenever the date carries >1 decree. If no name/alias hits and
    exactly ONE decree bears the date, fall back to it; otherwise ("", "") — ambiguous
    (caller keeps the crosswalk value or routes to residue)."""
    cands = idx.get(effective_date, [])
    if not cands:
        return ("", "")
    folds = [f for f in (fold_district_name(n) for n in (unit_name, *aliases) if n) if f]
    for c in cands:
        prose = fold_district_name(c["noi_dung"])
        if any(fn in prose for fn in folds):
            return (c["code"], c["url"])
    return (cands[0]["code"], cands[0]["url"]) if len(cands) == 1 else ("", "")
```

> **`fetch_decrees` url extension:** `fetch_decrees` currently drops per-row links (`pd.read_html`). Add a `url` column by parsing the Nghị định table anchors with `lxml` (already a dep) when present; where the list has no per-decree link, the curated `data/decree-urls.json` (`load_decree_urls`) supplies it. A decree with neither is emitted with the NSO root **and logged** by the D11 gate — never silently referenced as if authoritative.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_crosscheck_decrees.py -q`
Expected: PASS (existing cross-check tests + 4 new).

- [ ] **Step 5: Commit**

```bash
git add src/vn_admin_units/crosscheck_decrees.py tests/test_crosscheck_decrees.py
git commit -m "feat(phase2): authoritative decree lookup by unit + effective date"
```

---

## Task D5: Event discovery — structured-column classification

**Files:**
- Modify: `src/vn_admin_units/district_model.py`
- Test: `tests/test_district_events.py`

Classify each changed crosswalk row from its **structured columns** (always present; `Ghi Chú` is supplementary). Per design §Lineage resolution step 1: blank base = create; blank succ = dissolve; `base-province ≠ compare-province` = **re-parenting** (a `P131` change, same entity — the signal name-diff alone misses); tier-prefix change = retype; folded-name change = rename. These are **candidate** kinds; split/carve is decided in D6 (a retype+rename whose source vanishes is really a split product).

- [ ] **Step 1: Write the failing test** (`tests/test_district_events.py`)

```python
from vn_admin_units.district_model import unit_tier, classify_change, window_events
from vn_admin_units.crosswalk import read_district_crosswalk

def test_unit_tier_longest_prefix():
    assert unit_tier("Thành phố Lai Châu") == "Thành phố"
    assert unit_tier("Thị xã Ba Đồn") == "Thị xã"
    assert unit_tier("Huyện Từ Liêm") == "Huyện" and unit_tier("Quận 9") == "Quận"

def _row(bt, bm, bn, st, sm, sn):
    return {"base_tinh": bt, "base_ma": bm, "base_ten": bn,
            "succ_tinh": st, "succ_ma": sm, "succ_ten": sn,
            "base_hieu_luc": "", "succ_hieu_luc": "2013-12-28",
            "succ_nghi_dinh": "", "ghi_chu": ""}

def test_classify_from_structured_columns():
    assert classify_change(_row("", "", "", "01", "021", "Quận Bắc Từ Liêm")) == "create"
    assert classify_change(_row("04", "044", "Huyện Thông Nông", "", "", "")) == "dissolve"
    assert classify_change(_row("28", "271", "Huyện Ba Vì", "01", "271", "Huyện Ba Vì")) == "reparent"
    assert classify_change(_row("14", "116", "Thị xã Sơn La", "14", "116", "Thành phố Sơn La")) == "retype"
    assert classify_change(_row("01", "019", "Huyện Từ Liêm", "01", "019", "Quận Nam Từ Liêm")) == "retype_rename"

def test_window_events_isolates_2013_changes_from_real_window():
    rows = read_district_crosswalk("data/raw/crosswalk/district_2013-01-01_2014-01-01.xls")
    ev = window_events(rows)
    assert len(ev) == 17                                    # journal 2026-07-13.02
    tl = [e for e in ev if e["code_from"] == "019" or e["code_to"] == "019"]
    assert tl and tl[0]["kind"] == "retype_rename" and tl[0]["eff_date"] == "2013-12-28"
    assert any(e["kind"] == "create" and e["code_to"] == "021" for e in ev)   # Bắc Từ Liêm
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_district_events.py -q`
Expected: FAIL — `unit_tier`/`classify_change`/`window_events` not defined.

- [ ] **Step 3: Add event discovery to `district_model.py`**

```python
from vn_admin_units.names import fold_district_name

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_district_events.py -q`
Expected: PASS. If `window_events` count ≠ 17, the changed-row definition drifted — inspect against the journal's 2013 table (Từ Liêm split, Lai Châu upgrade, Ba Đồn carve, +14). Do **not** loosen the assertion; fix the classifier.

- [ ] **Step 5: Commit**

```bash
git add src/vn_admin_units/district_model.py tests/test_district_events.py
git commit -m "feat(phase2): district event discovery (structured-column classification)"
```

---

## Task D6: Lineage resolution — bucketing + carve-out/split discriminator

**Files:**
- Modify: `src/vn_admin_units/district_model.py`
- Test: `tests/test_district_events.py` (add)

Two resolvers (design §Lineage resolution steps 2 & 5): (a) group same-`(effective_date, province)` events into candidate buckets — one decree can cover several independent operations in one province (verified: 2020 Cao Bằng `897/NQ-UBTVQH14` = three distinct mergers), so a bucket is only a candidate set; and (b) the **carve-out vs. split discriminator** — a named source that **survives into the next window's roster** is a carve-out (parent persists → `P807`), one that is **gone** is a split/merger (predecessor ends → `P576`/`P1365`).

- [ ] **Step 1: Write the failing test** (append to `tests/test_district_events.py`)

```python
from vn_admin_units.district_model import group_by_event, source_survives, resolve_merge_target

def test_group_by_event_buckets_same_date_and_province():
    ev = [{"eff_date": "2020-03-01", "tinh_to": "04", "tinh_from": "04", "code_to": "049"},
          {"eff_date": "2020-03-01", "tinh_to": "", "tinh_from": "04", "code_to": ""},
          {"eff_date": "2020-06-01", "tinh_to": "38", "tinh_from": "38", "code_to": "407"}]
    g = group_by_event(ev)
    assert len(g[("2020-03-01", "04")]) == 2 and len(g[("2020-06-01", "38")]) == 1

def test_discriminator_carve_vs_split():
    roster_next = {"quang trach", "ba don"}          # both survive -> Quảng Trạch persists = carve
    assert source_survives("Huyện Quảng Trạch", roster_next) is True
    roster_no_tu_liem = {"nam tu liem", "bac tu liem"}
    assert source_survives("Huyện Từ Liêm", roster_no_tu_liem) is False   # gone -> split

def test_resolve_merge_target_prefers_ghichu_then_survivor():
    ev = {"ghi_chu": "Nhập toàn bộ ... của huyện Thông Nông  vào huyện Hà Quảng",
          "name_from": "Huyện Thông Nông"}
    assert resolve_merge_target(ev, {"ha quang": "041"}) == "041"   # target CODE via prose 'vào Y'
    ev2 = {"ghi_chu": "", "name_from": "Huyện Phục Hoà"}
    assert resolve_merge_target(ev2, {"quang hoa": "049"}) is None  # no prose target -> unresolved
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_district_events.py -q`
Expected: FAIL — `group_by_event`/`source_survives`/`resolve_merge_target` not defined.

- [ ] **Step 3: Add the resolvers to `district_model.py`**

```python
from collections import defaultdict

from vn_admin_units.ghichu import parse_district_ghichu


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_district_events.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vn_admin_units/district_model.py tests/test_district_events.py
git commit -m "feat(phase2): lineage resolution (bucketing + carve/split discriminator)"
```

---

## Task D6.5: Recover the true dissolve/merge effective date from the Nghị định list

**Files:**
- Modify: `src/vn_admin_units/crosscheck_decrees.py`
- Test: `tests/test_crosscheck_decrees.py` (add)

**Why this is its own task (2026-07-15 plan review, P1).** A blank-successor **dissolve** row carries no `succ_hieu_luc`; `window_events` falls back to the predecessor's `base_hieu_luc` — its *last-change date in the base snapshot* (typically the 2004 baseline), **not** the merger's effective date (journal `2026-07-13.02`). If that stale date flows into `_apply_dissolve`, both the predecessor's `valid_to` and the `merged_into` edge's `effective_date` are wrong → a **false `P576`/`P585`**, and it also corrupts the `decree_for` lookup (which is keyed by date). The date must be **recovered from the Nghị định list by unit name** (Decision 6 — the decree states its own `hiệu lực`), which simultaneously yields the establishing-resolution reference (Finding 3). This was previously buried in a D7 "iteration note" with **no test gate** — the ground-truth suite's `ended()` date helper was defined but never called. This task adds the recovery + a real date assertion.

- [ ] **Step 1: Write the failing test** (append to `tests/test_crosscheck_decrees.py`)

```python
from vn_admin_units.crosscheck_decrees import decrees_naming

def test_decrees_naming_recovers_true_date_for_blank_successor_dissolve():
    # Fixtures use decree-LIST phrasing (concise, verb-adjacent to the tier) — the form
    # is_district_structural is validated against (journal 2026-07-13.02), not verbose Ghi Chú prose.
    recs = [
        {"code": "897/NQ-UBTVQH14", "hieu_luc": "01/03/2020", "url": "https://vb/897",
         "noi_dung": "nhập huyện Thông Nông vào huyện Hà Quảng"},               # district merge -> kept
        {"code": "111/NQ-CP", "hieu_luc": "10/01/2004", "url": "https://vb/111",
         "noi_dung": "thành lập xã Cần Nông thuộc huyện Thông Nông"},           # COMMUNE op -> excluded (F3)
    ]
    hits = decrees_naming(recs, "Huyện Thông Nông", years={2019, 2020})
    assert len(hits) == 1                                                      # the commune op is filtered out
    assert hits[0]["effective_date"] == "2020-03-01" and hits[0]["code"] == "897/NQ-UBTVQH14"
    assert hits[0]["url"] == "https://vb/897"

def test_decrees_naming_year_window_and_alias():
    recs = [{"code": "132/NQ-CP", "hieu_luc": "28/12/2013", "url": "https://vb/132",
             "noi_dung": "thành lập quận Nam Từ Liêm và quận Bắc Từ Liêm trên cơ sở huyện Từ Liêm"}]
    assert decrees_naming(recs, "Quận X", aliases=["Huyện Từ Liêm"], years={2013})
    assert decrees_naming(recs, "Huyện Từ Liêm", years={2020}) == []      # out of the year window
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_crosscheck_decrees.py -q`
Expected: FAIL — `decrees_naming` not defined.

- [ ] **Step 3: Add the name-based recovery to `crosscheck_decrees.py`**

```python
def decrees_naming(records, unit_name: str, aliases=(), years=None) -> list:
    """District-structural decrees whose prose names `unit_name` (or an alias). "District-
    structural" is decided by `is_district_structural` (a district unit is the OBJECT of a
    structural verb — thành lập / chia tách / nhập / sáp nhập / giải thể / nâng cấp / đổi tên …),
    which is what keeps a commune/ward op out. Optional `years` restricts to effective years in
    the set (a tight window around the crosswalk snapshot) so an unrelated later decree that
    mentions the unit can't hijack the date.

    Returns [{code, url, effective_date, noi_dung}] sorted by effective_date. This is the
    authoritative recovery for a blank-successor dissolve row, whose crosswalk date is the
    predecessor's stale base date (journal 2026-07-13.02); the top hit's effective_date is
    the true merger date and its url the establishing reference.

    A verb-anywhere check would false-match a COMMUNE/WARD op that merely mentions the district
    ('chia xã … thuộc huyện X'), assigning a bogus district dissolve date (2026-07-15 review, F3).
    So the record must pass `is_district_structural` — the SAME object-level classifier the
    cross-check uses (a district unit is the *object* of a structural verb; province tier
    'trực thuộc trung ương' excluded). If a legitimate merge phrasing is missed, extend `_STRUCT`
    (the single source of truth) — never loosen the gate here."""
    folds = [f for f in (fold_district_name(n) for n in (unit_name, *aliases) if n) if f]
    out = []
    for r in records:
        iso = _iso_from_dmy(str(r["hieu_luc"]))
        yr = iso[:4]
        if years is not None and not (yr.isdigit() and int(yr) in years):
            continue
        nd = str(r["noi_dung"])
        if not is_district_structural(nd):          # exclude commune/ward-only + province-tier ops
            continue
        if any(fn in fold_district_name(nd) for fn in folds):
            out.append({"code": r["code"], "url": _clean_url(r.get("url")),
                        "effective_date": iso, "noi_dung": nd})
    return sorted(out, key=lambda d: d["effective_date"])


def cache_decrees(out: str = "data/raw/nghidinh.json") -> None:
    """Fetch the Nghị định list ONCE and cache it (code, dates, noi_dung, url) so the offline
    build + the D7 date assertions run without the network. Commit the JSON. `fetch_decrees`
    is extended (D4) to carry a `url` column; until a decree has one, the emit gate (D11)
    lists it for curation via data/decree-urls.json."""
    import json
    from pathlib import Path
    dec = fetch_decrees()
    cols = ["code", "hieu_luc", "noi_dung"] + (["url"] if "url" in dec.columns else [])
    recs = dec[cols].astype(str).to_dict("records")
    for r in recs:                                   # 'nan'/'none' -> "" so overrides + gate work
        r["url"] = _clean_url(r.get("url"))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(recs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"cached {len(recs)} Nghị định records -> {out}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_crosscheck_decrees.py -q`
Expected: PASS.

- [ ] **Step 5: Cache the Nghị định list (live, once) — the offline build + D7 dates depend on it**

Run: `uv run python -c "from vn_admin_units.crosscheck_decrees import cache_decrees; cache_decrees()"`
Expected: `cached N Nghị định records -> data/raw/nghidinh.json`. This is the single networked fetch; the committed JSON is what `build_districts` reads (the suite stays offline). If `fetch_decrees` doesn't yet expose per-row `url`s, records carry no `url` — that's fine here; the emit gate (D11) reports which decrees still need one, curated via `data/decree-urls.json`.

> **Consumed by D7.** `build_districts` loads these cached records and threads them into `_resolve_bucket` → `_apply_dissolve`, which calls `decrees_naming(recs, name_from, aliases, years={year, year+1})` (base + compare year — a 2024→2025 window can carry a 2025 effective date) to set the recovered date + reference on the `merged_into` edge and the predecessor's `valid_to`. A dissolve whose date can't be recovered goes to residue (`dissolve-date-unrecovered`), never a guessed date. The ground-truth date assertion (`test_cao_bang_three_mergers_dates_and_references`) is enabled in D7 Step 1 and **requires this cached file**.

- [ ] **Step 6: Commit**

```bash
git add src/vn_admin_units/crosscheck_decrees.py tests/test_crosscheck_decrees.py data/raw/nghidinh.json
git commit -m "feat(phase2): recover true dissolve/merge date + reference from Nghị định list by unit name"
```

---

## Task D7: Assemble entities + lineage (ground-truth gated)

**Files:**
- Modify: `src/vn_admin_units/district_model.py`
- Test: `tests/test_district_groundtruth.py`

Assembly (design §Graph assembly): seed roots from the 2005-01-01 roster (3-digit; the 2004→2005 window is the 5-digit→3-digit recode → old code becomes an alias), walk the yearly windows 2005→2024 + the 2025 tail applying events chronologically **keyed by district code**, resolve split/carve/merge buckets with the D6 discriminator, then apply the **universal 2025 abolition**. The **ground-truth test is the gate** (house style, like `test_lineage_groundtruth` / `test_province_history_groundtruth`): extend the assembly against the *real* cached windows until it passes; never weaken an assertion; route anything unclassifiable to `data/district-residue.json`.

The five canonical cases are grounded in the real windows (verified 2026-07-14):
- **Từ Liêm split** (2013-12-28, decree `132/NQ-CP`): `019 Huyện Từ Liêm` ends; new `Quận Nam Từ Liêm` (inherits `019`) + new `Quận Bắc Từ Liêm` (`021`); both `split` successors of the ended Từ Liêm.
- **Nông Sơn create→dissolve**: created `2008-04-23` (`49/519`, blank base), dissolved in the 2024 window (`519` → blank succ) — one entity with both a known `valid_from` and a `valid_to`.
- **2020 Cao Bằng three mergers** (`897/NQ-UBTVQH14`): Thông Nông→Hà Quảng, Trà Lĩnh→Trùng Khánh, Phục Hoà + Quảng Uyên(→renamed Quảng Hòa) — three distinct operations in one province/decree bucket.
- **2008 Hà Tây re-parenting**: the ~14 Hà Tây districts (province `28`→`01`) plus Mê Linh (`26`→`01`) keep their entity and gain a **second `parent_span`** at `2008-08-01`; no dissolution.
- **2025 abolition**: every district still in force at `2025-06-30` gets `valid_to = 2025-06-30` + the abolition flag (~696 districts — SOAP/Lịch Sử count, journal `2026-07-13.01`).

- [ ] **Step 1: Write the ground-truth test** (`tests/test_district_groundtruth.py`)

```python
from vn_admin_units.district_model import build_districts

def _build():
    return build_districts("data/raw/crosswalk")

def test_tu_liem_split_predecessor_ends_two_new_products():
    ents, edges = _build()
    tl = next(e for e in ents if e.name_vi == "Huyện Từ Liêm")
    assert tl.valid_to == "2013-12-27"                                  # last in-force day
    prod = [x for x in edges if x.predecessor == tl.local_id and x.relation == "split"]
    succ_names = {next(e for e in ents if e.local_id == x.successor).name_vi for x in prod}
    assert succ_names == {"Quận Nam Từ Liêm", "Quận Bắc Từ Liêm"}
    assert all(x.effective_date == "2013-12-28" for x in prod)
    nam = next(e for e in ents if e.name_vi == "Quận Nam Từ Liêm")
    assert nam.terminal_code == "019" and nam.valid_from == "2013-12-28"   # code inherited, new entity

def test_nong_son_create_then_dissolve_one_entity():
    ents, edges = _build()
    ns = [e for e in ents if e.name_vi == "Huyện Nông Sơn"]
    assert len(ns) == 1                                                 # not duplicated
    ns = ns[0]
    assert ns.valid_from == "2008-04-23"
    # Nông Sơn dissolves in the 2024→2025 window, so its recovered valid_to must be late-2024
    # or 2025 — NOT the stale 2008 base date a missed recovery (wrong year window) would leave.
    # `< 2025-06-30` alone is too weak (the 2008 date satisfies it); pin the lower bound.
    assert "2024-01-01" <= ns.valid_to < "2025-06-30", f"stale/unrecovered dissolve date: {ns.valid_to}"
    assert all(x.reference_url for x in edges if x.predecessor == ns.local_id)   # merge edge referenced

def test_cao_bang_three_mergers_dates_and_references():
    ents, edges = _build()
    # Real per-unit dates recovered from the SURVIVOR crosswalk rows (Execution corrections
    # 2026-07-17) — they DIFFER: Thông Nông merged into Hà Quảng on 2020-02-01 under decree 864,
    # while Trà Lĩnh/Phục Hoà are 2020-03-01 under 897. A regression = survivor-row recovery not wired.
    expect = {  # dissolved -> (valid_to, edge effective_date, decree code)
        "Huyện Thông Nông": ("2020-01-31", "2020-02-01", "864/NQ-UBTVQH14"),
        "Huyện Trà Lĩnh":   ("2020-02-29", "2020-03-01", "897/NQ-UBTVQH14"),
        "Huyện Phục Hoà":   ("2020-02-29", "2020-03-01", "897/NQ-UBTVQH14"),
    }
    for gone, (vto, eff, code) in expect.items():
        e = next(x for x in ents if x.name_vi == gone)
        assert e.valid_to == vto, f"{gone}: {e.valid_to} != {vto} (stale base date leaked?)"
        merged = [x for x in edges if x.predecessor == e.local_id
                  and x.relation in ("merged_into", "consolidated")]
        assert merged, f"{gone} has no merge edge"
        m = merged[0]
        assert m.effective_date == eff, f"{gone}: merge edge date {m.effective_date} != {eff}"
        assert code in m.decree, f"{gone}: decree {m.decree!r} lacks {code}"
        assert m.reference_url, f"{gone}: merge edge missing its establishing-resolution reference"

def test_ha_tay_reparenting_second_parent_span_no_dissolution():
    ents, _ = _build()
    ba_vi = next(e for e in ents if e.name_vi == "Huyện Ba Vì" and e.terminal_code == "271")
    codes = [(s["code"], s["from"], s["to"]) for s in ba_vi.parent_spans]
    assert ("28", None, "2008-07-31") in codes and ("01", "2008-08-01", "2025-06-30") in codes
    assert ba_vi.valid_to == "2025-06-30"                              # persists to abolition, not dissolved

def test_universal_2025_abolition_count():
    ents, _ = _build()
    abolished = [e for e in ents if e.valid_to == "2025-06-30"]
    assert 690 <= len(abolished) <= 700                                # ~696 (journal 2026-07-13.01)
    assert all(getattr(e, "abolished", False) for e in abolished) or \
        all(e.valid_to == "2025-06-30" for e in abolished)             # flagged via helper (Step 3)

def test_no_local_id_collisions():
    from vn_admin_units.district_model import detect_collisions
    ents, _ = _build()
    assert detect_collisions(ents) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_district_groundtruth.py -q`
Expected: FAIL — `build_districts` not defined.

- [ ] **Step 3: Implement `build_districts` in `district_model.py`**

```python
import glob
import json
import os
from pathlib import Path

from vn_admin_units.crosswalk import read_district_crosswalk


def _recode_aliases(window_dir: str) -> dict:
    """3-digit code -> pre-2004 5-digit code (alias), from the 2004→2005 recode window."""
    p = os.path.join(window_dir, "district_2004-01-01_2005-01-01.xls")
    out = {}
    if os.path.exists(p):
        for r in read_district_crosswalk(p):
            if r["succ_ma"] and r["base_ma"]:
                out[r["succ_ma"]] = r["base_ma"]
    return out


def _yearly_paths(window_dir: str) -> list:
    """Ordered (start_year, path) for the event windows: 2005→2006 … 2024→2025 +
    the 2025-01→06 tail. The 2004→2005 recode window is excluded (alias source only)."""
    out = []
    for p in sorted(glob.glob(os.path.join(window_dir, "district_20*-01-01_20*-01-01.xls"))):
        y = int(os.path.basename(p).split("_")[1][:4])
        if y >= 2005:
            out.append((y, p))
    tail = os.path.join(window_dir, "district_2025-01-01_2025-06-30.xls")
    if os.path.exists(tail):
        out.append((2025, tail))
    return out


def _minus_one_day(iso: str) -> str:
    from datetime import date, timedelta
    y, m, d = (int(x) for x in iso.split("-"))
    return (date(y, m, d) - timedelta(days=1)).isoformat()


def _load_cached_decrees(path: str = "data/raw/nghidinh.json") -> list:
    """Cached Nghị định records (fetched + saved by D11 so the build + tests are OFFLINE).
    Each {code, hieu_luc, noi_dung, url?}. Missing file -> [] (dates fall back + log)."""
    return json.loads(Path(path).read_text(encoding="utf-8")) if os.path.exists(path) else []


def _load_merge_targets(path: str = "data/district-merge-targets.json") -> dict:
    """Human-curated {dissolved_local_id: successor_local_id} overrides for merges the
    resolver can't pair automatically (multi-op bucket, no prose — design §Out of scope, name-
    disambiguation residue). This is the curation escape that clears the merge-target HARD GATE:
    the residue dump lists the local_ids that still need an entry. Missing file -> {}."""
    return json.loads(Path(path).read_text(encoding="utf-8")) if os.path.exists(path) else {}


def build_districts(window_dir: str, decrees=None):
    """Assemble the district entity + lineage graph 2004→2025 + the 2025 abolition.

    Spine: the 2005-01-01 roster as roots (valid_from=None). Walk each yearly
    window in order, keyed by CURRENT district code; apply reparent / rename /
    retype / create / dissolve, resolving split/carve/merge buckets via the D6
    discriminator; finally end every surviving entity at the 2025 abolition.

    `decrees` is the (cached) Nghị định record list; it authoritatively dates every
    dissolve/split/merge and supplies each edge's establishing reference (D4/D6.5).
    Returns (entities, edges). Cross-validation + residue logging per Steps 4/5."""
    from vn_admin_units.crosscheck_decrees import load_decree_urls, decree_index, _clean_url
    recode = _recode_aliases(window_dir)
    if decrees is None:
        decrees = _load_cached_decrees()
    urls = load_decree_urls()                       # curated code -> url overrides
    for r in decrees:                               # normalize 'nan', then fill from the curated map
        r["url"] = _clean_url(r.get("url")) or urls.get(r.get("code"), "")
    if not decrees:
        log.warning("no cached Nghị định records: dissolve dates fall back to crosswalk + every "
                    "dated statement references the NSO root (run D11 Step 4 to cache them before emit)")
    idx = decree_index(decrees)                     # date-keyed lookup, shared by both passes
    manual_targets = _load_merge_targets()          # curated successor overrides (clears the hard gate)
    ents = {}          # current code -> Entity
    all_ents = []      # every entity ever created (incl. ended)
    edges = []
    residue = []

    # seed roots from the 2005-01-01 roster (base side of the 2005→2006 window)
    seed_rows = read_district_crosswalk(os.path.join(window_dir, "district_2005-01-01_2006-01-01.xls"))
    for r in seed_rows:
        code = r["base_ma"]
        if not code:
            continue
        e = District(code=code, valid_from=None, valid_to=ABOLITION_VALID_TO,
                     name_vi=r["base_ten"], loai_hinh=unit_tier(r["base_ten"]),
                     aliases=[recode[code]] if code in recode else [],
                     parent_spans=[{"code": r["base_tinh"], "qid": None,
                                    "from": None, "to": ABOLITION_VALID_TO}])
        ents[code] = e
        all_ents.append(e)

    for year, path in _yearly_paths(window_dir):
        rows = read_district_crosswalk(path)
        events = window_events(rows)
        roster_next = {fold_district_name(r["succ_ten"]) for r in rows if r["succ_ma"]}

        # Pass 1 — same-entity relabels (no pairing needed), BEFORE bucket pairing so
        # renamed survivors are in place when dissolves resolve their target.
        for ev in events:
            if ev["kind"] == "reparent":
                _apply_reparent(ev, ents, residue, idx)
            elif ev["kind"] == "rename":
                _apply_rename(ev, ents, residue)

        # Merge-target lookup: folded name/alias -> CURRENT code, built from ALL live
        # entities (NOT just window rows) because the absorber is often unchanged this
        # window (no row) — e.g. Hà Quảng grows but doesn't move. Aliases cover a
        # survivor renamed the same window (Quảng Uyên→Quảng Hòa keeps 'quang uyen').
        code_by_fold = {}
        for e in ents.values():
            code_by_fold.setdefault(fold_district_name(e.name_vi), e.terminal_code)
            for a in e.aliases:
                code_by_fold.setdefault(fold_district_name(a), e.terminal_code)

        # Pass 2 — operations needing predecessor/successor pairing, per
        # (effective_date, province) bucket: split / carve / plain create / retype / merge.
        for (eff, prov), bucket in group_by_event(events).items():
            _resolve_bucket(bucket, eff, ents, all_ents, edges, residue, roster_next,
                            code_by_fold, idx, decrees, year, manual_targets)

    # universal 2025 abolition: every entity still in force at 2025-06-30 ends there.
    # Entities ended earlier (dissolve/split) already carry valid_to < ABOLITION_VALID_TO.
    for e in all_ents:
        if e.valid_to == ABOLITION_VALID_TO:
            e.abolished = True

    detect_collisions(all_ents)
    build_districts.residue = residue           # exposed for Step 4/5 logging
    return all_ents, edges
```

```python
def _mint(code, eff, name, tinh, aliases=None, ref_url=""):
    """A new district minted mid-era (valid_from=eff): split product, carve child, or plain
    creation. `ref_url` is the creating decree's establishing reference — stamped on BOTH the
    founding type span (its P571) and the initial parent span (its dated P131/P580), so neither
    falls back to the NSO root (F2)."""
    return District(code=code, valid_from=eff, valid_to=ABOLITION_VALID_TO,
                    name_vi=name, loai_hinh=unit_tier(name), aliases=aliases or [],
                    type_spans=[{"loai_hinh": unit_tier(name), "from": eff,
                                 "to": ABOLITION_VALID_TO, "reference_url": ref_url}],
                    parent_spans=[{"code": tinh, "qid": None, "from": eff,
                                   "to": ABOLITION_VALID_TO, "reference_url": ref_url}])


def _apply_reparent(ev, ents, residue, idx):
    from vn_admin_units.crosscheck_decrees import decree_for
    e = ents.get(ev["code_from"])
    if not e:
        residue.append(("reparent-miss", ev)); return
    eff = ev["eff_date"]
    # The re-parenting decree references BOTH the old span's P582 (membership ended) and the
    # new span's P580 (membership began), so stamp it on both (F2 — dated P131 needs its decree).
    _, url = decree_for(idx, ev["name_to"] or ev["name_from"], eff, aliases=[ev["name_from"]])
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


def _apply_retype(ev, eff, ents, residue, idx):
    """Same-entity type change (+ possible rename): end the current type span, open a
    new one, keep the old name as an alias if it actually changed."""
    from vn_admin_units.crosscheck_decrees import decree_for
    e = ents.get(ev["code_from"])
    if not e:
        residue.append(("retype-miss", ev)); return
    _, url = decree_for(idx, ev["name_to"], eff, aliases=[ev["name_from"]])   # retype decree (F2)
    # The retype decree references BOTH the old type's P582 (end) and the new type's P580 (start),
    # so stamp it on the closed span too — else the old-span dated P31 emits on the NSO root and
    # the reference gate blocks the build.
    e.type_spans[-1]["to"] = _minus_one_day(eff)
    e.type_spans[-1]["reference_url"] = url
    e.type_spans.append({"loai_hinh": unit_tier(ev["name_to"]), "from": eff,
                         "to": ABOLITION_VALID_TO, "reference_url": url})
    if fold_district_name(ev["name_from"]) != fold_district_name(ev["name_to"]) \
            and ev["name_from"] not in e.aliases:
        e.aliases.append(ev["name_from"])
    e.name_vi, e.loai_hinh = ev["name_to"], unit_tier(ev["name_to"])


def _apply_split(ev, eff, ents, all_ents, edges, bucket_creates, idx):
    """Từ Liêm case: the code-inheriting retype_rename row ends the old entity and
    mints a NEW same-code product; every create in this bucket is another product.
    Returns the set of create codes consumed (so they aren't also minted as plain new)."""
    from vn_admin_units.crosscheck_decrees import decree_for
    old = ents.get(ev["code_from"])
    if not old:
        return set()
    old.valid_to = _minus_one_day(eff)
    # one decree covers the whole split; look it up (via the SOURCE name) before minting so every
    # product's P571 + dated P131 cite it (F2).
    code, url = decree_for(idx, ev["name_to"], eff, aliases=[ev["name_from"]])
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


def _apply_create(ev, eff, ents, all_ents, edges, residue, roster_next, idx):
    """Materialize a newly-created district (blank base). If Ghi Chú names a source it
    was carved 'trên cơ sở'/'chia tách từ' AND that source SURVIVES, add a carved_from
    edge to the persisting parent (P807 at emit); otherwise a plain new entity (P571)."""
    from vn_admin_units.crosscheck_decrees import decree_for
    parsed = parse_district_ghichu(ev["ghi_chu"])
    src = parsed.get("source")
    # The creation decree is the child's founding reference — its P571 AND its dated P131 — whether
    # a carve-out or a plain new unit (F2). A plain creation has no edge, so _mint stamps the entity.
    code, url = decree_for(idx, ev["name_to"], eff, aliases=[src] if src else [])
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


def _apply_dissolve(ev, eff, ents, edges, residue, code_by_fold, decrees, year, manual_targets):
    """End a dissolved district and fold it into the merge target (a persisting survivor).
    The blank-successor row's `eff` is the predecessor's STALE base date, so recover the
    TRUE merger date + establishing reference from the Nghị định list by unit name (D6.5).
    Successor resolved via Ghi-Chú prose, else the curated `manual_targets` override; still
    unresolved OR date unrecovered → residue (both are hard-gated in build_districts_all)."""
    from vn_admin_units.crosscheck_decrees import decrees_naming
    e = ents.get(ev["code_from"])
    if not e:
        residue.append(("dissolve-miss", ev)); return
    # `year` is the window's BASE year; a dissolve effective date lies in (base, compare],
    # i.e. year {year, year+1} (compare = year+1) — NOT year-1. A 2024→2025 window (year=2024)
    # can carry a 2025-01-01 effective date (e.g. Nông Sơn), so both years are required.
    hits = decrees_naming(decrees, ev["name_from"], e.aliases, years={year, year + 1})
    if not hits:
        # NEVER guess a date (F2 / the "never a guessed date" contract). Flag it BLOCKING and
        # emit nothing for it: set valid_to=None so the abolition pass and emitter both SKIP it —
        # otherwise it keeps the default 2025-06-30 and would masquerade as a 2025 abolition even
        # in the direct build/test path (F3). The build assertion (build_districts_all + the
        # offline test's residue check) fails until the real date is recovered (curate the decree
        # / extend `_STRUCT`). It's removed from the live roster (it IS gone).
        residue.append(("dissolve-date-unrecovered", ev))
        e.valid_to = None
        ents.pop(ev["code_from"], None)
        return
    eff, decree, ref_url = hits[0]["effective_date"], hits[0]["code"], hits[0]["url"]
    e.valid_to = _minus_one_day(eff)
    # successor: Ghi-Chú prose (returns an event-time CODE → ents.get) first; else the curated manual
    # override, which stores the successor's stable LOCAL_ID (not a code — a code can be recoded after
    # the merger, so ents.get(code) could miss). Resolve the override by entity identity among live ents.
    tgt = ents.get(resolve_merge_target(ev, code_by_fold) or "")
    if not tgt and manual_targets.get(e.local_id):
        succ_local = manual_targets[e.local_id]
        tgt = next((x for x in ents.values() if x.local_id == succ_local), None)
    if tgt and tgt.local_id != e.local_id:
        edges.append(LineageEdge(e.local_id, tgt.local_id, "merged_into", share="whole",
                                 decree=decree, effective_date=eff, reference_url=ref_url))
    else:
        # Successor unresolvable from prose AND not in manual_targets → residue (HARD-gated in
        # build_districts_all; curate data/district-merge-targets.json to clear). We still stamp the
        # dissolution so a non-gated direct build emits a correct P576 rather than dropping it (F2).
        e.dissolution = (eff, ref_url)
        residue.append(("merge-target-unresolved", {"local_id": e.local_id, "name_from": ev["name_from"],
                                                     "eff": eff}))
    ents.pop(ev["code_from"], None)


def _resolve_bucket(bucket, eff, ents, all_ents, edges, residue, roster_next,
                    code_by_fold, idx, decrees, year, manual_targets):
    """Pair predecessors/successors within one (effective_date, province) bucket:
      1. retype_rename whose source vanished + creates present → SPLIT (consumes creates);
         otherwise a same-entity retype.
      2. plain retype (tier change only) → same entity.
      3. remaining creates → carve-out child (source survives) or plain new entity.
      4. dissolve → merge into the Ghi-Chú 'vào Y' survivor (else the `manual_targets` override).
    `idx` is the shared date-keyed decree lookup — split/carve/create/retype take their decree
    + establishing reference from it; dissolve recovers its true date+reference by unit name
    from `decrees` (D6.5). Every unplaced row lands in residue (logged, never silent)."""
    creates = [e for e in bucket if e["kind"] == "create"]
    consumed = set()
    for ev in bucket:
        if ev["kind"] == "retype_rename":
            if not source_survives(ev["name_from"], roster_next) and creates:
                consumed |= _apply_split(ev, eff, ents, all_ents, edges, creates, idx)
            else:
                _apply_retype(ev, eff, ents, residue, idx)
        elif ev["kind"] == "retype":
            _apply_retype(ev, eff, ents, residue, idx)
    for ev in creates:
        if ev["code_to"] not in consumed:
            _apply_create(ev, eff, ents, all_ents, edges, residue, roster_next, idx)
    for ev in bucket:
        if ev["kind"] == "dissolve":
            _apply_dissolve(ev, eff, ents, edges, residue, code_by_fold, decrees, year, manual_targets)
```

> **Iteration note (house style — this is the gated data step):** run Step 4; when a ground-truth assertion fails, extend the assembly against the *real* windows. Known refinement points to expect: **(a)** the Cao Bằng merges resolve "vào huyện Hà Quảng"/"vào huyện Quảng Uyên" via `code_by_fold` (built from live entities + aliases, so the unchanged absorber Hà Quảng and the renamed survivor Quảng Hòa both resolve); **(b)** the discriminator must not mislabel Ba Đồn (Quảng Trạch survives as `454` → carve, not split); **(c)** *dissolve-date recovery is now WIRED (D6.5), not deferred* — a blank-successor dissolve row carries the **predecessor's** `base_hieu_luc` (its 2004 last-change date), **not** the merger's effective date, so `_apply_dissolve` calls `decrees_naming` to recover the real date + establishing reference from the Nghị định list by unit name. The ground-truth `test_cao_bang_three_mergers_dates_and_references` now **asserts the merge date (2020-02-29 valid_to / 2020-03-01 edge) and a non-empty reference** — a regression there means the cached decrees are missing or the recovery isn't threaded through. Do **not** weaken the tests. **(d)** `test_no_blocking_residue` (Step 5) fails until you clear both blocking residue kinds — curate `data/district-merge-targets.json` (successors) and recover missing dates (re-cache `data/raw/nghidinh.json` / extend `_STRUCT`) during THIS task; also curate `data/decree-urls.json` for any recovered edge whose decree lacks a URL — so the D11 hard gates and its Step-3 suite are already satisfied. Every row the resolver can't place goes to `residue`; assert-count drift usually means a new bucket shape, not a broken test. The `abolished` attribute is set dynamically on the Entity (Python allows it); the ground-truth test tolerates either the flag or `valid_to`.

- [ ] **Step 4: Run the ground-truth suite; log the residue**

Run: `uv run pytest tests/test_district_groundtruth.py -q`
Expected: all PASS after iteration. Then dump the residue for review:

```bash
uv run python -c "from vn_admin_units.district_model import build_districts as B; import json; e,ed=B('data/raw/crosswalk'); open('data/district-residue.json','w').write(json.dumps(getattr(B,'residue',[]), ensure_ascii=False, indent=2)); open('data/districts.json','w').write(json.dumps([x.to_dict() for x in e], ensure_ascii=False, indent=2)); print(len(e),'entities',len(ed),'edges',len(getattr(B,'residue',[])),'residue')"
```
Expected: ~700 entities; residue is a short list (Đạ Tẻh↔Đạ Huoai code-reuse, multi-op merge targets). Inspect each and **clear the two BLOCKING kinds here in D7** (they hard-fail the build in D11 and are asserted by Step 5's `test_no_blocking_residue`, so curate them now — not at D11 Step 4, which runs *after* the D11 Step 3 suite):
  - `merge-target-unresolved` → add a `{dissolved_local_id: successor_local_id}` entry to **`data/district-merge-targets.json`** (look up the surviving successor's `local_id` in the `data/districts.json` this command just dumped — it's the living district the unit merged into), then re-run until it's gone. This *is* the design's manual-curation file for name-disambiguation residue — curated, not merely "accepted".
  - `dissolve-date-unrecovered` → the decree RECORD couldn't be found by `decrees_naming` (D6.5), so make it findable: ensure it's in **`data/raw/nghidinh.json`** (re-run `cache_decrees()` if the cache is stale/incomplete); if it's present but not matched, extend **`_STRUCT`** (its phrasing is rejected by `is_district_structural`) or the unit's alias/name set (fold match misses). **Not** `data/decree-urls.json` — that only attaches a URL to an *already-found* record; it can't surface a missing one.
  - *(reference, not date)* if a recovered merge/split/carve edge has an **empty `reference_url`** (the found decree record has no URL), add `{decree_code: url}` to **`data/decree-urls.json`**. D7's ground-truth asserts a non-empty reference on the *sampled* Cao Bằng/Nông Sơn edges; the **whole-graph** reference completeness is enforced by D11's `test_district_pipeline_offline_guards` (which runs `event_statements_missing_reference` over the full emitted batch in the Step-3 suite) — any residual URL gap fails there and is topped up in `data/decree-urls.json` (committed in D11).
  Any *non-lineage* residue (e.g. a pure code-reuse note) may remain as logged, accepted residue.

- [ ] **Step 5: Add the roster-delta cross-validation build assertion**

Append a checker + test (the events for year Y must exactly explain the roster delta between the Y and Y+1 snapshots — design §Graph assembly):

```python
def crossvalidate_window(rows: list) -> dict:
    """A window's changed events must exactly account for its create/dissolve delta.
    Returns {created, dissolved, events, ok} for a build assertion."""
    created = sum(1 for r in rows if not r["base_ma"] and r["succ_ma"])
    dissolved = sum(1 for r in rows if r["base_ma"] and not r["succ_ma"])
    ev = window_events(rows)
    ec = sum(1 for e in ev if e["kind"] == "create")
    ed = sum(1 for e in ev if e["kind"] == "dissolve")
    return {"created": created, "dissolved": dissolved,
            "event_creates": ec, "event_dissolves": ed,
            "ok": created == ec and dissolved == ed}
```

Test (append to `tests/test_district_groundtruth.py`):

```python
def test_roster_delta_crossvalidation_all_windows():
    import glob
    from vn_admin_units.crosswalk import read_district_crosswalk
    from vn_admin_units.district_model import crossvalidate_window
    for p in glob.glob("data/raw/crosswalk/district_20*-01-01_20*-01-01.xls"):
        rows = read_district_crosswalk(p)
        assert crossvalidate_window(rows)["ok"], f"delta mismatch in {p}"

def test_no_blocking_residue():
    # The two BLOCKING residue kinds must be cleared HERE in D7 (curate data/district-merge-targets.json
    # for successors; recover missing dates via cache_decrees/data/raw/nghidinh.json + _STRUCT) — not
    # deferred to D11, whose Step-3 suite would otherwise fail before Step 4 tells anyone to curate.
    # (data/decree-urls.json fixes missing REFERENCES, not dates.) Matches the D11 hard gates 1:1.
    from vn_admin_units.district_model import build_districts
    build_districts("data/raw/crosswalk")
    res = getattr(build_districts, "residue", [])
    assert not [r for r in res if r[0] == "dissolve-date-unrecovered"], "recover dissolve dates (D6.5)"
    assert not [r for r in res if r[0] == "merge-target-unresolved"], \
        "curate successors in data/district-merge-targets.json"
```

Run: `uv run pytest tests/test_district_groundtruth.py -q`
Expected: PASS (all windows balance; no blocking residue after curation).

- [ ] **Step 6: Commit**

```bash
git add src/vn_admin_units/district_model.py tests/test_district_groundtruth.py data/district-residue.json data/district-merge-targets.json data/decree-urls.json
git commit -m "feat(phase2): assemble district lineage 2004-2025 + abolition; ground-truth gated"
```

---

## Task D8: Reconciliation — bulk SPARQL + province-aware matching

**Files:**
- Modify: `src/vn_admin_units/reconcile.py`
- Test: `tests/test_district_reconcile.py`
- Produce: `mappings/districts-qid.csv`

Match on **(folded name + parent province)**, province as a **weak** tiebreak only — WD `P131` is frequently stale (design §4; `2026-07-10.08`): never discard a name match solely because WD's parent disagrees, and fall back to per-item `wbsearchentities`. Bulk SPARQL pulls all VN districts once (scales far better than ~700 per-item searches). Most items exist but are near-empty (Nông Sơn `Q2541962` = only `P31`/`P131`, verified), so edits are mostly additive; a few are genuine gaps (Bắc Từ Liêm has no `vi` item). Write a **separate** `local_id`-keyed mapping (never grow the province CSVs).

- [ ] **Step 1: Write the failing test** (`tests/test_district_reconcile.py`)

```python
from vn_admin_units.reconcile import (match_districts, write_district_mapping,
                                       load_district_seed, load_district_mapping,
                                       load_acknowledged_gaps)
from vn_admin_units.district_model import District

def _d(code, name, prov):
    return District(code=code, valid_from=None, valid_to="2025-06-30", name_vi=name,
                    loai_hinh="Huyện",
                    parent_spans=[{"code": prov, "qid": None, "from": None, "to": "2025-06-30"}])

def test_match_by_folded_name_province_weak_tiebreak():
    ents = [_d("519", "Huyện Nông Sơn", "49"), _d("021", "Quận Bắc Từ Liêm", "01")]
    candidates = [{"qid": "Q2541962", "label": "Nông Sơn", "parent_code": "49"},
                  {"qid": "Q_WRONG", "label": "Nông Sơn", "parent_code": "99"}]  # stale parent
    out = match_districts(ents, candidates)
    d = {e.terminal_code: e for e in out}
    assert d["519"].wikidata_qid == "Q2541962" and d["519"].qid_status == "existing"  # province picks right one
    assert d["021"].wikidata_qid is None and d["021"].qid_status == "new"             # genuine gap

def test_name_match_survives_when_province_disagrees_entirely():
    ents = [_d("911", "Thành phố Phú Quốc", "91")]
    candidates = [{"qid": "Q42589", "label": "Phú Quốc", "parent_code": "00"}]        # only hit, stale parent
    out = match_districts(ents, candidates)
    assert out[0].wikidata_qid == "Q42589"                    # not discarded for P131 mismatch (§4)

def test_alias_only_item_matches_not_new():
    ents = [_d("456", "Huyện Mỏ Cày Nam", "83")]
    # the bulk item's LABEL is a stale/English form; the GSO name is only an ALIAS
    candidates = [{"qid": "Q123", "label": "Mo Cay Nam District",
                   "aliases": ["Huyện Mỏ Cày Nam"], "parent_code": "83"}]
    out = match_districts(ents, candidates)
    assert out[0].wikidata_qid == "Q123" and out[0].qid_status == "existing"   # matched via alias, not 'new'

def test_bulk_miss_uses_search_fallback_before_new():
    ents = [_d("021", "Quận Bắc Từ Liêm", "01")]              # absent from the bulk pull
    calls = []
    def fake_search(name):
        calls.append(name)                                   # invoked with the tier-stripped name
        return [{"id": "Q999", "label": "Bắc Từ Liêm", "description": "district"}]
    def fake_verify(ids):
        return {"Q999": ["Q881"]}                            # P17 = Vietnam
    out = match_districts(ents, [], search_fn=fake_search, verify_fn=fake_verify)
    assert out[0].wikidata_qid == "Q999" and out[0].qid_status == "existing"
    assert calls and "Từ Liêm" in calls[0] and "Quận" not in calls[0]

def test_verified_no_hit_is_new():
    ents = [_d("021", "Quận Bắc Từ Liêm", "01")]
    out = match_districts(ents, [], search_fn=lambda n: [], verify_fn=lambda ids: {})
    assert out[0].wikidata_qid is None and out[0].qid_status == "new"   # only a VERIFIED gap is 'new'

def test_district_seed_roundtrip_preserves_manual(tmp_path):
    p = tmp_path / "districts-qid.csv"
    write_district_mapping([_d("519", "Huyện Nông Sơn", "49")], str(p))
    p.write_text(p.read_text().replace("d-519-base,519,Huyện Nông Sơn,49,,,needs-lookup",
                                       "d-519-base,519,Huyện Nông Sơn,49,Q2541962,existing,verified"),
                 encoding="utf-8")
    seed = load_district_seed(str(p))
    assert seed["d-519-base"] == ("Q2541962", "existing")

def test_matched_rows_survive_offline_load_and_rewrite(tmp_path):
    # F1: a live auto-match (status 'matched') must be readable offline AND not be downgraded
    # to needs-lookup / lose its QID on the next rebuild.
    p = tmp_path / "districts-qid.csv"
    p.write_text("local_id,terminal_code,name_vi,parent_code,wikidata_qid,qid_status,match_status\n"
                 "d-519-base,519,Huyện Nông Sơn,49,Q2541962,existing,matched\n", encoding="utf-8")
    mapping = load_district_mapping(str(p))
    assert mapping["d-519-base"] == ("Q2541962", "existing")     # load_district_seed would MISS this
    assert load_district_seed(str(p)) == {}                      # (only verified/manual)
    ent = _d("519", "Huyện Nông Sơn", "49")
    ent.wikidata_qid, ent.qid_status = mapping["d-519-base"]
    write_district_mapping([ent], str(p))
    row = p.read_text().splitlines()[1]
    assert row.endswith("Q2541962,existing,matched")            # QID + 'matched' preserved, not downgraded

def test_acknowledged_gap_is_loaded_and_not_downgraded(tmp_path):
    # F1: a human-acknowledged create-later gap (no QID, match_status='gap') is recognized by the
    # completeness gate AND survives a rewrite instead of reverting to needs-lookup.
    p = tmp_path / "districts-qid.csv"
    p.write_text("local_id,terminal_code,name_vi,parent_code,wikidata_qid,qid_status,match_status\n"
                 "d-021-2013-12-28,021,Quận Bắc Từ Liêm,01,,new,gap\n"
                 "d-777-base,777,Huyện X,55,,,needs-lookup\n", encoding="utf-8")
    assert load_acknowledged_gaps(str(p)) == {"d-021-2013-12-28"}      # only the 'gap' row
    ent = District(code="021", valid_from="2013-12-28", valid_to="2025-06-30",
                   name_vi="Quận Bắc Từ Liêm", loai_hinh="Quận")       # local_id == d-021-2013-12-28
    write_district_mapping([ent], str(p))
    row = next(l for l in p.read_text().splitlines() if l.startswith("d-021-2013-12-28"))
    assert row.endswith("gap") and "needs-lookup" not in row          # gap preserved, not downgraded

def test_audit_reports_gap_separately_from_unresolved(tmp_path):
    # No QIDs in this mapping -> audit makes zero network calls (offline-safe). A 'gap' row is a
    # reviewed create-later gap, NOT an issue; an un-triaged QID-less row IS 'UNRESOLVED'.
    from vn_admin_units.reconcile import audit_district_qids
    p = tmp_path / "districts-qid.csv"
    p.write_text("local_id,terminal_code,name_vi,parent_code,wikidata_qid,qid_status,match_status\n"
                 "d-021-2013-12-28,021,Quận Bắc Từ Liêm,01,,new,gap\n"
                 "d-777-base,777,Huyện X,55,,,needs-lookup\n", encoding="utf-8")
    issues = audit_district_qids(str(p))
    assert any(i.startswith("UNRESOLVED") and "d-777-base" in i for i in issues)   # un-triaged -> issue
    assert not any("d-021-2013-12-28" in i for i in issues)                        # acknowledged gap -> not an issue
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_district_reconcile.py -q`
Expected: FAIL — the new functions are not defined.

- [ ] **Step 3: Add district reconciliation to `reconcile.py`** (new functions; do not touch 1a/1b)

```python
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
    """Map each candidate's parent_qid → GSO province code (via the reconciled
    province mappings) so match_districts can use province as a weak tiebreak. A
    candidate whose parent_qid isn't in the map keeps parent_code=None (name-only)."""
    for c in candidates:
        c["parent_code"] = prov_qid_to_code.get(c.get("parent_qid"))
    return candidates


def match_districts(entities: list, candidates: list, search_fn=None, verify_fn=None) -> list:
    """Match each district Entity to a WD candidate by FOLDED NAME — indexing candidate
    LABELS **and aliases**, and testing the entity's OWN aliases too (a near-empty item
    often holds the GSO name only as an alias). Parent province is a WEAK tiebreak among
    same-name hits; a lone name hit is accepted even if its P131 disagrees (WD P131 is
    stale — design §4).

    A bulk miss is NOT immediately 'new': when `search_fn` (wbsearchentities) is supplied,
    fall back to a per-item search verified by `verify_fn` (P17=Vietnam) before conceding a
    gap (design §Reconciliation fallback). Only a *verified* no-hit becomes qid_status='new'.
    Both fns are injected so the unit tests stay offline; the pipeline (D11) passes the live
    `wd_search`/`wd_country`."""
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_district_reconcile.py -q`
Expected: PASS (9 tests — match/seed + alias-match + search-fallback + verified-gap + matched-rows-survive + acknowledged-gap + audit-gap-vs-unresolved; all offline, `search_fn`/`verify_fn` injected).

- [ ] **Step 5: Produce + manually verify the mapping (live)** — build entities (D7), fill parent-province QIDs from the **Phase-1b** history mapping (design dependency §1 — never emit `P131` with an unreconciled province value), pull SPARQL, match, write, then verify:

Use `cli.reconcile_districts_live` (defined in Task D11) — the single networked command that
fills province QIDs, attaches parent codes to the candidates, matches (with the
`wbsearchentities` fallback), and writes the mapping in the correct order — then audit:

```bash
uv run python -c "from vn_admin_units.cli import reconcile_districts_live; reconcile_districts_live()"
uv run python -c "from vn_admin_units.reconcile import audit_district_qids as A; [print(i) for i in A()]"
```
Resolve every flagged row by hand (`match_status=verified`/`manual`); a genuine no-item gap (e.g. Bắc Từ Liêm) that survives even the `wbsearchentities` fallback must be **explicitly marked `match_status='gap'`** (a reviewed create-later acknowledgment) — the completeness gate hard-fails on any un-triaged `needs-lookup` row, and the audit reports `gap` rows informationally (not as `UNRESOLVED`). Province tiebreaking is live via `attach_parent_codes` (candidate `parent_qid` → GSO code through the reconciled province mappings); same-name pairs whose WD `P131` is stale still match by name (design §4), and alias-only / stale-label items are rescued by the alias index + fallback rather than mislabeled `new`. All confirmed in the audit.

> Note: `reconcile_districts_live` is introduced in D11 (it needs `build_districts_all`'s sibling helpers); D8 delivers + unit-tests the functions it composes (`sparql_vn_districts`, `match_districts`, `write_district_mapping`, `audit_district_qids`). Run this live step after D11, or import the functions directly here.

- [ ] **Step 6: Commit**

```bash
git add src/vn_admin_units/reconcile.py tests/test_district_reconcile.py mappings/districts-qid.csv
git commit -m "feat(phase2): district reconciliation (bulk SPARQL, province-weak match, audit)"
```

---

## Task D9: Emit — relation-aware district QuickStatements

**Files:**
- Modify: `src/vn_admin_units/emit.py`
- Test: `tests/test_district_emit.py`

Rules (design §Emit), all via `core` primitives:
- **`P576` only on entities that actually END** — the `P576` **value is the event date = `valid_to` + 1** (`valid_to` is the last in-force day, per §Date convention — not itself the event date). A `carved_from` parent (persists) gets **no `P576`**. Every merger resolves a successor (Ghi-Chú prose or the curated `data/district-merge-targets.json` override) — an unresolved one is **hard-gated** in `build_districts_all`; the entity-stamped `dissolution` (emit still produces `P576`) is a defensive net for a non-gated direct build (F2).
- **Succession by relation:** an ended predecessor → `P7888`/`P1366` → successor; successor → `P1365` → predecessor; `P585` = event date. A **`carved_from`** child instead uses **`P807`** → parent + its own `P571` (parent gets neither).
- **`P571`** when `valid_from` is known (not gated on `qid_status`; audit existing claims first). **Referenced to the creating decree** — the edge's `reference_url`, else the founding `reference_url` the assembly stamped on `type_spans[0]` (plain creations have no edge), never the bare NSO root (F2).
- **`P131`** per `parent_span`, date-qualified (`P580`/`P582`) — Hà Tây districts emit two. A **dated span** (re-parenting / creation) is **referenced to its span's decree** (`reference_url`); only a bare baseline span (from=None) uses the NSO source. **Skip any span whose province `qid` is unresolved** (dependency §1) and log it.
- **`P31` retype** dated (`P580`/`P582`) per non-terminal type span, **referenced to the retype decree** on the span; district `P31` targets come from `core.P31_TARGETS` (extended + confirmed in D10).
- **2025 abolition:** `P576 = 2025-07-01` on every district still in force, referenced to the reform resolution; no successor.
- **Skip same-QID edges.** Every statement referenced (`S854`); the D11 gate hard-fails any lineage, dissolution, `P571`, or dated `P131`/`P31` statement left on the generic NSO root.

- [ ] **Step 1: Write the failing test** (`tests/test_district_emit.py`)

```python
from vn_admin_units.district_model import District
from vn_admin_units.core import LineageEdge
from vn_admin_units.emit import emit_district_quickstatements, ABOLITION_DATE

def _d(code, name, qid, vf=None, vto="2025-06-30", loai="Huyện", parent=None):
    d = District(code=code, valid_from=vf, valid_to=vto, name_vi=name, loai_hinh=loai,
                 parent_spans=parent or [{"code": "01", "qid": "Q1858", "from": vf, "to": vto}],
                 wikidata_qid=qid, qid_status="existing")
    return d

def test_universal_abolition_p576_on_survivor_no_successor():
    d = _d("271", "Huyện Ba Vì", "Q1234")
    qs = emit_district_quickstatements([d], [], default_ref_url="https://nso", abolition_ref="https://reform")
    p576 = next(l for l in qs.splitlines() if l.startswith("Q1234\tP576"))
    assert f"+{ABOLITION_DATE}T00:00:00Z/11" in p576 and '"https://reform"' in p576
    assert "P7888" not in qs and "P1366" not in qs                 # abolition has no successor

def test_dated_p131_per_parent_span():
    d = _d("271", "Huyện Ba Vì", "Q1234",
           parent=[{"code": "28", "qid": "Q1077294", "from": None, "to": "2008-07-31"},
                   {"code": "01", "qid": "Q1858", "from": "2008-08-01", "to": "2025-06-30"}])
    qs = emit_district_quickstatements([d], [], default_ref_url="https://nso", abolition_ref="https://reform")
    p131 = [l for l in qs.splitlines() if l.startswith("Q1234\tP131")]
    assert any("Q1077294" in l and "P582\t+2008-07-31" in l for l in p131)   # old parent end-dated
    assert any("Q1858" in l and "P580\t+2008-08-01" in l for l in p131)      # new parent start-dated

def test_carve_out_child_p807_and_p571_parent_persists():
    parent = _d("458", "Huyện Quảng Trạch", "Qpar")
    child = _d("454", "Huyện Quảng Trạch", "Qchild", vf="2013-12-21")   # Ba Đồn/Quảng Trạch carve
    edges = [LineageEdge(parent.local_id, child.local_id, "carved_from",
                         decree="Số: 125/NQ-CP", effective_date="2013-12-21", reference_url="https://d")]
    qs = emit_district_quickstatements([parent, child], edges, default_ref_url="https://nso", abolition_ref="https://reform")
    assert "Qchild\tP807\tQpar" in qs and "Qchild\tP571\t+2013-12-21" in qs
    assert not any(l.startswith("Qpar\tP576\t+2013-12-21") for l in qs.splitlines())  # parent NOT dissolved at carve

def test_split_predecessor_dissolved_products_succeed():
    old = _d("019", "Huyện Từ Liêm", "Qold", vto="2013-12-27")
    nam = _d("019", "Quận Nam Từ Liêm", "Qnam", vf="2013-12-28", loai="Quận")
    edges = [LineageEdge(old.local_id, nam.local_id, "split", share="partial",
                         decree="Số: 132/NQ-CP", effective_date="2013-12-28")]
    qs = emit_district_quickstatements([old, nam], edges, default_ref_url="https://nso", abolition_ref="https://reform")
    assert "Qold\tP576\t+2013-12-28" in qs                          # predecessor ends at split date
    assert "Qnam\tP1365\tQold" in qs and "Qnam\tP571\t+2013-12-28" in qs
    assert not any(l.startswith("Qold\tP576\t+2025-07-01") for l in qs.splitlines())  # not double-dissolved by abolition

def test_retype_p31_both_spans_cite_the_decree():
    # F1: a genuine retype emits TWO dated P31 (old P582 + new P580); BOTH must cite the retype
    # decree — the closed span too, else its dated P31 lands on the NSO root and the gate blocks.
    d = District(code="116", valid_from=None, valid_to="2025-06-30",
                 name_vi="Thành phố Sơn La", loai_hinh="Thành phố",
                 type_spans=[{"loai_hinh": "Thị xã", "from": None, "to": "2008-10-02",
                              "reference_url": "https://vb/retype"},
                             {"loai_hinh": "Thành phố", "from": "2008-10-03", "to": "2025-06-30",
                              "reference_url": "https://vb/retype"}],
                 parent_spans=[{"code": "14", "qid": "Q1", "from": None, "to": "2025-06-30"}],
                 wikidata_qid="Qsl", qid_status="existing")
    qs = emit_district_quickstatements([d], [], default_ref_url="https://nso", abolition_ref="https://reform")
    p31 = [l for l in qs.splitlines() if l.startswith("Qsl\tP31")]
    assert len(p31) == 2 and all('"https://vb/retype"' in l for l in p31)     # neither on the NSO root
    assert any("P582\t+2008-10-02" in l for l in p31) and any("P580\t+2008-10-03" in l for l in p31)

def test_merge_target_unresolved_still_emits_dissolution_p576():
    # F2: a dissolve whose successor couldn't be resolved still emitted its P576 (we know it
    # dissolved on the recovered date). The missing succession link is manual-curation residue.
    e = _d("044", "Huyện Thông Nông", "Qtn", vto="2020-02-29")
    e.dissolution = ("2020-03-01", "https://vb/897")        # stamped by _apply_dissolve (no edge)
    qs = emit_district_quickstatements([e], [], default_ref_url="https://nso", abolition_ref="https://reform")
    p576 = next(l for l in qs.splitlines() if l.startswith("Qtn\tP576"))
    assert "+2020-03-01T00:00:00Z/11" in p576 and '"https://vb/897"' in p576     # dissolution NOT dropped
    assert not any(l.startswith("Qtn\tP576\t+2025-07-01") for l in qs.splitlines())  # not an abolition
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_district_emit.py -q`
Expected: FAIL — `emit_district_quickstatements`/`ABOLITION_DATE` not defined.

- [ ] **Step 3: Add `emit_district_quickstatements` to `emit.py`** (built on `core`)

```python
from vn_admin_units.core import wd_date, ref_s854, p31_target, predecessor_ends

ABOLITION_DATE = "2025-07-01"        # two-tier reform; districts' P576 event date
ABOLITION_VALID_TO = "2025-06-30"


def emit_district_quickstatements(entities: list, edges: list, default_ref_url: str,
                                  abolition_ref: str) -> str:
    """Relation-aware QuickStatements for the district tier + the 2025 abolition.
    P576 fires only on entities that end: from a lineage edge's effective_date for
    a pre-abolition end, or ABOLITION_DATE for a survivor. carved_from parents never
    get P576. See docs/DESIGN-phase2.md §Emit."""
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
        # Audit existing WD claims before applying.
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
        # P576: pre-abolition end (from an edge, referenced to its own decree) OR a dissolution
        # with no resolved successor (entity-stamped e.dissolution — the district DID dissolve on
        # the recovered date even if its merge target is manual-curation residue, F2) OR the
        # universal abolition. Never on a carve-out parent (it persists — it has no ends_at entry
        # and no e.dissolution unless separately dissolved).
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
    return ("\n".join(out) + "\n") if out else ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_district_emit.py -q`
Expected: PASS (6 tests). ⚠️ These assert statement *shape* + references only — the district `P31` target QIDs are confirmed by the **Task D10 `describe_items` gate**, not here.

- [ ] **Step 5: Commit**

```bash
git add src/vn_admin_units/emit.py tests/test_district_emit.py
git commit -m "feat(phase2): relation-aware district emitter (P576-on-end, P807, dated P131, abolition)"
```

---

## Task D10: Extend the constraints gate (P131+P580/P582; confirm district P31 targets)

**Files:**
- Modify: `src/vn_admin_units/constraints.py` (+ `src/vn_admin_units/core.py` **only if** Step 5's `describe_items` shows a placeholder QID is wrong — the four district targets themselves were registered in R1)
- Test: `tests/test_constraints.py` (add)

The district emit adds `P131`+`P580`/`P582` (allowed-qualifier check, automated) and four district `P31` target items (registered as placeholders in R1) that must be **confirmed** before emit (a wrong target QID passes shape tests and emits a wrong `P31` — this bit Phase 1b, whose placeholders were a Myanmar settlement / a Benin arrondissement). `P807` value-type stays a manual gate (already reported by the tool).

- [ ] **Step 1: Write the failing test** (append to `tests/test_constraints.py`)

```python
from vn_admin_units import constraints as C

def test_phase2_checks_include_p131_qualifiers():
    combos = dict((p, q) for p, q in C.PHASE2_CHECKS)
    assert combos.get("P131") in ("P580", "P582") or ("P131", "P580") in C.PHASE2_CHECKS
    assert ("P131", "P582") in C.PHASE2_CHECKS

def test_district_p31_targets_registered():
    from vn_admin_units.core import P31_TARGETS
    for t in ("Huyện", "Quận", "Thị xã", "Thành phố"):
        assert t in P31_TARGETS and P31_TARGETS[t].startswith("Q")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_constraints.py -q`
Expected: FAIL — `PHASE2_CHECKS` missing. (`test_district_p31_targets_registered` already PASSES — the four district placeholders were registered in `core.P31_TARGETS` back in R1 so the D9 emitter could resolve targets; D10 **confirms/corrects** them, it doesn't first-register them.)

- [ ] **Step 3: Add the Phase-2 constraint checks + the confirmation gate**

The district `P31` placeholders already live in `core.P31_TARGETS` (R1). Do **not** re-add them here — D10 only adds the qualifier checks and the live `describe_items` confirmation (Step 5 corrects the placeholders if any is wrong).

In `constraints.py`, add:

```python
PHASE2_CHECKS = [("P131", "P580"), ("P131", "P582")]
```

And extend `main` (after the Phase-1b block) to report them + describe the district targets:

```python
    print("\n=== Phase-2 qualifier checks ===")
    for pid, qual in PHASE2_CHECKS:
        aq = allowed_qualifiers(pid)
        print(f"  {pid} + {qual}: {'OK' if qualifier_allowed(aq, qual) else 'DISALLOWED'}")
    print("\n=== Phase-2 district P31 target items — CONFIRM before emit ===")
    from vn_admin_units.core import P31_TARGETS
    describe_items([P31_TARGETS[t] for t in ("Huyện", "Quận", "Thị xã", "Thành phố")])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_constraints.py -q`
Expected: PASS.

- [ ] **Step 5: Run the gate live and CONFIRM the district P31 targets**

Run: `uv run python -m vn_admin_units.constraints P131 P807`
Expected: prints `P131 + P580/P582` verdicts **and** the labels/descriptions of the four district target items. **Confirm** each label is the correct Vietnamese district sense (rural district / urban district / district-level town / provincial city). If any is wrong, fix `core.P31_TARGETS` before emitting — the emit tests assert shape only. Confirm `P131`+`P580`/`P582` are allowed (or adjust emit).

- [ ] **Step 6: Commit**

```bash
git add src/vn_admin_units/constraints.py src/vn_admin_units/core.py tests/test_constraints.py
git commit -m "feat(phase2): constraints gate for P131 qualifiers + district P31 targets"
```

---

## Task D11: Wire the pipeline + produce artifacts (no upload)

**Files:**
- Modify: `src/vn_admin_units/cli.py`
- Test: `tests/test_pipeline.py` (add)
- Produce: `data/districts.json`, `data/district-lineage.json`, `statements/na-districts.qs`

The abolition reference (the two-tier reform resolution) is not yet in the repo — **source + confirm it in Step 4** (the same discipline Phase 1b used for the Hà Tây decree), defaulting to a documented candidate.

- [ ] **Step 1: Add `build_districts_all` to `cli.py`**

```python
# ── Live reconciliation (networked) — a MANUAL/audit command, NOT run by the test suite ──
def reconcile_districts_live() -> None:
    """LIVE Wikidata reconciliation: bulk SPARQL + per-item wbsearchentities fallback →
    writes mappings/districts-qid.csv. Networked; run manually to refresh the mapping. The
    offline build_districts_all and the test suite NEVER call it (open-question fix,
    2026-07-15 review — the default suite must not depend on the network)."""
    from vn_admin_units.district_model import build_districts
    from vn_admin_units.reconcile import (match_districts, sparql_vn_districts, attach_parent_codes,
                                          load_district_seed, apply_district_seed,
                                          write_district_mapping, wd_search, wd_country)
    ents, _ = build_districts("data/raw/crosswalk")
    code_qid, qid_code = _province_qid_maps("mappings/provinces-history-qid.csv",
                                            "mappings/provinces-qid.csv")
    _fill_parent_qids(ents, code_qid)                    # so province is a real weak tiebreak
    cands = attach_parent_codes(sparql_vn_districts(), qid_code)   # candidate parent_qid → GSO code
    ents = match_districts(ents, cands, search_fn=wd_search, verify_fn=wd_country)  # fallback before 'new'
    ents = apply_district_seed(ents, load_district_seed())
    write_district_mapping(ents)
    print(f"reconciled {sum(1 for e in ents if e.wikidata_qid)}/{len(ents)} -> mappings/districts-qid.csv")


# `cache_decrees()` (writes data/raw/nghidinh.json) lives in crosscheck_decrees.py (D6.5) —
# run it manually to refresh the cached Nghị định records the offline build reads.


# ── Offline assemble + emit — safe as a regression gate (no network) ──
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
    # build hard-fails until Step 4 fills the confirmed URL (F2). ~696 abolition statements ride on it.
    ABOLITION_REF = ""    # <- set to the confirmed two-tier-reform resolution URL in Step 4
    if not ABOLITION_REF or ABOLITION_REF == NSO_SOURCE_URL or not ABOLITION_REF.startswith("http"):
        raise SystemExit("ABOLITION_REF unset/placeholder: set it to the confirmed two-tier-reform "
                         "resolution URL (design §Emit — never the NSO root) before emitting.")

    ents, edges = build_districts("data/raw/crosswalk")
    # BLOCKING residue (F2): a dissolve whose true date couldn't be recovered was NOT guessed —
    # fail before any artifact rather than ship a stale P576/P585. Recover it (curate the decree /
    # extend `_STRUCT`) and rebuild.
    residue = getattr(build_districts, "residue", [])
    blocking = [r for r in residue if r[0] == "dissolve-date-unrecovered"]
    if blocking:
        raise SystemExit(f"DISSOLVE-DATE GATE: {len(blocking)} dissolves have no recovered date "
                         f"(never guessed). Make the decree RECORD findable: re-cache "
                         f"data/raw/nghidinh.json (cache_decrees) / extend _STRUCT / fix name "
                         f"matching, then rebuild. First: {blocking[0][1].get('name_from')}")
    # MERGE-TARGET GATE (hard): a dissolve whose successor couldn't be paired is blocking — curate
    # data/district-merge-targets.json ({dissolved_local_id: successor_local_id}) to clear it.
    unlinked = [r for r in residue if r[0] == "merge-target-unresolved"]
    if unlinked:
        raise SystemExit(f"MERGE-TARGET GATE: {len(unlinked)} dissolutions have no resolved "
                         f"successor. Add {{dissolved_local_id: successor_local_id}} entries to "
                         f"data/district-merge-targets.json (see data/district-residue.json), then "
                         f"rebuild. First: {unlinked[0][1]['local_id']} ({unlinked[0][1]['name_from']})")
    code_qid, _ = _province_qid_maps("mappings/provinces-history-qid.csv", "mappings/provinces-qid.csv")
    _fill_parent_qids(ents, code_qid)                        # P131 province QIDs (dependency §1)
    # Apply EVERY reconciled QID (matched/verified/manual) so live results reach emit (F1) —
    # NOT just the human-locked seed. Upload stays gated on the audit.
    ents = apply_district_seed(ents, load_district_mapping())
    # Pre-emit COMPLETENESS gate (F1): a district with no QID emits NOTHING and its lineage edges
    # are silently dropped, so an incomplete artifact must not pass. Fail unless every unresolved
    # district is an explicitly acknowledged create-later gap (match_status='gap'). Write the full
    # gap list for review; resolve via reconcile_districts_live or mark genuine no-item gaps 'gap'.
    ack = load_acknowledged_gaps()
    gaps = [e for e in ents if not e.wikidata_qid]
    unresolved = [e for e in gaps if e.local_id not in ack]
    if gaps:
        DATA.mkdir(exist_ok=True)
        (DATA / "district-gaps.json").write_text(
            json.dumps([e.to_dict() for e in gaps], ensure_ascii=False, indent=2), encoding="utf-8")
    if unresolved:
        raise SystemExit(f"COMPLETENESS GATE: {len(unresolved)} districts have no QID and are not "
                         f"acknowledged gaps (match_status='gap') — they would emit NOTHING and drop "
                         f"their lineage. Run reconcile_districts_live, or mark genuine no-item gaps "
                         f"'gap' in mappings/districts-qid.csv. See data/district-gaps.json. "
                         f"First: {unresolved[0].name_vi}")
    qs = emit_district_quickstatements(ents, edges, default_ref_url=NSO_SOURCE_URL, abolition_ref=ABOLITION_REF)
    # Emit gate (Findings 3 + F2) — HARD FAIL before ANY artifact is written: every event-driven
    # statement (succession / separation / pre-abolition dissolution / inception / dated P131 /
    # dated P31) MUST carry a real establishing-resolution decree URL — not missing, not 'nan',
    # not the generic NSO root. Curate the offenders' decrees into data/decree-urls.json and rebuild.
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
    S854 reference is NOT a real URL. Covered: succession/separation (P7888/P1366/P1365/P807),
    ALL dissolution incl. the universal 2025 abolition (P576 — design §Emit requires the reform
    resolution, NOT the NSO root; F2), inception (P571), and any DATED P131/P31 span (P580/P582 —
    a re-parenting / creation / retype event). A reference is bad if missing, empty, the literal
    'nan' (F1), the generic `root_url`, or not an http(s) URL. EXEMPT only: a bare baseline P131
    (no date qualifier — the NSO source is legitimate for pre-floor province membership). Empty
    result == every event traceable to a real establishing URL."""
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
```

> Note: 1a's `provinces-qid.csv` is keyed by 2-digit **terminal** province code (`gso_code`) and 1b's `provinces-history-qid.csv` by `terminal_code`; a district's early `parent_span` code (e.g. `28` Hà Tây) resolves via the 1b history mapping, its late code (`01` Hà Nội) via 1a. Pre-2004 3-digit province codes are below the district event floor and won't appear in `parent_spans`.

- [ ] **Step 2: Write the integration test** (append to `tests/test_pipeline.py`)

```python
def test_district_pipeline_offline_guards():
    # OFFLINE: build the graph + emit directly (no network). Synthetic QIDs make the emit
    # deterministic without touching Wikidata; the live path (reconcile_districts_live) is
    # exercised manually, never in the suite (2026-07-15 open-question fix).
    from vn_admin_units.district_model import build_districts
    from vn_admin_units.emit import emit_district_quickstatements
    ents, edges = build_districts("data/raw/crosswalk")
    # F3/F2: with the cached decrees + curated overrides committed, no dissolve is left dateless
    # (masquerading as a 2025 abolition) and every merger has a resolved successor — both are
    # hard-gated in build_districts_all, so the committed data state must produce neither residue.
    _res = getattr(build_districts, "residue", [])
    assert not [r for r in _res if r[0] == "dissolve-date-unrecovered"], \
        "unrecovered dissolve dates — cache data/raw/nghidinh.json (D6.5) before this test"
    assert not [r for r in _res if r[0] == "merge-target-unresolved"], \
        "unresolved merge successors — curate data/district-merge-targets.json"
    assert 690 <= len([e for e in ents if e.valid_to == "2025-06-30"]) <= 700     # count guard
    for i, e in enumerate(ents):                                                  # deterministic QIDs
        e.wikidata_qid, e.qid_status = f"Q{1000 + i}", "existing"
        for sp in e.parent_spans:                                                 # synthetic province QIDs so
            sp["qid"] = f"QP{sp['code']}"                                         # P131 is EMITTED (else skipped)
    qs = emit_district_quickstatements(ents, edges, default_ref_url="https://nso.example/",
                                       abolition_ref="https://reform.example/resolution")
    lines = qs.splitlines()
    assert lines, "no statements emitted"
    assert any("\tP576\t+2025-07-01T00:00:00Z/11" in l for l in lines)            # universal abolition
    for line in lines:
        p = line.split("\t")
        if len(p) >= 3 and p[1] in {"P7888", "P1366", "P1365", "P807"}:
            assert p[0] != p[2], f"self-referential: {line}"                      # no self-edges
        assert ("S854" in line or "S248" in line), f"unreferenced statement: {line}"
    # The REAL reference gate over the WHOLE emitted graph (not just sampled cases): passing
    # "https://nso.example/" as the root means any event statement left on the default (i.e. whose
    # decree lacked a URL) is flagged. With parent-span QIDs filled above, this now covers dated
    # P131 (re-parenting/creation) too — not just succession/P571/P31. Same check D11 Step 4 runs on
    # the live build, so a missing decree URL fails HERE in the suite (Step 3), not only in Step 4.
    from vn_admin_units.cli import event_statements_missing_reference
    assert event_statements_missing_reference(qs, "https://nso.example/") == [], \
        "event statements missing a real decree reference — curate data/decree-urls.json"

def test_event_ref_gate_requires_url_for_all_events_exempts_only_baseline_p131():
    from vn_admin_units.cli import event_statements_missing_reference
    root = "https://nso/"
    qs = "\n".join([
        f'Q1\tP1365\tQ2\tP585\t+2013-12-28T00:00:00Z/11\tS854\t"{root}"',        # succession on root -> BAD
        'Q1\tP571\t+2013-12-28T00:00:00Z/11\tS854\t"nan"',                        # inception, 'nan' ref -> BAD
        'Q7\tP807\tQ8\tS854\t""',                                                 # carve, empty ref -> BAD
        f'Q1\tP131\tQ9\tP580\t+2008-08-01T00:00:00Z/11\tS854\t"{root}"',          # dated (re-parent) P131 -> BAD
        f'Q2\tP576\t+2025-07-01T00:00:00Z/11\tS854\t"{root}"',                    # abolition on ROOT -> BAD (F2)
        'Q6\tP576\t+2025-07-01T00:00:00Z/11\tS854\t"https://reform/nq"',          # abolition w/ reform URL -> OK
        f'Q5\tP131\tQ9\tS854\t"{root}"',                                          # bare baseline P131 -> exempt
        'Q3\tP807\tQ4\tS854\t"https://vb/125"',                                   # carve w/ decree -> OK
    ])
    bad = event_statements_missing_reference(qs, root)
    assert len(bad) == 5
    assert any(b.startswith("Q2\t") and "\tP576\t+2025-07-01" in b for b in bad)  # root-referenced abolition flagged
    assert 'S854\t"https://reform/nq"' not in "\n".join(bad)         # abolition w/ real reform URL passes
    assert 'S854\t"https://vb/125"' not in "\n".join(bad)            # a real decree URL passes
    assert not any(b.startswith("Q5\t") for b in bad)                # bare baseline P131 exempt
```

> **The live path is never in the suite.** `test_district_pipeline_offline_guards` calls `build_districts` + `emit_district_quickstatements` directly (no SPARQL, no decree fetch). The offline `cli.build_districts_all` is exercised via its artifacts in Step 4; the networked `reconcile_districts_live` / `cache_decrees` are manual commands. This keeps `pytest` deterministic and offline (open-question fix). Note the D7 date assertions require the cached `data/raw/nghidinh.json` (produced by `cache_decrees`, D6.5) to be present.

- [ ] **Step 3: Run the full suite (regression gate)**

Run: `uv run pytest -q 2>&1 | tail -3`
Expected: all PASS — the 66 Movement-A tests + all Phase-2 tests, none regressed.

- [ ] **Step 4: Refresh the live mapping, then generate artifacts + confirm the abolition reference**

First the two networked commands (manual — not in the suite): cache the decrees (if not already done in D6.5 Step 5) and refresh the QID mapping:
Run: `uv run python -c "from vn_admin_units.crosscheck_decrees import cache_decrees; cache_decrees()"`
Run: `uv run python -c "from vn_admin_units.cli import reconcile_districts_live; reconcile_districts_live()"`
Then confirm the exact two-tier-reform instrument that abolished the district tier on 2025-07-01 (the National Assembly resolution / the amended Law on Local Government Organization). **Set `ABOLITION_REF` in `cli.build_districts_all` to that confirmed resolution URL** — it starts empty and the build refuses to run until you do (the ~696 abolition `P576` statements reference it; design §Emit forbids the NSO root, F2). Then run the OFFLINE build:
Run: `uv run python -c "from vn_admin_units.cli import build_districts_all; build_districts_all()"`
Expected: `built ~700 districts, N lineage edges`. The build **HARD-FAILS** (SystemExit, no artifacts) on any of: an unset/root `ABOLITION_REF` (F2); a `dissolve-date-unrecovered` — re-cache `data/raw/nghidinh.json` / extend `_STRUCT` to make the decree record findable (**not** `data/decree-urls.json`); a `merge-target-unresolved` — the **merge-target gate**, F2 (curate `{dissolved_local_id: successor_local_id}` into `data/district-merge-targets.json`); a district with no QID that isn't an acknowledged `gap` — the **completeness gate**, F1 (resolve via `reconcile_districts_live` or mark genuine no-item gaps `gap`; see `data/district-gaps.json`); or an event statement whose reference is missing/`nan`/non-URL/the NSO root (**reference gate**, curate `data/decree-urls.json`). In practice all of these are already cleared in **D7** — this offline build should pass first try. Rerun until it succeeds.

- [ ] **Step 5: Manual spot-check `statements/na-districts.qs`** — confirm:
  - Từ Liêm split: `Q<Từ Liêm> P576 +2013-12-28…`; `Q<Nam>/<Bắc> P571 +2013-12-28`, `P1365 → Q<Từ Liêm>`; no `P576 +2025-07-01` on Từ Liêm.
  - Nông Sơn: `P571 +2008-04-23` **and** a `P576` at its dissolution date (one entity, both bounds).
  - Hà Tây districts (Ba Vì …): two `P131` statements — old parent `Q<Hà Tây> … P582 +2008-07-31`, new parent `Q<Hà Nội> … P580 +2008-08-01`; **no `P576` at 2008** (re-parenting persists).
  - Carve-outs (Ba Đồn ← Quảng Trạch): `P807 → parent`, `P571`; **no `P576` on the persisting parent** at the carve date.
  - Universal abolition: `P576 +2025-07-01` on every survivor, referenced to the **confirmed reform resolution** (not the NSO root); no successor on those.
  - Every line carries `S854` (or `S248`); no self-referential `Pxxx Qx Qx`.
  - **Reference gate (F2/F3):** the build HARD-FAILS if any event statement — succession/separation, dissolution incl. the 2025 abolition, inception, or a dated `P131`/`P31` — lacks a real establishing URL, so a *successful* build already guarantees this. Confirm `data/decree-urls.json` curation is complete and no gate exit occurred.
  - **Completeness gate (F1):** the build HARD-FAILS on any district lacking a QID that isn't an acknowledged `gap`, so a successful build emitted every reconciled district. Review `data/district-gaps.json`; every genuine no-item gap is `match_status='gap'` (create-later), everything else resolved.
  - **Merge-target gate (F2):** the build HARD-FAILS if any merger's successor is unresolved, so a successful build already paired every dissolve. For each `merge-target-unresolved` in `data/district-residue.json`, add a `{dissolved_local_id: successor_local_id}` entry to `data/district-merge-targets.json` (the curation escape) and rebuild until the gate clears. Curate during **D7** (below), not here — D11 Step 3's suite already asserts the residue is empty.
  - Run `reconcile.audit_district_qids()` → resolve all returned issues (`UNRESOLVED`/`TYPE`/`LABEL`); the informational `GAP …` log lines are reviewed create-later gaps (`match_status='gap'`), NOT issues — the returned list is clean once acknowledged gaps are the only QID-less rows. Confirm no false `new` gaps (the `wbsearchentities` fallback ran during `reconcile_districts_live`). Run the D10 constraints gate → all combos OK + district `P31` targets confirmed.
  - **Do not upload** — emission only; upload is a separate reviewed step (personal WD account) after the audit + constraints gates pass.

- [ ] **Step 6: Commit**

```bash
git add src/vn_admin_units/cli.py tests/test_pipeline.py data/districts.json data/district-lineage.json data/district-gaps.json data/district-merge-targets.json statements/na-districts.qs mappings/districts-qid.csv data/decree-urls.json
git commit -m "feat(phase2): wire district pipeline; emit 2004-2025 lineage + 2025 abolition"
```

---

## Deferred / out of scope (explicit)

- **Upload** the batch (separate reviewed step; after the audit + constraints gates).
- **Phase-1a reference backfill** (design §3) — its own follow-up plan (per the scope decision for this plan).
- **Pre-2004 ancestry** (event floor) — Phase 4 / non-GSO sources.
- **Boundary-only adjustments** ("điều chỉnh địa giới … để mở rộng …" with no identity change) — not lineage events; the decree cross-check confirmed they legitimately don't appear in the diff.
- **Goal A** (district-composed NA11–NA15 electoral-unit exports) — a later build on this graph.
- **Ward re-parenting** at the 2025 abolition — Phase 3.
- **Name-disambiguation residue** → `data/district-residue.json` (logged, never silent).
- **Yearly-window blind spot** (same-unit-twice / create-and-dissolve within a year) — accepted risk; the decree cross-check (147 structural decrees, no real miss — journal `2026-07-13.02`) is the compensating control. Event-driven windows stay deferred to Phase 3.

## Self-review notes

- **Spec coverage (`DESIGN-phase2.md`):** tier-neutral core refactor §2 → Movement A (R1–R4); district `Ghi Chú` sibling parser §Lineage/§2 → D1; province-aware folding §Reconciliation → D2; model + `local_id`/collision §Data model → D3; authoritative decree source §Decisions 6 / §3 → D4; dissolve-date + reference recovery §Decisions 6 / §Emit → D6.5; event discovery incl. re-parenting §Graph assembly → D5; bucketing + carve/split discriminator §Lineage steps 2&5 / §5 → D6; assembly + cross-validation + residue §Graph assembly / §Testing → D7; bulk-SPARQL province-weak reconciliation + audit §Reconciliation / §4 → D8; relation-aware emit (P576-on-end, P807, dated P131, abolition) §Emit → D9; constraints extension §Emit / §Dependencies → D10; wiring + regression-guarded integration → D11.
- **Review findings (design §Dependencies & risks) baked in:** §1 Phase-1b dependency → `_fill_parent_qids` from the 1b mapping + emit skips unresolved province QIDs (D9/D11); §2 "extend = rewrite" → the whole of Movement A + a sibling `district_model`/`ghichu` (D1/D3–D7); §3 1a backfill → explicitly deferred; §4 stale WD `P131` → province is a weak tiebreak, name match kept (D8); §5 carve/split discriminator stated as an algorithm (D6/D7); §6 yearly blind spot → cross-check recorded as the compensating control (Out of scope).
- **2026-07-15 plan-review findings baked in:** (F1) dissolve-date recovery is a real, test-gated task (D6.5) with the D7 date assertion enabled — no more stale `base_hieu_luc` in `P576`/`P585`; (F2) `decree_for` matches source/alias names on ambiguous multi-decree dates, not just the successor label, and its fixture now carries two decrees on the split date; (F3) `decree_for`/edges carry a decree `url` and `build_districts_all` **hard-fails** (SystemExit, no artifacts) if any event statement lacks a real decree URL (`event_statements_missing_reference`) — we always require a decree URL; (F4) reconciliation indexes candidate + entity aliases and runs a verified `wbsearchentities` fallback before writing `qid_status="new"`; (F5) DESIGN §Emit `absorbed_into` wording corrected (predecessor ends → `P576`; the survivor/absorber persists); (open Q) the live Wikidata path is split into manual `reconcile_districts_live`/`cache_decrees` — the suite builds+emits offline with injected fns and synthetic QIDs.
- **2026-07-15 second-pass fixes:** (F1) `district_model` imports `json`/`Path` at module level (the `_load_cached_decrees` `NameError` is gone; the local `import json` shim dropped); (F2) dissolve-date recovery uses `years={year, year+1}` (base + compare — a 2024→2025 window carries 2025 effective dates), and the Nông Sơn ground-truth now pins `"2024-01-01" <= valid_to < "2025-06-30"` + a referenced edge instead of the too-loose `< 2025-06-30`; (F3-precision) `decrees_naming` gates on the validated `is_district_structural` object-level classifier (excludes `chia xã … thuộc huyện X` commune ops) rather than a verb-anywhere check; (F4/hard-fail) the reference gate is a `SystemExit` before artifact write, per the "always want a URL" rule.
- **2026-07-15 third-pass fixes:** (F1) the offline build applies `load_district_mapping` (ALL QID rows: matched/verified/manual) so `reconcile_districts_live`'s auto-matches reach emit, and `write_district_mapping` preserves the prior status of any resolved row (a rebuild never downgrades `matched`→`needs-lookup` or drops a QID); (F2) establishing references now cover **every** event statement — `P571` (creation decree, stamped on `type_spans[0]` by `_mint` for edge-less plain creations), dated `P131` (re-parenting/creation decree, stamped on both parent spans), and retype `P31` — and the gate hard-fails all of them while exempting the abolition P576 and bare baseline P131; (F3) the district-type audit no longer accepts `ward`-typed items (a lower tier — a ward match to a district is wrong).
- **2026-07-15 fourth-pass fixes:** (F1) a shared `_clean_url` normalizes pandas' `'nan'`/`'none'` URL cells to `""` in `cache_decrees`/`decree_index`/`decrees_naming` and at the `build_districts` merge (so curated overrides actually apply), and the reference gate — renamed `event_statements_missing_reference` — now rejects a reference that is missing, empty, `'nan'`, non-http, or the NSO root (not just the root); (F2) an unrecovered dissolve date is **blocking**: `_apply_dissolve` mutates nothing and emits no edge (never a guessed date), and `build_districts_all` hard-fails on `dissolve-date-unrecovered` residue before artifacts; (F3) `founding_ref` for `P571` is populated only from minting relations (`split`/`carved_from`), so a later `merged_into`/`absorbed_into` decree can't become an in-era district's inception reference.
- **2026-07-15 fifth-pass fixes:** (F1) a pre-emit **completeness gate** in `build_districts_all` hard-fails if any district lacks a QID that isn't an acknowledged `gap` (`load_acknowledged_gaps`) — a QID-less district emits nothing and drops its lineage, so the incomplete artifact can no longer pass silently; `write_district_mapping` preserves a `gap` acknowledgment across rebuilds and `data/district-gaps.json` reports every gap; (F2) `ABOLITION_REF` starts empty and the build refuses to run until it's a confirmed non-root URL, and the reference gate no longer exempts the abolition `P576` — every `P576` (incl. 2025-07-01) must cite a real establishing URL (design §Emit); (F3) an unrecovered dissolve now sets `valid_to=None` so it can't masquerade as a 2025 abolition in the direct build/test path, and the offline test asserts no `dissolve-date-unrecovered` residue.
- **2026-07-15 sixth-pass fix:** `audit_district_qids` now reconciles with the completeness gate — a QID-less row marked `match_status='gap'` is reported as an informational `GAP …` log line, NOT an `UNRESOLVED` returned issue, so "resolve all issues" can go clean while acknowledged create-later gaps remain; only un-triaged QID-less rows are `UNRESOLVED`. Offline-testable (a QID-less mapping triggers no WD calls).
- **2026-07-15 seventh-pass fixes:** (F1) `_apply_retype` stamps the retype decree on BOTH the closed old span and the new span, so the old-span dated `P31 … P582` cites the decree instead of the NSO root (which the gate would now block); test asserts both retype `P31` lines carry the decree. (F2) a merger with an unresolvable successor is now a **hard gate** in `build_districts_all` (per follow-up direction), cleared by curating `data/district-merge-targets.json` (`{dissolved_local_id: successor_local_id}`) which `_apply_dissolve` consults after prose resolution; the entity-stamped `e.dissolution` remains a defensive net so a non-gated direct build still emits the `P576` rather than dropping it, and the offline test asserts zero `merge-target-unresolved` residue. (F3-doc) the D8 live instruction no longer says genuine gaps "stay needs-lookup" — they must be marked `match_status='gap'` per the completeness gate/audit.
- **2026-07-16 twelfth-pass fix:** `test_district_pipeline_offline_guards` now fills each `parent_span["qid"]` with a synthetic province QID before emitting, so `P131` statements are actually produced (the emitter skips a span with no QID) and the whole-graph reference gate covers **dated `P131`** (re-parenting/creation) too — matching production `build_districts_all`, which fills parent QIDs before emit. Previously a missing dated-`P131` reference could pass Step 3 and fail only in Step 4.
- **2026-07-16 eleventh-pass fixes:** (F1) `test_district_pipeline_offline_guards` now runs the REAL `event_statements_missing_reference` over the whole emitted batch (root=`https://nso.example/`), so a missing decree reference anywhere in the graph fails in the Step-3 suite, not only in the D11 Step-4 live build; the D7 reference bullet now says D7 curates the sampled cases and D11's offline test enforces whole-graph completeness. (F2) two stale "`decree-urls.json` for dates" comments corrected — `test_no_blocking_residue`'s comment and the ninth-pass note now scope `decree-urls.json` to references, with dates recovered via `nghidinh.json`/`_STRUCT`.
- **2026-07-16 tenth-pass fixes:** (F1) the `dissolve-date-unrecovered` fix-text no longer points to `data/decree-urls.json` (which only attaches a URL to an already-found record) — it now points to making the decree RECORD findable: re-cache `data/raw/nghidinh.json` / extend `_STRUCT` / fix name-alias matching. `data/decree-urls.json` is scoped to *missing-reference* failures (the reference gate + D7's non-empty merge-edge `reference_url` assertion). Corrected in the D7 Step 4 bullets, iteration note (d), the D11 dissolve-date gate message, and the D11 Step 4 hard-fail list. (F2) the D7 commit now stages `data/decree-urls.json` too — D7 curates it and its ground-truth asserts merge edges carry a reference, so a green D7 must not depend on an uncommitted override.
- **2026-07-16 ninth-pass fixes:** (F1-sequencing) the two blocking residue kinds are now curated in **D7** — a new `test_no_blocking_residue` (D7 Step 5) fails until `data/district-merge-targets.json` (successors) and the recovered dates (`data/raw/nghidinh.json` / `_STRUCT`) are done, so D11 Step 3's suite (and its hard gates) are already satisfied; the D7 residue note no longer calls multi-op merge targets "accepted residue" (they're curated into the design's manual-curation file), and D7 commits the override file. (`data/decree-urls.json` is a separate D7 curation for the reference gate — see the tenth-pass note.) (F2) the `data/district-merge-targets.json` value is the successor's stable **`local_id`** (not a code that could be recoded after the merger); `_apply_dissolve` resolves it by entity identity among live `ents`, while prose resolution keeps its event-time-code path.
- **2026-07-15 eighth-pass fixes:** (F1) the four district `P31` targets are registered as placeholders in **R1** (not first added in D10), so the D9 emitter resolves them and its retype `P31` test actually passes as ordered; D10 now *confirms/corrects* them via `describe_items` rather than registering them. (F2) `write_district_mapping` no longer keeps `match_status='gap'` on a row that has since acquired a QID — a resolved row keeps only `verified`/`manual`/`matched`, else `matched`. (F3-doc) the D9 `P576` rule text is corrected: the `P576` value is the event date = `valid_to` + 1 (`valid_to` is the last in-force day), not `valid_to` itself.
- **Type consistency:** `core.Entity`/`LineageEdge` (superset) used by all tiers; `District(...)` → `Entity`; `dist_local_id`; `window_events`/`classify_change`/`unit_tier`; `group_by_event`/`source_survives`/`resolve_merge_target`; `build_districts` → `(entities, edges)`; `match_districts`/`load_district_mapping`/`load_acknowledged_gaps`/`write_district_mapping`/`audit_district_qids`; `emit_district_quickstatements(entities, edges, default_ref_url, abolition_ref)`; `event_statements_missing_reference`; `predecessor_ends`/`p31_target` — names identical across tasks.
- **Refactor safety:** each of R1–R4 ends on the full suite green (regression gate); R4 additionally proves `mappings/` is byte-stable (the artifact that matters for upload). The one intentional deviation — `entities.json`/`province-history-lineage.json` gain default keys — is called out where it happens.
- **Data-dependent iteration (house style):** D7 is gated by `tests/test_district_groundtruth.py` + the roster-delta cross-validation; extend the assembly against the real windows until green, never weaken assertions; unresolvable rows go to `data/district-residue.json`.
- **Confirmation gates that block emit:** the district `P31` target QIDs (D10 `describe_items`) and the 2025 abolition reference (D11 Step 4) are placeholders until confirmed live — the plan makes both mandatory before upload, mirroring how Phase 1b caught its wrong `P31` placeholders.

