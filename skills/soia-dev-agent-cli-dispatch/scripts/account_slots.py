#!/usr/bin/env python3
# @created_by claude opus 5.5
# @created_at 2026-11-18 16:10:00
# @modified_by claude opus 5.5
# @modified_at 2026-11-18 16:10:00
# @version 0.2.0
# @description Resolve per-CLI account slots (env overrides that isolate a login) by name or rotation.
# @changelog 0.2.0: `init` creates a slot's isolated home and links non-credential caches; `confirm` records whether two slots are the same account. 0.1.0: first version; slots live in the private config, never in the repository.
"""Account slots: one slot = a set of environment overrides for one CLI.

A slot isolates a CLI's login state (for example agy with its own ``HOME``)
so several accounts of the same CLI can be dispatched side by side. Slots are
declared in the optional private config (``slots:`` and ``slot_rotation:``,
see assets/config.example.yml); this script never reads, copies or prints a
credential, and it never picks a slot by remaining quota. Selection is only:

* explicit: ``--slot <name>`` (``default`` = no override, the main login);
* rotation: ``--rotate`` walks ``slot_rotation.<cli>`` round-robin and keeps
  only the last slot name per CLI in ``<state>/slots/rotation.json``.

Usage:
    python3 account_slots.py list [--cli agy] [--json]
    python3 account_slots.py resolve --cli agy --slot acct2 [--format json|shell]
    python3 account_slots.py resolve --cli agy --rotate [--peek]
    python3 account_slots.py exec --cli agy --slot acct2 -- agy models
    python3 account_slots.py init --cli agy --slot acct4 [--dry-run]
    python3 account_slots.py confirm --cli agy --slots acct2 acct3 --distinct|--same
    python3 account_slots.py --selftest
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalog_lib  # noqa: E402
import resolve_storage  # noqa: E402

DEFAULT_SLOT = "default"
SLOT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]{0,63}$")
# Slots isolate a login directory; they never carry a credential value.
SECRET_ENV_RE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|COOKIE|SESSION|AUTH)")
TEMPLATE_FIELD_RE = re.compile(r"\{([^{}]*)\}")
ALLOWED_TEMPLATE_FIELDS = {"slot", "home"}
EMAIL_RE = re.compile(r"[^\s@]+@[^\s@]+\.[A-Za-z]{2,}")
ROTATION_FILE = Path("slots") / "rotation.json"
IDENTITY_FILE = Path("slots") / "identity.json"

# Default isolated-home template per CLI for `init` when the slot is not declared yet.
DEFAULT_SLOT_ENV = {"agy": {"HOME": "~/.agy-profiles/{slot}"}}
# Non-credential config and caches that `init` links back to the real home when
# they exist there (git/npm/pnpm/playwright and the ~/.local bin dir).
DEFAULT_LINKS = {
    "agy": [".gitconfig", ".npmrc", ".npm-global", ".cache", ".local",
            "Library/pnpm", "Library/Caches/ms-playwright"],
}
# Never linked: they hold logins or keys, which a slot exists to keep apart.
NEVER_LINK = re.compile(
    r"^(?:\.gemini|\.codex|\.claude|\.ssh|\.gnupg|\.netrc|\.git-credentials|\.aws|\.docker|\.kube|"
    r"\.config/gcloud|\.config/gh|Library/Keychains|Library/Application Support)(?:/|$)"
)

# How each CLI isolates its login. `verified` is the evidence strength of the
# isolation itself, not of any account; see references/account-slots.md.
ISOLATION = {
    "agy": {"env": "HOME", "verified": "verified_2026-11-18"},
    "codex": {"env": "CODEX_HOME", "verified": "unverified"},
    "claude": {"env": "CLAUDE_CONFIG_DIR", "verified": "unverified"},
    "dsh": {"env": "DSH_HOME", "verified": "partial_2026-09-25"},
}


class SlotError(ValueError):
    """A slot declaration or selection is invalid; the message never carries env values."""


def known_executors() -> set[str]:
    path = Path(__file__).resolve().parents[1] / "references" / "supported-agents.yml"
    try:
        data = catalog_lib.load_catalog(path)
    except (OSError, catalog_lib.CatalogError):
        return set(ISOLATION)
    agents = data.get("agents") if isinstance(data, dict) else None
    return set(agents) if isinstance(agents, dict) else set(ISOLATION)


def validate_slot_name(name: Any) -> str:
    if not isinstance(name, str) or not SLOT_RE.fullmatch(name):
        raise SlotError("slot name must be 1-32 chars of lowercase letters, digits, '_' or '-'")
    return name


def _check_template(slot: str, var: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SlotError(f"slots.{slot}.env.{var} must be a non-empty string")
    if EMAIL_RE.search(value):
        raise SlotError(f"slots.{slot}.env.{var} looks like it contains an account address; use a slot name instead")
    for field in TEMPLATE_FIELD_RE.findall(value):
        if field not in ALLOWED_TEMPLATE_FIELDS:
            raise SlotError(f"slots.{slot}.env.{var} uses unknown template field {{{field}}}; allowed: {{slot}}, {{home}}")
    return value


def load_slots(config: Mapping[str, Any] | None, executors: set[str] | None = None) -> dict[str, dict[str, Any]]:
    """Validate and return the declared slots (the implicit `default` slot is not listed)."""
    raw = (config or {}).get("slots")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise SlotError("config slots must be a mapping of slot name -> declaration")
    executors = known_executors() if executors is None else executors
    slots: dict[str, dict[str, Any]] = {}
    for name, decl in raw.items():
        validate_slot_name(name)
        if name == DEFAULT_SLOT:
            raise SlotError("'default' is reserved for the main login and cannot be declared")
        if not isinstance(decl, dict):
            raise SlotError(f"slots.{name} must be a mapping")
        unknown = set(decl) - {"cli", "env", "note"}
        if unknown:
            raise SlotError(f"slots.{name} has unknown field(s): {', '.join(sorted(unknown))}")
        cli = decl.get("cli")
        if cli not in executors:
            raise SlotError(f"slots.{name}.cli must be an executor id from references/supported-agents.yml")
        env = decl.get("env")
        if not isinstance(env, dict) or not env:
            raise SlotError(f"slots.{name}.env must be a non-empty mapping of variable -> value template")
        for var, value in env.items():
            if not isinstance(var, str) or not ENV_NAME_RE.fullmatch(var):
                raise SlotError(f"slots.{name}.env has an invalid variable name")
            if SECRET_ENV_RE.search(var):
                raise SlotError(
                    f"slots.{name}.env.{var} looks like a credential variable; slots only isolate login directories"
                )
            _check_template(name, var, value)
        note = decl.get("note")
        if note is not None and (not isinstance(note, str) or len(note) > 200 or EMAIL_RE.search(note)):
            raise SlotError(f"slots.{name}.note must be a short non-identifying string (no account address)")
        slots[name] = {"cli": cli, "env": dict(env), "note": note}
    return slots


def rotation_order(config: Mapping[str, Any] | None, cli: str, slots: dict[str, dict[str, Any]]) -> list[str]:
    """Return the rotation order for a CLI: `slot_rotation.<cli>`, else default + declared slots."""
    raw = (config or {}).get("slot_rotation")
    if raw is not None and not isinstance(raw, dict):
        raise SlotError("config slot_rotation must be a mapping of cli -> [slot, ...]")
    declared = (raw or {}).get(cli)
    if declared is None:
        return [DEFAULT_SLOT] + sorted(name for name, slot in slots.items() if slot["cli"] == cli)
    if not isinstance(declared, list) or not declared:
        raise SlotError(f"slot_rotation.{cli} must be a non-empty list")
    order: list[str] = []
    for name in declared:
        validate_slot_name(name)
        if name != DEFAULT_SLOT and (name not in slots or slots[name]["cli"] != cli):
            raise SlotError(f"slot_rotation.{cli} names slot {name!r}, which is not declared for cli {cli!r}")
        if name in order:
            raise SlotError(f"slot_rotation.{cli} lists slot {name!r} twice")
        order.append(name)
    return order


def render_env(slot_name: str, slot: dict[str, Any] | None, home: Path | None = None) -> tuple[dict[str, str], dict[str, str]]:
    """Return (env, display_env). display_env shows the user's home as `~`."""
    if slot is None:
        return {}, {}
    real_home = (home or Path.home()).expanduser()
    env: dict[str, str] = {}
    display: dict[str, str] = {}
    for var, template in slot["env"].items():
        text = template.replace("{slot}", slot_name)
        shown = text.replace("{home}", "~")
        text = text.replace("{home}", str(real_home))
        if text == "~" or text.startswith("~/"):
            text = str(real_home) + text[1:]
        env[var] = text
        display[var] = shown
    return env, display


