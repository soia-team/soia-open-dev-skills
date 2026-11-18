#!/usr/bin/env python3
# @created_by claude opus 5.5
# @created_at 2026-11-18 16:30:00
# @modified_by claude opus 5.5
# @modified_at 2026-11-18 18:10:00
# @version 0.2.0
# @description Detect each agy account slot's login, list plan/quota/models, pick a slot for one dispatch and report it in one line.
# @changelog 0.2.0: detect first (slot home missing / `agy models` sign-in / ready) before any /usage call, exact login guidance, --pick with rotation that skips not-ready or exhausted slots, one-line report, same-account suspicion with remembered confirmation. 0.1.0: first version.
"""Per-slot Antigravity CLI (agy) status, quota overview and slot pick.

Detect first, ask never (with one exception). For every agy slot (default
login first, then `slot_rotation.agy` or the declared agy slots):

1. slot home missing                         -> ``not_created``
2. ``agy models`` fails asking to sign in     -> ``not_logged_in``
3. ``agy models`` lists models                -> ``ready``; only then
   ``agy -p "/usage"`` and ``"/credits"`` (``--output-format json``) run.
   Without a login ``/usage`` prints a sign-in URL and blocks, so it never
   runs before step 2 succeeds.

All commands are official read-only CLI calls that start no model turn and
spend no quota. Credential files, logs and conversation stores are never
read; raw CLI output is never printed. agy 1.5.10 print mode has no
plan/tier field, so ``plan`` is reported as not provided.

``--pick --model <id>`` chooses the slot for one dispatch: ``--slot <name>``
(explicit; a not-ready slot blocks, it is never swapped) or ``--rotate``
(round-robin; not-ready, exhausted or confirmed-duplicate slots are skipped
and named in the report). Without either it is the default login. Remaining
quota never ranks slots.

The only question it ever raises: two ready slots whose model list and every
quota window (with at least one window already used) are identical may be the
same Google account. ``account_slots.py confirm`` records the answer once.

Usage:
    python3 agy_quota.py [--slot <name> ...] [--json] [--skip-models]
    python3 agy_quota.py --pick --model gemini-4-argon-high [--slot <name> | --rotate [--peek]] [--json]
    python3 agy_quota.py --selftest
"""

from __future__ import annotations

import argparse
import concurrent.futures
import itertools
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
SIGN_IN_RE = re.compile(r"(?i)sign[ -]?in|log[ -]?in|authenticat|verify your account")
LABEL_SUFFIX_RE = re.compile(r"\s*\([^()]*\)\s*$")
GROUP_SHORT = {"Gemini Models": "Gemini", "Claude and GPT models": "Claude/GPT", "Gemini 4 Argon": "Argon"}
STATUS_TEXT = {"ready": "可用", "not_logged_in": "未登录", "not_created": "未建槽位", "unknown": "检测失败"}

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
    return None, "not_logged_in" if SIGN_IN_RE.search(f"{out}\n{err}") else "error"


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
            valid = isinstance(fraction, (int, float)) and not isinstance(fraction, bool)
            windows.append({
                "bucket_id": bucket.get("id"),
                "window": bucket.get("window"),
                "remaining_fraction": float(fraction) if valid else None,
                "remaining_percent": round(float(fraction) * 100, 1) if valid else None,
                "reset_at": bucket.get("reset_time"),
            })
        groups.append({"group": group.get("name"), "models": models, "note": note, "windows": windows})
    return groups


def parse_models(stdout: str) -> dict[str, str]:
    """Return {model id: display label} from `agy models` text output."""
    models: dict[str, str] = {}
    for line in stdout.splitlines():
        if "\t" not in line:
            continue  # progress lines such as "Fetching available models..."
        model_id, label = (part.strip() for part in line.split("\t", 1))
        if MODEL_ID_RE.fullmatch(model_id):
            models[model_id] = label
    return dict(sorted(models.items()))


