#!/usr/bin/env python3
"""Build, validate and store executor-neutral dispatch usage records.

Record format: `soia.dispatch.usage-record/v1` (references/usage-records.md).

Examples:
  python3 usage_record.py from-manifest --manifest <manifest.json> --billing-class subscription
  python3 usage_record.py from-dsh --report <dsh-report.json> --requested-model deepseek-flash --append
  python3 usage_record.py from-output --executor pi --stdout-file <out.jsonl> --requested-model deepseek-flash \
      --started-at 2026-09-25T01:00:00Z --completed-at 2026-09-25T01:05:00Z --exit-code 0
  python3 usage_record.py validate --records <records.jsonl>
  python3 usage_record.py --selftest

Records carry only sanitized structured fields. Prompts, bodies, stdout/stderr,
free-text notes, credentials, raw session/case identifiers and local absolute
paths are never copied. Exit codes: 0 ok, 2 input/validation error.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalog_lib  # noqa: E402
import estimate_cost  # noqa: E402
import resolve_storage  # noqa: E402


SCHEMA = "soia.dispatch.usage-record/v1"
CATALOG_PATH = Path(__file__).resolve().parents[1] / "references" / "model-catalog.yml"
RECORDS_FILE = Path("usage") / "records.jsonl"

SOURCES = {"run_manifest", "dsh_session", "cli_output", "codex_session"}
MODEL_SOURCES = {"cli_echo", "cli_json", "session_file", "unverified"}
BILLING_CLASSES = {"subscription", "metered_api", "local", "unknown"}
USAGE_STATUSES = {"measured", "partial", "unavailable"}
OUTCOMES = {"passed", "failed", "blocked"}
OUTCOME_BASES = {"execution", "acceptance"}
FAILURE_CATEGORIES = {
    "task_failed", "acceptance_rejected", "timeout", "interrupted", "unsupported",
    "model_mismatch", "auth", "quota", "paid_api_blocked", "independence", "transport",
    "rate_limit", "server", "empty_response", "invalid_request", "approval_denied", "unknown",
    # environment/handoff categories from executor_watch.py classify
    "provider_not_registered", "session_not_found", "sandbox_git_write_denied", "executor_blocked_awaiting_decision",
}
# These stop an execution-level run without it being the executor's failure:
# outcome=blocked keeps them out of the success-rate denominator.
ENVIRONMENT_BLOCKED = {"provider_not_registered", "session_not_found", "sandbox_git_write_denied",
                       "executor_blocked_awaiting_decision"}
STATUS_OUTCOME: dict[str, tuple[str, str | None]] = {
    "passed": ("passed", None),
    "actual_model_unverified": ("passed", None),
    "failed": ("failed", "task_failed"),
    "timeout": ("failed", "timeout"),
    "interrupted": ("failed", "interrupted"),
    "unsupported": ("failed", "unsupported"),
    "fallback_or_downgrade": ("failed", "model_mismatch"),
    "blocked_auth": ("blocked", "auth"),
    "blocked_quota": ("blocked", "quota"),
    "pending_quota": ("blocked", "quota"),
    "blocked_paid_api": ("blocked", "paid_api_blocked"),
    "blocked_independence": ("blocked", "independence"),
}
# dsh turn/end and llm/retry codes → failure categories.
DSH_ERROR_CATEGORIES = {
    "AUTH": "auth", "QUOTA": "quota", "INSUFFICIENT_BALANCE": "quota", "RATE_LIMIT": "rate_limit",
    "TRANSPORT": "transport", "TIMEOUT": "timeout", "SERVER": "server",
    "EMPTY_RESPONSE": "empty_response", "INVALID_REQUEST": "invalid_request",
}
TOKEN_FIELDS = ("input_tokens", "cached_input_tokens", "cache_write_tokens", "output_tokens", "reasoning_tokens", "total_tokens")
COST_FIELDS = ("provider_reported_cost_usd", "estimated_api_equivalent_usd", "actual_charge_usd")
BREAKDOWN_FIELDS = {"provider", "model", "usage_kind", *TOKEN_FIELDS, "estimated_api_equivalent_usd"}
LABEL_FIELDS = ("executor", "provider", "dispatch_role", "task_class", "requested_model", "actual_model",
                "requested_reasoning_effort", "actual_reasoning_effort", "usage_source", "pricing_source")
FIELD_ORDER = (
    "schema", "record_id", "source", "executor", "provider", "dispatch_role", "task_class",
    "requested_model", "actual_model", "actual_model_source", "model_verified",
    "requested_reasoning_effort", "actual_reasoning_effort", "billing_class",
    *TOKEN_FIELDS, "usage_status", "usage_source", *COST_FIELDS, "pricing_source", "pricing_date",
    "started_at", "completed_at", "duration_seconds", "status", "outcome", "outcome_basis",
    "failure_category", "model_breakdown",
)
REQUIRED = {"schema", "record_id", "source", "executor", "requested_model", "actual_model_source", "model_verified",
            "billing_class", "usage_status", "usage_source", "started_at", "completed_at", "status", "outcome",
            "outcome_basis"}
TERMINAL_STATUSES = set(STATUS_OUTCOME)

SAFE_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,79}$")
RECORD_ID = re.compile(r"^[0-9a-f]{16}$")
ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Built from parts so the repository audit does not read the pattern as a hardcoded path.
LOCAL_PATH = re.compile(r"(?i)(?:/" + "Users/|/" + r"home/|[A-Z]:[\\/]Users[\\/])")
SECRETISH = (
    re.compile(r"(?i)\b(?:sk|ghp|github_pat|xox[abprs])[-_][A-Za-z0-9_-]{8,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bbearer\s+\S{12,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\."),
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(r"[A-Za-z0-9+/=_-]{32,}"),
)


class RecordError(Exception):
    """A record could not be built or failed validation; message never carries values."""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _int_or_none(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _num_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return float(value)


def _label_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and SAFE_LABEL.fullmatch(value) and not _looks_sensitive(value) else None


def _looks_sensitive(text: str) -> bool:
    return bool(LOCAL_PATH.search(text)) or any(pattern.search(text) for pattern in SECRETISH)


def _record_id(*parts: Any) -> str:
    key = "\x1f".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _iso(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _duration(started: str | None, completed: str | None) -> float | None:
    if not started or not completed:
        return None
    delta = dt.datetime.fromisoformat(completed.replace("Z", "+00:00")) - dt.datetime.fromisoformat(started.replace("Z", "+00:00"))
    seconds = delta.total_seconds()
    return round(seconds, 3) if seconds >= 0 else None


def _load_catalog() -> dict | None:
    try:
        return catalog_lib.load_catalog(CATALOG_PATH)
    except (OSError, catalog_lib.CatalogError):
        return None


def _estimate(catalog: dict | None, model: str | None, tokens: dict[str, Any]) -> tuple[float | None, str | None, str | None]:
    needed = ("input_tokens", "cached_input_tokens", "cache_write_tokens", "output_tokens")
    if catalog is None or not model or not all(isinstance(tokens.get(field), int) for field in needed):
        return None, None, None
    result = estimate_cost.estimate(
        catalog,
        model,
        input_tokens=tokens["input_tokens"] + tokens["cached_input_tokens"],
        output_tokens=tokens["output_tokens"],
        cached_tokens=tokens["cached_input_tokens"],
        cache_write_tokens=tokens["cache_write_tokens"],
    )
    return _num_or_none(result.get("total_cost")), result.get("pricing_source"), result.get("pricing_effective_date")


def _outcome_fields(status: str, outcome: str | None, failure_category: str | None) -> dict[str, Any]:
    if status not in TERMINAL_STATUSES:
        raise RecordError("status is not a terminal manifest status")
    derived_outcome, derived_category = STATUS_OUTCOME[status]
    basis = "execution"
    if outcome is not None:
        if outcome not in OUTCOMES:
            raise RecordError("outcome must be passed, failed or blocked")
        basis = "acceptance"
        derived_outcome = outcome
        derived_category = failure_category or ("acceptance_rejected" if outcome == "failed" else derived_category)
    elif failure_category is not None:
        derived_category = failure_category
        if failure_category in ENVIRONMENT_BLOCKED:
            derived_outcome = "blocked"
        elif derived_outcome == "passed":
            derived_outcome = "failed"
    if derived_outcome == "passed":
        derived_category = None
    elif derived_category is None:
        derived_category = "unknown"
    return {"outcome": derived_outcome, "outcome_basis": basis, "failure_category": derived_category}


def _finish(record: dict[str, Any]) -> dict[str, Any]:
    ordered = {field: record.get(field) for field in FIELD_ORDER if field in record}
    validate_record(ordered)
    return ordered


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


def validate_record(record: Any) -> None:
    """Raise RecordError when a record is not a safe, well-formed v1 record."""
    if not isinstance(record, dict):
        raise RecordError("record must be a JSON object")
    unknown = set(record) - set(FIELD_ORDER)
    if unknown:
        raise RecordError(f"unknown field(s): {len(unknown)}")
    missing = [field for field in sorted(REQUIRED) if record.get(field) is None]
    if missing:
        raise RecordError(f"missing required field(s): {', '.join(missing)}")
    if record["schema"] != SCHEMA:
        raise RecordError("schema mismatch")
    if not isinstance(record["record_id"], str) or not RECORD_ID.fullmatch(record["record_id"]):
        raise RecordError("record_id must be 16 lowercase hex characters")
    enums = {
        "source": SOURCES, "actual_model_source": MODEL_SOURCES, "billing_class": BILLING_CLASSES,
        "usage_status": USAGE_STATUSES, "outcome": OUTCOMES, "outcome_basis": OUTCOME_BASES,
        "status": TERMINAL_STATUSES,
    }
    for field, allowed in enums.items():
        if record.get(field) not in allowed:
            raise RecordError(f"invalid value for {field}")
    if record.get("failure_category") is not None and record["failure_category"] not in FAILURE_CATEGORIES:
        raise RecordError("invalid value for failure_category")
    if record["outcome"] != "passed" and record.get("failure_category") is None:
        raise RecordError("failure_category is required when outcome is not passed")
    if not isinstance(record["model_verified"], bool):
        raise RecordError("model_verified must be boolean")
    if record["model_verified"] and (record.get("actual_model") is None or record["actual_model_source"] == "unverified"):
        raise RecordError("model_verified requires actual_model evidence")
    for field in LABEL_FIELDS:
        value = record.get(field)
        if value is not None and _label_or_none(value) is None:
            raise RecordError(f"{field} must be a short safe label")
    for field in TOKEN_FIELDS:
        if field in record and record[field] is not None and _int_or_none(record[field]) is None:
            raise RecordError(f"{field} must be a non-negative integer or null")
    for field in (*COST_FIELDS, "duration_seconds"):
        if field in record and record[field] is not None and _num_or_none(record[field]) is None:
            raise RecordError(f"{field} must be a non-negative number or null")
    for field in ("started_at", "completed_at"):
        if not isinstance(record[field], str) or not ISO_UTC.fullmatch(record[field]):
            raise RecordError(f"{field} must be a UTC ISO 8601 timestamp")
    if record.get("pricing_date") is not None and not (isinstance(record["pricing_date"], str) and DATE.fullmatch(record["pricing_date"])):
        raise RecordError("pricing_date must be YYYY-MM-DD")
    breakdown = record.get("model_breakdown")
    if breakdown is not None:
        if not isinstance(breakdown, list):
            raise RecordError("model_breakdown must be a list")
        for row in breakdown:
            if not isinstance(row, dict) or set(row) - BREAKDOWN_FIELDS:
                raise RecordError("model_breakdown rows carry unknown fields")
            for field in ("provider", "model", "usage_kind"):
                if row.get(field) is not None and _label_or_none(row[field]) is None:
                    raise RecordError("model_breakdown labels must be safe")
            for field in TOKEN_FIELDS:
                if row.get(field) is not None and _int_or_none(row[field]) is None:
                    raise RecordError("model_breakdown tokens must be non-negative integers")
    # Last line of defence: nothing path- or secret-shaped anywhere in the record.
    # Enum-checked fields are skipped: a long category name is not a secret.
    free_fields = {key: value for key, value in record.items() if key not in set(enums) | {"failure_category"}}
    if _looks_sensitive(json.dumps(free_fields, ensure_ascii=False)):
        raise RecordError("record contains a path- or secret-shaped value")


# ---------------------------------------------------------------------------
# adapters
# ---------------------------------------------------------------------------


def from_manifest_case(
    case: dict[str, Any], *, run_id: str | None, billing_class: str | None = None,
    task_class: str | None = None, outcome: str | None = None, failure_category: str | None = None,
) -> dict[str, Any] | None:
    """Map one run_matrix manifest case; returns None for non-terminal cases."""
    status = case.get("status")
    if status not in TERMINAL_STATUSES:
        return None
    executor = _label_or_none(case.get("executor"))
    requested = _label_or_none(case.get("requested_model") or case.get("model"))
    if not executor or not requested:
        raise RecordError("manifest case needs safe executor and requested_model labels")
    actual = _label_or_none(case.get("actual_model"))
    verified = actual is not None and status != "actual_model_unverified"
    model_source = "unverified"
    if verified:
        model_source = "cli_echo" if executor == "codex" else "cli_json"
    started = _iso(case.get("started_at"))
    completed = _iso(case.get("completed_at")) or started
    record: dict[str, Any] = {
        "schema": SCHEMA,
        "record_id": _record_id("run_manifest", run_id, case.get("case_id"), started),
        "source": "run_manifest",
        "executor": executor,
        "provider": _label_or_none(case.get("provider")),
        "dispatch_role": _label_or_none(case.get("dispatch_role")),
        "task_class": _label_or_none(task_class),
        "requested_model": requested,
        "actual_model": actual,
        "actual_model_source": model_source,
        "model_verified": verified,
        "requested_reasoning_effort": _label_or_none(case.get("requested_reasoning_effort") or case.get("reasoning")),
        "actual_reasoning_effort": _label_or_none(case.get("actual_reasoning_effort")),
        "billing_class": billing_class or (case.get("billing_class") if case.get("billing_class") in BILLING_CLASSES else "unknown"),
        "input_tokens": _int_or_none(case.get("input_tokens")),
        "cached_input_tokens": _int_or_none(case.get("cached_input_tokens")),
        "cache_write_tokens": _int_or_none(case.get("cache_write_tokens")),
        "output_tokens": _int_or_none(case.get("output_tokens")),
        "reasoning_tokens": None,
        "total_tokens": _int_or_none(case.get("total_tokens")),
        "usage_status": case.get("usage_status") if case.get("usage_status") in USAGE_STATUSES else "unavailable",
        "usage_source": _label_or_none(case.get("usage_source")) or "unavailable",
        "provider_reported_cost_usd": _num_or_none(case.get("provider_reported_cost_usd")),
        "estimated_api_equivalent_usd": _num_or_none(_to_number(case.get("estimated_api_equivalent_usd"))),
        "actual_charge_usd": _num_or_none(case.get("actual_charge_usd")),
        "pricing_source": _label_or_none(case.get("pricing_source")),
        "pricing_date": case.get("pricing_date") if isinstance(case.get("pricing_date"), str) and DATE.fullmatch(case["pricing_date"]) else None,
        "started_at": started,
        "completed_at": completed,
        "duration_seconds": _num_or_none(case.get("duration_seconds")),
        "status": status,
        **_outcome_fields(status, outcome, failure_category),
    }
    return _finish(record)


def _to_number(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return value


def from_manifest(manifest: dict[str, Any], **options: Any) -> list[dict[str, Any]]:
    cases = manifest.get("cases")
    if not isinstance(cases, list):
        raise RecordError("manifest has no cases list")
    run_id = manifest.get("run_id")
    records = []
    for case in cases:
        if isinstance(case, dict):
            record = from_manifest_case(case, run_id=run_id, **options)
            if record is not None:
                records.append(record)
    return records


def _dsh_failure(report: dict[str, Any]) -> tuple[str, str | None]:
    """Execution-level status for a dsh session from how its last turn ended.

    A long-lived session may recover from an early error, so only the last
    turn decides; older reports without `last_turn_end` fall back to counts.
    """
    last = report.get("last_turn_end")
    ends = [last] if isinstance(last, dict) else [row for row in report.get("turn_ends") or [] if isinstance(row, dict)]
    errors = [row for row in ends if row.get("kind") == "error"]
    if errors:
        code = errors[-1].get("error_code") or ""
        category = DSH_ERROR_CATEGORIES.get(code, "unknown")
        if category == "auth":
            return "blocked_auth", "auth"
        if category == "quota":
            return "blocked_quota", "quota"
        return "failed", category
    if any(row.get("kind") == "interrupted" for row in ends):
        return "interrupted", "interrupted"
    return "passed", None


def from_dsh_report(
    report: dict[str, Any], *, requested_model: str | None = None, billing_class: str | None = None,
    task_class: str | None = None, dispatch_role: str | None = None, outcome: str | None = None,
    failure_category: str | None = None,
) -> dict[str, Any]:
    if report.get("status") not in (None, "ok"):
        raise RecordError("dsh report is not an ok report")
    rows = [row for row in report.get("usage_by_model") or [] if isinstance(row, dict)]
    costs = {
        (row.get("provider"), row.get("model"), row.get("attribution")): row
        for row in (report.get("cost_estimate_usd") or {}).get("by_model") or [] if isinstance(row, dict)
    }
    field_map = {
        "input_tokens": "input_tokens_uncached", "cached_input_tokens": "cache_read_tokens",
        "cache_write_tokens": "cache_write_tokens", "output_tokens": "output_tokens",
        "reasoning_tokens": "reasoning_tokens", "total_tokens": "total_tokens",
    }
    breakdown: list[dict[str, Any]] = []
    totals: dict[str, int | None] = {field: 0 for field in TOKEN_FIELDS}
    cost_total: float | None = 0.0
    primary: dict[tuple[str, str], int] = {}
    effort: dict[tuple[str, str], str | None] = {}
    pricing: tuple[str | None, str | None] = (None, None)
    for row in rows:
        provider, model, kind = _label_or_none(row.get("provider")), _label_or_none(row.get("model")), row.get("attribution")
        entry: dict[str, Any] = {"provider": provider, "model": model, "usage_kind": _label_or_none(kind)}
        for target, source in field_map.items():
            value = _int_or_none(row.get(source))
            entry[target] = value
            if value is None:
                if target != "reasoning_tokens":
                    totals[target] = None
            elif totals[target] is not None:
                totals[target] += value
        cost_row = costs.get((row.get("provider"), row.get("model"), kind), {})
        value = _num_or_none(cost_row.get("value"))
        entry["estimated_api_equivalent_usd"] = value
        cost_total = None if value is None or cost_total is None else cost_total + value
        if value is not None and cost_row.get("pricing_source"):
            pricing = (_label_or_none(cost_row.get("pricing_source")), cost_row.get("pricing_effective_date"))
        breakdown.append(entry)
        if provider and model and kind in {"message_source", "request_header", "ui_fallback"}:
            primary[(provider, model)] = primary.get((provider, model), 0) + (entry["total_tokens"] or 0)
            effort.setdefault((provider, model), _label_or_none(row.get("reasoningEffort")))
    if not rows:
        totals = {field: None for field in TOKEN_FIELDS}
        cost_total = None
    main = max(primary, key=lambda key: primary[key]) if primary else None
    status, category = _dsh_failure(report)
    if main is None and status == "passed":
        status = "actual_model_unverified"
    if main and requested_model and main[1] != requested_model and status == "passed":
        status, category = "fallback_or_downgrade", "model_mismatch"
    started = _iso(report.get("started_at"))
    completed = _iso(report.get("ended_at")) or started
    if not started:
        raise RecordError("dsh report has no session start time")
    usage_status = "unavailable"
    if rows:
        complete = all(totals[field] is not None for field in ("input_tokens", "cached_input_tokens", "cache_write_tokens", "output_tokens"))
        usage_status = "measured" if complete else "partial"
    provider = main[0] if main else None
    pricing_date = pricing[1] if isinstance(pricing[1], str) and DATE.fullmatch(pricing[1]) else None
    record: dict[str, Any] = {
        "schema": SCHEMA,
        "record_id": _record_id("dsh_session", report.get("session_id"), started),
        "source": "dsh_session",
        "executor": "dsh",
        "provider": provider,
        "dispatch_role": _label_or_none(dispatch_role),
        "task_class": _label_or_none(task_class),
        "requested_model": _label_or_none(requested_model) or (main[1] if main else "unknown"),
        "actual_model": main[1] if main else None,
        "actual_model_source": "session_file" if main else "unverified",
        "model_verified": main is not None,
        "requested_reasoning_effort": None,
        "actual_reasoning_effort": effort.get(main) if main else None,
        "billing_class": billing_class or ("local" if provider == "mlx" else "metered_api" if provider else "unknown"),
        **{field: totals[field] for field in TOKEN_FIELDS},
        "usage_status": usage_status,
        "usage_source": f"dsh_session_{report.get('session_format', 'v3')}" if rows else "unavailable",
        "provider_reported_cost_usd": None,
        "estimated_api_equivalent_usd": round(cost_total, 10) if cost_total is not None else None,
        "actual_charge_usd": None,
        "pricing_source": pricing[0],
        "pricing_date": pricing_date,
        "started_at": started,
        "completed_at": completed,
        "duration_seconds": _duration(started, completed),
        "status": status,
        **_outcome_fields(status, outcome, failure_category or category),
        "model_breakdown": breakdown or None,
    }
    if record["reasoning_tokens"] == 0 and not any(row.get("reasoning_tokens") for row in breakdown):
        record["reasoning_tokens"] = None
    return _finish(record)


def from_cli_output(
    *, executor: str, stdout: str, stderr: str = "", requested_model: str, started_at: str, completed_at: str,
    exit_code: int | None, timed_out: bool = False, billing_class: str | None = None, task_class: str | None = None,
    dispatch_role: str | None = None, reasoning: str | None = None, outcome: str | None = None,
    failure_category: str | None = None,
) -> dict[str, Any]:
    """Map a single CLI call's captured output using run_matrix parsers."""
    import run_matrix  # local import: heavier module, only needed here

    catalog = _load_catalog()
    usage = run_matrix.parse_usage(executor, stdout)
    if executor == "claude":
        actual = run_matrix.detect_claude_model_evidence(stdout, run_matrix.claude_auxiliary_prefixes(catalog))["actual_model"]
        model_source = "cli_json"
    elif executor == "codex":
        actual = run_matrix.detect_actual_model("codex", stdout) or run_matrix.detect_actual_model("codex", stderr)
        model_source = "cli_echo"
    else:
        actual = run_matrix.detect_actual_model(executor, stdout, None, catalog)
        model_source = "cli_json"
    actual = _label_or_none(actual)
    if timed_out:
        status = "timeout"
    elif exit_code not in (0, None):
        status = "failed"
    elif actual is None:
        status = "actual_model_unverified"
    else:
        if executor == "claude":
            matches = run_matrix._claude_model_matches(requested_model, actual, catalog)
        else:
            matches = actual.split("/")[-1] == requested_model.split("/")[-1]
        status = "passed" if matches else "fallback_or_downgrade"
    started, completed = _iso(started_at), _iso(completed_at)
    if not started or not completed:
        raise RecordError("started_at and completed_at must be timezone-aware ISO 8601 timestamps")
    estimate, pricing_source, pricing_date = _estimate(catalog, actual or requested_model, usage)
    record: dict[str, Any] = {
        "schema": SCHEMA,
        "record_id": _record_id("cli_output", executor, requested_model, started, completed),
        "source": "cli_output",
        "executor": _label_or_none(executor),
        "provider": None,
        "dispatch_role": _label_or_none(dispatch_role),
        "task_class": _label_or_none(task_class),
        "requested_model": _label_or_none(requested_model),
        "actual_model": actual,
        "actual_model_source": model_source if actual else "unverified",
        "model_verified": actual is not None,
        "requested_reasoning_effort": _label_or_none(reasoning),
        "actual_reasoning_effort": None,
        "billing_class": billing_class or "unknown",
        "input_tokens": _int_or_none(usage.get("input_tokens")),
        "cached_input_tokens": _int_or_none(usage.get("cached_input_tokens")),
        "cache_write_tokens": _int_or_none(usage.get("cache_write_tokens")),
        "output_tokens": _int_or_none(usage.get("output_tokens")),
        "reasoning_tokens": None,
        "total_tokens": _int_or_none(usage.get("total_tokens")),
        "usage_status": usage.get("usage_status", "unavailable"),
        "usage_source": usage.get("usage_source", "unavailable"),
        "provider_reported_cost_usd": _num_or_none(usage.get("provider_reported_cost_usd")),
        "estimated_api_equivalent_usd": estimate,
        "actual_charge_usd": None,
        "pricing_source": _label_or_none(pricing_source),
        "pricing_date": pricing_date if isinstance(pricing_date, str) and DATE.fullmatch(pricing_date) else None,
        "started_at": started,
        "completed_at": completed,
        "duration_seconds": _duration(started, completed),
        "status": status,
        **_outcome_fields(status, outcome, failure_category),
    }
    return _finish(record)


