#!/usr/bin/env python3
# @created_by openai/gpt-5
# @created_at 2026-07-10 17:58:15
# @modified_by anthropic/claude-opus-5
# @modified_at 2026-09-02 00:00:00
# @version 0.2.0
# @description Select a verified executor model and reasoning effort from model-catalog.yml.
# @changelog Add dispatch_role and the reviewer Independence Gate over catalog provider/model_family.
"""Mechanically route an executor family to a verified model/effort pair."""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalog_lib  # noqa: E402


class RouteError(Exception):
    pass


class IndependenceGateError(RouteError):
    """Raised when a reviewer would not be independent of the executor."""


# dispatch_role values recognized by the Independence Gate. Only `reviewer`
# is gated here: a reviewer that shares the executor's provider AND
# model_family cannot supply independent judgement about that executor's own
# output. The other roles are accepted and recorded, but not constrained.
DISPATCH_ROLES = ("coordinator", "executor", "verifier", "reviewer", "adversary", "mechanical")
GATED_ROLES = ("reviewer",)


PREFERRED_EFFORTS = {
    "easy": ["low", "medium", "high", "xhigh", "max"],
    "medium": ["medium", "high", "low", "xhigh", "max"],
    "hard": ["high", "xhigh", "max", "medium", "low"],
}


def _models_for_executor(data: dict, executor: str) -> list[dict[str, Any]]:
    result = []
    for provider in (data.get("providers") or {}).values():
        if isinstance(provider, dict) and provider.get("executor_cli") == executor:
            result.extend(model for model in provider.get("models", []) if isinstance(model, dict))
    return result


def _choose_effort(model: dict[str, Any], complexity: str, requested: str | None) -> tuple[str | None, str]:
    levels = model.get("supported_reasoning_levels") or []
    confidence = model.get("reasoning_levels_confidence")
    if requested:
        if requested in levels:
            return requested, ("explicit_unverified"
                               if confidence == "unverified" else "explicit")
        if confidence == "unverified":
            return requested, "explicit_unverified"
        raise RouteError(f"reasoning effort {requested!r} is not verified for {model.get('model_id')!r}")
    if confidence not in {"smoke_tested", "verified"}:
        return None, "explicit_unverified"
    default = model.get("default_reasoning_level")
    for candidate in PREFERRED_EFFORTS[complexity]:
        if candidate in levels:
            return candidate, "verified_auto"
    if default in levels:
        return default, "verified_auto"
    return None, "explicit_unverified"


def _cost_range(model: dict[str, Any]) -> dict[str, str | None]:
    pricing = model.get("pricing") or {}
    input_rate = pricing.get("input_per_1m")
    output_rate = pricing.get("output_per_1m")
    if not isinstance(input_rate, (int, float)) or not isinstance(output_rate, (int, float)):
        return {"basis": "1M input + 1M output, standard tier", "min_usd": None, "max_usd": None}
    total = Decimal(str(input_rate)) + Decimal(str(output_rate))
    value = format(total, "f").rstrip("0").rstrip(".") or "0"
    return {"basis": "1M input + 1M output, standard tier", "min_usd": value, "max_usd": value}


def _resolve_identity(data: dict, requested: str) -> tuple[str, str] | None:
    """Return (provider, model_family) for a catalog model, or None if unknown."""
    resolution = catalog_lib.find_model(data, requested)
    model = resolution.get("model")
    provider = resolution.get("provider")
    if not isinstance(model, dict) or not provider:
        return None
    family = model.get("model_family")
    return (str(provider), str(family) if family else "")