def model_groups(row: dict[str, Any], model_id: str) -> list[dict[str, Any]]:
    """Quota groups that cover a model, matched by its display label (with or without the effort suffix)."""
    label = (row.get("model_labels") or {}).get(model_id)
    if not label:
        return []
    names = {label, LABEL_SUFFIX_RE.sub("", label)}
    return [g for g in row.get("quota_groups") or [] if g["group"] in names or names & set(g["models"] or [])]


def model_quota_state(row: dict[str, Any], model_id: str) -> str:
    groups = model_groups(row, model_id)
    windows = [w for g in groups for w in g["windows"] if w["remaining_fraction"] is not None]
    if not windows:
        return "unknown"
    return "exhausted" if any(w["remaining_fraction"] <= 0 for w in windows) else "available"


def login_command(row: dict[str, Any]) -> str:
    home = (row.get("profile") or {}).get("HOME")
    return "agy" if row["slot"] == account_slots.DEFAULT_SLOT else f"HOME={home} agy"


def next_steps(row: dict[str, Any]) -> list[str]:
    status = row["login_status"]
    if status == "not_created":
        return [
            f"槽位 {row['slot']} 还没建：python3 scripts/account_slots.py init --cli agy --slot {row['slot']}"
            "（建目录并软链 git/npm/pnpm/playwright 缓存，不碰登录态）",
            f"然后请你在终端运行：{login_command(row)}，在弹出的浏览器里完成 Google 授权（助手不能代登），好了告诉我，我再检测一次。",
        ]
    if status == "not_logged_in":
        return [f"槽位 {row['slot']} 未登录：请你在终端运行 {login_command(row)}，在弹出的浏览器里完成 Google 授权"
                "（助手不能代登）；好了告诉我，我再检测一次，以检测结果为准。"]
    if status == "unknown":
        return [f"槽位 {row['slot']} 检测失败（{row.get('detect_error') or 'unknown'}）：先单独运行 {login_command(row)} models 看提示。"]
    return []


def probe_slot(resolved: dict[str, Any], runner: Runner, base_env: dict[str, str], *, skip_models: bool = False) -> dict[str, Any]:
    env = account_slots.apply_env(base_env, resolved["env"])
    # Keep the account address out of any banner the CLI might print.
    env["AGY_CLI_HIDE_ACCOUNT_INFO"] = "1"
    row: dict[str, Any] = {
        "slot": resolved["slot"],
        "profile": resolved["display_env"] or {"HOME": "~"},
        "probed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "login_status": "unknown",
        "detect_error": None,
        "plan": None,
        "plan_source": NOT_PROVIDED,
        "cli_version": "unknown",
        "quota_groups": [],
        "ai_credits_remaining": None,
        "models": None,
        "model_labels": {},
    }
    slot_home = account_slots.isolation_dir(resolved)
    if resolved["slot"] != account_slots.DEFAULT_SLOT and slot_home is not None and not slot_home.is_dir():
        row["login_status"] = "not_created"
        row["next_steps"] = next_steps(row)
        return row
    code, out, _ = runner([CLI, "--version"], env)
    row["cli_version"] = out.strip().splitlines()[0] if code == 0 and out.strip() else "unknown"
    # Login detection: `agy models` exits non-zero with a sign-in hint and never blocks.
    code, out, err = runner([CLI, "models"], env)
    labels = parse_models(out) if code == 0 else {}
    if labels:
        row["login_status"] = "ready"
    elif code == 127:
        row["detect_error"] = "cli_missing"
    elif code == 124:
        row["detect_error"] = "timeout"
    elif SIGN_IN_RE.search(f"{out}\n{err}"):
        row["login_status"] = "not_logged_in"
    else:
        row["detect_error"] = "error"
    if row["login_status"] != "ready":
        row["next_steps"] = next_steps(row)
        return row
    row["model_labels"] = labels
    row["models"] = None if skip_models else list(labels)
    usage, error = _print_json(runner, env, "/usage")
    row["quota_groups"] = parse_usage(usage) if usage else []
    row["usage_error"] = error
    credits, credits_error = _print_json(runner, env, "/credits") if usage else (None, error)
    credit_value = (((credits or {}).get("command") or {}).get("data") or {}).get("remaining_credits")
    row["ai_credits_remaining"] = credit_value if isinstance(credit_value, (int, float)) and not isinstance(credit_value, bool) else None
    row["credits_error"] = credits_error
    row["next_steps"] = []
    return row