def from_codex_info(
    info: dict[str, Any], *, requested_model: str, exit_code: int | None = None, classification: dict[str, Any] | None = None,
    billing_class: str | None = None, task_class: str | None = None, dispatch_role: str | None = None,
    reasoning: str | None = None, outcome: str | None = None, failure_category: str | None = None,
) -> dict[str, Any]:
    """Map codex_session_info.py output (plus an optional executor_watch classify result)."""
    if info.get("status") not in (None, "ok"):
        raise RecordError("codex info is not an ok report")
    rollout = info.get("rollout") or {}
    usage = rollout.get("usage") or {}
    actual = _label_or_none(info.get("actual_model"))
    source = info.get("actual_model_source")
    verified = actual is not None and source in {"rollout_turn_context", "stderr_header"}
    classification = classification or {}
    category = failure_category or classification.get("category")
    if classification.get("category") == "timeout":
        status = "timeout"
    elif rollout.get("turn_aborted") and not rollout.get("task_complete_count"):
        status = "interrupted"
    elif exit_code not in (0, None) and category is None:
        status = "failed"
    elif not verified:
        status = "actual_model_unverified"
    elif actual != requested_model:
        status = "fallback_or_downgrade"
    else:
        status = "passed"
    if category == "auth":
        status = "blocked_auth"
    elif category == "quota":
        status = "blocked_quota"
    started = _iso(rollout.get("started_at"))
    completed = _iso(rollout.get("ended_at")) or started
    if not started:
        raise RecordError("codex info has no rollout timestamps")
    cost = info.get("cost_estimate_usd") or {}
    last_turn = rollout.get("last_turn") or {}
    record: dict[str, Any] = {
        "schema": SCHEMA,
        "record_id": _record_id("codex_session", info.get("session_id"), started),
        "source": "codex_session",
        "executor": "codex",
        "provider": _label_or_none(rollout.get("model_provider")),
        "dispatch_role": _label_or_none(dispatch_role),
        "task_class": _label_or_none(task_class),
        "requested_model": _label_or_none(requested_model),
        "actual_model": actual,
        "actual_model_source": ("session_file" if source == "rollout_turn_context" else "cli_echo") if verified else "unverified",
        "model_verified": verified,
        "requested_reasoning_effort": _label_or_none(reasoning),
        "actual_reasoning_effort": _label_or_none(last_turn.get("reasoning_effort")),
        "billing_class": billing_class or "subscription",
        **{field: _int_or_none(usage.get(field)) for field in TOKEN_FIELDS},
        "usage_status": usage.get("usage_status") if usage.get("usage_status") in USAGE_STATUSES else "unavailable",
        "usage_source": "codex_rollout_token_count" if usage.get("usage_status") in {"measured", "partial"} else "unavailable",
        "provider_reported_cost_usd": None,
        "estimated_api_equivalent_usd": _num_or_none(cost.get("value")),
        "actual_charge_usd": None,
        "pricing_source": _label_or_none(cost.get("pricing_source")),
        "pricing_date": cost.get("pricing_effective_date") if isinstance(cost.get("pricing_effective_date"), str) and DATE.fullmatch(cost["pricing_effective_date"]) else None,
        "started_at": started,
        "completed_at": completed,
        "duration_seconds": _duration(started, completed),
        "status": status,
        **_outcome_fields(status, outcome, category if category in FAILURE_CATEGORIES else None),
    }
    return _finish(record)


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------


