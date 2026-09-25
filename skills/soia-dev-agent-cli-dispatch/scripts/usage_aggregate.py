#!/usr/bin/env python3
"""Aggregate local usage records into a non-sensitive per executor/model summary.

Summary format: `soia.dispatch.usage-summary/v1` (references/usage-records.md).

Examples:
  python3 usage_aggregate.py --since-days 30 --min-samples 3
  python3 usage_aggregate.py --records <records.jsonl> --task-class implement
  python3 usage_aggregate.py --since-days 30 --jev-state <state.txt>
  python3 usage_aggregate.py --selftest

Everything runs locally. The summary drops record ids, exact timestamps and
single-record detail. `--jev-state` writes a compact text state for
`jev_check.py`; it is scanned with the same outbound rules first and is not
written when the scan finds anything. The state is corroborating input for a
recommendation, never a dispatch, quota or permission gate.

Exit codes: 0 ok, 2 input error or outbound scan hit.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jev_check  # noqa: E402
import usage_record  # noqa: E402


SUMMARY_SCHEMA = "soia.dispatch.usage-summary/v1"
TOKEN_FIELDS = ("input_tokens", "cached_input_tokens", "cache_write_tokens", "output_tokens", "total_tokens")


def _parse_time(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def aggregate(
    records: Iterable[dict[str, Any]], *, now: dt.datetime | None = None, since_days: int | None = 30,
    min_samples: int = 3, recent_failures: int = 5, task_class: str | None = None,
) -> dict[str, Any]:
    now = now or dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(days=since_days) if since_days is not None else None
    groups: dict[tuple[str, str, bool], list[dict[str, Any]]] = collections.defaultdict(list)
    skipped_invalid = 0
    for record in records:
        try:
            usage_record.validate_record(record)
        except usage_record.RecordError:
            skipped_invalid += 1
            continue
        if task_class is not None and record.get("task_class") != task_class:
            continue
        if cutoff is not None and _parse_time(record["completed_at"]) < cutoff:
            continue
        verified = bool(record["model_verified"])
        model = record["actual_model"] if verified else record["requested_model"]
        groups[(record["executor"], model, verified)].append(record)

    rows = []
    for (executor, model, verified), items in sorted(groups.items()):
        items.sort(key=lambda item: item["completed_at"])
        outcomes = collections.Counter(item["outcome"] for item in items)
        decided = outcomes["passed"] + outcomes["failed"]
        failures = [item for item in items if item["outcome"] != "passed"][-recent_failures:]
        avg_tokens = {
            field: _mean([item[field] for item in items if isinstance(item.get(field), int)])
            for field in TOKEN_FIELDS
        }
        rows.append({
            "executor": executor,
            "model": model,
            "model_verified": verified,
            "samples": len(items),
            "low_sample": len(items) < min_samples,
            "outcomes": {key: outcomes[key] for key in ("passed", "failed", "blocked")},
            "success_rate": round(outcomes["passed"] / decided, 4) if decided else None,
            "blocked_rate": round(outcomes["blocked"] / len(items), 4),
            "acceptance_samples": sum(1 for item in items if item["outcome_basis"] == "acceptance"),
            "usage_samples": sum(1 for item in items if item["usage_status"] != "unavailable"),
            "avg_tokens": avg_tokens,
            "avg_estimated_api_equivalent_usd": _mean(
                [item["estimated_api_equivalent_usd"] for item in items if item.get("estimated_api_equivalent_usd") is not None]),
            "avg_provider_reported_cost_usd": _mean(
                [item["provider_reported_cost_usd"] for item in items if item.get("provider_reported_cost_usd") is not None]),
            "avg_duration_seconds": _mean([item["duration_seconds"] for item in items if item.get("duration_seconds") is not None]),
            "billing_classes": sorted({item["billing_class"] for item in items}),
            "recent_failure_categories": dict(sorted(collections.Counter(item["failure_category"] for item in failures).items())),
            "last_seen_date": items[-1]["completed_at"][:10],
        })
    return {
        "schema": SUMMARY_SCHEMA,
        "generated_on": now.strftime("%Y-%m-%d"),
        "window_days": since_days,
        "task_class": task_class,
        "min_samples": min_samples,
        "recent_failure_window": recent_failures,
        "skipped_invalid_records": skipped_invalid,
        "groups": rows,
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "na"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return str(round(value)) if abs(value) >= 1000 else f"{value:.4g}"
    return str(value)


def jev_state(summary: dict[str, Any]) -> str:
    """Compact, line-oriented text; only the fields Jev's recommendation reads."""
    lines = [
        "Local dispatch usage summary (aggregated; corroborating evidence only, not a quota or permission gate).",
        f"window_days={_fmt(summary['window_days'])} task_class={_fmt(summary['task_class'])} generated_on={summary['generated_on']}",
        "Columns: candidate | samples | low_sample | success_rate | blocked_rate | acceptance_samples | "
        "avg_in/cache_read/cache_write/out tokens | avg_api_equiv_usd | avg_reported_usd | billing | recent_failures",
    ]
    for row in summary["groups"]:
        tokens = row["avg_tokens"]
        token_text = "/".join(_fmt(tokens[field]) for field in ("input_tokens", "cached_input_tokens", "cache_write_tokens", "output_tokens"))
        failures = ",".join(f"{key}:{value}" for key, value in row["recent_failure_categories"].items()) or "none"
        candidate = f"{row['executor']}:{row['model']}" + ("" if row["model_verified"] else "(unverified)")
        lines.append(" | ".join([
            candidate, str(row["samples"]), _fmt(row["low_sample"]), _fmt(row["success_rate"]), _fmt(row["blocked_rate"]),
            str(row["acceptance_samples"]), token_text, _fmt(row["avg_estimated_api_equivalent_usd"]),
            _fmt(row["avg_provider_reported_cost_usd"]), ",".join(row["billing_classes"]), failures,
        ]))
    return "\n".join(lines) + "\n"