def _same_windows(a: dict[str, Any], b: dict[str, Any]) -> tuple[bool, bool]:
    """(identical, has_used_window): identical groups/windows, and at least one window below 100%."""
    def key(row: dict[str, Any]) -> list[tuple[Any, ...]]:
        return sorted(
            (g["group"], w["bucket_id"], round(w["remaining_fraction"], 4) if w["remaining_fraction"] is not None else None, w["reset_at"])
            for g in row["quota_groups"] for w in g["windows"]
        )
    ka, kb = key(a), key(b)
    used = any(item[2] is not None and item[2] < 1 for item in ka)
    return bool(ka) and ka == kb, used


def identity_checks(rows: list[dict[str, Any]], state_dir: Path | None) -> list[dict[str, Any]]:
    """Flag ready slot pairs that look like the same account, unless the user already answered."""
    checks = []
    ready = [row for row in rows if row["login_status"] == "ready"]
    for a, b in itertools.combinations(ready, 2):
        decision = account_slots.identity_decision(state_dir, CLI, a["slot"], b["slot"])
        if decision:
            checks.append({"slots": [a["slot"], b["slot"]], "status": f"confirmed_{decision}"})
            continue
        identical, used = _same_windows(a, b)
        if identical and used and a["model_labels"] == b["model_labels"]:
            checks.append({
                "slots": [a["slot"], b["slot"]],
                "status": "suspected_same",
                "question": (f"槽位 {a['slot']} 和 {b['slot']} 的模型清单与各额度窗口（含已用掉的部分和重置时间）完全一致，"
                             "可能是同一个 Google 账号。是同一个吗？"),
                "record_answer": (f"python3 scripts/account_slots.py confirm --cli agy --slots {a['slot']} {b['slot']} "
                                  "--same 或 --distinct"),
            })
    return checks


def slot_order(config: dict[str, Any], requested: list[str] | None) -> list[str]:
    if requested:
        return [account_slots.validate_slot_name(name) for name in requested]
    slots = account_slots.load_slots(config)
    return account_slots.rotation_order(config, CLI, slots)


def collect(config: dict[str, Any], requested: list[str] | None, runner: Runner, base_env: dict[str, str] | None = None,
            *, skip_models: bool = False, home: Path | None = None, state_dir: Path | None = None) -> dict[str, Any]:
    base = dict(base_env) if base_env is not None else account_slots.apply_env(None, {})
    resolved = [account_slots.resolve_slot(config, CLI, name, home=home) for name in slot_order(config, requested)]
    # Slots have separate HOMEs, so their probes are independent; run them side by side.
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(4, len(resolved)))) as pool:
        rows = list(pool.map(lambda item: probe_slot(item, runner, base, skip_models=skip_models), resolved))
    return {
        "schema": "soia.dispatch.agy-quota/v2",
        "cli": CLI,
        "source": "agy models; then agy -p /usage|/credits --output-format json (no model turn, no quota spent)",
        "note": "slot choice is explicit or round-robin; remaining quota never ranks slots",
        "slots": rows,
        "identity_checks": identity_checks(rows, state_dir),
    }