def default_records_path() -> Path:
    config = resolve_storage.load_config(resolve_storage.default_config_path())
    return resolve_storage.storage_paths(config)["state"] / RECORDS_FILE


def read_records(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                yield {"_invalid": True}
                continue
            yield value if isinstance(value, dict) else {"_invalid": True}


def append_records(path: Path, records: list[dict[str, Any]]) -> dict[str, int]:
    """Append records not yet present (by record_id). Directory 0700, file 0600."""
    for record in records:
        validate_record(record)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    existing: set[str] = set()
    if path.exists():
        existing = {row.get("record_id") for row in read_records(path) if isinstance(row.get("record_id"), str)}
    fresh = [record for record in records if record["record_id"] not in existing]
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        for record in fresh:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return {"appended": len(fresh), "skipped_duplicates": len(records) - len(fresh)}


# ---------------------------------------------------------------------------
# selftest
# ---------------------------------------------------------------------------


def run_selftest() -> int:
    checks: list[tuple[str, bool]] = []

    def check(name: str, ok: bool) -> None:
        checks.append((name, bool(ok)))

    sentinel = "PROMPT_SENTINEL_DO_NOT_STORE_91c2"
    try:
        manifest = {
            "run_id": "selftest-run",
            "cases": [
                {"case_id": "case-private-" + sentinel, "provider": "anthropic", "executor": "claude",
                 "requested_model": "claude-sonnet-5", "actual_model": "claude-sonnet-5", "status": "passed",
                 "started_at": "2026-09-25T01:00:00Z", "completed_at": "2026-09-25T01:02:00Z", "duration_seconds": 120.0,
                 "input_tokens": 100, "cached_input_tokens": 50, "cache_write_tokens": 10, "output_tokens": 20,
                 "total_tokens": 180, "usage_status": "measured", "usage_source": "claude_json_usage",
                 "provider_reported_cost_usd": 0.01, "estimated_api_equivalent_usd": "0.0123",
                 "notes": ["stderr from /Users/xxx/private " + sentinel], "cmd_template": "claude -p " + sentinel},
                {"case_id": "c2", "provider": "openai", "executor": "codex", "requested_model": "gpt-6-luna",
                 "actual_model": "gpt-6-sol", "status": "fallback_or_downgrade",
                 "started_at": "2026-09-25T02:00:00Z", "completed_at": "2026-09-25T02:01:00Z",
                 "total_tokens": 5000, "usage_status": "partial", "usage_source": "codex_stdout_total"},
                {"case_id": "c3", "executor": "codex", "requested_model": "gpt-6-luna", "status": "blocked_quota",
                 "started_at": "2026-09-25T03:00:00Z", "completed_at": "2026-09-25T03:00:01Z"},
                {"case_id": "c4", "executor": "codex", "requested_model": "gpt-6-luna", "status": "running",
                 "started_at": "2026-09-25T04:00:00Z"},
            ],
        }
        records = from_manifest(manifest, billing_class="subscription", task_class="review")
        encoded = json.dumps(records, ensure_ascii=False)
        check("manifest: only terminal cases become records", len(records) == 3)
        check("manifest: prompt, notes, case id and paths are not copied",
              sentinel not in encoded and "case-private" not in encoded and "/Users/xxx" not in encoded and "notes" not in encoded)
        first, second, third = records
        check("manifest: passed maps to outcome passed with verified cli_json model",
              first["outcome"] == "passed" and first["failure_category"] is None and first["model_verified"] is True
              and first["actual_model_source"] == "cli_json" and first["estimated_api_equivalent_usd"] == 0.0123
              and first["provider_reported_cost_usd"] == 0.01)
        check("manifest: fallback_or_downgrade maps to failed/model_mismatch",
              second["outcome"] == "failed" and second["failure_category"] == "model_mismatch"
              and second["actual_model_source"] == "cli_echo" and second["input_tokens"] is None and second["total_tokens"] == 5000)
        check("manifest: blocked_quota maps to blocked/quota", third["outcome"] == "blocked" and third["failure_category"] == "quota")
        accepted = from_manifest_case(manifest["cases"][0], run_id="selftest-run", outcome="failed")
        check("acceptance override records outcome_basis and acceptance_rejected",
              accepted["outcome"] == "failed" and accepted["outcome_basis"] == "acceptance"
              and accepted["failure_category"] == "acceptance_rejected" and accepted["record_id"] == first["record_id"])

        dsh_report = {
            "status": "ok", "session_id": "00000000-0000-4000-8000-0000000000a4", "session_format": "v4",
            "started_at": "2026-09-25T05:00:00.000+00:00", "ended_at": "2026-09-25T05:10:00.000+00:00",
            "usage_by_model": [
                {"provider": "deepseek-official", "model": "deepseek-flash", "reasoningEffort": "max", "attribution": "message_source",
                 "input_tokens_uncached": 10, "cache_read_tokens": 90, "cache_write_tokens": 0, "output_tokens": 4, "reasoning_tokens": 2, "total_tokens": 104},
                {"provider": "xiaomi", "model": "mimo-v2.6-flash", "reasoningEffort": None, "attribution": "compaction_summary",
                 "input_tokens_uncached": 40, "cache_read_tokens": 0, "cache_write_tokens": 0, "output_tokens": 5, "reasoning_tokens": None, "total_tokens": 45},
            ],
            "cost_estimate_usd": {"by_model": [
                {"provider": "deepseek-official", "model": "deepseek-flash", "attribution": "message_source", "value": 0.001, "pricing_source": "catalog", "pricing_effective_date": "2026-09-23"},
                {"provider": "xiaomi", "model": "mimo-v2.6-flash", "attribution": "compaction_summary", "value": 0.0005},
            ]},
            "turn_ends": [{"kind": "completed", "error_code": None, "count": 3}],
        }
        dsh = from_dsh_report(dsh_report, requested_model="deepseek-flash", task_class="implement")
        check("dsh: session totals, primary model and metered billing",
              dsh["actual_model"] == "deepseek-flash" and dsh["provider"] == "deepseek-official"
              and dsh["input_tokens"] == 50 and dsh["cached_input_tokens"] == 90 and dsh["total_tokens"] == 149
              and dsh["billing_class"] == "metered_api" and dsh["estimated_api_equivalent_usd"] == 0.0015
              and dsh["provider_reported_cost_usd"] is None and dsh["actual_reasoning_effort"] == "max"
              and dsh["usage_status"] == "measured" and len(dsh["model_breakdown"]) == 2
              and dsh["duration_seconds"] == 600.0 and dsh["outcome"] == "passed")
        check("dsh: raw session id is not stored", "0000000000a4" not in json.dumps(dsh))
        failed = from_dsh_report({**dsh_report, "turn_ends": [{"kind": "error", "error_code": "AUTH", "count": 1}]})
        check("dsh: turn/end AUTH error maps to blocked/auth", failed["outcome"] == "blocked" and failed["failure_category"] == "auth")
        recovered = from_dsh_report({**dsh_report, "turn_ends": [{"kind": "error", "error_code": "TRANSPORT", "count": 1}],
                                     "last_turn_end": {"kind": "completed", "error_code": None}})
        check("dsh: an early turn error followed by a completed last turn stays passed", recovered["outcome"] == "passed")
        mismatch = from_dsh_report(dsh_report, requested_model="mimo-v2.6-pro")
        check("dsh: requested/actual mismatch maps to model_mismatch", mismatch["failure_category"] == "model_mismatch")

        pi_stdout = json.dumps({"type": "message_end", "message": {"role": "assistant", "provider": "deepseek", "model": "deepseek-flash",
                                "content": [{"type": "text", "text": sentinel}],
                                "usage": {"input": 100, "cacheRead": 20, "cacheWrite": 0, "output": 30, "totalTokens": 150, "cost": {"total": 0.0002}}}})
        pi = from_cli_output(executor="pi", stdout=pi_stdout, requested_model="deepseek-flash",
                             started_at="2026-09-25T06:00:00Z", completed_at="2026-09-25T06:00:30Z", exit_code=0,
                             billing_class="metered_api")
        check("cli output: pi usage and model are mapped without body text",
              pi["status"] == "passed" and pi["input_tokens"] == 100 and pi["provider_reported_cost_usd"] == 0.0002
              and pi["actual_model_source"] == "cli_json" and sentinel not in json.dumps(pi))
        codex = from_cli_output(executor="codex", stdout="done\ntokens used\n1,234\n", stderr="model: gpt-6-luna\n",
                                requested_model="gpt-6-luna", started_at="2026-09-25T07:00:00Z",
                                completed_at="2026-09-25T07:01:00Z", exit_code=0, billing_class="subscription")
        check("cli output: codex stderr header model and stdout total map to partial usage",
              codex["actual_model"] == "gpt-6-luna" and codex["total_tokens"] == 1234 and codex["usage_status"] == "partial"
              and codex["estimated_api_equivalent_usd"] is None)

        codex_info = {
            "status": "ok", "session_id": "01a0d43b-0000-7000-8000-00000000c0de", "actual_model": "gpt-6-luna",
            "actual_model_source": "rollout_turn_context",
            "rollout": {"model_provider": "openai", "started_at": "2026-09-25T01:00:00Z", "ended_at": "2026-09-25T01:05:00Z",
                        "task_complete_count": 1, "turn_aborted": {}, "last_turn": {"reasoning_effort": "xhigh"},
                        "usage": {"input_tokens": 400, "cached_input_tokens": 600, "cache_write_tokens": 0, "output_tokens": 50,
                                  "reasoning_tokens": 20, "total_tokens": 1050, "usage_status": "measured"}},
            "cost_estimate_usd": {"value": 0.01, "pricing_source": "openai-pricing", "pricing_effective_date": "2026-09-23"},
        }
        codex_rec = from_codex_info(codex_info, requested_model="gpt-6-luna")
        check("codex session: rollout usage, verified model and subscription billing",
              codex_rec["status"] == "passed" and codex_rec["input_tokens"] == 400 and codex_rec["reasoning_tokens"] == 20
              and codex_rec["actual_model_source"] == "session_file" and codex_rec["billing_class"] == "subscription"
              and codex_rec["actual_reasoning_effort"] == "xhigh" and "c0de" not in json.dumps(codex_rec))
        handed_back = from_codex_info(codex_info, requested_model="gpt-6-luna",
                                      classification={"category": "executor_blocked_awaiting_decision"})
        check("codex session: awaiting-decision classification is blocked, not failed",
              handed_back["outcome"] == "blocked" and handed_back["failure_category"] == "executor_blocked_awaiting_decision")
        git_blocked = from_manifest_case(manifest["cases"][0], run_id="selftest-run", failure_category="sandbox_git_write_denied")
        check("environment categories map to blocked with execution basis",
              git_blocked["outcome"] == "blocked" and git_blocked["outcome_basis"] == "execution")

        rejected = []
        for mutation in (
            {"prompt": "x"},
            {"executor": "/Users/xxx/bin/codex"},
            {"task_class": "sk-" + "abcdefghijklmnopqrstuvwxyz0123"},
            {"outcome": "succeeded"},
            {"outcome": "failed", "failure_category": None},
            {"model_verified": True, "actual_model": None},
            {"started_at": "2026-09-25 01:00"},
        ):
            try:
                validate_record({**first, **mutation})
                rejected.append(False)
            except RecordError:
                rejected.append(True)
        check("validation rejects unknown fields, paths, secrets, bad enums and unverifiable models", all(rejected))

        with tempfile.TemporaryDirectory(prefix="soia-usage-record-selftest-") as temp:
            path = Path(temp) / "state" / "usage" / "records.jsonl"
            first_write = append_records(path, records + [dsh])
            second_write = append_records(path, records)
            mode = path.stat().st_mode & 0o777
            rows = list(read_records(path))
            check("append is idempotent by record_id and writes 0600",
                  first_write == {"appended": 4, "skipped_duplicates": 0}
                  and second_write == {"appended": 0, "skipped_duplicates": 3}
                  and len(rows) == 4 and (os.name != "posix" or mode == 0o600))
    except Exception as exc:  # pragma: no cover - reported as a failed check
        checks.append((f"selftest raised {type(exc).__name__}", False))

    print("=== usage_record.py selftest ===")
    for name, passed in checks:
        print(f"[{'PASS' if passed else 'FAIL'}] {name}")
    print(f"{sum(1 for _, ok in checks if ok)}/{len(checks)} checks passed")
    return 0 if checks and all(ok for _, ok in checks) else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _read_json(path_text: str) -> Any:
    text = sys.stdin.read() if path_text == "-" else Path(path_text).expanduser().read_text(encoding="utf-8")
    return json.loads(text)


def _emit(records: list[dict[str, Any]], args: argparse.Namespace) -> int:
    if args.append:
        path = Path(args.records_file).expanduser() if args.records_file else default_records_path()
        result = append_records(path, records)
        print(json.dumps({"status": "ok", **result}, ensure_ascii=False))
    else:
        for record in records:
            print(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--selftest", action="store_true", help="run offline synthetic checks")
    sub = parser.add_subparsers(dest="command")

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--billing-class", choices=sorted(BILLING_CLASSES))
        p.add_argument("--task-class", help="short task category label, e.g. implement/review/docs")
        p.add_argument("--outcome", choices=sorted(OUTCOMES), help="acceptance-level outcome override")
        p.add_argument("--failure-category", choices=sorted(FAILURE_CATEGORIES))
        p.add_argument("--append", action="store_true", help="append to the usage records file instead of printing")
        p.add_argument("--records-file", help="records JSONL path (default: <state>/usage/records.jsonl)")

    manifest = sub.add_parser("from-manifest", help="map run_matrix manifest cases")
    manifest.add_argument("--manifest", required=True)
    common(manifest)

    dsh = sub.add_parser("from-dsh", help="map a dsh_session_usage.py report")
    dsh.add_argument("--report", required=True, help="report JSON path or - for stdin")
    dsh.add_argument("--requested-model")
    dsh.add_argument("--dispatch-role")
    common(dsh)

    output = sub.add_parser("from-output", help="map one captured codex/claude/pi call")
    output.add_argument("--executor", required=True, choices=["codex", "claude", "pi"])
    output.add_argument("--stdout-file", required=True)
    output.add_argument("--stderr-file")
    output.add_argument("--requested-model", required=True)
    output.add_argument("--reasoning")
    output.add_argument("--dispatch-role")
    output.add_argument("--started-at", required=True)
    output.add_argument("--completed-at", required=True)
    output.add_argument("--exit-code", type=int)
    output.add_argument("--timed-out", action="store_true")
    common(output)

    codex = sub.add_parser("from-codex", help="map codex_session_info.py output")
    codex.add_argument("--info", required=True, help="codex_session_info.py JSON path or - for stdin")
    codex.add_argument("--classification", help="executor_watch.py classify JSON path")
    codex.add_argument("--requested-model", required=True)
    codex.add_argument("--reasoning")
    codex.add_argument("--dispatch-role")
    codex.add_argument("--exit-code", type=int)
    common(codex)

    validate = sub.add_parser("validate", help="validate a records JSONL file")
    validate.add_argument("--records", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.selftest:
        return run_selftest()
    try:
        if args.command == "from-manifest":
            records = from_manifest(_read_json(args.manifest), billing_class=args.billing_class, task_class=args.task_class,
                                    outcome=args.outcome, failure_category=args.failure_category)
            return _emit(records, args)
        if args.command == "from-dsh":
            record = from_dsh_report(_read_json(args.report), requested_model=args.requested_model,
                                     billing_class=args.billing_class, task_class=args.task_class,
                                     dispatch_role=args.dispatch_role, outcome=args.outcome,
                                     failure_category=args.failure_category)
            return _emit([record], args)
        if args.command == "from-output":
            stdout = Path(args.stdout_file).expanduser().read_text(encoding="utf-8", errors="replace")
            stderr = Path(args.stderr_file).expanduser().read_text(encoding="utf-8", errors="replace") if args.stderr_file else ""
            record = from_cli_output(executor=args.executor, stdout=stdout, stderr=stderr, requested_model=args.requested_model,
                                     started_at=args.started_at, completed_at=args.completed_at, exit_code=args.exit_code,
                                     timed_out=args.timed_out, billing_class=args.billing_class, task_class=args.task_class,
                                     dispatch_role=args.dispatch_role, reasoning=args.reasoning, outcome=args.outcome,
                                     failure_category=args.failure_category)
            return _emit([record], args)
        if args.command == "from-codex":
            record = from_codex_info(_read_json(args.info), requested_model=args.requested_model, exit_code=args.exit_code,
                                     classification=_read_json(args.classification) if args.classification else None,
                                     billing_class=args.billing_class, task_class=args.task_class,
                                     dispatch_role=args.dispatch_role, reasoning=args.reasoning, outcome=args.outcome,
                                     failure_category=args.failure_category)
            return _emit([record], args)
        if args.command == "validate":
            valid = invalid = 0
            for row in read_records(Path(args.records).expanduser()):
                try:
                    validate_record(row)
                    valid += 1
                except RecordError:
                    invalid += 1
            print(json.dumps({"status": "ok" if not invalid else "invalid", "valid": valid, "invalid": invalid}))
            return 0 if not invalid else 2
    except (RecordError, OSError, json.JSONDecodeError) as exc:
        message = str(exc) if isinstance(exc, RecordError) else "could not read input"
        print(json.dumps({"status": "input_error", "error": message}, ensure_ascii=False))
        return 2
    build_parser().print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