def check_independence(data: dict, role: str | None, reviewer_model: str | None, executor_model: str | None) -> dict[str, Any] | None:
    """Independence Gate. Returns an evidence dict, or raises for a conflict.

    Only applies to gated roles (currently `reviewer`). A reviewer must be
    told which model produced the work under review (`executor_model`);
    without it there is no way to prove independence, so the gate blocks
    rather than assuming. Same provider AND same model_family means the
    reviewer is the same generation of the same model line as the
    implementer -- that is not an independent second opinion.
    """
    if not role:
        return None
    if role not in DISPATCH_ROLES:
        raise RouteError(f"unknown dispatch_role {role!r}; expected one of {list(DISPATCH_ROLES)}")
    if role not in GATED_ROLES:
        return {"dispatch_role": role, "independence": "not_gated"}
    if not executor_model:
        raise IndependenceGateError(
            f"independence_gate: dispatch_role={role!r} requires --executor-model "
            "(the model that produced the work under review); independence cannot be asserted without it"
        )
    reviewer_identity = _resolve_identity(data, reviewer_model) if reviewer_model else None
    executor_identity = _resolve_identity(data, executor_model)
    if executor_identity is None:
        raise IndependenceGateError(
            f"independence_gate: executor model {executor_model!r} is not in the catalog, "
            "so its provider/model_family cannot be compared; register it before dispatching a reviewer"
        )
    if reviewer_identity is None:
        return {
            "dispatch_role": role,
            "independence": "unverified",
            "executor_model": executor_model,
            "executor_model_family": executor_identity[1],
            "note": "reviewer model is not resolvable in the catalog; independence is unverified, not proven",
        }
    if reviewer_identity == executor_identity:
        raise IndependenceGateError(
            f"independence_gate: reviewer model {reviewer_model!r} and executor model "
            f"{executor_model!r} share provider={reviewer_identity[0]!r} and "
            f"model_family={reviewer_identity[1]!r}; a same-family reviewer is not independent"
        )
    return {
        "dispatch_role": role,
        "independence": "independent",
        "executor_model": executor_model,
        "executor_model_family": executor_identity[1],
        "reviewer_model_family": reviewer_identity[1],
    }


def route_model(data: dict, executor: str, complexity: str, requested_model: str | None = None, requested_reasoning: str | None = None, role: str | None = None, executor_model: str | None = None) -> dict[str, Any]:
    if complexity not in PREFERRED_EFFORTS:
        raise RouteError(f"invalid complexity {complexity!r}")
    if requested_model:
        resolution = catalog_lib.find_model(data, requested_model)
        model = resolution.get("model")
        provider = resolution.get("provider")
        if not isinstance(model, dict) or not provider:
            raise RouteError(f"model {requested_model!r} not found in catalog")
        provider_block = (data.get("providers") or {}).get(provider) or {}
        if provider_block.get("executor_cli") != executor:
            raise RouteError(f"model {requested_model!r} does not belong to executor {executor!r}")
        effort, effort_status = _choose_effort(model, complexity, requested_reasoning)
        selection_status = effort_status if effort_status == "explicit_unverified" else "explicit"
        reason = "explicit model/reasoning selection takes precedence"
    else:
        candidates = [
            model for model in _models_for_executor(data, executor)
            if complexity in (model.get("routing_profile") or [])
            and model.get("discovered_at") and model.get("discovery_evidence")
            and model.get("supported_reasoning_levels")
            and model.get("reasoning_levels_confidence") in {"smoke_tested", "verified"}
        ]
        if not candidates:
            raise RouteError(f"no verified {complexity!r} routing candidate for executor {executor!r}")
        candidates.sort(key=lambda item: item.get("model_id", ""))
        model = candidates[0]
        effort, selection_status = _choose_effort(model, complexity, None)
        reason = f"catalog routing_profile={complexity}; discovery and reasoning evidence are present"
    independence = check_independence(data, role, model.get("model_id"), executor_model)
    receipt_extra = {"independence_gate": independence} if independence else {}
    return {
        **receipt_extra,
        "executor": executor,
        "selected_model": model.get("model_id"),
        "selected_reasoning_effort": effort,
        "task_complexity": complexity,
        "selection_reason": reason,
        "estimated_cost_range": _cost_range(model),
        "catalog_version": data.get("updated_at"),
        "selection_status": selection_status,
        "routing_evidence": model.get("discovery_evidence"),
    }


