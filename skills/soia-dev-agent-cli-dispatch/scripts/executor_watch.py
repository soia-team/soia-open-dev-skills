#!/usr/bin/env python3
"""Liveness probe, bounded wait and exit-reason classification for dispatched CLIs.

Examples:
  python3 executor_watch.py probe --pid <pid> --log <stdout.log> --log <session-file>
  python3 executor_watch.py wait --pid <pid> --log <stdout.log> --interval 30 --idle-limit 900 --timeout 7200
  python3 executor_watch.py classify --executor dsh --stdout <out> --stderr <err> --exit-code 0
  python3 executor_watch.py classify --executor codex --stderr <err> --last-message <-o file> --exit-code 0
  python3 executor_watch.py --selftest

Liveness uses three signals, each sampled twice: the process (and its
descendants) exists, their summed CPU time grows, and watched log/session files
grow. One sample alone is not evidence; a truncated `head` of a log is never used.

`classify` reads captured output locally and returns only a category, an
outcome for usage records, a completion estimate and the ids of matched rules;
it never echoes the matched lines. Exit codes of dsh are 0 even for several
failures, so the text rules matter more than the exit code.

Exit codes: 0 ok (wait: process exited), 2 input error, 5 wait stalled
(idle limit reached), 6 wait timed out, 1 selftest failure.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable


EXIT_STALLED = 5
EXIT_TIMEOUT = 6

# (rule id, executor or "*", regex, category) — order matters: first match wins
# within a stream, but all matches are reported.
RULES: tuple[tuple[str, str, re.Pattern[str], str], ...] = (
    ("dsh_no_adapter", "dsh", re.compile(r"NO_ADAPTER: no adapter registered for provider"), "provider_not_registered"),
    ("dsh_session_missing", "dsh", re.compile(r'session "[^"]*" does not exist'), "session_not_found"),
    ("dsh_session_corrupt", "dsh", re.compile(r"failed to observe session .*corrupt session log"), "session_not_found"),
    ("git_lock_denied", "*", re.compile(r"\.git/\S*index\.lock\S*[：:]\s*Operation not permitted|index\.lock.*Operation not permitted"), "sandbox_git_write_denied"),
    ("sandbox_escalation_denied", "*", re.compile(r"sandbox escalation to \"?[a-z-]+\"? requires approval"), "sandbox_git_write_denied"),
    ("auth_error", "*", re.compile(r"(?i)\b(?:401 Unauthorized|invalid api key|not logged in|authentication failed|AUTH\b.*error)"), "auth"),
    ("quota_error", "*", re.compile(r"(?i)usage limit|usage_limit|quota exceeded|insufficient[_ ]balance|rate_limit_reached"), "quota"),
    ("rate_limited", "*", re.compile(r"(?i)\b429\b|rate limit(?:ed)?\b"), "rate_limit"),
    ("transport_error", "*", re.compile(r"(?i)stream disconnected|connection reset|ECONNRESET|TRANSPORT"), "transport"),
    ("unrecognized_args", "*", re.compile(r"error: unrecognized arguments"), "task_failed"),
)
# Executor stopped on purpose and handed a decision back: not a crash.
AWAITING_DECISION = re.compile(
    r"未修改|未提交|暂停|等待(?:你|您|主控)(?:的)?(?:选择|裁决|确认|决定)|未开始改动|需要(?:你|您|主控)裁决|"
    r"(?i:awaiting (?:your )?decision|paused for (?:a )?decision|no changes (?:were )?made|did not (?:modify|commit))"
)
BLOCKED_CATEGORIES = {"provider_not_registered", "session_not_found", "sandbox_git_write_denied",
                      "executor_blocked_awaiting_decision", "auth", "quota"}


class InputError(Exception):
    """Invalid input; message never carries private values."""


# ---------------------------------------------------------------------------
# liveness
# ---------------------------------------------------------------------------

def _cpu_seconds(text: str) -> float | None:
    """Parse ps TIME ([[dd-]hh:]mm:ss[.cc])."""
    text = text.strip()
    if not text:
        return None
    days = 0
    if "-" in text:
        day_text, text = text.split("-", 1)
        days = int(day_text)
    parts = [float(part) for part in text.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    hours, minutes, seconds = parts
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def _process_table() -> dict[int, tuple[int, float]]:
    """pid -> (ppid, cpu seconds) for every visible process."""
    completed = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,time="], stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, check=False)
    table: dict[int, tuple[int, float]] = {}
    for line in completed.stdout.splitlines():
        fields = line.split()
        if len(fields) < 3:
            continue
        try:
            table[int(fields[0])] = (int(fields[1]), _cpu_seconds(fields[2]) or 0.0)
        except ValueError:
            continue
    return table


def _tree(pid: int, table: dict[int, tuple[int, float]]) -> list[int]:
    children: dict[int, list[int]] = {}
    for child, (parent, _) in table.items():
        children.setdefault(parent, []).append(child)
    found, stack = [], [pid]
    while stack:
        current = stack.pop()
        if current in table:
            found.append(current)
            stack.extend(children.get(current, []))
    return found


def sample(pid: int, logs: list[Path], table_fn: Callable[[], dict[int, tuple[int, float]]] = _process_table) -> dict[str, Any]:
    table = table_fn()
    tree = _tree(pid, table)
    sizes = {}
    for index, path in enumerate(logs):
        try:
            sizes[index] = path.stat().st_size
        except OSError:
            sizes[index] = None
    return {
        "time": time.time(),
        "alive": pid in table,
        "process_count": len(tree),
        "cpu_seconds": round(sum(table[p][1] for p in tree), 2) if tree else None,
        "log_bytes": sizes,
    }


def compare(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    cpu_delta = None
    if first["cpu_seconds"] is not None and second["cpu_seconds"] is not None:
        cpu_delta = round(second["cpu_seconds"] - first["cpu_seconds"], 2)
    log_delta = {}
    for key, size in second["log_bytes"].items():
        before = first["log_bytes"].get(key)
        log_delta[key] = None if size is None or before is None else size - before
    grew = any(delta and delta > 0 for delta in log_delta.values())
    if not second["alive"]:
        state = "exited"
    elif (cpu_delta or 0) > 0.05 or grew:
        state = "alive_progressing"
    else:
        state = "alive_idle"
    return {
        "state": state,
        "interval_seconds": round(second["time"] - first["time"], 1),
        "process_count": second["process_count"],
        "cpu_delta_seconds": cpu_delta,
        "log_growth_bytes": [log_delta[key] for key in sorted(log_delta)],
    }


def probe(pid: int, logs: list[Path], interval: float, *, sleep: Callable[[float], None] = time.sleep,
          table_fn: Callable[[], dict[int, tuple[int, float]]] = _process_table) -> dict[str, Any]:
    first = sample(pid, logs, table_fn)
    if not first["alive"]:
        return {"state": "exited", "interval_seconds": 0, "process_count": 0, "cpu_delta_seconds": None,
                "log_growth_bytes": [None for _ in logs]}
    sleep(interval)
    return compare(first, sample(pid, logs, table_fn))


def wait(pid: int, logs: list[Path], *, interval: float, idle_limit: float, timeout: float | None,
         sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
         table_fn: Callable[[], dict[int, tuple[int, float]]] = _process_table) -> tuple[int, dict[str, Any]]:
    start = clock()
    idle_since: float | None = None
    probes = 0
    last: dict[str, Any] = {}
    while True:
        last = probe(pid, logs, interval, sleep=sleep, table_fn=table_fn)
        probes += 1
        now = clock()
        if last["state"] == "exited":
            return 0, {"result": "exited", "probes": probes, "elapsed_seconds": round(now - start, 1)}
        if last["state"] == "alive_idle":
            idle_since = idle_since if idle_since is not None else now - last["interval_seconds"]
            if now - idle_since >= idle_limit:
                return EXIT_STALLED, {"result": "stalled", "probes": probes, "idle_seconds": round(now - idle_since, 1),
                                      "elapsed_seconds": round(now - start, 1), "last": last}
        else:
            idle_since = None
        if timeout is not None and now - start >= timeout:
            return EXIT_TIMEOUT, {"result": "timeout", "probes": probes, "elapsed_seconds": round(now - start, 1), "last": last}


# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------

def classify(*, executor: str, stdout: str = "", stderr: str = "", last_message: str = "",
             exit_code: int | None = None, timed_out: bool = False) -> dict[str, Any]:
    text = f"{stdout}\n{stderr}"
    matched = [(rule_id, category) for rule_id, target, pattern, category in RULES
               if target in ("*", executor) and pattern.search(text)]
    awaiting = bool(last_message and AWAITING_DECISION.search(last_message))
    category: str | None
    if timed_out:
        category = "timeout"
    elif matched:
        # Environment/config blockers outrank generic transport noise.
        priority = ["provider_not_registered", "session_not_found", "auth", "quota", "sandbox_git_write_denied",
                    "rate_limit", "transport", "task_failed"]
        category = min((c for _, c in matched), key=lambda c: priority.index(c) if c in priority else len(priority))
    elif awaiting and exit_code in (0, None):
        category = "executor_blocked_awaiting_decision"
    elif exit_code not in (0, None):
        category = "task_failed"
    else:
        category = None
    if awaiting:
        matched.append(("last_message_awaiting_decision", "executor_blocked_awaiting_decision"))
    if category is None:
        outcome, completion = "passed", "complete"
    elif category in BLOCKED_CATEGORIES:
        outcome = "blocked"
        completion = "partial" if category == "sandbox_git_write_denied" else "none"
    else:
        outcome, completion = "failed", "unknown"
    return {
        "executor": executor,
        "exit_code": exit_code,
        "category": category,
        "outcome": outcome,
        "completion": completion,
        "matched_rules": sorted({rule for rule, _ in matched}),
        "notes": [
            "outcome is execution-level; the controller still verifies diffs and artifacts",
            "sandbox_git_write_denied: changes may remain uncommitted in the worktree; inspect and commit from the controller",
        ] if category == "sandbox_git_write_denied" else ["outcome is execution-level; the controller still verifies diffs and artifacts"],
    }


# ---------------------------------------------------------------------------
# selftest
# ---------------------------------------------------------------------------

def run_selftest() -> int:
    checks: list[tuple[str, bool]] = []

    def check(name: str, ok: bool) -> None:
        checks.append((name, bool(ok)))

    try:
        check("ps TIME parsing covers mm:ss, hh:mm:ss and days",
              _cpu_seconds("0:01.50") == 1.5 and _cpu_seconds("1:02:03") == 3723 and _cpu_seconds("2-00:00:01") == 172801)
        state = {"cpu": 10.0, "alive": True}

        def table() -> dict[int, tuple[int, float]]:
            if not state["alive"]:
                return {1: (0, 0.0)}
            return {1: (0, 0.0), 100: (1, state["cpu"]), 101: (100, 1.0)}

        with tempfile.TemporaryDirectory(prefix="soia-executor-watch-selftest-") as temp:
            log = Path(temp) / "out.log"
            log.write_text("a")

            def grow_cpu(_: float) -> None:
                state["cpu"] += 2.0

            result = probe(100, [log], 1, sleep=grow_cpu, table_fn=table)
            check("child CPU growth reads as alive_progressing", result["state"] == "alive_progressing"
                  and result["process_count"] == 2 and result["cpu_delta_seconds"] == 2.0)

            def grow_log(_: float) -> None:
                with log.open("a") as handle:
                    handle.write("more")

            result = probe(100, [log, Path(temp) / "missing.log"], 1, sleep=grow_log, table_fn=table)
            check("log growth alone reads as progressing; missing logs are null",
                  result["state"] == "alive_progressing" and result["log_growth_bytes"] == [4, None])
            result = probe(100, [log], 1, sleep=lambda _: None, table_fn=table)
            check("no CPU or log growth reads as alive_idle", result["state"] == "alive_idle")

            clock = {"t": 0.0}

            def tick(seconds: float) -> None:
                clock["t"] += seconds

            code, info = wait(100, [log], interval=60, idle_limit=180, timeout=None, sleep=tick,
                              clock=lambda: clock["t"], table_fn=table)
            check("wait reports stalled after the idle limit", code == EXIT_STALLED and info["result"] == "stalled")

            calls = {"n": 0}

            def exit_after_two(seconds: float) -> None:
                clock["t"] += seconds
                calls["n"] += 1
                state["cpu"] += 1
                if calls["n"] >= 2:
                    state["alive"] = False

            code, info = wait(100, [log], interval=30, idle_limit=600, timeout=None, sleep=exit_after_two,
                              clock=lambda: clock["t"], table_fn=table)
            check("wait returns 0 when the process exits", code == 0 and info["result"] == "exited")
            state["alive"] = True
            def tick_and_grow(seconds: float) -> None:
                clock["t"] += seconds
                state["cpu"] += 1

            code, info = wait(100, [log], interval=30, idle_limit=10_000, timeout=90, sleep=tick_and_grow,
                              clock=lambda: clock["t"], table_fn=table)
            check("wait honours the overall timeout", code == EXIT_TIMEOUT and info["result"] == "timeout")

        git_denied = classify(
            executor="dsh", exit_code=0,
            stdout="致命错误：无法创建 '<path>/.git/worktrees/wt/index.lock'：Operation not permitted\n"
                   'Error: sandbox escalation to "danger-full-access" requires approval, but no approval channel is available',
        )
        check("sandbox .git write denial is blocked/partial, not a crash",
              git_denied["category"] == "sandbox_git_write_denied" and git_denied["outcome"] == "blocked"
              and git_denied["completion"] == "partial" and "<path>" not in json.dumps(git_denied))
        no_adapter = classify(executor="dsh", exit_code=0, stderr='dsh: NO_ADAPTER: no adapter registered for provider "xiaomi"')
        check("NO_ADAPTER is provider_not_registered", no_adapter["category"] == "provider_not_registered" and no_adapter["outcome"] == "blocked")
        missing = classify(executor="dsh", exit_code=0,
                           stderr='dsh: session "abc" does not exist; omit --session-id to start a new Session')
        check("unknown dsh session is session_not_found", missing["category"] == "session_not_found")
        awaiting = classify(executor="codex", exit_code=0, last_message="结论：未修改、未提交，等待你选择方案 A 或 B。")
        check("codex handing back a decision is executor_blocked_awaiting_decision",
              awaiting["category"] == "executor_blocked_awaiting_decision" and awaiting["outcome"] == "blocked")
        bad_args = classify(executor="codex", exit_code=0, stderr="tool.py: error: unrecognized arguments: --write",
                            last_message="暂停，等待主控裁决")
        check("a concrete error outranks the awaiting-decision wording", bad_args["category"] == "task_failed"
              and "last_message_awaiting_decision" in bad_args["matched_rules"])
        quota = classify(executor="codex", exit_code=1, stderr="ERROR: You've hit your usage limit.")
        check("usage limit is quota/blocked", quota["category"] == "quota" and quota["outcome"] == "blocked")
        clean = classify(executor="codex", exit_code=0, last_message="已完成并提交。")
        check("clean exit is passed/complete", clean["category"] is None and clean["outcome"] == "passed")
        crashed = classify(executor="codex", exit_code=137)
        check("non-zero exit without a rule is task_failed", crashed["category"] == "task_failed" and crashed["outcome"] == "failed")
        check("timeout wins", classify(executor="dsh", timed_out=True)["category"] == "timeout")
    except Exception as exc:  # pragma: no cover
        checks.append((f"selftest raised {type(exc).__name__}", False))

    print("=== executor_watch.py selftest ===")
    for name, passed in checks:
        print(f"[{'PASS' if passed else 'FAIL'}] {name}")
    print(f"{sum(1 for _, ok in checks if ok)}/{len(checks)} checks passed")
    return 0 if checks and all(ok for _, ok in checks) else 1


def _read(path: str | None) -> str:
    return Path(path).expanduser().read_text(encoding="utf-8", errors="replace") if path else ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--selftest", action="store_true")
    sub = parser.add_subparsers(dest="command")
    for name in ("probe", "wait"):
        p = sub.add_parser(name)
        p.add_argument("--pid", type=int, required=True)
        p.add_argument("--log", action="append", default=[], help="log or session file whose growth shows progress (repeatable)")
        p.add_argument("--interval", type=float, default=10 if name == "probe" else 30)
        if name == "wait":
            p.add_argument("--idle-limit", type=float, default=900, help="seconds without CPU or log growth before 'stalled'")
            p.add_argument("--timeout", type=float, help="overall wall-clock limit in seconds")
    c = sub.add_parser("classify")
    c.add_argument("--executor", required=True, choices=["dsh", "codex", "claude", "pi", "agy", "qoder", "other"])
    c.add_argument("--stdout")
    c.add_argument("--stderr")
    c.add_argument("--last-message", help="codex -o file or the executor's final message")
    c.add_argument("--exit-code", type=int)
    c.add_argument("--timed-out", action="store_true")
    args = parser.parse_args(argv)
    if args.selftest:
        return run_selftest()
    try:
        if args.command == "probe":
            print(json.dumps(probe(args.pid, [Path(p).expanduser() for p in args.log], args.interval)))
            return 0
        if args.command == "wait":
            code, info = wait(args.pid, [Path(p).expanduser() for p in args.log], interval=args.interval,
                              idle_limit=args.idle_limit, timeout=args.timeout)
            print(json.dumps(info))
            return code
        if args.command == "classify":
            print(json.dumps(classify(executor=args.executor, stdout=_read(args.stdout), stderr=_read(args.stderr),
                                      last_message=_read(args.last_message), exit_code=args.exit_code,
                                      timed_out=args.timed_out), ensure_ascii=False))
            return 0
    except OSError:
        print(json.dumps({"status": "input_error", "error": "could not read an input file"}))
        return 2
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
