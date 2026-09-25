#!/usr/bin/env python3
"""Read-only, privacy-filtered codex session evidence: id, model, usage, resume template.

Examples:
  python3 codex_session_info.py --stderr-file <codex-stderr.log>
  python3 codex_session_info.py --session <uuid>
  python3 codex_session_info.py --stderr-file <log> --cwd-check "$PWD"
  python3 codex_session_info.py --selftest

Sources, strongest first:
  1. the rollout file `$CODEX_HOME/sessions/YYYY/MM/DD/rollout-*-<id>.jsonl`
     (`session_meta`, `turn_context`, `event_msg/token_count`, `task_complete`,
     `turn_aborted`); subagent threads link back through `session_meta.session_id`;
  2. the `codex exec` stderr header (`model:`, `provider:`, `reasoning effort:`,
     `sandbox:`, `approval:`, `session id:`).

Output never includes prompts, messages, tool calls, base instructions, git
remotes, account/credit data or the session working directory. The resume
command is a template with placeholders.

Exit codes: 0 ok, 2 input error, 1 selftest failure.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalog_lib  # noqa: E402
import estimate_cost  # noqa: E402


CATALOG_PATH = Path(__file__).resolve().parents[1] / "references" / "model-catalog.yml"
UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
SAFE_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
HEADER_FIELDS = {
    "model": "model",
    "provider": "provider",
    "reasoning effort": "reasoning_effort",
    "sandbox": "sandbox",
    "approval": "approval",
    "session id": "session_id",
}
HEADER_RE = re.compile(r"^(model|provider|reasoning effort|sandbox|approval|session id):\s*(\S+)\s*$", re.MULTILINE)
VERSION_RE = re.compile(r"^OpenAI Codex v(\S+)", re.MULTILINE)
USAGE_KEYS = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens",
              "reasoning_output_tokens", "total_tokens")


class InputError(Exception):
    """Input or local-read problem; message never carries private values."""


def _label(value: Any) -> str | None:
    return value if isinstance(value, str) and SAFE_LABEL.fullmatch(value) else None


def _iso(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch_iso(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return dt.datetime.fromtimestamp(value, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_header(text: str) -> dict[str, Any]:
    """Parse the `codex exec` stderr session header (first occurrence of each field)."""
    header: dict[str, Any] = {}
    for key, value in HEADER_RE.findall(text[:8000]):
        field = HEADER_FIELDS[key]
        if field not in header:
            header[field] = value if field == "session_id" and UUID.fullmatch(value) else _label(value)
    version = VERSION_RE.search(text[:2000])
    if version:
        header["cli_version"] = _label(version.group(1))
    return header


def _codex_home(value: str | None) -> Path:
    base = value or os.environ.get("CODEX_HOME") or "~/.codex"
    return Path(base).expanduser()


def _rollouts(home: Path) -> list[Path]:
    return sorted(home.glob("sessions/*/*/*/rollout-*.jsonl"))


def _find_rollout(home: Path, session_id: str) -> Path:
    if not UUID.fullmatch(session_id):
        raise InputError("session must be a full UUID")
    matches = [path for path in _rollouts(home) if path.name.endswith(f"-{session_id.lower()}.jsonl")]
    if len(matches) != 1:
        raise InputError("session id must match exactly one rollout file")
    return matches[0]


def _read_events(path: Path) -> list[dict[str, Any]]:
    events = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


def _first_meta(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and event.get("type") == "session_meta" and isinstance(event.get("payload"), dict):
                return event["payload"]
            return {}
    return {}


def _usage(total: dict[str, Any] | None) -> dict[str, Any]:
    """Map codex totals (input includes cached/cache-write) to dispatch fields."""
    if not isinstance(total, dict) or not all(type(total.get(key)) is int for key in ("input_tokens", "output_tokens")):
        return {"usage_status": "unavailable"}
    cached = total.get("cached_input_tokens") if type(total.get("cached_input_tokens")) is int else None
    cache_write = total.get("cache_write_input_tokens") if type(total.get("cache_write_input_tokens")) is int else 0
    uncached = total["input_tokens"] - (cached or 0) - cache_write if cached is not None else None
    return {
        "input_tokens": uncached if uncached is None or uncached >= 0 else None,
        "cached_input_tokens": cached,
        "cache_write_tokens": cache_write,
        "output_tokens": total["output_tokens"],
        "reasoning_tokens": total.get("reasoning_output_tokens") if type(total.get("reasoning_output_tokens")) is int else None,
        "total_tokens": total.get("total_tokens") if type(total.get("total_tokens")) is int else None,
        "usage_status": "measured" if uncached is not None and uncached >= 0 else "partial",
        "note": "codex input_tokens includes cached and cache-write tokens; input_tokens here is the uncached remainder",
    }


def _summarize_rollout(path: Path) -> dict[str, Any]:
    events = _read_events(path)
    meta: dict[str, Any] = {}
    turn_models: list[tuple[str | None, str | None, str | None, str | None]] = []
    last_total: dict[str, Any] | None = None
    rate: dict[str, Any] | None = None
    completes = 0
    aborts: dict[str, int] = {}
    first_ts = last_ts = None
    for event in events:
        ts = _iso(event.get("timestamp"))
        if ts:
            first_ts = ts if first_ts is None else min(first_ts, ts)
            last_ts = ts if last_ts is None else max(last_ts, ts)
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        kind = event.get("type")
        if kind == "session_meta" and not meta:
            meta = payload
        elif kind == "turn_context":
            sandbox = payload.get("sandbox_policy")
            turn_models.append((
                _label(payload.get("model")),
                _label(payload.get("effort")),
                _label(sandbox.get("type")) if isinstance(sandbox, dict) else None,
                _label(payload.get("approval_policy")),
            ))
        elif kind == "event_msg":
            ptype = payload.get("type")
            if ptype == "token_count":
                info = payload.get("info")
                if isinstance(info, dict) and isinstance(info.get("total_token_usage"), dict):
                    last_total = info["total_token_usage"]
                limits = payload.get("rate_limits")
                primary = limits.get("primary") if isinstance(limits, dict) else None
                if isinstance(primary, dict):
                    rate = {
                        "used_percent": primary.get("used_percent") if isinstance(primary.get("used_percent"), (int, float)) else None,
                        "window_minutes": primary.get("window_minutes") if type(primary.get("window_minutes")) is int else None,
                        "resets_at": _epoch_iso(primary.get("resets_at")),
                        "observed_at": ts,
                    }
            elif ptype == "task_complete":
                completes += 1
            elif ptype == "turn_aborted":
                reason = payload.get("reason") if isinstance(payload.get("reason"), str) and SAFE_LABEL.fullmatch(payload["reason"]) else "unknown"
                aborts[reason] = aborts.get(reason, 0) + 1
    models = sorted({(m, e) for m, e, _, _ in turn_models if m}, key=lambda item: (item[0], item[1] or ""))
    last_ctx = turn_models[-1] if turn_models else (None, None, None, None)
    return {
        "id": meta.get("id") if isinstance(meta.get("id"), str) and UUID.fullmatch(meta["id"]) else None,
        "parent_session_id": meta.get("session_id") if isinstance(meta.get("session_id"), str) and UUID.fullmatch(meta["session_id"]) else None,
        "thread_source": _label(meta.get("thread_source")),
        "originator": _label(meta.get("originator")),
        "cli_version": _label(meta.get("cli_version")),
        "model_provider": _label(meta.get("model_provider")),
        "models": [{"model": m, "reasoning_effort": e} for m, e in models],
        "last_turn": {"model": last_ctx[0], "reasoning_effort": last_ctx[1], "sandbox": last_ctx[2], "approval": last_ctx[3]},
        "turns": len(turn_models),
        "task_complete_count": completes,
        "turn_aborted": aborts,
        "started_at": first_ts,
        "ended_at": last_ts,
        "usage": _usage(last_total),
        "rate_limit_primary_last_seen": rate,
        "_cwd": meta.get("cwd") if isinstance(meta.get("cwd"), str) else None,
    }


def _estimate(model: str | None, usage: dict[str, Any]) -> dict[str, Any]:
    needed = ("input_tokens", "cached_input_tokens", "cache_write_tokens", "output_tokens")
    if not model or not all(type(usage.get(key)) is int for key in needed):
        return {"value": None, "reason": "model or usage split unavailable"}
    try:
        catalog = catalog_lib.load_catalog(CATALOG_PATH)
    except (OSError, catalog_lib.CatalogError):
        return {"value": None, "reason": "model catalog could not be loaded"}
    result = estimate_cost.estimate(
        catalog, model,
        input_tokens=usage["input_tokens"] + usage["cached_input_tokens"],
        output_tokens=usage["output_tokens"],
        cached_tokens=usage["cached_input_tokens"],
        cache_write_tokens=usage["cache_write_tokens"],
    )
    return {
        "value": result.get("total_cost"),
        "reason": result.get("total_cost_unavailable_reason"),
        "pricing_source": result.get("pricing_source"),
        "pricing_effective_date": result.get("pricing_effective_date"),
        "basis": "api_equivalent_estimate",
    }


def resume_template(session_id: str | None, model: str | None, effort: str | None, sandbox: str | None,
                    approval: str | None) -> str:
    """`codex exec resume` has no -s/-C: sandbox and approval go through -c, and cwd must match."""
    parts = ["cd <original-workdir> &&", "codex exec resume"]
    parts.append(f"-m {model}" if model else "-m <model>")
    parts.append(f"-c model_reasoning_effort='\"{effort}\"'" if effort else "-c model_reasoning_effort='\"<effort>\"'")
    parts.append(f"-c sandbox_mode='\"{sandbox}\"'" if sandbox else "-c sandbox_mode='\"<sandbox>\"'")
    if approval:
        parts.append(f"-c approval_policy='\"{approval}\"'")
    parts.append("-o <last-message-file>")
    parts.append(session_id or "<session-id>")
    parts.append('"$(cat <prompt-file>)"')
    return " ".join(parts)


def analyze(*, codex_home: str | None, session: str | None, stderr_text: str | None,
            cwd_check: str | None = None) -> dict[str, Any]:
    header = parse_header(stderr_text) if stderr_text else {}
    session_id = session or header.get("session_id")
    report: dict[str, Any] = {"session_id": session_id, "header": header or None}
    if not session_id:
        raise InputError("no session id: pass --session or a stderr file with a `session id:` line")
    home = _codex_home(codex_home)
    try:
        main_path = _find_rollout(home, session_id)
    except InputError:
        if not header:
            raise
        main_path = None
        report["rollout"] = None
        report["rollout_error"] = "rollout file not found for this session id"
    if main_path is not None:
        main = _summarize_rollout(main_path)
        cwd = main.pop("_cwd")
        report["rollout"] = main
        children = []
        for path in _rollouts(home):
            if path == main_path:
                continue
            meta = _first_meta(path)
            if meta.get("session_id") == session_id and meta.get("id") != session_id:
                child = _summarize_rollout(path)
                child.pop("_cwd")
                children.append({key: child[key] for key in ("thread_source", "models", "turns", "turn_aborted", "usage")})
        report["subagents"] = children
        if cwd_check is not None:
            report["cwd_matches"] = cwd is not None and os.path.realpath(os.path.expanduser(cwd_check)) == os.path.realpath(cwd)
    rollout = report.get("rollout") or {}
    last = rollout.get("last_turn") or {}
    model = last.get("model") or header.get("model")
    report["actual_model"] = model
    report["actual_model_source"] = "rollout_turn_context" if last.get("model") else ("stderr_header" if header.get("model") else "unverified")
    report["header_rollout_model_agree"] = (
        None if not (header.get("model") and last.get("model")) else header["model"] == last["model"]
    )
    usage = rollout.get("usage") or {"usage_status": "unavailable"}
    report["cost_estimate_usd"] = _estimate(model, usage)
    report["resume_command_template"] = resume_template(
        session_id if UUID.fullmatch(session_id) else None,
        model,
        last.get("reasoning_effort") or header.get("reasoning_effort"),
        last.get("sandbox") or header.get("sandbox"),
        last.get("approval") or header.get("approval"),
    )
    report["resume_notes"] = [
        "run from the session's original working directory: resume filters sessions by cwd (--all disables that)",
        "`codex exec resume` rejects -s/--sandbox and -C; pass sandbox/approval with -c",
        "rate_limit_primary_last_seen is a historical observation, not a live quota probe",
    ]
    return report


# ---------------------------------------------------------------------------
# selftest
# ---------------------------------------------------------------------------

def _write_fixture(home: Path, sentinel: str) -> tuple[str, str]:
    main_id = "01a0d43b-0000-7000-8000-00000000c0de"
    child_id = "01a0d43b-0000-7000-8000-00000000c1d0"
    day = home / "sessions" / "2026" / "09" / "25"
    day.mkdir(parents=True)

    def line(kind: str, payload: dict[str, Any], ts: str) -> str:
        return json.dumps({"timestamp": ts, "type": kind, "payload": payload}) + "\n"

    usage = {"input_tokens": 1000, "cached_input_tokens": 600, "cache_write_input_tokens": 0,
             "output_tokens": 50, "reasoning_output_tokens": 20, "total_tokens": 1050}
    main = [
        line("session_meta", {"id": main_id, "session_id": main_id, "originator": "codex_exec", "cli_version": "0.156.1",
                              "model_provider": "openai", "thread_source": "user", "cwd": "/Users/xxx/private-repo",
                              "git": {"repository_url": "https://example.com/" + sentinel},
                              "base_instructions": {"text": sentinel}}, "2026-09-25T01:00:00.000Z"),
        line("turn_context", {"model": "gpt-6-luna", "effort": "xhigh", "sandbox_policy": {"type": "danger-full-access"},
                              "approval_policy": "never", "cwd": "/Users/xxx/private-repo"}, "2026-09-25T01:00:01.000Z"),
        line("response_item", {"type": "message", "content": [{"text": sentinel}]}, "2026-09-25T01:00:02.000Z"),
        line("event_msg", {"type": "token_count", "info": {"total_token_usage": usage},
                           "rate_limits": {"primary": {"used_percent": 42.0, "window_minutes": 300, "resets_at": 1790000000},
                                           "credits": {"balance": "99"}, "plan_type": "secret-plan"}}, "2026-09-25T01:04:00.000Z"),
        line("event_msg", {"type": "turn_aborted", "reason": "interrupted"}, "2026-09-25T01:04:30.000Z"),
        line("event_msg", {"type": "task_complete", "last_agent_message": sentinel}, "2026-09-25T01:05:00.000Z"),
    ]
    (day / f"rollout-2026-09-25T01-00-00-{main_id}.jsonl").write_text("".join(main))
    child = [
        line("session_meta", {"id": child_id, "session_id": main_id, "thread_source": "subagent", "cwd": "/Users/xxx/private-repo"},
             "2026-09-25T01:01:00.000Z"),
        line("turn_context", {"model": "gpt-6-sol", "effort": "high", "sandbox_policy": {"type": "read-only"}}, "2026-09-25T01:01:01.000Z"),
        line("event_msg", {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 10, "cached_input_tokens": 0,
                                                                                  "output_tokens": 5, "total_tokens": 15}}},
             "2026-09-25T01:02:00.000Z"),
    ]
    (day / f"rollout-2026-09-25T01-01-00-{child_id}.jsonl").write_text("".join(child))
    return main_id, child_id


def run_selftest() -> int:
    checks: list[tuple[str, bool]] = []

    def check(name: str, ok: bool) -> None:
        checks.append((name, bool(ok)))

    sentinel = "BODY_SENTINEL_CODEX_DO_NOT_PRINT_5d1e"
    try:
        with tempfile.TemporaryDirectory(prefix="soia-codex-session-selftest-") as temp:
            home = Path(temp) / "codex-home"
            main_id, _ = _write_fixture(home, sentinel)
            stderr = ("OpenAI Codex v0.156.1\n--------\nworkdir: /Users/xxx/private-repo\nmodel: gpt-6-luna\nprovider: openai\n"
                      "approval: never\nsandbox: danger-full-access\nreasoning effort: xhigh\nreasoning summaries: none\n"
                      f"session id: {main_id}\n--------\n")
            report = analyze(codex_home=str(home), session=None, stderr_text=stderr, cwd_check="/Users/xxx/private-repo")
            encoded = json.dumps(report)
            check("header gives session id, model, effort, sandbox and version",
                  report["header"]["session_id"] == main_id and report["header"]["model"] == "gpt-6-luna"
                  and report["header"]["reasoning_effort"] == "xhigh" and report["header"]["cli_version"] == "0.156.1")
            check("rollout turn_context is the model evidence and agrees with the header",
                  report["actual_model"] == "gpt-6-luna" and report["actual_model_source"] == "rollout_turn_context"
                  and report["header_rollout_model_agree"] is True)
            usage = report["rollout"]["usage"]
            check("codex input total is split into uncached + cached",
                  usage["input_tokens"] == 400 and usage["cached_input_tokens"] == 600 and usage["output_tokens"] == 50
                  and usage["reasoning_tokens"] == 20 and usage["usage_status"] == "measured")
            check("subagent threads are linked by session_meta.session_id",
                  len(report["subagents"]) == 1 and report["subagents"][0]["models"][0]["model"] == "gpt-6-sol")
            check("aborts, completions and last-seen rate limit are reported",
                  report["rollout"]["turn_aborted"] == {"interrupted": 1} and report["rollout"]["task_complete_count"] == 1
                  and report["rollout"]["rate_limit_primary_last_seen"]["used_percent"] == 42.0)
            template = report["resume_command_template"]
            check("resume template uses -c for sandbox/approval and never -s/-C",
                  f"codex exec resume -m gpt-6-luna" in template and "sandbox_mode='\"danger-full-access\"'" in template
                  and "approval_policy='\"never\"'" in template and " -s " not in template and " -C " not in template
                  and template.startswith("cd <original-workdir>") and template.find(main_id) > 0)
            check("cwd is compared, not printed", report["cwd_matches"] is True and "private-repo" not in encoded)
            check("bodies, instructions, git remote, credits and plan are not emitted",
                  sentinel not in encoded and "secret-plan" not in encoded and "balance" not in encoded)
            try:
                analyze(codex_home=str(home), session="not-a-uuid", stderr_text=None)
                bad = False
            except InputError:
                bad = True
            check("invalid session id is an input error", bad)
            header_only = analyze(codex_home=str(Path(temp) / "empty"), session=None, stderr_text=stderr)
            check("header-only evidence works when the rollout is missing",
                  header_only["rollout"] is None and header_only["actual_model_source"] == "stderr_header")
    except Exception as exc:  # pragma: no cover
        checks.append((f"selftest raised {type(exc).__name__}", False))

    print("=== codex_session_info.py selftest ===")
    for name, passed in checks:
        print(f"[{'PASS' if passed else 'FAIL'}] {name}")
    print(f"{sum(1 for _, ok in checks if ok)}/{len(checks)} checks passed")
    return 0 if checks and all(ok for _, ok in checks) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", help="full session UUID")
    parser.add_argument("--stderr-file", help="captured `codex exec` stderr (session header)")
    parser.add_argument("--codex-home", help="codex home (default: $CODEX_HOME or ~/.codex)")
    parser.add_argument("--cwd-check", help="report whether this directory is the session's original cwd")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)
    if args.selftest:
        return run_selftest()
    try:
        stderr_text = Path(args.stderr_file).expanduser().read_text(encoding="utf-8", errors="replace") if args.stderr_file else None
        report = analyze(codex_home=args.codex_home, session=args.session, stderr_text=stderr_text, cwd_check=args.cwd_check)
    except InputError as exc:
        print(json.dumps({"status": "input_error", "error": str(exc)}))
        return 2
    except OSError:
        print(json.dumps({"status": "input_error", "error": "could not read codex session data"}))
        return 2
    report["status"] = "ok"
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
