#!/usr/bin/env python3
# @created_by claude opus 5.5
# @created_at 2026-11-18 16:30:00
# @modified_by claude opus 5.5
# @modified_at 2026-11-18 16:30:00
# @version 0.1.0
# @description List each agy account slot's plan, quota windows, AI credits and models via official read-only commands.
# @changelog 0.1.0: first version; agy 1.5.10 print-mode /usage, /credits and `agy models`.
"""Per-slot Antigravity CLI (agy) quota overview.

For every agy slot (default login first, then `slot_rotation.agy` or the
declared agy slots) this runs only official read-only CLI commands that start
no model turn and spend no quota:

* ``agy -p "/usage" --output-format json``   -> model groups, 5h / weekly windows
* ``agy -p "/credits" --output-format json`` -> remaining AI credits
* ``agy models``                             -> model ids the account can use

It never reads credential files, logs or conversation stores, and never
prints raw CLI output: only parsed fields, with anything address-shaped
removed. agy 1.5.10 print mode has no plan/tier field (the tier is shown only
in the interactive banner), so ``plan`` is reported as not provided.
This is an observation for humans choosing a slot; it does not pick one.

Usage:
    python3 agy_quota.py [--slot <name> ...] [--json] [--skip-models]
    python3 agy_quota.py --selftest
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import account_slots  # noqa: E402
import resolve_storage  # noqa: E402

CLI = "agy"
NOT_PROVIDED = "CLI 不提供"
TIMEOUT_SECONDS = 90
EMAIL_RE = re.compile(r"[^\s@\"]+@[^\s@\"]+\.[A-Za-z]{2,}")
MODEL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,79}$")
GROUP_MODELS_PREFIX = "Models within this group:"
AUTH_HINT_RE = re.compile(r"(?i)sign[ -]?in|log[ -]?in|authenticat|verify your account|consent")

Runner = Callable[[list[str], dict[str, str]], tuple[int, str, str]]


def _scrub(text: Any) -> Any:
    return EMAIL_RE.sub("<redacted>", text) if isinstance(text, str) else text


def default_runner(command: list[str], env: dict[str, str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            command, env=env, capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
            cwd=tempfile.gettempdir(), stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return 127, "", "agy not found"
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _print_json(runner: Runner, env: dict[str, str], slash: str) -> tuple[dict[str, Any] | None, str | None]:
    code, out, err = runner([CLI, "-p", slash, "--output-format", "json"], env)
    payload = None
    for line in reversed(out.strip().splitlines()):
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            payload = candidate
            break
    if code == 0 and payload and payload.get("status") == "SUCCESS":
        return payload, None
    if code == 124:
        return None, "timeout"
    if code == 127:
        return None, "cli_missing"
    return None, "blocked_user_action" if AUTH_HINT_RE.search(f"{out}\n{err}") else "error"


def parse_usage(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = ((payload.get("command") or {}).get("data")) or {}
    groups = []
    for group in data.get("groups") or []:
        if not isinstance(group, dict):
            continue
        description = group.get("description") or ""
        models = None
        note = None
        if description.startswith(GROUP_MODELS_PREFIX):
            models = [item.strip() for item in description[len(GROUP_MODELS_PREFIX):].split(",") if item.strip()]
        elif description:
            note = _scrub(description)
        windows = []
        for bucket in group.get("buckets") or []:
            if not isinstance(bucket, dict):
                continue
            fraction = bucket.get("remaining_fraction")
            percent = round(float(fraction) * 100, 1) if isinstance(fraction, (int, float)) and not isinstance(fraction, bool) else None
            windows.append({
                "bucket_id": bucket.get("id"),
                "window": bucket.get("window"),
                "remaining_percent": percent,
                "reset_at": bucket.get("reset_time"),
            })
        groups.append({"group": group.get("name"), "models": models, "note": note, "windows": windows})
    return groups


def parse_models(stdout: str) -> list[str]:
    ids = []
    for line in stdout.splitlines():
        if "\t" not in line:
            continue  # progress lines such as "Fetching available models..."
        model_id = line.split("\t", 1)[0].strip()
        if MODEL_ID_RE.fullmatch(model_id):
            ids.append(model_id)
    return sorted(set(ids))


def probe_slot(resolved: dict[str, Any], runner: Runner, base_env: dict[str, str], *, skip_models: bool = False) -> dict[str, Any]:
    env = account_slots.apply_env(base_env, resolved["env"])
    # Keep the account address out of any banner the CLI might print.
    env["AGY_CLI_HIDE_ACCOUNT_INFO"] = "1"
    row: dict[str, Any] = {
        "slot": resolved["slot"],
        "profile": resolved["display_env"] or {"HOME": "~ (default login)"},
        "probed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "plan": None,
        "plan_source": NOT_PROVIDED,
    }
    code, out, _ = runner([CLI, "--version"], env)
    row["cli_version"] = out.strip().splitlines()[0] if code == 0 and out.strip() else "unknown"
    usage, error = _print_json(runner, env, "/usage")
    row["auth_status"] = "ok" if usage else ("blocked_user_action" if error == "blocked_user_action" else "unknown")
    row["usage_error"] = error
    row["quota_groups"] = parse_usage(usage) if usage else []
    credits, credits_error = _print_json(runner, env, "/credits") if usage else (None, error)
    credit_value = (((credits or {}).get("command") or {}).get("data") or {}).get("remaining_credits")
    row["ai_credits_remaining"] = credit_value if isinstance(credit_value, (int, float)) and not isinstance(credit_value, bool) else None
    row["credits_error"] = credits_error
    if skip_models:
        row["models"] = None
    else:
        code, out, _ = runner([CLI, "models"], env)
        row["models"] = parse_models(out) if code == 0 else None
        row["models_error"] = None if code == 0 else "error"
    return row


def slot_order(config: dict[str, Any], requested: list[str] | None) -> list[str]:
    if requested:
        return [account_slots.validate_slot_name(name) for name in requested]
    slots = account_slots.load_slots(config)
    return account_slots.rotation_order(config, CLI, slots)


def collect(config: dict[str, Any], requested: list[str] | None, runner: Runner, base_env: dict[str, str] | None = None,
            *, skip_models: bool = False, home: Path | None = None) -> dict[str, Any]:
    base = dict(base_env) if base_env is not None else account_slots.apply_env(None, {})
    resolved = [account_slots.resolve_slot(config, CLI, name, home=home) for name in slot_order(config, requested)]
    # Slots have separate HOMEs, so their probes are independent; run them side by side.
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(4, len(resolved)))) as pool:
        rows = list(pool.map(lambda item: probe_slot(item, runner, base, skip_models=skip_models), resolved))
    return {
        "schema": "soia.dispatch.agy-quota/v1",
        "cli": CLI,
        "source": "agy -p /usage|/credits --output-format json; agy models (no model turn, no quota spent)",
        "note": "observation only: slot choice stays explicit or round-robin; no quota-based auto-selection",
        "slots": rows,
    }


def _fmt_window(window: dict[str, Any]) -> str:
    label = {"5h": "5h", "weekly": "7d"}.get(window.get("window"), window.get("window") or "?")
    percent = "?" if window.get("remaining_percent") is None else f"{window['remaining_percent']:g}%"
    return f"{label} 剩 {percent}（重置 {window.get('reset_at') or '?'}）"


def render_text(report: dict[str, Any]) -> str:
    lines = []
    for row in report["slots"]:
        profile = " ".join(f"{k}={v}" for k, v in row["profile"].items())
        lines.append(f"## 槽位 {row['slot']}  [{profile}]  agy {row['cli_version']}  auth={row['auth_status']}")
        lines.append(f"- 套餐：{row['plan'] or row['plan_source']}")
        credits = row["ai_credits_remaining"]
        lines.append(f"- AI credits 剩余：{credits if credits is not None else '未取到'}")
        if row["usage_error"]:
            lines.append(f"- 额度：未取到（{row['usage_error']}）")
        for group in row["quota_groups"]:
            members = f"（{', '.join(group['models'])}）" if group["models"] else ""
            windows = "；".join(_fmt_window(w) for w in group["windows"]) or "无窗口"
            lines.append(f"- {group['group']}{members}：{windows}")
            if group["note"]:
                lines.append(f"  - CLI 说明：{group['note']}")
        if row["models"] is None:
            lines.append("- 模型：未列出")
        else:
            lines.append(f"- 模型（{len(row['models'])}）：{' '.join(row['models'])}")
        lines.append("")
    lines.append("时间为 UTC；5h/7d 窗口与重置时间来自 agy /usage。槽位选择仍是显式或轮流，不按余量自动调度。")
    return "\n".join(lines)


def run_selftest() -> int:
    checks: list[tuple[str, bool]] = []

    def check(name: str, ok: bool) -> None:
        checks.append((name, bool(ok)))

    fixture = Path(__file__).resolve().parents[1] / "assets" / "fixtures" / "agy-usage-1.5.10.redacted.json"
    usage_text = fixture.read_text(encoding="utf-8")
    credits_text = json.dumps({"status": "SUCCESS", "command": {"name": "credits", "data": {"remaining_credits": 0}}})
    models_text = "Fetching available models...\ngemini-4-argon-high\tGemini 4 Argon (High)\ngemini-4-carbon-high\tGemini 4 Carbon (High)\n"
    seen: list[tuple[list[str], str | None, str | None]] = []

    def fake(command: list[str], env: dict[str, str]) -> tuple[int, str, str]:
        seen.append((command, env.get("HOME"), env.get("AGY_CLI_HIDE_ACCOUNT_INFO")))
        if command[1:] == ["--version"]:
            return 0, "1.5.10\n", ""
        if command[1:] == ["models"]:
            return 0, models_text, ""
        if "/usage" in command:
            if env.get("HOME", "").endswith("acct3"):
                return 1, "", "Please sign in to continue: someone@example.com"
            return 0, usage_text, ""
        if "/credits" in command:
            return 0, credits_text, ""
        return 1, "", "unexpected"

    config = {"slots": {"acct2": {"cli": "agy", "env": {"HOME": "~/.agy-profiles/{slot}"}},
                        "acct3": {"cli": "agy", "env": {"HOME": "~/.agy-profiles/{slot}"}}}}
    home = Path("selftest-home")
    report = collect(config, None, fake, {"PATH": "/bin", "HOME": str(home)}, home=home)
    rows = {row["slot"]: row for row in report["slots"]}
    check("default login first, then declared agy slots", [row["slot"] for row in report["slots"]] == ["default", "acct2", "acct3"])
    check("default slot keeps the main HOME", any(cmd[1:] == ["--version"] and h == str(home) for cmd, h, _ in seen))
    check("slot HOME is applied", any(h == str(home / ".agy-profiles" / "acct2") for _, h, _ in seen))
    acct2 = rows["acct2"]
    groups = {g["group"]: g for g in acct2["quota_groups"]}
    check("three quota groups parsed", set(groups) == {"Gemini Models", "Claude and GPT models", "Gemini 4 Argon"})
    gem = {w["window"]: w for w in groups["Gemini Models"]["windows"]}
    check("5h and weekly windows carry percent and reset", gem["5h"]["remaining_percent"] == 96.7 and gem["weekly"]["reset_at"] == "2026-11-25T04:38:55Z")
    check("group members parsed from CLI description", groups["Claude and GPT models"]["models"] == ["Claude Opus 5.5", "Claude Sonnet 5.5", "GPT-OSS 120B"])
    check("non-member description kept as CLI note", groups["Gemini 4 Argon"]["models"] is None and "Argon" in (groups["Gemini 4 Argon"]["note"] or ""))
    check("plan is reported as not provided, never guessed", acct2["plan"] is None and acct2["plan_source"] == NOT_PROVIDED)
    check("credits parsed", acct2["ai_credits_remaining"] == 0)
    check("models parsed without progress line", acct2["models"] == ["gemini-4-argon-high", "gemini-4-carbon-high"])
    acct3 = rows["acct3"]
    check("sign-in prompt maps to blocked_user_action", acct3["auth_status"] == "blocked_user_action" and acct3["quota_groups"] == [])
    blob = json.dumps(report, ensure_ascii=False) + render_text(report)
    check("no address or raw stderr leaks into output", "@" not in blob and "sign in to continue" not in blob)
    check("account banner is hidden for every call", bool(seen) and all(flag == "1" for _, _, flag in seen))
    check("text view shows 5h and 7d", "5h 剩 96.7%" in render_text(report) and "7d 剩 99" in render_text(report))
    check("explicit --slot narrows the list", [r["slot"] for r in collect(config, ["acct2"], fake, {"HOME": str(home)}, home=home, skip_models=True)["slots"]] == ["acct2"])

    for label, ok in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")
    passed = sum(1 for _, ok in checks if ok)
    print(f"{passed}/{len(checks)} checks passed")
    return 0 if passed == len(checks) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", help="private config.yml (default follows SOIA_DEV_AGENT_CLI_DISPATCH_CONFIG_FILE)")
    parser.add_argument("--slot", action="append", help="limit to these slots (repeatable); default lists all agy slots")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--skip-models", action="store_true", help="skip `agy models`")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)
    if args.selftest:
        return run_selftest()
    try:
        path = Path(args.config).expanduser() if args.config else resolve_storage.default_config_path()
        config = resolve_storage.load_config(path)
        report = collect(config, args.slot, default_runner, skip_models=args.skip_models)
    except (account_slots.SlotError, ValueError) as exc:
        print(json.dumps({"status": "slot_error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render_text(report))
    return 0 if all(row["auth_status"] == "ok" for row in report["slots"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
