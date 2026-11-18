#!/usr/bin/env python3
# @created_by claude opus 4.6
# @created_at 2026-08-04 12:04:00
# @modified_by claude opus 5.5
# @modified_at 2026-11-18 17:10:00
# @version 0.2.1
# @description Resolve optional config and portable state/temp paths for dispatch runs.
# @changelog 0.2.1: reject non-mapping `slots`/`slot_rotation` (account slots). 0.2.0: Validate run ids and enforce a non-destructive retained-run capacity gate.
"""Resolve config and user-owned storage paths for dispatch runs."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalog_lib  # noqa: E402


SKILL_NAME = "soia-dev-agent-cli-dispatch"
CONFIG_ENV_VAR = "SOIA_DEV_AGENT_CLI_DISPATCH_CONFIG_FILE"
DEFAULT_MAX_RUNS = 50
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _path_value(value: object) -> Path | None:
    if not isinstance(value, str) or not value or value.startswith("<"):
        return None
    return Path(value).expanduser()


def _base_from_env(values: Mapping[str, str], name: str, fallback: Path) -> Path:
    configured = _path_value(values.get(name))
    return configured or fallback


def default_config_path(env: Mapping[str, str] | None = None, home: Path | None = None) -> Path:
    values = os.environ if env is None else env
    user_home = Path.home() if home is None else home
    explicit = _path_value(values.get(CONFIG_ENV_VAR))
    if explicit:
        return explicit
    config_home = _base_from_env(values, "SOIA_SKILLS_CONFIG_HOME", user_home / ".config" / "soia-skills")
    return config_home / SKILL_NAME / "config.yml"


def load_config(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = catalog_lib.load_catalog(path)
    except (OSError, catalog_lib.CatalogError) as exc:
        raise ValueError(f"failed to load config {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("config schema_version must be 1")
    if data.get("env") is not None and not isinstance(data["env"], dict):
        raise ValueError("config env must be a mapping")
    if data.get("storage") is not None and not isinstance(data["storage"], dict):
        raise ValueError("config storage must be a mapping")
    if data.get("retention") is not None and not isinstance(data["retention"], dict):
        raise ValueError("config retention must be a mapping")
    for key in ("slots", "slot_rotation"):
        if data.get(key) is not None and not isinstance(data[key], dict):
            raise ValueError(f"config {key} must be a mapping (see references/account-slots.md)")
    max_runs = retained_run_limit(data)
    if max_runs < 1:
        raise ValueError("retention.max_runs must be a positive integer")
    return data


def effective_env(config: Mapping[str, object], env: Mapping[str, str] | None = None) -> dict[str, str]:
    values = dict(config.get("env", {}) or {})
    values.update(os.environ if env is None else env)
    return {str(key): str(value) for key, value in values.items() if value is not None}


def storage_paths(
    config: Mapping[str, object] | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
    temp_root: Path | None = None,
) -> dict[str, Path]:
    config = config or {}
    values = effective_env(config, env)
    user_home = Path.home() if home is None else home
    state_base = _base_from_env(values, "SOIA_SKILLS_STATE_HOME", user_home / ".local" / "state" / "soia-skills")
    temp_base = Path(tempfile.gettempdir()) if temp_root is None else temp_root

    storage = config.get("storage", {})
    if not isinstance(storage, dict):
        storage = {}
    state_override = _path_value(values.get("SOIA_DISPATCH_STATE_DIR")) or _path_value(storage.get("manifest_root"))
    temp_override = _path_value(values.get("SOIA_DISPATCH_TEMP_DIR")) or _path_value(storage.get("prompt_root"))
    state_dir = state_override or state_base / SKILL_NAME
    temp_dir = temp_override or temp_base / SKILL_NAME
    return {
        "state": state_dir,
        "runs": state_dir / "runs",
        "temp": temp_dir,
        "prompts": temp_dir / "prompts",
    }


def retained_run_limit(config: Mapping[str, object] | None = None) -> int:
    retention = (config or {}).get("retention", {})
    value = retention.get("max_runs", DEFAULT_MAX_RUNS) if isinstance(retention, dict) else DEFAULT_MAX_RUNS
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("retention.max_runs must be a positive integer")
    return value


def ensure_run_capacity(runs_root: Path, run_id: str, max_runs: int) -> None:
    if (runs_root / run_id).exists() or not runs_root.is_dir():
        return
    retained = sum(1 for child in runs_root.iterdir() if child.is_dir() and (child / "manifest.json").is_file())
    if retained >= max_runs:
        raise ValueError(
            f"retained run limit reached ({retained}/{max_runs}); inspect and explicitly clean old runs before starting a new run"
        )


def resolve_manifest_dir(
    run_id: str,
    explicit: str | None = None,
    config: Mapping[str, object] | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
    temp_root: Path | None = None,
) -> Path:
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError("run_id must be 1-128 characters using letters, digits, dot, underscore, or hyphen")
    if explicit:
        return Path(explicit).expanduser()
    return storage_paths(config=config, env=env, home=home, temp_root=temp_root)["runs"] / run_id


def run_selftest() -> int:
    fake_home = Path("test-home")
    config = {
        "schema_version": 1,
        "env": {"SOIA_DISPATCH_STATE_DIR": "<ignored-placeholder>"},
        "storage": {"manifest_root": None},
        "retention": {"max_runs": 2},
    }
    paths = storage_paths(config=config, env={}, home=fake_home, temp_root=Path("test-temp"))
    invalid_run_blocked = False
    try:
        resolve_manifest_dir("../escape", config=config, env={}, home=fake_home)
    except ValueError:
        invalid_run_blocked = True
    capacity_blocked = False
    with tempfile.TemporaryDirectory() as tmp:
        runs_root = Path(tmp)
        for run_name in ("run-1", "run-2"):
            run_dir = runs_root / run_name
            run_dir.mkdir()
            (run_dir / "manifest.json").write_text("{}", encoding="utf-8")
        try:
            ensure_run_capacity(runs_root, "run-3", retained_run_limit(config))
        except ValueError:
            capacity_blocked = True
        ensure_run_capacity(runs_root, "run-2", retained_run_limit(config))
    checks = [
        ("default config path", default_config_path(env={}, home=fake_home) == fake_home / ".config/soia-skills" / SKILL_NAME / "config.yml"),
        ("config root override is not double-nested", default_config_path(env={"SOIA_SKILLS_CONFIG_HOME": "custom-config"}, home=fake_home) == Path("custom-config") / SKILL_NAME / "config.yml"),
        ("state path is user-owned", paths["runs"] == fake_home / ".local/state/soia-skills" / SKILL_NAME / "runs"),
        ("state root override is not double-nested", storage_paths(config={}, env={"SOIA_SKILLS_STATE_HOME": "custom-state"}, home=fake_home)["runs"] == Path("custom-state") / SKILL_NAME / "runs"),
        ("temp path is isolated", paths["prompts"] == Path("test-temp") / SKILL_NAME / "prompts"),
        ("run path includes run id", resolve_manifest_dir("run-1", config=config, env={}, home=fake_home, temp_root=Path("test-temp")) == paths["runs"] / "run-1"),
        ("invalid run id is blocked", invalid_run_blocked),
        ("retention limit parsed", retained_run_limit(config) == 2),
        ("new run blocked at retention limit", capacity_blocked),
    ]
    for label, passed in checks:
        print(f"[{'PASS' if passed else 'FAIL'}] {label}")
    return 0 if all(passed for _, passed in checks) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return run_selftest()
    config_path = args.config or default_config_path()
    try:
        config = load_config(config_path)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    paths = storage_paths(config=config)
    if args.run_id:
        paths["run"] = resolve_manifest_dir(args.run_id, config=config)
    result = {name: str(path) for name, path in paths.items()}
    result["max_runs"] = retained_run_limit(config)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for name, path in result.items():
            print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
