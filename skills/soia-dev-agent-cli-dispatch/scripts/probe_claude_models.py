#!/usr/bin/env python3
# @created_by anthropic/claude-opus-5
# @created_at 2026-09-02 00:00:00
# @modified_by anthropic/claude-opus-5
# @modified_at 2026-09-02 00:00:00
# @version 0.1.0
# @description Probe which Claude Code model ids the local CLI actually serves, and detect fallbacks.
# @changelog Initial probe: stream-json system/assistant/result parsing, auxiliary-model exclusion, selftest fixtures.
"""Probe Claude Code model ids against the locally installed `claude` CLI.

Answers one question per model id: when you ask for it, what does the CLI
actually serve? Three outcomes are distinguished, because the 2026-09-02
probe (CLI 2.1.257) found all three in one run:

  exact         requested id was served
  fallback      a type=system event named a different fallback_model
  unrecognized  the CLI exited non-zero with [claude-code:unrecognized_model]

Each model is one real `-p` call, so this DOES consume quota/credits. It is
deliberately minimal (one turn, no tools, no MCP, no settings) and never
writes to the working directory. Run it from a neutral directory.

Usage:
    python3 probe_claude_models.py --models claude-opus-5,claude-sonnet-5
    python3 probe_claude_models.py --selftest   # fixtures only, no CLI calls
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_matrix  # noqa: E402

DEFAULT_PROMPT = "Reply with exactly the single word OK."
DEFAULT_TIMEOUT_SECONDS = 150


def build_command(model: str, prompt: str = DEFAULT_PROMPT) -> list[str]:
    """The exact isolated invocation used by the 2026-09-02 probe.

    `env -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT` matters: without it a probe
    launched from inside a Claude Code session inherits the host's own
    entrypoint markers. The empty MCP config must be
    {"mcpServers":{}} -- a bare {} is rejected before the model is reached.
    """
    return [
        "env", "-u", "CLAUDECODE", "-u", "CLAUDE_CODE_ENTRYPOINT",
        "claude", "-p",
        "--model", model,
        "--output-format", "stream-json",
        "--verbose",
        "--tools", "",
        "--max-turns", "1",
        "--setting-sources", "",
        "--mcp-config", '{"mcpServers":{}}',
        "--strict-mcp-config",
        "--", prompt,
    ]


def parse_probe_output(requested: str, stdout: str, stderr: str, returncode: int | None, seconds: float) -> dict[str, Any]:
    """Classify one probe result. Pure function -- no subprocess, fixture-testable."""
    unrecognized_match = run_matrix.CLAUDE_UNRECOGNIZED_MODEL_RE.search(f"{stdout}\n{stderr}")
    evidence = run_matrix.detect_claude_model_evidence(
        stdout, run_matrix.CLAUDE_AUXILIARY_MODEL_PREFIXES
    )
    if unrecognized_match:
        outcome = "unrecognized"
    elif evidence["fallback_model"]:
        outcome = "fallback"
    elif evidence["actual_model"] is None:
        outcome = "unverified"
    elif run_matrix._normalize_claude_model_id(evidence["actual_model"]) == requested:
        outcome = "exact"
    else:
        outcome = "mismatch"
    return {
        "requested": requested,
        "actual": evidence["actual_model"],
        "fallback": evidence["fallback_model"],
        "original_model": evidence["original_model"],
        "unrecognized": unrecognized_match.group(0).strip() if unrecognized_match else None,
        "evidence_source": evidence["evidence_source"],
        "outcome": outcome,
        "rc": returncode,
        "secs": round(seconds, 3),
    }


def probe_model(model: str, prompt: str = DEFAULT_PROMPT, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    cmd = build_command(model, prompt)
    start = time.monotonic()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_seconds)
        stdout, stderr, rc = proc.stdout or "", proc.stderr or "", proc.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        rc = None
    seconds = time.monotonic() - start
    result = parse_probe_output(model, stdout, stderr, rc, seconds)
    if rc is None:
        result["outcome"] = "timeout"
    return result


def run_selftest() -> int:
    """Fixture-only checks. Never invokes the CLI."""
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        checks.append((name, condition, detail))

    exact_stream = "\n".join([
        '{"type":"system","subtype":"init","model":"claude-fable-5-1"}',
        '{"type":"assistant","message":{"role":"assistant","model":"claude-fable-5-1"}}',
        '{"type":"result","subtype":"success","modelUsage":'
        '{"claude-haiku-4-5-20251001":{"inputTokens":900},"claude-fable-5-1":{"inputTokens":2}}}',
    ])
    exact = parse_probe_output("claude-fable-5-1", exact_stream, "", 0, 6.0)
    check(
        "exact: auxiliary model excluded, requested id confirmed",
        exact["outcome"] == "exact" and exact["actual"] == "claude-fable-5-1",
        f"{exact['outcome']} / {exact['actual']}",
    )

    fallback_stream = "\n".join([
        '{"type":"system","subtype":"init","model":"claude-fable-5"}',
        '{"type":"assistant","message":{"role":"assistant","model":"claude-opus-4-8"}}',
        '{"type":"system","subtype":"model_refusal_fallback",'
        '"original_model":"claude-fable-5","fallback_model":"claude-opus-4-8"}',
        '{"type":"result","subtype":"success","modelUsage":'
        '{"claude-haiku-4-5-20251001":{"inputTokens":900},"claude-opus-5":{"inputTokens":2}}}',
    ])
    fallback = parse_probe_output("claude-fable-5", fallback_stream, "", 0, 5.0)
    check(
        "fallback: system event wins over modelUsage and assistant echo",
        fallback["outcome"] == "fallback"
        and fallback["fallback"] == "claude-opus-4-8"
        and fallback["original_model"] == "claude-fable-5"
        and fallback["actual"] == "claude-opus-4-8",
        json.dumps(fallback, ensure_ascii=False),
    )

    unrecognized = parse_probe_output(
        "claude-sonnet-4-8",
        "",
        '[claude-code:unrecognized_model] {"model":"claude-sonnet-4-8","query_source":"sdk"}\n',
        1,
        5.0,
    )
    check(
        "unrecognized: stderr marker classified and kept verbatim",
        unrecognized["outcome"] == "unrecognized"
        and unrecognized["unrecognized"].startswith("[claude-code:unrecognized_model]")
        and unrecognized["actual"] is None,
        json.dumps(unrecognized, ensure_ascii=False),
    )

    empty = parse_probe_output("claude-opus-5", "", "", 0, 1.0)
    check(
        "no parseable evidence -> unverified, never the requested id echoed back",
        empty["outcome"] == "unverified" and empty["actual"] is None,
        json.dumps(empty, ensure_ascii=False),
    )

    cmd = build_command("claude-opus-5")
    check(
        "command keeps the isolation flags and the -- terminator",
        cmd[:5] == ["env", "-u", "CLAUDECODE", "-u", "CLAUDE_CODE_ENTRYPOINT"]
        and "--strict-mcp-config" in cmd
        and '{"mcpServers":{}}' in cmd
        and cmd[-2] == "--",
        " ".join(cmd),
    )

    print("=== probe_claude_models.py selftest ===")
    for name, passed, detail in checks:
        line = f"[{'PASS' if passed else 'FAIL'}] {name}"
        if detail and not passed:
            line += f" -- {detail}"
        print(line)
    passed_count = sum(1 for _, p, _ in checks if p)
    print(f"{passed_count}/{len(checks)} checks passed")
    return 0 if passed_count == len(checks) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", help="comma-separated Claude model ids to probe")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()

    if args.selftest:
        return run_selftest()
    if not args.models:
        parser.error("--models is required unless --selftest is used")
    if shutil.which("claude") is None:
        print(json.dumps({"error": "claude CLI not found on PATH"}, ensure_ascii=False), file=sys.stderr)
        return 2

    models = [item.strip() for item in args.models.split(",") if item.strip()]
    results = [probe_model(model, args.prompt, args.timeout_seconds) for model in models]
    print(json.dumps({
        "probed_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cli_version": run_matrix.probe_cli_version("claude"),
        "cwd": os.getcwd(),
        "results": results,
    }, ensure_ascii=False, indent=2))
    return 0 if all(r["outcome"] == "exact" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