def _read_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".slots-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def read_rotation(state_dir: Path) -> dict[str, Any]:
    return _read_state(state_dir / ROTATION_FILE)


def record_rotation(state_dir: Path, cli: str, slot: str) -> None:
    state = read_rotation(state_dir)
    state[cli] = {"last": slot, "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    _write_state(state_dir / ROTATION_FILE, state)


def rotation_start(order: list[str], state_dir: Path, cli: str) -> list[str]:
    """Return `order` rotated so it starts at the slot after the last one used."""
    entry = read_rotation(state_dir).get(cli)
    last = entry.get("last") if isinstance(entry, dict) else None
    first = next_rotation(order, last)
    index = order.index(first)
    return order[index:] + order[:index]


def _pair_key(a: str, b: str) -> str:
    return "|".join(sorted((a, b)))


def identity_decision(state_dir: Path | None, cli: str, a: str, b: str) -> str | None:
    """`same` / `distinct` if the user already confirmed this slot pair, else None."""
    if state_dir is None:
        return None
    entry = _read_state(state_dir / IDENTITY_FILE).get(cli)
    value = entry.get(_pair_key(a, b)) if isinstance(entry, dict) else None
    return value if value in ("same", "distinct") else None


def record_identity(state_dir: Path, cli: str, a: str, b: str, decision: str) -> None:
    if decision not in ("same", "distinct"):
        raise SlotError("identity decision must be 'same' or 'distinct'")
    validate_slot_name(a)
    validate_slot_name(b)
    if a == b:
        raise SlotError("confirm needs two different slots")
    path = state_dir / IDENTITY_FILE
    state = _read_state(path)
    entry = state.get(cli) if isinstance(state.get(cli), dict) else {}
    entry[_pair_key(a, b)] = decision
    state[cli] = entry
    _write_state(path, state)


def isolation_dir(resolved: dict[str, Any]) -> Path | None:
    """The slot's isolated login directory (value of the CLI's isolation variable), if any."""
    var = resolved.get("isolation_env")
    value = (resolved.get("env") or {}).get(var) if var else None
    return Path(value) if value else None


def init_slot(
    config: Mapping[str, Any] | None, cli: str, slot: str, *, links: list[str] | None = None,
    dry_run: bool = False, home: Path | None = None, executors: set[str] | None = None,
) -> dict[str, Any]:
    """Create a slot's isolated home and link non-credential caches back to the real home.

    Uses the declared slot if there is one, else the CLI's default template. It
    never logs in, never copies a login, never links a credential store and
    never overwrites an existing entry. The private config is not edited:
    `config_snippet` is returned for the user to add when the slot is new.
    """
    validate_slot_name(slot)
    if slot == DEFAULT_SLOT:
        raise SlotError("the default slot is the main login; there is nothing to create")
    real_home = (home or Path.home()).expanduser()
    slots = load_slots(config, executors)
    declared = slots.get(slot)
    if declared is not None and declared["cli"] != cli:
        raise SlotError(f"slot {slot!r} belongs to cli {declared['cli']!r}, not {cli!r}")
    if declared is None:
        template = DEFAULT_SLOT_ENV.get(cli)
        if template is None:
            raise SlotError(f"no default slot template for cli {cli!r}; declare the slot in the private config first")
        declared = {"cli": cli, "env": dict(template), "note": None}
    env, display = render_env(slot, declared, real_home)
    var = (ISOLATION.get(cli) or {}).get("env")
    if not var or var not in env:
        raise SlotError(f"slot {slot!r} does not override {var or 'an isolation variable'}; nothing to create")
    target = Path(env[var])
    actions: list[dict[str, str]] = []
    if not target.exists():
        actions.append({"action": "mkdir", "path": display[var]})
        if not dry_run:
            target.mkdir(parents=True, mode=0o700)
    names = DEFAULT_LINKS.get(cli, []) if links is None else links
    for name in names:
        rel = name.strip().strip("/")
        if not rel or rel.startswith("..") or "/../" in f"/{rel}/" or NEVER_LINK.match(rel):
            actions.append({"action": "refused", "path": rel, "reason": "credential store or unsafe path"})
            continue
        source = real_home / rel
        dest = target / rel
        if not source.exists():
            actions.append({"action": "skip", "path": rel, "reason": "not present in the main home"})
            continue
        if dest.exists() or dest.is_symlink():
            actions.append({"action": "skip", "path": rel, "reason": "already present in the slot"})
            continue
        actions.append({"action": "link", "path": rel})
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.symlink_to(source)
    snippet = None
    if slot not in slots:
        lines = ["slots:", f"  {slot}:", f"    cli: {cli}", "    env:"]
        lines += [f'      {key}: "{value}"' for key, value in declared["env"].items()]
        snippet = "\n".join(lines)
    return {"cli": cli, "slot": slot, "dry_run": dry_run, "isolation_env": var,
            "slot_home": display[var], "actions": actions, "config_snippet": snippet}


def next_rotation(order: list[str], last: str | None) -> str:
    if last in order:
        return order[(order.index(last) + 1) % len(order)]
    return order[0]


def resolve_slot(
    config: Mapping[str, Any] | None,
    cli: str,
    slot: str | None = None,
    *,
    rotate: bool = False,
    peek: bool = False,
    state_dir: Path | None = None,
    home: Path | None = None,
    executors: set[str] | None = None,
) -> dict[str, Any]:
    """Pick a slot for one CLI (explicit name, rotation, or default) and render its env."""
    if slot is not None and rotate:
        raise SlotError("pass either --slot or --rotate, not both")
    slots = load_slots(config, executors)
    chosen = DEFAULT_SLOT
    basis = "default"
    if slot is not None:
        chosen = validate_slot_name(slot)
        basis = "explicit"
    elif rotate:
        order = rotation_order(config, cli, slots)
        if state_dir is None:
            raise SlotError("rotation needs a state directory")
        chosen = rotation_start(order, state_dir, cli)[0]
        basis = "rotation"
        if not peek:
            record_rotation(state_dir, cli, chosen)
    declared = None
    if chosen != DEFAULT_SLOT:
        declared = slots.get(chosen)
        if declared is None:
            raise SlotError(f"slot {chosen!r} is not declared in the private config")
        if declared["cli"] != cli:
            raise SlotError(f"slot {chosen!r} belongs to cli {declared['cli']!r}, not {cli!r}")
    env, display = render_env(chosen, declared, home)
    isolation = ISOLATION.get(cli)
    warnings = []
    if declared is not None and isolation and isolation["env"] not in env:
        warnings.append(f"slot does not override {isolation['env']}, the documented login isolation for {cli}")
    return {
        "cli": cli,
        "slot": chosen,
        "selection_basis": basis,
        "env": env,
        "display_env": display,
        "isolation_env": isolation["env"] if isolation else None,
        "isolation_verified": isolation["verified"] if isolation else "unknown",
        "note": declared.get("note") if declared else None,
        "warnings": warnings,
    }


def apply_env(base: Mapping[str, str] | None, overrides: Mapping[str, str]) -> dict[str, str]:
    merged = dict(os.environ if base is None else base)
    merged.update(overrides)
    return merged


def scoped_quota_key(key: str, slot: str | None) -> str:
    """Quota is per account: append `@<slot>` for a non-default slot unless already scoped."""
    if not slot or slot == DEFAULT_SLOT or "@" in key:
        return key
    return f"{key}@{slot}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _load_config(path_text: str | None) -> tuple[dict[str, Any], Path]:
    path = Path(path_text).expanduser() if path_text else resolve_storage.default_config_path()
    config = resolve_storage.load_config(path)
    return config, resolve_storage.storage_paths(config)["state"]


def cmd_list(args: argparse.Namespace) -> int:
    config, _ = _load_config(args.config)
    slots = load_slots(config)
    clis = sorted({args.cli} if args.cli else ({slot["cli"] for slot in slots.values()} | set(ISOLATION)))
    rows = []
    for cli in clis:
        for name in rotation_order(config, cli, slots) if cli in {s["cli"] for s in slots.values()} else [DEFAULT_SLOT]:
            resolved = resolve_slot(config, cli, name)
            rows.append({key: resolved[key] for key in ("cli", "slot", "display_env", "isolation_env", "isolation_verified", "note")})
    if args.json:
        print(json.dumps({"slots": rows}, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            env = " ".join(f"{k}={v}" for k, v in row["display_env"].items()) or "(no override)"
            print(f"{row['cli']}\t{row['slot']}\t{env}\t{row['isolation_verified']}\t{row['note'] or ''}")
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    config, state_dir = _load_config(args.config)
    resolved = resolve_slot(config, args.cli, args.slot, rotate=args.rotate, peek=args.peek, state_dir=state_dir)
    if args.format == "shell":
        for var, value in resolved["env"].items():
            print(f"export {var}={shlex.quote(value)}")
        print(f"export SOIA_DISPATCH_SLOT={shlex.quote(resolved['slot'])}")
    else:
        print(json.dumps(resolved, ensure_ascii=False, indent=2))
    return 0


def cmd_exec(args: argparse.Namespace) -> int:
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise SlotError("exec needs a command after --")
    config, state_dir = _load_config(args.config)
    resolved = resolve_slot(config, args.cli, args.slot, rotate=args.rotate, state_dir=state_dir)
    env = apply_env(None, {**resolved["env"], "SOIA_DISPATCH_SLOT": resolved["slot"]})
    print(f"[account_slots] cli={resolved['cli']} slot={resolved['slot']} basis={resolved['selection_basis']}", file=sys.stderr)
    return subprocess.call(command, env=env)


def cmd_init(args: argparse.Namespace) -> int:
    config, _ = _load_config(args.config)
    result = init_slot(config, args.cli, args.slot, links=args.link, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_confirm(args: argparse.Namespace) -> int:
    _, state_dir = _load_config(args.config)
    a, b = args.slots
    record_identity(state_dir, args.cli, a, b, "same" if args.same else "distinct")
    print(json.dumps({"status": "ok", "cli": args.cli, "slots": sorted((a, b)),
                      "decision": "same" if args.same else "distinct"}, ensure_ascii=False))
    return 0


def run_selftest() -> int:
    checks: list[tuple[str, bool]] = []

    def check(name: str, ok: bool) -> None:
        checks.append((name, bool(ok)))

    def raises(fn) -> bool:
        try:
            fn()
        except SlotError:
            return True
        return False

    executors = {"agy", "codex", "claude", "dsh"}
    home = Path("selftest-home")
    config = {
        "schema_version": 1,
        "slots": {
            "acct2": {"cli": "agy", "env": {"HOME": "~/.agy-profiles/{slot}"}, "note": "second consumer account"},
            "acct3": {"cli": "agy", "env": {"HOME": "{home}/.agy-profiles/{slot}"}},
            "work": {"cli": "codex", "env": {"CODEX_HOME": "~/.codex-work"}},
        },
        "slot_rotation": {"agy": ["default", "acct2", "acct3"]},
    }
    slots = load_slots(config, executors)
    check("declared slots load", set(slots) == {"acct2", "acct3", "work"})
    default = resolve_slot(config, "agy", None, home=home, executors=executors)
    check("no slot means default login with no override", default["slot"] == "default" and default["env"] == {})
    acct2 = resolve_slot(config, "agy", "acct2", home=home, executors=executors)
    check("~ and {slot} render against the real home",
          acct2["env"] == {"HOME": str(home / ".agy-profiles" / "acct2")} and acct2["display_env"] == {"HOME": "~/.agy-profiles/acct2"})
    acct3 = resolve_slot(config, "agy", "acct3", home=home, executors=executors)
    check("{home} renders and displays as ~", acct3["env"]["HOME"] == str(home) + "/.agy-profiles/acct3" and acct3["display_env"]["HOME"] == "~/.agy-profiles/acct3")
    check("agy isolation is marked verified", acct2["isolation_verified"].startswith("verified"))
    check("slot of another cli is refused", raises(lambda: resolve_slot(config, "agy", "work", home=home, executors=executors)))
    check("undeclared slot is refused", raises(lambda: resolve_slot(config, "agy", "acct9", home=home, executors=executors)))
    check("slot and rotate together are refused", raises(lambda: resolve_slot(config, "agy", "acct2", rotate=True, executors=executors)))
    bad_cases = {
        "credential variable": {"x": {"cli": "agy", "env": {"GEMINI_API_KEY": "v"}}},
        "address in value": {"x": {"cli": "agy", "env": {"HOME": "~/p/someone@example.com"}}},
        "address in note": {"x": {"cli": "agy", "env": {"HOME": "~/p"}, "note": "someone@example.com"}},
        "unknown template field": {"x": {"cli": "agy", "env": {"HOME": "{user}/p"}}},
        "reserved default": {"default": {"cli": "agy", "env": {"HOME": "~/p"}}},
        "unknown cli": {"x": {"cli": "nope", "env": {"HOME": "~/p"}}},
        "unknown field": {"x": {"cli": "agy", "env": {"HOME": "~/p"}, "email": "x"}},
        "bad name": {"Bad Name": {"cli": "agy", "env": {"HOME": "~/p"}}},
    }
    for label, bad in bad_cases.items():
        check(f"rejects {label}", raises(lambda bad=bad: load_slots({"slots": bad}, executors)))
    check("rotation naming an undeclared slot is refused",
          raises(lambda: rotation_order({"slot_rotation": {"agy": ["default", "ghost"]}}, "agy", slots)))
    check("implicit rotation is default + declared slots of that cli",
          rotation_order({}, "agy", slots) == ["default", "acct2", "acct3"])
    with tempfile.TemporaryDirectory() as tmp:
        state = Path(tmp)
        picks = [resolve_slot(config, "agy", rotate=True, state_dir=state, home=home, executors=executors)["slot"] for _ in range(4)]
        check("rotation walks round-robin and wraps", picks == ["default", "acct2", "acct3", "default"])
        peek = resolve_slot(config, "agy", rotate=True, peek=True, state_dir=state, home=home, executors=executors)["slot"]
        after = resolve_slot(config, "agy", rotate=True, state_dir=state, home=home, executors=executors)["slot"]
        check("peek does not advance rotation", peek == "acct2" and after == "acct2")
        stored = json.loads((state / ROTATION_FILE).read_text(encoding="utf-8"))
        check("rotation state stores only the last slot name", set(stored) == {"agy"} and set(stored["agy"]) == {"last", "updated_at"})
        check("rotation state file is 0600", (os.stat(state / ROTATION_FILE).st_mode & 0o777) == 0o600 or os.name == "nt")
    check("quota key is scoped per slot", scoped_quota_key("agy:gemini-4-argon-high", "acct2") == "agy:gemini-4-argon-high@acct2")
    check("default slot keeps the quota key", scoped_quota_key("codex", "default") == "codex" and scoped_quota_key("codex", None) == "codex")
    merged = apply_env({"PATH": "/bin", "HOME": "x"}, acct2["env"])
    check("apply_env overrides only the slot variables", merged["PATH"] == "/bin" and merged["HOME"] == acct2["env"]["HOME"])
    check("repository executors include agy", "agy" in known_executors())
    with tempfile.TemporaryDirectory() as tmp:
        fake_home = Path(tmp) / "home"
        (fake_home / ".cache").mkdir(parents=True)
        (fake_home / ".gitconfig").write_text("[user]\n", encoding="utf-8")
        (fake_home / ".gemini").mkdir()
        preview = init_slot({}, "agy", "acct4", dry_run=True, home=fake_home, executors=executors)
        check("init dry-run writes nothing", not (fake_home / ".agy-profiles").exists()
              and {a["action"] for a in preview["actions"]} >= {"mkdir", "link"})
        done = init_slot({}, "agy", "acct4", links=[".gitconfig", ".cache", ".gemini", ".ssh", "../x"],
                         home=fake_home, executors=executors)
        slot_home = fake_home / ".agy-profiles" / "acct4"
        check("init creates the slot home 0700", slot_home.is_dir() and (os.name == "nt" or (slot_home.stat().st_mode & 0o777) == 0o700))
        check("init links non-credential caches", (slot_home / ".cache").is_symlink() and (slot_home / ".gitconfig").is_symlink())
        refused = {a["path"] for a in done["actions"] if a["action"] == "refused"}
        check("init never links a login store or escapes the home", {".gemini", ".ssh", "../x"} <= refused
              and not (slot_home / ".gemini").exists())
        check("init returns a config snippet for an undeclared slot",
              done["config_snippet"] is not None and "acct4" in done["config_snippet"] and "@" not in done["config_snippet"])
        again = init_slot({}, "agy", "acct4", links=[".cache"], home=fake_home, executors=executors)
        check("init is idempotent and never overwrites", again["actions"] == [{"action": "skip", "path": ".cache", "reason": "already present in the slot"}])
        check("init refuses the default slot", raises(lambda: init_slot({}, "agy", "default", home=fake_home, executors=executors)))
        state = Path(tmp) / "state"
        check("no identity decision before confirm", identity_decision(state, "agy", "acct2", "acct3") is None)
        record_identity(state, "agy", "acct3", "acct2", "distinct")
        check("identity decision is remembered per unordered pair", identity_decision(state, "agy", "acct2", "acct3") == "distinct")
        stored = (state / IDENTITY_FILE).read_text(encoding="utf-8")
        check("identity state keeps only slot names", "acct2|acct3" in stored and "@" not in stored)
        check("confirm refuses the same slot twice", raises(lambda: record_identity(state, "agy", "acct2", "acct2", "same")))

    for label, ok in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")
    passed = sum(1 for _, ok in checks if ok)
    print(f"{passed}/{len(checks)} checks passed")
    return 0 if passed == len(checks) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--config", help="private config.yml (default follows SOIA_DEV_AGENT_CLI_DISPATCH_CONFIG_FILE)")
    sub = parser.add_subparsers(dest="command_name")

    p_list = sub.add_parser("list", help="list slots per cli (values shown with ~)")
    p_list.add_argument("--cli")
    p_list.add_argument("--json", action="store_true")

    def selection(p: argparse.ArgumentParser) -> None:
        p.add_argument("--cli", required=True, help="executor id, e.g. agy")
        p.add_argument("--slot", help="slot name; omit for the default login")
        p.add_argument("--rotate", action="store_true", help="take the next slot in slot_rotation.<cli>")

    p_resolve = sub.add_parser("resolve", help="print the chosen slot and its env overrides")
    selection(p_resolve)
    p_resolve.add_argument("--peek", action="store_true", help="with --rotate: show the next slot without advancing")
    p_resolve.add_argument("--format", choices=["json", "shell"], default="json")

    p_exec = sub.add_parser("exec", help="run a command with the slot's env overrides")
    selection(p_exec)
    p_exec.add_argument("command", nargs=argparse.REMAINDER)

    p_init = sub.add_parser("init", help="create a slot's isolated home and link non-credential caches")
    p_init.add_argument("--cli", required=True)
    p_init.add_argument("--slot", required=True)
    p_init.add_argument("--link", action="append", help="relative path under the home to link (repeatable); default per cli")
    p_init.add_argument("--dry-run", action="store_true")

    p_confirm = sub.add_parser("confirm", help="remember whether two slots are the same account")
    p_confirm.add_argument("--cli", required=True)
    p_confirm.add_argument("--slots", nargs=2, required=True, metavar="SLOT")
    group = p_confirm.add_mutually_exclusive_group(required=True)
    group.add_argument("--distinct", action="store_true")
    group.add_argument("--same", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.selftest:
        return run_selftest()
    handlers = {"list": cmd_list, "resolve": cmd_resolve, "exec": cmd_exec, "init": cmd_init, "confirm": cmd_confirm}
    if args.command_name not in handlers:
        parser.print_help()
        return 2
    try:
        return handlers[args.command_name](args)
    except (SlotError, ValueError) as exc:
        print(json.dumps({"status": "slot_error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