def write_jev_state(summary: dict[str, Any], path: Path, extra_patterns: list[str] | None = None) -> dict[str, Any]:
    text = jev_state(summary)
    hits = jev_check.scan_inputs(text, {}, extra_patterns)
    if any(pattern.search(text) for pattern in jev_check.LOCAL_PATH_PATTERNS):
        hits["local_path"] = hits.get("local_path", 0) + 1
    if hits:
        return {"status": "blocked_by_scan", "categories": hits}
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    return {"status": "ok", "bytes": len(text.encode("utf-8")), "groups": len(summary["groups"])}


def _load(path: Path) -> list[dict[str, Any]]:
    return list(usage_record.read_records(path))


# ---------------------------------------------------------------------------
# selftest
# ---------------------------------------------------------------------------


def _fixture_records() -> list[dict[str, Any]]:
    def rec(i: int, executor: str, model: str, status: str, *, day: int, verified: bool = True, cost: float | None = 0.01,
            task: str = "implement", outcome: str | None = None, basis_failure: str | None = None) -> dict[str, Any]:
        base = {
            "schema": usage_record.SCHEMA,
            "record_id": f"{i:016x}",
            "source": "run_manifest",
            "executor": executor,
            "task_class": task,
            "requested_model": model,
            "actual_model": model if verified else None,
            "actual_model_source": "cli_json" if verified else "unverified",
            "model_verified": verified,
            "billing_class": "metered_api" if executor == "dsh" else "subscription",
            "input_tokens": 100 * i, "cached_input_tokens": 10, "cache_write_tokens": 0, "output_tokens": 5, "total_tokens": 100 * i + 15,
            "usage_status": "measured", "usage_source": "fixture",
            "estimated_api_equivalent_usd": cost,
            "started_at": f"2026-09-{day:02d}T01:00:00Z", "completed_at": f"2026-09-{day:02d}T01:10:00Z", "duration_seconds": 600.0,
            "status": status,
        }
        base.update(usage_record._outcome_fields(status, outcome, basis_failure))
        usage_record.validate_record(base)
        return base

    return [
        rec(1, "dsh", "deepseek-flash", "passed", day=20),
        rec(2, "dsh", "deepseek-flash", "failed", day=21),
        rec(3, "dsh", "deepseek-flash", "blocked_quota", day=22),
        rec(4, "dsh", "deepseek-flash", "passed", day=23, cost=None),
        rec(5, "dsh", "deepseek-flash", "passed", day=24, outcome="failed"),  # acceptance rejected
        rec(6, "codex", "gpt-6-luna", "passed", day=24),
        rec(7, "codex", "gpt-6-luna", "actual_model_unverified", day=24, verified=False),
        rec(8, "codex", "gpt-6-luna", "passed", day=1),  # outside a 14-day window
        rec(9, "pi", "deepseek-flash", "timeout", day=24, task="review"),
    ]