def pick_slot(report: dict[str, Any], model: str, *, slot: str | None = None, rotate: bool = False,
              order: list[str] | None = None) -> dict[str, Any]:
    """Pick the slot for one dispatch. Explicit/default never swaps; rotation skips not-ready slots."""
    rows = {row["slot"]: row for row in report["slots"]}
    duplicates = {check["slots"][1] for check in report["identity_checks"] if check["status"] == "confirmed_same"}
    if rotate:
        candidates, basis = list(order or rows), "rotation"
    else:
        candidates, basis = [slot or account_slots.DEFAULT_SLOT], ("explicit" if slot else "default")
    skipped: list[dict[str, str]] = []
    for name in candidates:
        row = rows.get(name)
        reason = None
        if row is None:
            reason = "未检测"
        elif row["login_status"] != "ready":
            reason = STATUS_TEXT[row["login_status"]]
        elif rotate and name in duplicates:
            reason = "与另一槽位是同一账号"
        elif model not in row["model_labels"]:
            reason = f"账号不提供 {model}"
        elif model_quota_state(row, model) == "exhausted":
            reason = "该模型所在额度组已耗尽"
        if reason is None:
            return {"status": "picked", "slot": name, "model": model, "basis": basis,
                    "quota_state": model_quota_state(row, model), "skipped": skipped}
        skipped.append({"slot": name, "reason": reason})
    alternatives = [
        name for name, row in rows.items()
        if name not in candidates and row["login_status"] == "ready" and model in row["model_labels"]
        and model_quota_state(row, model) != "exhausted"
    ]
    return {"status": "blocked", "slot": None, "model": model, "basis": basis, "quota_state": None,
            "skipped": skipped, "alternatives": alternatives}


def _windows_short(row: dict[str, Any], groups: list[dict[str, Any]] | None = None) -> str:
    parts = []
    for group in row["quota_groups"] if groups is None else groups:
        windows = "/".join(
            f"{ {'5h': '5h', 'weekly': '7d'}.get(w['window'], w['window'])}{w['remaining_percent']:g}%"
            for w in group["windows"] if w["remaining_percent"] is not None
        )
        parts.append(f"{GROUP_SHORT.get(group['group'], group['group'])} {windows}")
    return "，".join(parts) or "额度未取到"


def brief_line(report: dict[str, Any], pick: dict[str, Any] | None = None) -> str:
    cells = []
    for row in report["slots"]:
        if row["login_status"] == "ready":
            groups = model_groups(row, pick["model"]) if pick else None
            cells.append(f"{row['slot']} 可用（{_windows_short(row, groups or None)}）")
        else:
            cells.append(f"{row['slot']} {STATUS_TEXT[row['login_status']]}")
    line = "agy 槽位：" + "；".join(cells)
    if pick:
        if pick["status"] == "picked":
            line += f" → 本单用 {pick['slot']} / {pick['model']}"
            if pick["quota_state"] == "unknown":
                line += "（该模型额度组未识别）"
        else:
            line += f" → 没有可用槽位跑 {pick['model']}"
            if pick.get("alternatives"):
                line += f"（能跑的槽位：{'、'.join(pick['alternatives'])}，用 --slot 指定或 --rotate 轮流）"
        if pick["skipped"]:
            line += "；跳过 " + "、".join(f"{item['slot']}（{item['reason']}）" for item in pick["skipped"])
    return line


