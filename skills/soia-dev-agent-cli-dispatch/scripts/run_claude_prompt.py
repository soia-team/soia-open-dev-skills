#!/usr/bin/env python3
# @created_by openai/gpt-5
# @created_at 2026-07-11
# @modified_by claude sonnet 5
# @modified_at 2026-09-14 18:10:00
# @version 0.3.1
# @description Run a Claude Code prompt file through stdin without shell quoting or option confusion.
# @changelog build_command now appends --verbose whenever --output-format
#            stream-json is requested: the real CLI (2.1.268, confirmed
#            2026-09-14 via a read-only argument-validation call that fails
#            before any model dispatch) rejects `--print --output-format
#            stream-json` without it ("Error: When using --print,
#            --output-format=stream-json requires --verbose"), matching the
#            already-verified command shape in probe_claude_models.py. Added
#            a selftest check on build_command's output directly (no
#            subprocess) so this is a regression on the command shape, not
#            just on run_streaming's fake child process.
"""Run a persisted prompt through Claude Code without putting it in argv.

Prompts may begin with YAML frontmatter (``---``), contain shell metacharacters,
or exceed a comfortable command-line length. Passing the prompt through stdin
avoids both shell interpolation and CLI option confusion.

The script writes Claude stdout unchanged to stdout so JSON mode remains
machine-readable. Diagnostics go to stderr.

``--output-format stream-json`` is streamed to our stdout line-by-line as the
child process emits it, so a long-running dispatch stays observable instead of
going silent until exit (which has caused a coordinator to misjudge a live
process as stuck). ``json``/``text`` modes keep the original buffered
behavior unchanged: those formats only emit a single payload at the end
regardless of transport, so streaming them would not add observability.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Sequence

DEFAULT_TIMEOUT_SECONDS = 900


def build_command(args: argparse.Namespace) -> list[str]:
    command = [
        args.claude_bin,
        "--permission-mode",
        args.permission_mode,
        "--print",
        "--output-format",
        args.output_format,
    ]
    if args.output_format == "stream-json":
        # Real CLI requirement (claude 2.1.268, verified 2026-09-14 against
        # a live --help-adjacent argument-validation error, not a model
        # call): `--print --output-format stream-json` without --verbose is
        # rejected before any dispatch happens. Must be present in every
        # stream-json command, not just the one in probe_claude_models.py.
        command.append("--verbose")
    if args.tools:
        command.extend(["--tools", args.tools])
    if args.model:
        command.extend(["--model", args.model])
    if args.effort:
        command.extend(["--effort", args.effort])
    if not args.persist_session:
        command.append("--no-session-persistence")
    return command


def run_with_stdin(command: Sequence[str], prompt: str, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        input=prompt,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def run_streaming(
    command: Sequence[str],
    prompt: str,
    timeout: int,
    line_sink=None,
) -> subprocess.CompletedProcess[str]:
    """Run ``command`` with ``prompt`` on stdin, writing each stdout line as it arrives.

    Unlike ``run_with_stdin`` (which buffers everything until the process
    exits), this streams stdout line-by-line to ``line_sink`` (defaults to
    ``sys.stdout``) while the child is still running, so a long task stays
    observable. Stdin is fed and stdout/stderr are drained on separate
    threads to avoid the classic deadlock (a child that fills its stdout pipe
    before we finish writing stdin). The real exit code and a real
    ``subprocess.TimeoutExpired`` (child killed, not left running) are always
    preserved -- this function does not fabricate progress or hide a stall.
    """
    sink = line_sink or sys.stdout
    proc = subprocess.Popen(  # noqa: S603
        list(command),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    def feed_stdin() -> None:
        try:
            assert proc.stdin is not None
            proc.stdin.write(prompt)
        except (BrokenPipeError, OSError):
            pass
        finally:
            if proc.stdin is not None:
                proc.stdin.close()

    stdout_chunks: list[str] = []

    def pump_stdout() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            stdout_chunks.append(line)
            sink.write(line)
            sink.flush()
        proc.stdout.close()

    stderr_holder: dict[str, str] = {"text": ""}

    def pump_stderr() -> None:
        assert proc.stderr is not None
        stderr_holder["text"] = proc.stderr.read()
        proc.stderr.close()

    threads = [
        threading.Thread(target=feed_stdin, daemon=True),
        threading.Thread(target=pump_stdout, daemon=True),
        threading.Thread(target=pump_stderr, daemon=True),
    ]
    start = time.monotonic()
    for thread in threads:
        thread.start()

    remaining = timeout - (time.monotonic() - start)
    try:
        proc.wait(timeout=max(remaining, 0))
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        for thread in threads:
            thread.join(timeout=5)
        raise subprocess.TimeoutExpired(list(command), timeout)

    for thread in threads:
        thread.join(timeout=5)

    return subprocess.CompletedProcess(
        list(command), proc.returncode, "".join(stdout_chunks), stderr_holder["text"]
    )


class _CapturingSink:
    """Stdout-like sink that timestamps each write, for proving liveness in the selftest."""

    def __init__(self) -> None:
        self.events: list[tuple[float, str]] = []
        self.start = time.monotonic()

    def write(self, data: str) -> None:
        self.events.append((time.monotonic() - self.start, data))

    def flush(self) -> None:
        pass


def _build_command_for_format(output_format: str) -> list[str]:
    """Construct the args.Namespace build_command needs, isolated from argparse defaults."""
    return build_command(
        argparse.Namespace(
            claude_bin="claude",
            permission_mode="auto",
            output_format=output_format,
            tools=None,
            model=None,
            effort=None,
            persist_session=False,
        )
    )


def run_selftest() -> int:
    prompt = "---\ntitle: regression fixture\n---\nReview this file.\n"
    probe = [
        sys.executable,
        "-c",
        (
            "import json,sys; data=sys.stdin.read(); "
            "print(json.dumps({'starts_with_yaml': data.startswith('---'), "
            "'chars': len(data)}))"
        ),
    ]
    result = run_with_stdin(probe, prompt, timeout=10)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = {}
    checks: dict[str, bool] = {
        "process_passed": result.returncode == 0,
        "yaml_frontmatter_reached_stdin": payload.get("starts_with_yaml") is True,
        "prompt_not_truncated": payload.get("chars") == len(prompt),
        "prompt_not_in_argv": prompt not in probe,
    }

    # build_command -> CLI invocation shape, checked directly on the argv list
    # (no subprocess at all): the real CLI rejects `--print --output-format
    # stream-json` without --verbose, so it must always be present for that
    # format and absent otherwise. This is a regression on build_command
    # itself, distinct from the run_streaming checks below which only prove
    # the streaming plumbing works against a fake child process.
    stream_json_command = _build_command_for_format("stream-json")
    checks["build_command_stream_json_includes_verbose"] = "--verbose" in stream_json_command
    checks["build_command_json_omits_verbose"] = "--verbose" not in _build_command_for_format("json")
    checks["build_command_text_omits_verbose"] = "--verbose" not in _build_command_for_format("text")

    # json/text mode is unaffected by the streaming change: run_with_stdin still
    # buffers a single payload and hands back the whole, unmodified stdout text.
    json_probe = [
        sys.executable,
        "-c",
        "import json; print(json.dumps({'ok': True, 'model': 'probe-model', 'n': 42}))",
    ]
    json_result = run_with_stdin(json_probe, "", timeout=10)
    try:
        json_payload = json.loads(json_result.stdout)
    except json.JSONDecodeError:
        json_payload = {}
    checks["json_mode_stdout_stays_complete_and_valid"] = (
        json_result.returncode == 0
        and json_payload == {"ok": True, "model": "probe-model", "n": 42}
    )

    # stream-json liveness: a line printed before a sleep must reach the sink
    # well before the process exits. A buffered implementation (the old
    # capture_output behavior) would deliver both lines at the same instant,
    # at or after the sleep -- so this is a falsifiable liveness check, not a
    # timing tolerance.
    stream_probe = [
        sys.executable,
        "-c",
        "import sys, time\n"
        "print('first'); sys.stdout.flush()\n"
        "time.sleep(0.3)\n"
        "print('second'); sys.stdout.flush()\n",
    ]
    stream_sink = _CapturingSink()
    stream_result = run_streaming(stream_probe, "", timeout=10, line_sink=stream_sink)
    total_elapsed = time.monotonic() - stream_sink.start
    first_line_elapsed = stream_sink.events[0][0] if stream_sink.events else None
    checks["stream_json_first_line_arrives_before_process_exits"] = (
        first_line_elapsed is not None
        and first_line_elapsed < 0.2
        and total_elapsed >= 0.25
    )
    checks["stream_json_full_stdout_still_assembled"] = stream_result.stdout == "first\nsecond\n"
    checks["stream_json_exit_code_zero_preserved"] = stream_result.returncode == 0

    # Non-zero exit codes must survive the streaming path unchanged.
    exit_probe = [sys.executable, "-c", "import sys; sys.exit(3)"]
    exit_result = run_streaming(exit_probe, "", timeout=10, line_sink=_CapturingSink())
    checks["stream_json_nonzero_exit_code_preserved"] = exit_result.returncode == 3

    # A hung child must be killed at the timeout, not left running silently
    # while we wait out its full sleep -- that is the exact "looked stuck"
    # failure mode this fix targets.
    timeout_probe = [sys.executable, "-c", "import time; time.sleep(5)"]
    timeout_start = time.monotonic()
    timed_out = False
    try:
        run_streaming(timeout_probe, "", timeout=1, line_sink=_CapturingSink())
    except subprocess.TimeoutExpired:
        timed_out = True
    timeout_elapsed = time.monotonic() - timeout_start
    checks["stream_json_timeout_kills_child_promptly"] = timed_out and timeout_elapsed < 3

    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
    return 0 if all(checks.values()) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a Claude Code prompt file through stdin and preserve stdout."
    )
    parser.add_argument("--prompt-file", type=Path, help="UTF-8 prompt file to send through stdin.")
    parser.add_argument("--claude-bin", default=os.environ.get("CLAUDE_BIN", "claude"))
    parser.add_argument("--model", help="Explicit Claude model id or alias.")
    parser.add_argument(
        "--effort",
        choices=["low", "medium", "high", "xhigh", "max"],
        help="Claude reasoning effort supported by the installed CLI.",
    )
    parser.add_argument("--permission-mode", default="auto")
    parser.add_argument("--tools", help="Comma-separated Claude tool allowlist, e.g. Read,Grep,Glob.")
    parser.add_argument(
        "--output-format",
        choices=["text", "json", "stream-json"],
        default="json",
    )
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--persist-session", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.selftest:
        return run_selftest()
    if args.prompt_file is None:
        print("ERROR: --prompt-file is required unless --selftest is used", file=sys.stderr)
        return 2
    if args.timeout <= 0:
        print("ERROR: --timeout must be positive", file=sys.stderr)
        return 2
    try:
        prompt = args.prompt_file.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"ERROR: cannot read prompt file: {exc}", file=sys.stderr)
        return 2
    if not prompt.strip():
        print("ERROR: prompt file is empty", file=sys.stderr)
        return 2

    command = build_command(args)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "command": command,
                    "prompt_file": str(args.prompt_file),
                    "prompt_chars": len(prompt),
                    "transport": "stdin",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    streaming = args.output_format == "stream-json"
    try:
        if streaming:
            # Already written to our stdout line-by-line as it arrived.
            result = run_streaming(command, prompt, timeout=args.timeout)
        else:
            result = run_with_stdin(command, prompt, timeout=args.timeout)
    except FileNotFoundError:
        print(f"ERROR: Claude CLI not found: {args.claude_bin}", file=sys.stderr)
        return 127
    except subprocess.TimeoutExpired:
        print(f"ERROR: Claude CLI timed out after {args.timeout}s", file=sys.stderr)
        return 124

    if not streaming and result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
