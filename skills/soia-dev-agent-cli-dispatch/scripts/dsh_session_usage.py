#!/usr/bin/env python3
"""Read-only, privacy-filtered dsh session usage and evidence report (v3, v4).

Examples:
  python3 dsh_session_usage.py --session <uuid-or-prefix>
  python3 dsh_session_usage.py --marker <unique-prompt-marker>
  python3 dsh_session_usage.py --session <uuid-or-prefix> --with-title
  python3 dsh_session_usage.py --selftest

Session JSONL is decompressed in memory through the system `zstd` command. The
report contains metadata, model identifiers, aggregate usage and cost estimates;
it never emits message bodies, tool arguments/results, paths or raw approval text.

Supported on-disk formats are `session.v3.jsonl.zstd` and `session.v4.jsonl.zstd`.
When dsh migrates a session, both files can sit in one session directory; the
highest supported version is read. A session that only has an unknown format
exits with status `unsupported_format` (exit 4) instead of guessing.

Exit codes: 0 ok, 2 input_error, 3 selftest skipped (zstd missing),
4 unsupported_format, 1 selftest failure.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterator

import catalog_lib
import estimate_cost


CATALOG_PATH = Path(__file__).resolve().parents[1] / "references" / "model-catalog.yml"
TOKEN_FIELDS = (
    "inputTokens",
    "outputTokens",
    "cacheReadTokens",
    "cacheWriteTokens",
    "reasoningTokens",
    "totalTokens",
)
REQUIRED_COST_FIELDS = ("inputTokens", "outputTokens", "cacheReadTokens", "cacheWriteTokens")
SAFE_LABEL = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
SAFE_EFFORT = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
SECRET_TEXT_PATTERNS = (
    re.compile(r"(?i)\b(?:sk-[A-Za-z0-9_-]{12,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|xox[abp]-[A-Za-z0-9-]{10,})\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{12,}=?"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:password|secret|token)\s*=\s*[^\s,;]+"),
    re.compile(r"\b[A-Za-z0-9_-]{32,}\b"),
)
LOCAL_PATH_PATTERNS = (
    re.compile(r"(?i)(?:/Users|/home)/[^/\\\s]+/"),
    re.compile(r"(?i)[A-Z]:\\Users\\[^\\/\s]+\\"),
)
SESSION_PREFIX = re.compile(r"^[0-9a-fA-F-]+$")
SESSION_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
RETRY_POLICY_KEYS = {"EMPTY_RESPONSE", "RATE_LIMIT", "SERVER", "TIMEOUT", "TRANSPORT"}
SUPPORTED_FORMATS = (4, 3)  # preference order: newest first
SESSION_FILE_RE = re.compile(r"^session\.v([0-9]+)\.jsonl\.zstd$")
SAFE_CODE = re.compile(r"^[A-Z0-9_]{1,40}$")
SAFE_KIND = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


class InputError(Exception):
    """An input, dependency, or local session-read error safe to display."""


class UnsupportedFormat(InputError):
    """The selected session exists but its on-disk format is not understood."""


def _label(value: Any) -> str | None:
    if isinstance(value, str):
        if _contains_secret(value):
            return "<redacted>"
        if SAFE_LABEL.fullmatch(value):
            return value
        return "<redacted>"
    return None


def _effort(value: Any) -> str | None:
    if isinstance(value, str):
        if _contains_secret(value):
            return "<redacted>"
        if SAFE_EFFORT.fullmatch(value):
            return value
        return "<redacted>"
    return None


def _contains_secret(value: str) -> bool:
    return any(pattern.search(value) for pattern in SECRET_TEXT_PATTERNS)


def _rewrite_local_paths(value: str) -> str:
    rewritten = value
    for pattern in LOCAL_PATH_PATTERNS:
        rewritten = pattern.sub("~/", rewritten)
    return rewritten


def _identity(provider: Any, model: Any, effort: Any = None) -> tuple[str, str, str | None]:
    return (_label(provider) or "unknown", _label(model) or "unknown", _effort(effort))


def _timestamp(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    try:
        return dt.datetime.fromtimestamp(value / 1000, tz=dt.timezone.utc).isoformat(timespec="milliseconds")
    except (OverflowError, OSError, ValueError):
        return None


def _time_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return float(value)


def _safe_title(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join("".join(ch for ch in _rewrite_local_paths(value) if ch.isprintable()).split())
    for pattern in SECRET_TEXT_PATTERNS:
        normalized = pattern.sub("<redacted>", normalized)
    if not SAFE_LABEL.fullmatch(normalized):
        return "<redacted>"
    return normalized[:40]


def _user_texts(data: dict[str, Any]) -> Iterator[str]:
    content = data.get("content")
    if isinstance(content, str):
        yield content
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, str):
                yield item
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                yield item["text"]


def _iter_events(path: Path) -> Iterator[dict[str, Any]]:
    if shutil.which("zstd") is None:
        raise InputError("zstd is required; install the zstd command-line tool")
    try:
        process = subprocess.Popen(
            ["zstd", "-dc", os.fspath(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        raise InputError("zstd is required; install the zstd command-line tool") from exc
    assert process.stdout is not None
    try:
        for raw_line in process.stdout:
            try:
                event = json.loads(raw_line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if isinstance(event, dict):
                yield event
    finally:
        closing_early = sys.exc_info()[0] is GeneratorExit
        process.stdout.close()
        if closing_early and process.poll() is None:
            process.terminate()
        code = process.wait()
        if code != 0 and not closing_early:
            raise InputError("could not decompress a dsh session file")


def _format_versions(session_dir: Path) -> list[int]:
    versions = []
    for path in session_dir.iterdir():
        match = SESSION_FILE_RE.fullmatch(path.name)
        if match and path.is_file():
            versions.append(int(match.group(1)))
    return sorted(versions, reverse=True)


def _session_dirs(dsh_home: Path) -> list[Path]:
    """Every `session-*` directory holding at least one `session.vN` file."""
    return sorted({path.parent for path in dsh_home.glob("sessions/*/session-*/session.v*.jsonl.zstd")})


def _session_format(session_dir: Path) -> int:
    versions = _format_versions(session_dir)
    for version in SUPPORTED_FORMATS:
        if version in versions:
            return version
    found = ", ".join(f"v{version}" for version in versions) or "none"
    supported = ", ".join(f"v{version}" for version in sorted(SUPPORTED_FORMATS))
    raise UnsupportedFormat(f"unsupported dsh session format ({found}); supported: {supported}")


def _session_file(session_dir: Path, version: int | None = None) -> Path:
    version = _session_format(session_dir) if version is None else version
    return session_dir / f"session.v{version}.jsonl.zstd"


def _find_by_session(dsh_home: Path, requested: str) -> Path:
    if not SESSION_PREFIX.fullmatch(requested):
        raise InputError("session must be a UUID or hexadecimal UUID prefix")
    prefix = f"session-{requested.lower()}"
    matches = [path for path in _session_dirs(dsh_home) if path.name.lower().startswith(prefix)]
    if len(matches) != 1:
        raise InputError("session selector must match exactly one session")
    if not SESSION_UUID.fullmatch(matches[0].name.removeprefix("session-")):
        raise InputError("selected session has an invalid identifier")
    return matches[0]


def _marker_texts(event: dict[str, Any]) -> Iterator[str]:
    """User-authored text: v3/v4 `user/message`, plus v4 inbox splices."""
    data = event.get("data")
    if not isinstance(data, dict):
        return
    if event.get("type") == "user/message":
        yield from _user_texts(data)
    elif event.get("type") == "agent/inbox/spliced":
        inserted = data.get("inserted")
        for item in inserted if isinstance(inserted, list) else []:
            if isinstance(item, dict) and item.get("role") == "user":
                yield from _user_texts(item)


def _find_by_marker(dsh_home: Path, marker: str) -> Path:
    if not marker or not marker.strip():
        raise InputError("marker must not be empty")
    matches: list[Path] = []
    unsupported = 0
    for session_dir in _session_dirs(dsh_home):
        try:
            session_file = _session_file(session_dir)
        except UnsupportedFormat:
            unsupported += 1
            continue
        found = False
        for event in _iter_events(session_file):
            if any(marker in text for text in _marker_texts(event)):
                found = True
                break
        if found:
            matches.append(session_dir)
            if len(matches) > 1:
                raise InputError("marker must identify exactly one session")
    if not matches and unsupported:
        raise UnsupportedFormat(
            f"marker matched no supported session; {unsupported} session(s) use an unsupported format"
        )
    if len(matches) != 1:
        raise InputError("marker must identify exactly one session")
    if not SESSION_UUID.fullmatch(matches[0].name.removeprefix("session-")):
        raise InputError("selected session has an invalid identifier")
    return matches[0]


def _numeric_tokens(usage: dict[str, Any]) -> dict[str, int]:
    return {
        field: value
        for field in TOKEN_FIELDS
        if type(value := usage.get(field)) is int and value >= 0
    }


def _reason_category(value: Any) -> str:
    """Map private approval prose to a small, non-reversible category label."""
    if not isinstance(value, str):
        return "policy_review"
    normalized = value.lower()
    if "glob" in normalized and ("quote" in normalized or "unquoted" in normalized):
        return "unquoted_glob"
    if "grep" in normalized and ("dialect" in normalized or "syntax" in normalized):
        return "grep_syntax_compatibility"
    return "command_risk_policy"


def _denied(outcome: Any, data: dict[str, Any]) -> bool:
    if data.get("approved") is False or data.get("allowed") is False:
        return True
    if not isinstance(outcome, str):
        return False
    return outcome.strip().lower() in {"deny", "denied", "reject", "rejected", "block", "blocked"}


def _policy_models(value: Any) -> list[dict[str, str | None]]:
    found: list[dict[str, str | None]] = []

    def add(item: Any) -> None:
        if isinstance(item, str):
            parts = item.split("/", 1)
            if len(parts) == 2:
                provider, model = _label(parts[0]), _label(parts[1])
            else:
                provider, model = None, _label(item)
            if model:
                found.append({"provider": provider, "model": model})
        elif isinstance(item, dict):
            provider, model = _label(item.get("provider")), _label(item.get("model"))
            if model:
                found.append({"provider": provider, "model": model})
            else:
                for nested in item.values():
                    if isinstance(nested, (dict, list, str)):
                        add(nested)
        elif isinstance(item, list):
            for nested in item:
                add(nested)

    add(value)
    unique = {(row["provider"], row["model"]): row for row in found}
    return [unique[key] for key in sorted(unique, key=lambda pair: (pair[0] or "", pair[1] or ""))]


def _tool_model(arguments: Any) -> tuple[str, str, str | None] | None:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return None
    if not isinstance(arguments, dict):
        return None
    candidate = arguments
    if isinstance(arguments.get("model"), dict):
        candidate = arguments["model"]
    provider, model = _label(candidate.get("provider")), _label(candidate.get("model"))
    if not provider or not model:
        return None
    effort = _effort(candidate.get("reasoningEffort") or candidate.get("effort"))
    return provider, model, effort


def _usage_object(data: dict[str, Any]) -> dict[str, Any] | None:
    message = data.get("message")
    if isinstance(message, dict) and isinstance(message.get("usage"), dict):
        return message["usage"]
    usage = data.get("usage")
    return usage if isinstance(usage, dict) else None


def _request_config(data: dict[str, Any]) -> tuple[str, str, str | None] | None:
    header = data.get("header")
    config = header.get("config") if isinstance(header, dict) else None
    if not isinstance(config, dict):
        return None
    provider, model = _label(config.get("provider")), _label(config.get("model"))
    if not provider or not model:
        return None
    return provider, model, _effort(config.get("reasoningEffort"))


def _selection(data: dict[str, Any]) -> tuple[str, str, str | None] | None:
    if not isinstance(data, dict):
        return None
    provider, model = _label(data.get("provider")), _label(data.get("model"))
    if not provider or not model:
        return None
    return provider, model, _effort(data.get("reasoningEffort"))


def _message_source(data: dict[str, Any]) -> tuple[str, str] | None:
    """v4 assistant messages name the model that produced them."""
    message = data.get("message")
    source = message.get("source") if isinstance(message, dict) else None
    if not isinstance(source, dict) or source.get("kind") != "model":
        return None
    provider, model = _label(source.get("provider")), _label(source.get("model"))
    if not provider or not model:
        return None
    return provider, model


def _stream_usage(data: dict[str, Any]) -> dict[str, Any] | None:
    """Usage reported inside a v4 `assistant/attempt` stream (an attempt that was not kept)."""
    stream = data.get("stream")
    found: dict[str, Any] | None = None
    for item in stream if isinstance(stream, list) else []:
        chunk = item.get("chunk") if isinstance(item, dict) else None
        if isinstance(chunk, dict) and chunk.get("type") == "usage" and isinstance(chunk.get("usage"), dict):
            found = chunk["usage"]
    return found


def _usage_with_inferred_cache(usage: dict[str, Any], safe: dict[str, Any]) -> dict[str, int]:
    safe_usage = _numeric_tokens(usage)
    missing_cache = {
        field for field in ("cacheReadTokens", "cacheWriteTokens")
        if field not in safe_usage
    }
    # dsh may omit a zero-valued cache counter. Infer zero only if
    # totalTokens independently reconciles to all available input,
    # output and cache counters for this message.
    if (
        missing_cache
        and all(field in safe_usage for field in ("inputTokens", "outputTokens", "totalTokens"))
        and safe_usage["totalTokens"] == sum(
            safe_usage.get(field, 0)
            for field in ("inputTokens", "outputTokens", "cacheReadTokens", "cacheWriteTokens")
        )
    ):
        safe_usage.update({field: 0 for field in missing_cache})
        safe["cache_metrics_inferred_zero"] = True
    return safe_usage


def _read_report(session_dir: Path, *, with_title: bool, marker: str | None = None) -> dict[str, Any]:
    format_version = _session_format(session_dir)
    events: list[dict[str, Any]] = []
    marker_found = False
    raw_title: str | None = None
    first_time: float | None = None
    last_time: float | None = None
    header_version: int | None = None
    for index, event in enumerate(_iter_events(_session_file(session_dir, format_version))):
        event_type = event.get("type")
        if event_type == "session" and "data" not in event:
            version = event.get("version")
            header_version = version if type(version) is int else None
            if header_version is not None and header_version != format_version:
                raise UnsupportedFormat(
                    f"session header declares v{header_version} but file is v{format_version}"
                )
            continue
        data = event.get("data")
        if not isinstance(data, dict):
            continue
        event_time = _time_number(event.get("time"))
        if event_time is not None:
            first_time = event_time if first_time is None else min(first_time, event_time)
            last_time = event_time if last_time is None else max(last_time, event_time)

        if marker and not marker_found:
            marker_found = any(marker in text for text in _marker_texts(event))

        sequence = event.get("seq")
        safe: dict[str, Any] = {
            "index": index,
            "sequence": sequence if type(sequence) is int and sequence >= 0 else None,
            "time_number": event_time,
            "time": _timestamp(event.get("time")),
            "type": event_type,
        }
        if event_type == "session/title":
            candidate = data.get("title") or data.get("name")
            if isinstance(candidate, str):
                raw_title = candidate
        elif event_type == "request/header":
            safe["identity"] = _request_config(data)
        elif event_type == "model/selection":
            safe["identity"] = _selection(data)
        elif event_type == "assistant/message":
            usage = _usage_object(data)
            if usage is not None:
                safe["usage"] = _usage_with_inferred_cache(usage, safe)
                safe["source_identity"] = _message_source(data)
        elif event_type == "assistant/attempt":
            usage = _stream_usage(data)
            if usage is None:
                continue
            safe["usage"] = _usage_with_inferred_cache(usage, safe)
            safe["usage_kind"] = "aborted_attempt"
        elif event_type == "compaction/summary":
            usage = data.get("usage")
            if not isinstance(usage, dict):
                continue
            safe["usage"] = _usage_with_inferred_cache(usage, safe)
            safe["usage_kind"] = "compaction_summary"
            provider, model = _label(data.get("provider")), _label(data.get("model"))
            safe["source_identity"] = (provider, model) if provider and model else None
        elif event_type == "turn/end":
            reason = data.get("reason") if isinstance(data.get("reason"), dict) else {}
            kind = reason.get("kind")
            error = reason.get("error") if isinstance(reason.get("error"), dict) else {}
            code = error.get("code")
            safe["turn_end_kind"] = kind if isinstance(kind, str) and SAFE_KIND.fullmatch(kind) else "unknown"
            safe["turn_end_error_code"] = code if isinstance(code, str) and SAFE_CODE.fullmatch(code) else (None if code is None else "unknown")
        elif event_type == "subagent/model-selection-policy":
            safe["allowed_models"] = _policy_models(data.get("allowedModels"))
        elif event_type == "tool/call" and data.get("name") == "subagent":
            safe["child_identity"] = _tool_model(data.get("arguments"))
        elif event_type == "llm/retry":
            failure = data.get("failure") if isinstance(data.get("failure"), dict) else {}
            raw_category = failure.get("code") or data.get("policyKey") or failure.get("policyKey")
            if not isinstance(raw_category, str):
                raw_category = "unknown"
            normalized_category = re.sub(r"[^A-Z0-9]+", "_", raw_category.upper()).strip("_")
            raw_policy = data.get("policyKey") or failure.get("policyKey")
            if not isinstance(raw_policy, str):
                raw_policy = "unknown"
            normalized_policy = re.sub(r"[^A-Z0-9]+", "_", raw_policy.upper()).strip("_")
            safe["provider"] = _label(data.get("provider")) or "unknown"
            safe["failure_category"] = next(
                (known for known in sorted(RETRY_POLICY_KEYS) if known in normalized_category),
                "unknown",
            )
            safe["policy_key"] = next(
                (known for known in sorted(RETRY_POLICY_KEYS) if known in normalized_policy),
                "unknown",
            )
        elif event_type == "approval/asked":
            safe["approval_reason_category"] = _reason_category(data.get("reason"))
        elif event_type == "approval/decided":
            safe["approval_denied"] = _denied(data.get("outcome"), data)
        elif event_type == "compaction/start":
            pass
        elif event_type == "request/context":
            context = data.get("context") if isinstance(data.get("context"), dict) else data
            window = context.get("contextWindow") if isinstance(context, dict) else None
            safe["context_window"] = window if type(window) is int and window >= 0 else None
        else:
            continue
        events.append(safe)

    # Order by event time, use seq to disambiguate same-millisecond events, and
    # retain JSONL order as the final tie breaker.
    events.sort(key=lambda item: (
        item["time_number"] if item["time_number"] is not None else float("inf"),
        item["sequence"] if item["sequence"] is not None else item["index"],
        item["index"],
    ))
    request_counts: collections.Counter[tuple[str, str, str | None]] = collections.Counter()
    request_first_seen: dict[tuple[str, str, str | None], str | None] = {}
    request_last_seen: dict[tuple[str, str, str | None], str | None] = {}
    selections: list[dict[str, Any]] = []
    usage: dict[tuple[str, str, str | None, str], dict[str, Any]] = {}
    retry_counts: collections.Counter[tuple[str, str, str]] = collections.Counter()
    approval_reason_counts: collections.Counter[str] = collections.Counter()
    pending_approvals: collections.deque[str] = collections.deque()
    denied_count = 0
    compaction_count = 0
    context_windows: list[int] = []
    policies: collections.Counter[tuple[tuple[str | None, str | None], ...]] = collections.Counter()
    child_counts: collections.Counter[tuple[str, str, str | None, bool | None, str]] = collections.Counter()
    subagent_call_count = 0
    current_identity: tuple[str, str, str | None] | None = None
    current_request_identity: tuple[str, str, str | None] | None = None
    current_ui_identity: tuple[str, str, str | None] | None = None
    have_request_header = False
    current_allowed_models: list[dict[str, str | None]] = []
    unassigned_usage_count = 0
    turn_end_counts: collections.Counter[tuple[str, str | None]] = collections.Counter()
    last_turn_end: dict[str, str | None] | None = None

    for event in events:
        event_type = event["type"]
        identity = event.get("identity")
        if event_type == "request/header" and identity:
            current_identity = identity
            current_request_identity = identity
            have_request_header = True
            if identity not in request_first_seen:
                request_first_seen[identity] = event.get("time")
            request_last_seen[identity] = event.get("time")
            request_counts[identity] += 1
        elif event_type == "model/selection" and identity:
            current_ui_identity = identity
            if not have_request_header:
                current_identity = identity
            selections.append({
                "time": event.get("time"),
                "provider": identity[0],
                "model": identity[1],
                "reasoningEffort": identity[2],
            })
        elif event_type in {"assistant/message", "assistant/attempt", "compaction/summary"} and "usage" in event:
            source = event.get("source_identity")
            if source is not None:
                # v4 message source is the strongest per-message evidence; keep
                # the effort only when the active request header names the same model.
                effort = (
                    current_request_identity[2]
                    if current_request_identity is not None and current_request_identity[:2] == source
                    else None
                )
                usage_identity = (source[0], source[1], effort)
                attribution = event.get("usage_kind", "message_source")
            elif current_request_identity is not None:
                usage_identity = current_request_identity
                attribution = event.get("usage_kind", "request_header")
            elif current_ui_identity is not None:
                usage_identity = current_ui_identity
                attribution = "ui_fallback"
            else:
                usage_identity = ("unknown", "unknown", None)
                attribution = "unknown"
                unassigned_usage_count += 1
            bucket = usage.setdefault((*usage_identity, attribution), {
                "messages": 0,
                "sums": collections.Counter(),
                "present": collections.Counter(),
                "cache_metrics_inferred_zero_messages": 0,
            })
            bucket["messages"] += 1
            if event.get("cache_metrics_inferred_zero"):
                bucket["cache_metrics_inferred_zero_messages"] += 1
            for field, value in event["usage"].items():
                bucket["sums"][field] += value
                bucket["present"][field] += 1
        elif event_type == "subagent/model-selection-policy":
            allowed = event.get("allowed_models", [])
            policies[tuple((item.get("provider"), item.get("model")) for item in allowed)] += 1
            current_allowed_models = allowed
        elif event_type == "tool/call" and "child_identity" in event:
            subagent_call_count += 1
            child = event.get("child_identity")
            model_source = "tool_call_arguments"
            if child is None and len(current_allowed_models) == 1:
                policy_model = current_allowed_models[0]
                if policy_model.get("provider") and policy_model.get("model"):
                    child = (policy_model["provider"], policy_model["model"], None)
                    model_source = "single_allowed_model_policy"
            if child is None:
                child_counts[("unknown", "unknown", None, None, "unavailable")] += 1
            else:
                differs = current_identity is not None and (child[0], child[1]) != (current_identity[0], current_identity[1])
                child_counts[(child[0], child[1], child[2], differs, model_source)] += 1
        elif event_type == "llm/retry":
            retry_counts[(event.get("provider", "unknown"), event.get("failure_category", "unknown"), event.get("policy_key", "unknown"))] += 1
        elif event_type == "approval/asked":
            pending_approvals.append(event.get("approval_reason_category", "command_risk_policy"))
        elif event_type == "approval/decided":
            category = pending_approvals.popleft() if pending_approvals else "policy_review"
            if event.get("approval_denied"):
                denied_count += 1
                approval_reason_counts[category] += 1
        elif event_type == "compaction/start":
            compaction_count += 1
        elif event_type == "request/context" and event.get("context_window") is not None:
            context_windows.append(event["context_window"])
        elif event_type == "turn/end":
            turn_end_counts[(event["turn_end_kind"], event["turn_end_error_code"])] += 1
            last_turn_end = {"kind": event["turn_end_kind"], "error_code": event["turn_end_error_code"]}

    request_rows = [
        {
            "provider": provider,
            "model": model,
            "reasoningEffort": effort,
            "request_count": count,
            "first_request_at": request_first_seen[(provider, model, effort)],
            "last_request_at": request_last_seen[(provider, model, effort)],
        }
        for (provider, model, effort), count in request_counts.items()
    ]
    usage_rows: list[dict[str, Any]] = []
    cost_rows: list[dict[str, Any]] = []
    try:
        catalog = catalog_lib.load_catalog(CATALOG_PATH)
    except (OSError, catalog_lib.CatalogError):
        catalog = None

    for (provider, model, effort, attribution), bucket in sorted(
        usage.items(), key=lambda item: (item[0][0], item[0][1], item[0][2] or "", item[0][3])
    ):
        row: dict[str, Any] = {
            "provider": provider,
            "model": model,
            "reasoningEffort": effort,
            "attribution": attribution,
            "message_count": bucket["messages"],
            "cache_metrics_inferred_zero_messages": bucket["cache_metrics_inferred_zero_messages"],
        }
        for field in TOKEN_FIELDS:
            count = bucket["present"][field]
            row_field = {
                "inputTokens": "input_tokens_uncached",
                "outputTokens": "output_tokens",
                "cacheReadTokens": "cache_read_tokens",
                "cacheWriteTokens": "cache_write_tokens",
                "reasoningTokens": "reasoning_tokens",
                "totalTokens": "total_tokens",
            }[field]
            row[row_field] = bucket["sums"][field] if count else None
            if count and count != bucket["messages"]:
                row.setdefault("partial_fields", []).append(row_field)
        usage_rows.append(row)

        estimate_row: dict[str, Any] = {
            "provider": provider,
            "model": model,
            "reasoningEffort": effort,
            "attribution": attribution,
            "value": None,
            "value_decimal": None,
            "reason": None,
        }
        missing = [field for field in REQUIRED_COST_FIELDS if bucket["present"][field] != bucket["messages"]]
        if missing:
            estimate_row["reason"] = "usage is missing one or more required cost fields"
        elif catalog is None:
            estimate_row["reason"] = "model catalog could not be loaded"
        else:
            total_input = bucket["sums"]["inputTokens"] + bucket["sums"]["cacheReadTokens"]
            result = estimate_cost.estimate(
                catalog,
                model=model,
                input_tokens=total_input,
                output_tokens=bucket["sums"]["outputTokens"],
                cached_tokens=bucket["sums"]["cacheReadTokens"],
                cache_write_tokens=bucket["sums"]["cacheWriteTokens"],
            )
            estimate_row["value"] = result.get("total_cost")
            estimate_row["value_decimal"] = result.get("total_cost_decimal")
            estimate_row["reason"] = result.get("total_cost_unavailable_reason")
            estimate_row["confidence"] = result.get("confidence")
            estimate_row["pricing_source"] = result.get("pricing_source")
            estimate_row["pricing_effective_date"] = result.get("pricing_effective_date")
            if model == "deepseek-flash":
                estimate_row["pricing_period"] = "peak (catalog scalar)"
            elif model == "deepseek-v4-pro":
                estimate_row["pricing_period"] = "regular/off-peak (catalog scalar)"
        cost_rows.append(estimate_row)

    policy_rows = [
        {
            "allowedModels": [{"provider": provider, "model": model} for provider, model in policy],
            "policy_count": count,
        }
        for policy, count in sorted(policies.items(), key=lambda item: tuple((provider or "", model or "") for provider, model in item[0]))
    ]
    child_rows = [
        {
            "provider": provider,
            "model": model,
            "reasoningEffort": effort,
            "call_count": count,
            "differs_from_main_at_call": differs,
            "model_source": source,
        }
        for (provider, model, effort, differs, source), count in sorted(child_counts.items(), key=lambda item: tuple("" if part is None else str(part) for part in item[0]))
    ]
    known_comparison_calls = sum(
        count for (_, _, _, differs, _), count in child_counts.items() if differs is not None
    )
    report: dict[str, Any] = {
        "session_id": session_dir.name.removeprefix("session-"),
        "session_format": f"v{format_version}",
        "started_at": _timestamp(first_time),
        "ended_at": _timestamp(last_time),
        "request_models": request_rows,
        "ui_selections": selections,
        "usage_by_model": usage_rows,
        "subagents": {
            "call_count": subagent_call_count,
            "allowed_models_policies": policy_rows,
            "model_evidence": child_rows,
            "child_model_differs_from_main": any(key[3] is True for key in child_counts),
            "comparison_basis": "explicit tool-call model; otherwise singleton allowedModels policy",
            "comparison_complete": subagent_call_count > 0 and known_comparison_calls == subagent_call_count,
        },
        "retries": [
            {"provider": provider, "failure_category": category, "policy_key": policy, "count": count}
            for (provider, category, policy), count in sorted(retry_counts.items())
        ],
        "approvals": {
            "denied_count": denied_count,
            "denial_reason_categories": [
                {"category": category, "count": count}
                for category, count in sorted(approval_reason_counts.items())
            ],
        },
        "compactions": {"count": compaction_count},
        "turn_ends": [
            {"kind": kind, "error_code": code, "count": count}
            for (kind, code), count in sorted(turn_end_counts.items(), key=lambda item: (item[0][0], item[0][1] or ""))
        ],
        "last_turn_end": last_turn_end,
        "cost_estimate_usd": {"currency": "USD", "by_model": cost_rows},
        "context_windows_observed": sorted(set(context_windows)),
        "unassigned_usage_message_count": unassigned_usage_count,
    }
    if with_title:
        report["title"] = _safe_title(raw_title)
    report["marker_matched"] = marker_found if marker else None
    return report


def analyze(*, session: str | None, marker: str | None, dsh_home: str, with_title: bool = False) -> dict[str, Any]:
    home = Path(dsh_home).expanduser()
    if not home.is_dir():
        raise InputError("dsh home or sessions directory is unavailable")
    if session:
        session_dir = _find_by_session(home, session)
    elif marker is not None:
        session_dir = _find_by_marker(home, marker)
    else:
        raise InputError("provide exactly one of --session or --marker")
    report = _read_report(session_dir, with_title=with_title, marker=marker)
    if marker and not report.get("marker_matched"):
        raise InputError("marker did not match a user message in the selected session")
    return report


def _write_fixture_session(zstd: str, path: Path) -> str:
    sentinel = "BODY_SENTINEL_DO_NOT_PRINT_4f7c9a"
    title_sentinel = "sk-" + "r6-title-sentinel-abcdefghijklmnopqrstuvwxyz"
    events = [
        {"type": "session/title", "seq": 1, "time": 1000, "data": {"title": "/Users/xxx/private-project title-sentinel " + title_sentinel}},
        {"type": "user/message", "seq": 2, "time": 1100, "data": {"content": [{"type": "text", "text": "marker-R4-fixture " + sentinel}]}},
        {"type": "model/selection", "seq": 3, "time": 1150, "data": {"provider": "xiaomi", "model": "mimo-v2.6-pro-ultraspeed", "reasoningEffort": "max"}},
        {"type": "assistant/message", "seq": 4, "time": 1175, "data": {"message": {"content": [{"type": "text", "text": sentinel}], "usage": {"inputTokens": 5, "outputTokens": 2, "cacheReadTokens": 10, "cacheWriteTokens": 1, "totalTokens": 18}}}},
        {"type": "request/header", "seq": 5, "time": 1200, "data": {"header": {"config": {"provider": "deepseek-official", "model": "deepseek-flash", "reasoningEffort": "max", "maxTokens": 128}}}},
        {"type": "model/selection", "seq": 6, "time": 1250, "data": {"provider": "xiaomi", "model": "/Users/xxx/private-model", "reasoningEffort": "max"}},
        {"type": "assistant/message", "seq": 7, "time": 1300, "data": {"message": {"content": [{"type": "text", "text": sentinel}], "usage": {"inputTokens": 10, "outputTokens": 4, "cacheReadTokens": 90, "cacheWriteTokens": 5, "reasoningTokens": 2, "totalTokens": 111}}}},
        {"type": "request/header", "seq": 8, "time": 1500, "data": {"header": {"config": {"provider": "xiaomi", "model": "mimo-v2.6-flash", "reasoningEffort": "max", "maxTokens": 128}}}},
        {"type": "assistant/message", "seq": 9, "time": 1600, "data": {"message": {"content": [{"type": "text", "text": sentinel}], "usage": {"inputTokens": 20, "outputTokens": 8, "cacheReadTokens": 180, "cacheWriteTokens": 10, "totalTokens": 218}}}},
        {"type": "request/header", "seq": 10, "time": 1700, "data": {"header": {"config": {"provider": "xiaomi", "model": "mimo-v2.6-pro", "reasoningEffort": "xhigh", "maxTokens": 128}}}},
        {"type": "assistant/message", "seq": 11, "time": 1800, "data": {"message": {"content": [{"type": "text", "text": sentinel}], "usage": {"inputTokens": 30, "outputTokens": 12, "totalTokens": 42}}}},
        {"type": "subagent/model-selection-policy", "seq": 12, "time": 1900, "data": {"allowedModels": [{"provider": "deepseek-official", "model": "deepseek-flash"}]}},
        {"type": "tool/call", "seq": 13, "time": 2000, "data": {"name": "subagent", "arguments": json.dumps({"provider": "deepseek-official", "model": "deepseek-flash", "reasoningEffort": "max", "prompt": sentinel})}},
        {"type": "llm/retry", "seq": 14, "time": 2100, "data": {"provider": "xiaomi", "retry": 1, "maxRetries": 5, "policyKey": "EMPTY_RESPONSE", "failure": {"code": "TRANSPORT", "message": sentinel}}},
        {"type": "llm/retry", "seq": 15, "time": 2200, "data": {"provider": "xiaomi", "retry": 2, "maxRetries": 5, "policyKey": "EMPTY_RESPONSE", "failure": {"code": "TIMEOUT", "message": sentinel}}},
        {"type": "approval/asked", "seq": 16, "time": 2300, "data": {"toolName": "shell", "reason": "grep syntax differs across implementations; " + sentinel}},
        {"type": "approval/decided", "seq": 17, "time": 2400, "data": {"outcome": "denied"}},
        {"type": "compaction/start", "seq": 18, "time": 2500, "data": {}},
        {"type": "request/context", "seq": 19, "time": 2600, "data": {"context": {"contextWindow": 1000000}}},
        {"type": "request/header", "seq": 20, "time": 2700, "data": {"header": {"config": {"provider": "xiaomi", "model": "/Users/xxx/private-model", "reasoningEffort": "high", "maxTokens": 128}}}},
    ]
    payload = "".join(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n" for event in events).encode("utf-8")
    completed = subprocess.run([zstd, "-q", "-c"], input=payload, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if completed.returncode != 0:
        raise RuntimeError("could not create synthetic compressed session")
    path.write_bytes(completed.stdout)
    return sentinel + " " + title_sentinel


V4_FIXTURE_PATH = Path(__file__).resolve().parents[1] / "assets" / "fixtures" / "dsh-session-v4.redacted.jsonl"
V4_BODY_SENTINEL = "BODY_SENTINEL_V4_DO_NOT_PRINT_8e21"


def _compress(zstd: str, payload: bytes, path: Path) -> None:
    completed = subprocess.run([zstd, "-q", "-c"], input=payload, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if completed.returncode != 0:
        raise RuntimeError("could not create synthetic compressed session")
    path.write_bytes(completed.stdout)


def _v4_checks(zstd: str, root: Path, check: Any) -> None:
    """Exercise the redacted v4 fixture, v3/v4 coexistence, and unknown formats."""
    fixture = V4_FIXTURE_PATH.read_bytes()
    dsh_home = root / "dsh-home-v4"
    project = dsh_home / "sessions" / "fixture-project-v4"
    only_v4 = project / "session-00000000-0000-4000-8000-0000000000a4"
    both = project / "session-00000000-0000-4000-8000-0000000000b4"
    only_v5 = project / "session-00000000-0000-4000-8000-0000000000c5"
    mismatch = project / "session-00000000-0000-4000-8000-0000000000d4"
    for directory in (only_v4, both, only_v5, mismatch):
        directory.mkdir(parents=True, mode=0o700)
    _compress(zstd, fixture, only_v4 / "session.v4.jsonl.zstd")
    (only_v4 / "session.lock").write_bytes(b"")
    # A migrated session keeps its old v3 file next to v4; v4 must win.
    stale_v3 = json.dumps({"type": "assistant/message", "seq": 1, "time": 1, "data": {"message": {"usage": {
        "inputTokens": 999, "outputTokens": 999, "cacheReadTokens": 0, "cacheWriteTokens": 0, "totalTokens": 1998}}}}) + "\n"
    _compress(zstd, stale_v3.encode(), both / "session.v3.jsonl.zstd")
    _compress(zstd, fixture.replace(b"marker-V4-fixture", b"marker-V4-other"), both / "session.v4.jsonl.zstd")
    _compress(zstd, fixture.replace(b"marker-V4-fixture", b"marker-V5-fixture"), only_v5 / "session.v5.jsonl.zstd")
    _compress(zstd, fixture.replace(b'"version":4', b'"version":5', 1).replace(b"marker-V4-fixture", b"marker-V4-mismatch"),
              mismatch / "session.v4.jsonl.zstd")
    snapshot = {
        str(path.relative_to(dsh_home)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in dsh_home.rglob("*") if path.is_file()
    }

    report = analyze(session="00000000-0000-4000-8000-0000000000a4", marker=None, dsh_home=str(dsh_home))
    encoded = json.dumps(report, ensure_ascii=False)
    rows = {(row["model"], row["attribution"]): row for row in report["usage_by_model"]}
    check("v4-only session is located and reported as v4", report["session_format"] == "v4")
    check(
        "v4 usage is attributed by per-message source, not only the request header",
        rows.get(("deepseek-flash", "message_source"), {}).get("input_tokens_uncached") == 10
        and rows.get(("deepseek-flash", "message_source"), {}).get("reasoningEffort") == "max"
        and rows.get(("mimo-v2.6-flash", "message_source"), {}).get("input_tokens_uncached") == 20
        and rows.get(("mimo-v2.6-flash", "message_source"), {}).get("reasoningEffort") is None,
    )
    check(
        "v4 compaction summary and aborted attempt usage are reported as separate rows",
        rows.get(("mimo-v2.6-flash", "compaction_summary"), {}).get("input_tokens_uncached") == 40
        and rows.get(("deepseek-flash", "aborted_attempt"), {}).get("input_tokens_uncached") == 3
        and rows.get(("deepseek-flash", "aborted_attempt"), {}).get("cache_metrics_inferred_zero_messages") == 1,
    )
    check(
        "v4 turn end kinds and error codes are counted without messages",
        {(row["kind"], row["error_code"], row["count"]) for row in report["turn_ends"]}
        == {("error", "AUTH", 1), ("completed", None, 1)}
        and report["last_turn_end"] == {"kind": "completed", "error_code": None},
    )
    check(
        "v4 retries and flat request/context are read",
        report["retries"] == [{"provider": "deepseek-official", "failure_category": "TRANSPORT", "policy_key": "TRANSPORT", "count": 1}]
        and report["context_windows_observed"] == [1000000],
    )
    by_marker = analyze(session=None, marker="marker-V4-fixture", dsh_home=str(dsh_home))
    check("v4 marker is found in inbox-spliced user messages", by_marker["session_id"].endswith("0000000000a4") and by_marker["marker_matched"] is True)
    check(
        "v4 report omits bodies, header cwd, tool arguments and response ids",
        V4_BODY_SENTINEL not in encoded
        and "private-project-v4" not in encoded
        and V4_BODY_SENTINEL not in json.dumps(by_marker, ensure_ascii=False),
    )
    migrated = analyze(session="00000000-0000-4000-8000-0000000000b4", marker=None, dsh_home=str(dsh_home))
    check(
        "a migrated directory with v3 and v4 reads v4",
        migrated["session_format"] == "v4"
        and all(row["input_tokens_uncached"] != 999 for row in migrated["usage_by_model"]),
    )
    try:
        analyze(session="00000000-0000-4000-8000-0000000000c5", marker=None, dsh_home=str(dsh_home))
        unsupported_ok = False
    except UnsupportedFormat as exc:
        unsupported_ok = "v5" in str(exc)
    try:
        analyze(session="00000000-0000-4000-8000-0000000000d4", marker=None, dsh_home=str(dsh_home))
        mismatch_ok = False
    except UnsupportedFormat:
        mismatch_ok = True
    check("an unknown session format raises UnsupportedFormat instead of guessing", unsupported_ok)
    check("a header version that disagrees with the file name is rejected", mismatch_ok)
    completed = subprocess.run(
        [sys.executable, os.fspath(Path(__file__).resolve()), "--dsh-home", os.fspath(dsh_home), "--session", "00000000-0000-4000-8000-0000000000c5"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    check(
        "CLI exits 4 with status unsupported_format",
        completed.returncode == 4 and json.loads(completed.stdout).get("status") == "unsupported_format",
    )
    after = {
        str(path.relative_to(dsh_home)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in dsh_home.rglob("*") if path.is_file()
    }
    check("v4 analysis does not modify the dsh session directory", snapshot == after)


def run_selftest() -> int:
    zstd = shutil.which("zstd")
    if not zstd:
        print("=== dsh_session_usage.py selftest ===")
        print("SKIPPED: zstd unavailable")
        return 3

    checks: list[tuple[str, bool]] = []

    def check(name: str, ok: bool) -> None:
        checks.append((name, bool(ok)))

    try:
        with tempfile.TemporaryDirectory(prefix="soia-dev-agent-cli-dispatch-session-selftest-") as temp:
            root = Path(temp)
            dsh_home = root / "dsh-home"
            session_dir = dsh_home / "sessions" / "fixture-project" / "session-00000000-0000-4000-8000-000000000001"
            session_dir.mkdir(parents=True, mode=0o700)
            session_file = _session_file(session_dir, 3)
            sentinel = _write_fixture_session(zstd, session_file)
            file_snapshot = {
                str(path.relative_to(dsh_home)): (path.stat().st_mode, path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())
                for path in dsh_home.rglob("*") if path.is_file()
            }

            by_session = analyze(session="00000000", marker=None, dsh_home=str(dsh_home))
            with_title = analyze(session="00000000", marker=None, dsh_home=str(dsh_home), with_title=True)
            by_marker = analyze(session=None, marker="marker-R4-fixture", dsh_home=str(dsh_home))
            encoded = json.dumps(by_session, ensure_ascii=False)
            identities = {(row["provider"], row["model"]): row for row in by_session["usage_by_model"]}
            check(
                "usage stays with request header A after UI selection changes to B",
                identities.get(("deepseek-official", "deepseek-flash"), {}).get("input_tokens_uncached") == 10
                and identities.get(("deepseek-official", "deepseek-flash"), {}).get("attribution") == "request_header"
                and identities.get(("xiaomi", "mimo-v2.6-flash"), {}).get("input_tokens_uncached") == 20
                and identities.get(("xiaomi", "mimo-v2.6-pro"), {}).get("input_tokens_uncached") == 30,
            )
            fallback_row = next((row for row in by_session["usage_by_model"] if row["model"] == "mimo-v2.6-pro-ultraspeed"), {})
            check(
                "UI selection is only a pre-header usage fallback",
                fallback_row.get("input_tokens_uncached") == 5 and fallback_row.get("attribution") == "ui_fallback",
            )
            check(
                "subagent policy and distinct child model are reported",
                by_session["subagents"]["call_count"] == 1
                and by_session["subagents"]["allowed_models_policies"][0]["allowedModels"] == [{"provider": "deepseek-official", "model": "deepseek-flash"}]
                and by_session["subagents"]["model_evidence"][0]["model_source"] == "tool_call_arguments"
                and by_session["subagents"]["child_model_differs_from_main"] is True,
            )
            check(
                "retry categories and denied approvals are counted without reason prose",
                {(row["provider"], row["failure_category"], row["policy_key"], row["count"]) for row in by_session["retries"]}
                == {("xiaomi", "TRANSPORT", "EMPTY_RESPONSE", 1), ("xiaomi", "TIMEOUT", "EMPTY_RESPONSE", 1)}
                and by_session["approvals"]["denied_count"] == 1
                and by_session["approvals"]["denial_reason_categories"] == [{"category": "grep_syntax_compatibility", "count": 1}],
            )
            check("marker locates the same session by user-message content", by_marker["session_id"] == by_session["session_id"] and by_marker["marker_matched"] is True)
            check("report omits message, prompt, tool, and approval body sentinel", sentinel not in encoded and sentinel not in json.dumps(by_marker, ensure_ascii=False))
            check("title is omitted by default", "title" not in by_session and "title" not in by_marker)
            title_encoded = json.dumps(with_title, ensure_ascii=False)
            check(
                "opt-in title is redacted and path-shaped model labels are suppressed",
                with_title.get("title") == "<redacted>"
                and sentinel not in title_encoded
                and "/Users/xxx/private-project" not in title_encoded
                and "private-project" not in title_encoded
                and "title-sentinel" not in title_encoded
                and "sk-" + "r6-title-sentinel" not in title_encoded
                and "/Users/xxx/private-model" not in encoded
                and "private-model" not in encoded
                and any(row["model"] == "<redacted>" for row in by_session["ui_selections"]),
            )
            check(
                "path-shaped request model is redacted from model evidence",
                any(row["model"] == "<redacted>" for row in by_session["request_models"]),
            )
            check(
                "local path rewriting covers Unix and Windows home paths",
                _rewrite_local_paths("/Users/xxx/a /home/xxx/b C:\\Users\\xxx\\c") == "~/a ~/b ~/c",
            )
            pro_usage = identities.get(("xiaomi", "mimo-v2.6-pro"), {})
            pro_cost = next(
                (item for item in by_session["cost_estimate_usd"]["by_model"] if item["model"] == "mimo-v2.6-pro"),
                {},
            )
            check(
                "missing zero cache counters are inferred only when totalTokens reconciles",
                pro_usage.get("cache_read_tokens") == 0
                and pro_usage.get("cache_write_tokens") == 0
                and pro_usage.get("cache_metrics_inferred_zero_messages") == 1
                and pro_cost.get("value") is not None,
            )
            after = {
                str(path.relative_to(dsh_home)): (path.stat().st_mode, path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())
                for path in dsh_home.rglob("*") if path.is_file()
            }
            check("analysis does not modify the dsh session directory", file_snapshot == after and len(after) == 1)
            check("cost estimate includes cache-read tokens", identities.get(("deepseek-official", "deepseek-flash"), {}).get("cache_read_tokens") == 90 and by_session["cost_estimate_usd"]["by_model"][0]["value"] is not None)
            _v4_checks(zstd, root, check)
    except Exception:
        checks.append(("selftest completed without exposing local/session content", False))

    print("=== dsh_session_usage.py selftest ===")
    for name, passed in checks:
        print(f"[{'PASS' if passed else 'FAIL'}] {name}")
    print(f"{sum(1 for _, ok in checks if ok)}/{len(checks)} checks passed")
    return 0 if checks and all(passed for _, passed in checks) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    selector = parser.add_mutually_exclusive_group()
    selector.add_argument("--session", help="Full session UUID or UUID prefix")
    selector.add_argument("--marker", help="Unique string from a user/message; used to locate a session by content")
    parser.add_argument("--dsh-home", default="~/.dsh", help="dsh home directory (default: ~/.dsh)")
    parser.add_argument("--with-title", action="store_true", help="include a sanitized session title (omitted by default)")
    parser.add_argument("--selftest", action="store_true", help="run offline synthetic compressed-session tests")
    args = parser.parse_args()

    if args.selftest:
        return run_selftest()
    try:
        if not args.session and args.marker is None:
            raise InputError("provide exactly one of --session or --marker")
        report = analyze(session=args.session, marker=args.marker, dsh_home=args.dsh_home, with_title=args.with_title)
    except UnsupportedFormat as exc:
        print(json.dumps({"status": "unsupported_format", "error": str(exc)}, ensure_ascii=False))
        return 4
    except InputError as exc:
        print(json.dumps({"status": "input_error", "error": str(exc)}, ensure_ascii=False))
        return 2
    except OSError:
        print(json.dumps({"status": "input_error", "error": "could not read dsh session data"}, ensure_ascii=False))
        return 2
    report["status"] = "ok"
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