def render_text(report: dict[str, Any]) -> str:
    lines = []
    for row in report["slots"]:
        profile = " ".join(f"{k}={v}" for k, v in row["profile"].items())
        lines.append(f"## 槽位 {row['slot']}  [{profile}]  agy {row['cli_version']}  {STATUS_TEXT[row['login_status']]}")
        if row["login_status"] != "ready":
            lines += [f"- {step}" for step in row.get("next_steps") or []]
            lines.append("")
            continue
        lines.append(f"- 套餐：{row['plan'] or row['plan_source']}")
        credits = row["ai_credits_remaining"]
        lines.append(f"- AI credits 剩余：{credits if credits is not None else '未取到'}")
        if row.get("usage_error"):
            lines.append(f"- 额度：未取到（{row['usage_error']}）")
        for group in row["quota_groups"]:
            members = f"（{', '.join(group['models'])}）" if group["models"] else ""
            windows = "；".join(
                f"{ {'5h': '5h', 'weekly': '7d'}.get(w['window'], w['window'])} 剩 "
                f"{'?' if w['remaining_percent'] is None else format(w['remaining_percent'], 'g') + '%'}（重置 {w['reset_at'] or '?'}）"
                for w in group["windows"]
            ) or "无窗口"
            lines.append(f"- {group['group']}{members}：{windows}")
            if group["note"]:
                lines.append(f"  - CLI 说明：{group['note']}")
        if row["models"] is None:
            lines.append("- 模型：未列出")
        else:
            lines.append(f"- 模型（{len(row['models'])}）：{' '.join(row['models'])}")
        lines.append("")
    for check in report["identity_checks"]:
        if check["status"] == "suspected_same":
            lines.append(f"需要你确认一次：{check['question']}（记录：{check['record_answer']}）")
    lines.append("时间为 UTC；5h/7d 窗口与重置时间来自 agy /usage。槽位选择是显式或轮流，不按余量排序。")
    return "\n".join(lines)