def run_selftest() -> int:
    checks: list[tuple[str, bool]] = []

    def check(name: str, ok: bool) -> None:
        checks.append((name, bool(ok)))

    try:
        now = dt.datetime(2026, 9, 25, tzinfo=dt.timezone.utc)
        records = _fixture_records()
        summary = aggregate(records + [{"schema": "bogus"}], now=now, since_days=14, min_samples=3)
        groups = {(row["executor"], row["model"], row["model_verified"]): row for row in summary["groups"]}
        dsh = groups[("dsh", "deepseek-flash", True)]
        check("success rate excludes blocked from the denominator",
              dsh["samples"] == 5 and dsh["outcomes"] == {"passed": 2, "failed": 2, "blocked": 1}
              and dsh["success_rate"] == 0.5 and dsh["blocked_rate"] == 0.2)
        check("acceptance overrides are counted separately", dsh["acceptance_samples"] == 1)
        check("averages use only records that carry the value",
              dsh["avg_estimated_api_equivalent_usd"] == 0.01 and dsh["avg_tokens"]["input_tokens"] == 300.0)
        check("recent failure categories are counted by category",
              dsh["recent_failure_categories"] == {"acceptance_rejected": 1, "quota": 1, "task_failed": 1})
        check("verified and unverified models are separate groups",
              groups[("codex", "gpt-6-luna", True)]["samples"] == 1 and groups[("codex", "gpt-6-luna", False)]["samples"] == 1)
        check("window excludes old records and low_sample is flagged",
              groups[("codex", "gpt-6-luna", True)]["low_sample"] is True and dsh["low_sample"] is False)
        check("invalid records are skipped and counted", summary["skipped_invalid_records"] == 1)
        by_task = aggregate(records, now=now, since_days=14, task_class="review")
        check("task_class filter narrows groups", [(row["executor"], row["model"]) for row in by_task["groups"]] == [("pi", "deepseek-flash")])
        encoded = json.dumps(summary)
        check("summary omits record ids and exact timestamps",
              not any(record["record_id"] in encoded for record in records) and "T01:" not in encoded)

        with tempfile.TemporaryDirectory(prefix="soia-usage-aggregate-selftest-") as temp:
            state_path = Path(temp) / "state.txt"
            result = write_jev_state(summary, state_path)
            text = state_path.read_text(encoding="utf-8") if state_path.exists() else ""
            check("jev state passes the outbound scan and is written 0600",
                  result["status"] == "ok" and "dsh:deepseek-flash" in text and "not a quota or permission gate" in text
                  and (os.name != "posix" or state_path.stat().st_mode & 0o777 == 0o600))
            check("jev state is accepted by jev_check dry-run input scanning", jev_check.scan_inputs(text, {}) == {})
            poisoned = json.loads(json.dumps(summary))
            poisoned["groups"][0]["model"] = "/Users/xxx/private-model"
            blocked_path = Path(temp) / "blocked.txt"
            blocked = write_jev_state(poisoned, blocked_path)
            check("a path-shaped value blocks the jev state and nothing is written",
                  blocked["status"] == "blocked_by_scan" and not blocked_path.exists())
    except Exception as exc:  # pragma: no cover - reported as a failed check
        checks.append((f"selftest raised {type(exc).__name__}", False))

    print("=== usage_aggregate.py selftest ===")
    for name, passed in checks:
        print(f"[{'PASS' if passed else 'FAIL'}] {name}")
    print(f"{sum(1 for _, ok in checks if ok)}/{len(checks)} checks passed")
    return 0 if checks and all(ok for _, ok in checks) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--records", help="records JSONL (default: <state>/usage/records.jsonl)")
    parser.add_argument("--since-days", type=int, default=30, help="window in days; 0 means all records")
    parser.add_argument("--min-samples", type=int, default=3)
    parser.add_argument("--recent-failures", type=int, default=5)
    parser.add_argument("--task-class")
    parser.add_argument("--jev-state", help="write a scanned compact text state for jev_check.py")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)
    if args.selftest:
        return run_selftest()
    try:
        path = Path(args.records).expanduser() if args.records else usage_record.default_records_path()
        summary = aggregate(_load(path), since_days=args.since_days or None, min_samples=args.min_samples,
                            recent_failures=args.recent_failures, task_class=args.task_class)
    except (OSError, ValueError):
        print(json.dumps({"status": "input_error", "error": "could not read usage records"}))
        return 2
    if args.jev_state:
        try:
            extra = jev_check.load_private_config().get("extra_block_patterns")
        except jev_check.InputError:
            print(json.dumps({"status": "input_error", "error": "could not read private Jev configuration"}))
            return 2
        result = write_jev_state(summary, Path(args.jev_state).expanduser(), extra)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["status"] == "ok" else 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