def run_selftest() -> int:
    data = catalog_lib.load_catalog(Path(__file__).resolve().parents[1] / "references" / "model-catalog.yml")
    checks: list[tuple[str, bool]] = []
    checks.append(("codex easy -> luna low", route_model(data, "codex", "easy")["selected_model"] == "gpt-5.6-luna" and route_model(data, "codex", "easy")["selected_reasoning_effort"] == "low"))
    checks.append(("codex medium -> terra medium", route_model(data, "codex", "medium")["selected_model"] == "gpt-5.6-terra" and route_model(data, "codex", "medium")["selected_reasoning_effort"] == "medium"))
    checks.append(("codex hard -> sol high", route_model(data, "codex", "hard")["selected_model"] == "gpt-5.6-sol" and route_model(data, "codex", "hard")["selected_reasoning_effort"] == "high"))
    pi_easy = route_model(data, "pi", "easy")
    checks.append(("pi easy -> deepseek-v4-flash low", pi_easy["selected_model"] == "deepseek-v4-flash" and pi_easy["selected_reasoning_effort"] == "low" and pi_easy["selection_status"] == "verified_auto"))
    pi_explicit = route_model(data, "pi", "easy", "deepseek/deepseek-v4-flash", "low")
    checks.append(("pi provider-qualified explicit model resolves", pi_explicit["selected_model"] == "deepseek-v4-flash" and pi_explicit["selection_status"] == "explicit"))
    pi_vision_low = route_model(data, "pi", "easy", "deepseek-v4-flash-vision-exp", "low")
    checks.append((
        "pi vision-exp low is explicit with Pi JSONL smoke evidence",
        pi_vision_low["selected_model"] == "deepseek-v4-flash-vision-exp"
        and pi_vision_low["selected_reasoning_effort"] == "low"
        and pi_vision_low["selection_status"] == "explicit",
    ))
    for unverified_level in ("off", "high", "max"):
        try:
            route_model(data, "pi", "easy", "deepseek-v4-flash-vision-exp", unverified_level)
        except RouteError:
            checks.append((f"pi vision-exp {unverified_level} blocks as unverified", True))
        else:
            checks.append((f"pi vision-exp {unverified_level} blocks as unverified", False))
    pi_vision_no_reasoning = route_model(data, "pi", "easy", "deepseek-v4-flash-vision-exp")
    checks.append((
        "pi vision-exp explicit model without reasoning selects only verified low",
        pi_vision_no_reasoning["selected_model"] == "deepseek-v4-flash-vision-exp"
        and pi_vision_no_reasoning["selected_reasoning_effort"] == "low"
        and pi_vision_no_reasoning["selection_status"] == "explicit",
    ))
    pi_auto = route_model(data, "pi", "easy")
    checks.append((
        "pi easy auto-route never selects the UI-only-observed vision model",
        pi_auto["selected_model"] != "deepseek-v4-flash-vision-exp",
    ))
    codex_unverified = route_model(data, "codex", "easy", "gpt-5.5", "high")
    checks.append((
        "explicit reasoning listed with unverified confidence stays explicit_unverified",
        codex_unverified["selection_status"] == "explicit_unverified"
        and codex_unverified["selected_reasoning_effort"] == "high",
    ))
    try:
        route_model(data, "pi", "medium")
    except RouteError:
        checks.append(("pi medium blocks without task-quality evidence", True))
    else:
        checks.append(("pi medium blocks without task-quality evidence", False))
    explicit = route_model(data, "codex", "easy", "gpt-5.6-sol", "xhigh")
    checks.append(("explicit model/effort wins", explicit["selected_model"] == "gpt-5.6-sol" and explicit["selected_reasoning_effort"] == "xhigh" and explicit["selection_status"] == "explicit"))
    try:
        route_model(data, "claude", "hard")
    except RouteError:
        checks.append(("no verified claude hard candidate blocks", True))
    else:
        checks.append(("no verified claude hard candidate blocks", False))
    try:
        route_model(data, "agy", "easy")
    except RouteError:
        checks.append(("agy blocks without verified catalog candidate", True))
    else:
        checks.append(("agy blocks without verified catalog candidate", False))
    try:
        route_model(data, "agy", "easy", "gemini-3.5-flash")
    except RouteError:
        checks.append(("agy rejects Gemini API catalog ids even when explicitly requested", True))
    else:
        checks.append(("agy rejects Gemini API catalog ids even when explicitly requested", False))
    # --- Independence Gate (dispatch_role) ---
    try:
        route_model(data, "claude", "medium", "claude-sonnet-5", role="reviewer", executor_model="claude-sonnet-5")
    except IndependenceGateError:
        checks.append(("reviewer with the same model as the executor blocks", True))
    else:
        checks.append(("reviewer with the same model as the executor blocks", False))
    try:
        route_model(data, "claude", "medium", "claude-opus-4-8", role="reviewer", executor_model="claude-opus-4-7")
    except IndependenceGateError:
        checks.append(("reviewer in the same model_family as the executor blocks", True))
    else:
        checks.append(("reviewer in the same model_family as the executor blocks", False))
    try:
        route_model(data, "claude", "medium", "claude-sonnet-5", role="reviewer")
    except IndependenceGateError:
        checks.append(("reviewer without --executor-model blocks", True))
    else:
        checks.append(("reviewer without --executor-model blocks", False))
    cross_provider = route_model(
        data, "claude", "medium", "claude-opus-4-8", role="reviewer",
        executor_model="deepseek-v4-flash-vision-exp",
    )
    checks.append((
        "reviewer from a different provider passes the gate",
        cross_provider["independence_gate"]["independence"] == "independent"
        and cross_provider["selection_status"] != "blocked",
    ))
    cross_generation = route_model(
        data, "claude", "medium", "claude-opus-5", role="reviewer", executor_model="claude-opus-4-8",
    )
    checks.append((
        "opus-5 reviewing opus-4-8 is independent (distinct model_family)",
        cross_generation["independence_gate"]["independence"] == "independent",
    ))
    non_gated = route_model(data, "claude", "medium", role="executor")
    checks.append((
        "non-reviewer roles are recorded but not gated",
        non_gated["independence_gate"]["independence"] == "not_gated",
    ))
    no_role = route_model(data, "claude", "medium")
    checks.append(("omitting --role leaves the receipt unchanged", "independence_gate" not in no_role))
    try:
        route_model(data, "claude", "medium", role="auditor")
    except RouteError:
        checks.append(("unknown dispatch_role blocks", True))
    else:
        checks.append(("unknown dispatch_role blocks", False))

    receipt = route_model(data, "claude", "medium")
    checks.append(("route receipt has fixed fields", all(key in receipt for key in ("selected_model", "selected_reasoning_effort", "task_complexity", "selection_reason", "estimated_cost_range", "catalog_version", "selection_status"))))
    print("=== route_model.py selftest ===")
    for name, passed in checks:
        print(f"[{'PASS' if passed else 'FAIL'}] {name}")
    passed_count = sum(1 for _, passed in checks if passed)
    print(f"{passed_count}/{len(checks)} checks passed")
    return 0 if passed_count == len(checks) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executor", choices=["codex", "claude", "agy", "gemini", "kimi", "opencode", "qwen", "pi"])
    parser.add_argument("--complexity", choices=["easy", "medium", "hard"])
    parser.add_argument("--model")
    parser.add_argument("--reasoning")
    parser.add_argument("--role", choices=list(DISPATCH_ROLES), help="dispatch_role for this call; 'reviewer' activates the Independence Gate")
    parser.add_argument("--executor-model", dest="executor_model", help="model that produced the work under review; required when --role reviewer")
    parser.add_argument("--catalog")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return run_selftest()
    if not args.executor or not args.complexity:
        parser.error("--executor and --complexity are required unless --selftest is used")
    catalog_path = Path(args.catalog) if args.catalog else Path(__file__).resolve().parents[1] / "references" / "model-catalog.yml"
    try:
        data = catalog_lib.load_catalog(catalog_path)
        validation = catalog_lib.validate_catalog(data)
        if validation["errors"]:
            raise RouteError("invalid catalog: " + "; ".join(validation["errors"][:5]))
        result = route_model(
            data, args.executor, args.complexity, args.model, args.reasoning,
            role=args.role, executor_model=args.executor_model,
        )
    except (OSError, catalog_lib.CatalogError, RouteError) as exc:
        print(json.dumps({"selection_status": "blocked", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