def run_selftest() -> int:
    checks: list[tuple[str, bool]] = []

    def check(name: str, ok: bool) -> None:
        checks.append((name, bool(ok)))

    fixture = Path(__file__).resolve().parents[1] / "assets" / "fixtures" / "agy-usage-1.5.10.redacted.json"
    usage_text = fixture.read_text(encoding="utf-8")
    exhausted_text = usage_text.replace('"remaining_fraction":0.1588', '"remaining_fraction":0')
    credits_text = json.dumps({"status": "SUCCESS", "command": {"name": "credits", "data": {"remaining_credits": 0}}})
    models_main = ("Fetching available models...\ngemini-4-argon-high\tGemini 4 Argon (High)\n"
                   "gemini-4-hydrogen-medium\tGemini 4 Hydrogen (Medium)\n")
    models_other = models_main + "gemini-4-carbon-high\tGemini 4 Carbon (High)\n"
    seen: list[tuple[list[str], str | None, str | None]] = []

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        for name in ("acct2", "acct3", "acct4"):
            (home / ".agy-profiles" / name).mkdir(parents=True)

        def fake(command: list[str], env: dict[str, str]) -> tuple[int, str, str]:
            h = env.get("HOME", "")
            seen.append((command, h, env.get("AGY_CLI_HIDE_ACCOUNT_INFO")))
            if command[1:] == ["--version"]:
                return 0, "1.5.10\n", ""
            if h.endswith("acct3"):
                if command[1:] == ["models"]:
                    return 1, "Fetching available models...\n", "Error: Please sign in to view available models. someone@example.com\n"
                return 0, "Authentication required. Please visit the URL to log in: https://accounts.example/o?state=x\n", ""
            if command[1:] == ["models"]:
                return 0, models_other if h.endswith(("acct2", "acct4")) else models_main, ""
            if "/usage" in command:
                return 0, exhausted_text if h.endswith("acct4") else usage_text, ""
            if "/credits" in command:
                return 0, credits_text, ""
            return 1, "", "unexpected"

        config = {"slots": {name: {"cli": "agy", "env": {"HOME": "~/.agy-profiles/{slot}"}}
                            for name in ("acct2", "acct3", "acct4", "acct5")}}
        state = Path(tmp) / "state"
        report = collect(config, None, fake, {"PATH": "/bin", "HOME": str(home)}, home=home, state_dir=state)
        rows = {row["slot"]: row for row in report["slots"]}
        check("default first, then declared slots", [r["slot"] for r in report["slots"]] == ["default", "acct2", "acct3", "acct4", "acct5"])
        check("missing slot home is not_created without calling agy",
              rows["acct5"]["login_status"] == "not_created" and not any(h.endswith("acct5") for _, h, _ in seen))
        check("sign-in error on `agy models` is not_logged_in", rows["acct3"]["login_status"] == "not_logged_in")
        check("/usage never runs for a slot that is not logged in",
              not any("/usage" in cmd and h.endswith("acct3") for cmd, h, _ in seen))
        check("not-logged-in guidance gives the exact command and says the assistant cannot sign in",
              any("HOME=~/.agy-profiles/acct3 agy" in step and "不能代登" in step for step in rows["acct3"]["next_steps"]))
        check("not-created guidance creates the slot first", "account_slots.py init --cli agy --slot acct5" in rows["acct5"]["next_steps"][0])
        check("ready slot lists models and quota", rows["acct2"]["login_status"] == "ready"
              and "gemini-4-carbon-high" in rows["acct2"]["models"] and rows["acct2"]["quota_groups"])
        gem = {w["window"]: w for g in rows["acct2"]["quota_groups"] if g["group"] == "Gemini Models" for w in g["windows"]}
        check("5h and weekly windows carry percent and reset", gem["5h"]["remaining_percent"] == 96.7 and gem["weekly"]["reset_at"] == "2026-11-25T04:38:55Z")
        check("plan is reported as not provided, never guessed", rows["acct2"]["plan"] is None and rows["acct2"]["plan_source"] == NOT_PROVIDED)
        check("model maps to its quota group by label", [g["group"] for g in model_groups(rows["default"], "gemini-4-hydrogen-medium")] == ["Gemini Models"]
              and [g["group"] for g in model_groups(rows["default"], "gemini-4-argon-high")] == ["Gemini 4 Argon"])
        check("exhausted group is detected", model_quota_state(rows["acct4"], "gemini-4-argon-high") == "exhausted"
              and model_quota_state(rows["acct2"], "gemini-4-argon-high") == "available")
        suspected = [c for c in report["identity_checks"] if c["status"] == "suspected_same"]
        # default vs acct2: different model lists; acct2 vs acct4: same models but one window exhausted.
        check("different model lists or windows raise no question", suspected == [])
        twin = json.loads(json.dumps(report))
        for row in twin["slots"]:
            if row["slot"] == "acct4":
                row["quota_groups"] = json.loads(json.dumps(rows["acct2"]["quota_groups"]))
        twin_checks = identity_checks(twin["slots"], state)
        check("true twin slots raise exactly one question with the confirm command",
              [c["slots"] for c in twin_checks if c["status"] == "suspected_same"] == [["acct2", "acct4"]]
              and "account_slots.py confirm" in twin_checks[0]["record_answer"])
        account_slots.record_identity(state, CLI, "acct4", "acct2", "distinct")
        check("a confirmed pair is never asked again",
              [c["status"] for c in identity_checks(twin["slots"], state)] == ["confirmed_distinct"])
        fresh = json.loads(json.dumps(twin))
        for row in fresh["slots"]:
            for group in row["quota_groups"]:
                for window in group["windows"]:
                    window["remaining_fraction"], window["remaining_percent"] = 1.0, 100.0
        check("untouched (all 100%) twins are not enough evidence to ask",
              not [c for c in identity_checks(fresh["slots"], None) if c["status"] == "suspected_same"])

        order = ["default", "acct2", "acct3", "acct4", "acct5"]
        rot = pick_slot(report, "gemini-4-carbon-high", rotate=True, order=order)
        check("rotation skips a slot that lacks the model and picks the next ready one",
              rot["slot"] == "acct2" and rot["skipped"] == [{"slot": "default", "reason": "账号不提供 gemini-4-carbon-high"}])
        rot2 = pick_slot(report, "gemini-4-argon-high", rotate=True, order=["acct3", "acct4", "acct5", "acct2"])
        check("rotation skips not-logged-in, exhausted and not-created slots and says why",
              rot2["slot"] == "acct2" and [s["reason"] for s in rot2["skipped"]] == ["未登录", "该模型所在额度组已耗尽", "未建槽位"])
        explicit = pick_slot(report, "gemini-4-argon-high", slot="acct4")
        check("an explicit exhausted slot blocks instead of being swapped and names alternatives",
              explicit["status"] == "blocked" and explicit["slot"] is None and explicit["alternatives"] == ["default", "acct2"]
              and "能跑的槽位：default、acct2" in brief_line(report, explicit))
        default_pick = pick_slot(report, "gemini-4-argon-high")
        check("no --slot means the default login", default_pick["slot"] == "default" and default_pick["basis"] == "default")
        line = brief_line(report, rot2)
        check("one-line report names slots, windows, the pick and what was skipped",
              line.startswith("agy 槽位：default 可用（Argon 7d") and "acct3 未登录" in line and "→ 本单用 acct2 / gemini-4-argon-high" in line
              and "跳过 acct3（未登录）" in line and "\n" not in line)
        blob = json.dumps(report, ensure_ascii=False) + render_text(report) + line
        check("no address, sign-in URL or raw stderr leaks into output",
              "@" not in blob and "accounts.example" not in blob and "Please sign in" not in blob)
        check("account banner is hidden for every call", bool(seen) and all(flag == "1" for _, _, flag in seen))

    for label, ok in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")
    passed = sum(1 for _, ok in checks if ok)
    print(f"{passed}/{len(checks)} checks passed")
    return 0 if passed == len(checks) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", help="private config.yml (default follows SOIA_DEV_AGENT_CLI_DISPATCH_CONFIG_FILE)")
    parser.add_argument("--slot", action="append", help="without --pick: limit to these slots (repeatable); with --pick: the explicit slot")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--skip-models", action="store_true", help="omit the model list from the output (login is still detected)")
    parser.add_argument("--pick", action="store_true", help="choose the slot for one dispatch and print one line")
    parser.add_argument("--model", help="with --pick: the agy model id the dispatch will use")
    parser.add_argument("--rotate", action="store_true", help="with --pick: round-robin, skipping slots that cannot run the model")
    parser.add_argument("--peek", action="store_true", help="with --pick --rotate: do not advance the rotation")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)
    if args.selftest:
        return run_selftest()
    try:
        path = Path(args.config).expanduser() if args.config else resolve_storage.default_config_path()
        config = resolve_storage.load_config(path)
        state_dir = resolve_storage.storage_paths(config)["state"]
        if args.pick:
            if not args.model:
                parser.error("--pick needs --model")
            if args.rotate and args.slot:
                parser.error("--pick takes either --slot or --rotate")
            if args.slot and len(args.slot) > 1:
                parser.error("--pick takes one --slot")
            slots = account_slots.load_slots(config)
            order = account_slots.rotation_order(config, CLI, slots)
            if args.rotate:
                order = account_slots.rotation_start(order, state_dir, CLI)
            report = collect(config, None, default_runner, skip_models=True, state_dir=state_dir)
            pick = pick_slot(report, args.model, slot=args.slot[0] if args.slot else None, rotate=args.rotate, order=order)
            if args.rotate and pick["status"] == "picked" and not args.peek:
                account_slots.record_rotation(state_dir, CLI, pick["slot"])
            report["pick"] = pick
            if args.json:
                print(json.dumps(report, ensure_ascii=False, indent=2))
            else:
                print(brief_line(report, pick))
                for row in report["slots"]:
                    for step in row.get("next_steps") or []:
                        print(f"- {step}")
                for item in report["identity_checks"]:
                    if item["status"] == "suspected_same":
                        print(f"- 需要你确认一次：{item['question']}（记录：{item['record_answer']}）")
            return 0 if pick["status"] == "picked" else 3
        report = collect(config, args.slot, default_runner, skip_models=args.skip_models, state_dir=state_dir)
    except (account_slots.SlotError, ValueError) as exc:
        print(json.dumps({"status": "slot_error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render_text(report))
    return 0 if all(row["login_status"] == "ready" for row in report["slots"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
