"""Resumable rescue cache for authoritative GSO/NSO ward SOAP snapshots.

The ward crosswalk omits ``MaQuanHuyen``. These ``DanhMucPhuongXa`` snapshots
are therefore required both for point-in-time membership and for resolving
duplicate pre-reform ward names within their former districts.

Examples:
  # Show/fetch the five highest-priority 2025/2026 snapshots.
  uv run python -m vn_admin_units.ward_rescue --dry-run
  uv run python -m vn_admin_units.ward_rescue

  # Reviewed history: annual anchors plus effective-date snapshots.
  uv run python -m vn_admin_units.ward_rescue --scope history --dry-run
  uv run python -m vn_admin_units.ward_rescue --scope history

  # Emergency ceiling: add the day before every legal event.
  uv run python -m vn_admin_units.ward_rescue --scope history-bracketed --dry-run
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable

from vn_admin_units import rawcache
from vn_admin_units.crosscheck_decrees import is_ward_structural
from vn_admin_units.soap import TIERS, URL as SOAP_URL, fetch_units_raw, parse_rows


LEGAL_INDEX = Path("data/raw/nghidinh.json")

# Ordered for a brief recovery window: preserve the core 2025 reform first,
# then the known 2026 Đồng Nai boundary, then the current roster.
CRITICAL_BOUNDARIES = (
    (date(2025, 6, 30), "pre-2025 reform roster"),
    (date(2025, 7, 1), "post-2025 reform roster"),
    (date(2026, 4, 29), "pre-2026 Đồng Nai event roster"),
    (date(2026, 4, 30), "post-2026 Đồng Nai event roster"),
)


@dataclass(frozen=True)
class SnapshotRequest:
    snapshot_date: date
    reasons: tuple[str, ...]

    @property
    def dmy(self) -> str:
        return self.snapshot_date.strftime("%d/%m/%Y")

    @property
    def iso(self) -> str:
        return self.snapshot_date.isoformat()

    @property
    def relpath(self) -> str:
        return f"soap/DanhMucPhuongXa_{self.iso}.xml.gz"

    @property
    def legacy_relpath(self) -> str:
        return f"soap/DanhMucPhuongXa_{self.iso}.xml"


def parse_dmy(value: str) -> date:
    return datetime.strptime(value, "%d/%m/%Y").date()


def load_legal_records(path: Path = LEGAL_INDEX) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def is_ward_relevant(record: dict) -> bool:
    """Legal-index filter for an instrument explicitly affecting ward units."""
    return is_ward_structural(str(record.get("noi_dung", "")))


def _add_reason(planned: dict[date, list[str]], when: date, reason: str, today: date) -> None:
    if when <= today:
        reasons = planned.setdefault(when, [])
        if reason not in reasons:
            reasons.append(reason)


def build_plan(records: Iterable[dict] = (), scope: str = "critical",
               today: date | None = None) -> list[SnapshotRequest]:
    """Build a priority-ordered critical or historical acquisition plan.

    ``history`` requests each reviewed effective date once. Consecutive event
    snapshots naturally bracket later events, avoiding a redundant day-before
    request for every instrument. ``history-bracketed`` retains that expensive
    high-recall ceiling for diagnosing an incomplete or ambiguous legal index.
    """
    if scope not in {"critical", "history", "history-bracketed"}:
        raise ValueError(f"unknown rescue scope: {scope}")
    today = today or date.today()
    planned: dict[date, list[str]] = {}
    priority: list[date] = []

    for when, reason in CRITICAL_BOUNDARIES:
        if when <= today:
            _add_reason(planned, when, reason, today)
            priority.append(when)
    _add_reason(planned, today, "current roster", today)
    priority.append(today)

    if scope in {"history", "history-bracketed"}:
        for when, reason in (
            (date(2002, 1, 1), "GSO source-floor anchor"),
            (date(2004, 1, 1), "pre-2004 code-transition anchor"),
            (date(2004, 7, 1), "post-2004 code-transition anchor"),
            (date(2005, 1, 1), "post-transition baseline"),
        ):
            _add_reason(planned, when, reason, today)

        for year in range(2005, today.year + 1):
            _add_reason(planned, date(year, 1, 1), "annual audit anchor", today)

        for record in records:
            if not is_ward_relevant(record):
                continue
            try:
                effective = parse_dmy(str(record["hieu_luc"]))
            except (KeyError, TypeError, ValueError):
                continue
            if effective.year < 2005 or effective > today:
                continue
            code = str(record.get("code", "unknown instrument"))
            if scope == "history-bracketed":
                _add_reason(planned, effective - timedelta(days=1), f"pre-event: {code}", today)
            _add_reason(planned, effective, f"effective event: {code}", today)

    ordered = []
    seen = set()
    for when in (*priority, *sorted(planned)):
        if when not in seen:
            seen.add(when)
            ordered.append(SnapshotRequest(when, tuple(planned[when])))
    return ordered


def explicit_plan(values: Iterable[str]) -> list[SnapshotRequest]:
    seen = set()
    out = []
    for value in values:
        when = parse_dmy(value)
        if when not in seen:
            seen.add(when)
            out.append(SnapshotRequest(when, ("explicit request",)))
    return out


def roster_metrics(rows: list[dict]) -> dict:
    """Return identity and duplicate metrics for one parsed ward roster."""
    identity_keys = [
        (row["MaTinh"], row["MaQuanHuyen"], row["MaPhuongXa"])
        for row in rows
    ]
    exact_rows = [tuple(row.get(field, "") for field in TIERS["ward"][1]) for row in rows]
    duplicate_identity_rows = len(rows) - len(set(identity_keys))
    duplicate_rows = len(rows) - len(set(exact_rows))
    return {
        "rows": len(rows),
        "distinct_codes": len({row["MaPhuongXa"] for row in rows}),
        "distinct_identity_keys": len(set(identity_keys)),
        "duplicate_identity_rows": duplicate_identity_rows,
        "duplicate_rows": duplicate_rows,
        "conflicting_identity_rows": duplicate_identity_rows - duplicate_rows,
        "missing_parent_codes": sum(not row["MaQuanHuyen"] for row in rows),
        "parent_pairs": len({(row["MaTinh"], row["MaQuanHuyen"]) for row in rows}),
    }


def cache_snapshot(request: SnapshotRequest, *, max_attempts: int = 5,
                   base_delay: float = 2.0, timeout: int = 180, force: bool = False,
                   fetcher: Callable | None = None, sleeper: Callable[[float], None] = time.sleep
                   ) -> str:
    """Fetch, validate, and manifest one ward snapshot; return cached/fetched."""
    if not force:
        if rawcache.raw_is_verified(request.relpath):
            return "cached"
        if rawcache.raw_is_verified(request.legacy_relpath):
            rawcache.migrate_raw_to_gzip(request.legacy_relpath)
            return "compressed"
    fetcher = fetcher or fetch_units_raw
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            content = fetcher("ward", request.dmy, timeout=timeout)
            if isinstance(content, str):
                content = content.encode("utf-8")
            rows = parse_rows(content.decode("utf-8"), TIERS["ward"][1])
            if not rows:
                raise ValueError("SOAP response contained no ward rows")
            rawcache.save_raw_gzip(request.relpath, content, {
                "source_url": SOAP_URL,
                "method": "DanhMucPhuongXa",
                "params": {"DenNgay": request.dmy, "Tinh": "", "QuanHuyen": ""},
                **roster_metrics(rows),
                "reasons": list(request.reasons),
            })
            return "fetched"
        except Exception as exc:  # network/parser failures share the same retry policy
            last_error = exc
            if attempt < max_attempts:
                sleeper(base_delay * (2 ** (attempt - 1)))
    raise RuntimeError(
        f"failed {request.dmy} after {max_attempts} attempt(s): {last_error}"
    ) from last_error


def print_checklist(plan: list[SnapshotRequest]) -> None:
    statuses = [(item, rawcache.raw_is_verified(item.relpath)) for item in plan]
    verified = sum(is_verified for _, is_verified in statuses)
    print(f"Ward snapshot rescue checklist: {len(plan)} dates "
          f"({verified} verified, {len(plan) - verified} missing)")
    for item, is_verified in statuses:
        status = "VERIFIED" if is_verified else "MISSING"
        print(f"  {status:8} {item.dmy}  {item.relpath}  {'; '.join(item.reasons)}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Rescue-cache exact DanhMucPhuongXa SOAP snapshots with resume + retries.")
    parser.add_argument(
        "--scope", choices=("critical", "history", "history-bracketed"),
        default="critical",
        help=("critical (default); reviewed event-date history; or emergency "
              "history-bracketed with an extra pre-event date"),
    )
    parser.add_argument("--date", action="append", default=[], metavar="DD/MM/YYYY",
                        help="fetch an explicit date instead of a predefined scope; repeatable")
    parser.add_argument("--dry-run", action="store_true", help="print checklist without fetching")
    parser.add_argument("--limit", type=int, help="process only the first N priority dates")
    parser.add_argument("--max-attempts", type=int, default=5)
    parser.add_argument("--base-delay", type=float, default=2.0)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--force", action="store_true", help="refetch even if hash-verified")
    parser.add_argument("--continue-on-error", action="store_true",
                        help="try later dates after one snapshot exhausts its retries")
    parser.add_argument("--legal-index", type=Path, default=LEGAL_INDEX)
    args = parser.parse_args(argv)

    if args.max_attempts < 1:
        parser.error("--max-attempts must be at least 1")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")

    if args.date:
        plan = explicit_plan(args.date)
    else:
        records = load_legal_records(args.legal_index) if args.scope != "critical" else []
        plan = build_plan(records, args.scope)
    if args.limit:
        plan = plan[:args.limit]

    print_checklist(plan)
    if args.dry_run:
        return

    failures = []
    for index, request in enumerate(plan, 1):
        try:
            result = cache_snapshot(
                request, max_attempts=args.max_attempts, base_delay=args.base_delay,
                timeout=args.timeout, force=args.force)
            print(f"[{index}/{len(plan)}] {result:7} {request.dmy}")
        except RuntimeError as exc:
            failures.append(str(exc))
            print(f"[{index}/{len(plan)}] FAILED  {exc}")
            if not args.continue_on_error:
                print("Stopping after the first exhausted date; rerun will resume verified files.")
                break
    if failures:
        print(f"Rescue incomplete: {len(failures)} snapshot(s) failed; rerun resumes verified files.")
        raise SystemExit(1)
    print("Ward snapshot rescue complete.")


if __name__ == "__main__":
    main()
