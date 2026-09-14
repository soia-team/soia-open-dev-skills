#!/usr/bin/env python3
# @created_by openai/gpt-5
# @created_at 2026-07-10 17:58:15
# @modified_by dsh + deepseek-flash (actual model unverified)
# @modified_at 2026-09-14 10:56:45
# @version 0.4.0
# @description Select a verified executor model and reasoning effort from model-catalog.yml.
# @changelog Quota evidence is re-validated inside route_model (a copied kind string is not a credential): auth/source/probed_at/model/bucket checks run on every library call, unknown catalog models and unparseable probe times are rejected per row, an observation with bucket=unknown never authorizes and catalog quota_scope_keys are no longer injected as observed scopes, and selected_observation is chosen to match the bound model+scope instead of the first same-model row.
"""Mechanically route an executor family to a verified model/effort pair.

The live-quota precheck is mandatory evidence, not a post-hoc check: a route
succeeds only when a validated `quota_observations[]` report carries
`auth_status=ok` and an observation that is `available` for the selected
model's own bucket, with the model/bucket/scope binding checked against the
catalog. The evidence is re-validated at the point of use, because a copied
`kind` string proves nothing: unknown catalog models, unparseable probe times
and observations that name no concrete bucket never authorize. Missing,
malformed or mis-bound reports block with a non-zero exit; they are never
normalized into a valid binding, and customer approval cannot rewrite an
exhausted or unknown bucket into an available one.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
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
# is gated here. The default policy compares provider/model_family; an explicit
# different_model policy compares canonical model IDs. Neither permits the
# same model. Other roles are accepted and recorded, but not constrained.
DISPATCH_ROLES = ("coordinator", "executor", "verifier", "reviewer", "adversary", "mechanical")
GATED_ROLES = ("reviewer",)


PREFERRED_EFFORTS = {
    "easy": ["low", "medium", "high", "xhigh", "max"],
    "medium": ["medium", "high", "low", "xhigh", "max"],
    "hard": ["high", "xhigh", "max", "medium", "low"],
}

# Quota precheck vocabulary. `available` is the only state that can authorize a
# selection; `source` and `probed_at` are required on every observation so a
# hand-written or stale claim cannot pass as a live reading.
QUOTA_STATES = ("available", "exhausted", "unknown")
RECOMMENDATIONS = ("proceed", "hold", "skip")
UNKNOWN_SCOPE_TEXT = "unknown"
EVIDENCE_KIND = "quota_precheck/1"


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


def _text(value: Any) -> str | None:
    """Return a trimmed non-empty string, or None for anything else."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _resolve_model(data: dict, requested: str) -> tuple[dict[str, Any] | None, str | None]:
    """Resolve a model string to (catalog entry, provider name), or (None, None)."""
    resolution = catalog_lib.find_model(data, requested)
    model = resolution.get("model")
    provider = resolution.get("provider")
    if not isinstance(model, dict) or not isinstance(provider, str) or not provider:
        return None, None
    return model, provider


def _provider_executor(data: dict, provider: str | None) -> str | None:
    block = (data.get("providers") or {}).get(provider) or {}
    executor = block.get("executor_cli")
    return str(executor) if executor else None


def _bucket_index(data: dict) -> dict[str, set[str]]:
    """Map every catalog-declared quota bucket to the model ids that declare it."""
    index: dict[str, set[str]] = {}
    for provider in (data.get("providers") or {}).values():
        if not isinstance(provider, dict):
            continue
        for model in provider.get("models", []) or []:
            if not isinstance(model, dict) or not model.get("model_id"):
                continue
            for raw in model.get("quota_scope_keys") or []:
                bucket = _text(raw)
                if bucket:
                    index.setdefault(bucket, set()).add(str(model["model_id"]))
    return index


def _effective_scope(executor: str, model_id: str | None, bucket: str) -> str:
    """Quota scope key for one observation.

    A real bucket name is the scope; an unavailable bucket name falls back to
    `executor:model`, matching the quota_scope_key rule in dispatch-contract.md.
    """
    if bucket and bucket.lower() != UNKNOWN_SCOPE_TEXT:
        return bucket
    return f"{executor}:{model_id or 'unknown'}"


def _parse_probed_at(value: str) -> datetime | None:
    """Parse a probe timestamp, accepting ISO-8601 with an optional trailing Z.

    Parseability is the whole requirement here: this fix does not invent a
    maximum age or freshness window, and it does not claim to authenticate the
    probe source. A value that cannot be read as a time cannot support a
    live-quota claim either way.
    """
    text = value.strip()
    if text[-1:] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _normalize_observation(data: dict, bucket_index: dict[str, set[str]], executor: str, item: Any, index: int) -> dict[str, Any]:
    """Validate one `quota_observations[]` item and return its normalized record.

    Every item must carry a non-empty `bucket`, `model`, `state`, `source` and
    `probed_at`, and its `model` must resolve in the catalog. An item that names
    a catalog model must also bind that model to a bucket the model can actually
    use; a mismatch is reported instead of being normalized away. A bucket name
    of `unknown` is recorded (the contract uses it when a probe cannot name the
    bucket) but is marked non-authorizing: it names no concrete bucket, so it
    can never prove availability for any model and no catalog scope is
    substituted for it.
    """
    if not isinstance(item, dict):
        raise RouteError(
            f"quota_evidence_malformed: quota_observations[{index}] must be an object, "
            f"got {type(item).__name__}"
        )
    bucket = _text(item.get("bucket"))
    model_text = _text(item.get("model"))
    state = _text(item.get("state"))
    missing = [name for name, value in (("bucket", bucket), ("model", model_text), ("state", state)) if not value]
    if missing:
        raise RouteError(
            f"quota_evidence_malformed: quota_observations[{index}] is missing non-empty {', '.join(missing)}"
        )
    if state not in QUOTA_STATES:
        raise RouteError(
            f"quota_evidence_malformed: quota_observations[{index}].state={state!r} is not one of {list(QUOTA_STATES)}"
        )
    source = _text(item.get("source"))
    probed_at = _text(item.get("probed_at"))
    if not source or not probed_at:
        absent = ", ".join(
            name for name, value in (("source", source), ("probed_at", probed_at)) if not value
        )
        raise RouteError(
            f"quota_evidence_incomplete: quota_observations[{index}] ({model_text!r} / bucket {bucket!r}) "
            f"has no non-empty {absent}; only a reading from this run's read-only probe can authorize a selection"
        )
    if _parse_probed_at(probed_at) is None:
        raise RouteError(
            f"quota_evidence_malformed: quota_observations[{index}] ({model_text!r} / bucket {bucket!r}) "
            f"has probed_at={probed_at!r}, which is not a parseable timestamp; a probe time that cannot be "
            "read cannot support a live-quota claim"
        )
    model, _provider = _resolve_model(data, model_text)
    if model is None or not model.get("model_id"):
        raise RouteError(
            f"quota_binding_conflict: quota_observations[{index}] names model {model_text!r}, which does not "
            "resolve in the catalog; every observation model must be catalog-resolvable and an unresolvable "
            "model authorizes nothing"
        )
    model_id = str(model["model_id"])
    declared = [key for key in (_text(raw) for raw in (model.get("quota_scope_keys") or [])) if key]
    real_bucket = bucket if bucket.lower() != UNKNOWN_SCOPE_TEXT else None
    if real_bucket and declared and real_bucket not in declared:
        raise RouteError(
            f"quota_binding_conflict: quota_observations[{index}] binds bucket {bucket!r} to model {model_id!r}, "
            f"but that model's declared quota_scope_keys are {declared}; the binding is not normalized into a valid one"
        )
    if real_bucket and real_bucket in bucket_index and model_id not in bucket_index[real_bucket]:
        raise RouteError(
            f"quota_binding_conflict: bucket {bucket!r} is declared by {sorted(bucket_index[real_bucket])} in the catalog, "
            f"not by observation model {model_id!r}; an alias or whitespace-normalized model does not launder the mismatch"
        )
    return {
        "index": index,
        "bucket": bucket,
        "model": model_text,
        "model_id": model_id,
        "state": state,
        "source": source,
        "probed_at": probed_at,
        "reset_at": _text(item.get("reset_at")),
        "scope_key": _effective_scope(executor, model_id, bucket),
        "bucket_known": real_bucket is not None,
    }


def normalize_quota_report(payload: Any, data: dict, source_label: str = "<inline>") -> dict[str, Any]:
    """Validate a quota precheck report and return the evidence route_model consumes.

    Stable error prefixes let a blocked route be traced to exactly one broken
    requirement: `quota_evidence_malformed`, `quota_evidence_incomplete`,
    `auth_not_ok`, `quota_binding_conflict`, `recommendation_blocked`.

    Only observations that name a concrete bucket appear in the returned
    `available` list; a bucket recorded as `unknown` stays in `observations` as
    non-authorizing evidence. The returned dict is a convenience view, not a
    credential: `route_model()` re-validates the same content before use.
    """
    if not isinstance(payload, dict):
        raise RouteError(
            "quota_evidence_malformed: the quota precheck report must be a JSON object carrying 'executor', "
            "'auth_status' and 'quota_observations[]'; a bare list cannot prove auth_status or a bucket binding"
        )
    executor = _text(payload.get("executor"))
    auth_status = _text(payload.get("auth_status"))
    if not executor:
        raise RouteError("quota_evidence_malformed: report is missing a non-empty 'executor'")
    if not auth_status:
        raise RouteError(
            "quota_evidence_malformed: report is missing a non-empty 'auth_status'; auth_status=ok is a proceed condition"
        )
    if auth_status != "ok":
        raise RouteError(
            f"auth_not_ok: precheck auth_status={auth_status!r} for executor {executor!r}; only auth_status=ok plus an "
            "available observation bound to the selected model can authorize a dispatch. Customer approval covers cost "
            "and waiting preferences only and cannot rewrite this fact."
        )
    items = payload.get("quota_observations")
    if not isinstance(items, list) or not items:
        raise RouteError(
            "quota_evidence_incomplete: report must carry a non-empty 'quota_observations' list; "
            "an empty or missing list cannot authorize a selection"
        )
    raw_selected = payload.get("selected_model")
    raw_scope = payload.get("quota_scope_key")
    if (raw_selected is None) != (raw_scope is None):
        raise RouteError(
            "quota_binding_conflict: 'selected_model' and 'quota_scope_key' must be present together; a half-bound "
            "report cannot be checked against the observation it claims"
        )
    selected_model = _text(raw_selected) if raw_selected is not None else None
    quota_scope_key = _text(raw_scope) if raw_scope is not None else None
    if raw_selected is not None and not selected_model:
        raise RouteError("quota_evidence_malformed: 'selected_model' is present but empty")
    if raw_scope is not None and not quota_scope_key:
        raise RouteError("quota_evidence_malformed: 'quota_scope_key' is present but empty")
    raw_recommendation = payload.get("recommendation")
    recommendation = _text(raw_recommendation) if raw_recommendation is not None else None
    if raw_recommendation is not None and recommendation not in RECOMMENDATIONS:
        raise RouteError(
            f"quota_evidence_malformed: recommendation={raw_recommendation!r} is not one of {list(RECOMMENDATIONS)}"
        )
    if recommendation in ("hold", "skip"):
        raise RouteError(
            f"recommendation_blocked: precheck recommendation={recommendation!r}; the report itself says not to dispatch, "
            "and customer approval cannot turn that into a selection"
        )
    bucket_index = _bucket_index(data)
    observations = [
        _normalize_observation(data, bucket_index, executor, item, index)
        for index, item in enumerate(items)
    ]
    available = [
        obs for obs in observations
        if obs["state"] == "available" and obs["bucket_known"]
    ]
    return {
        "kind": EVIDENCE_KIND,
        "source": source_label,
        "executor": executor,
        "auth_status": auth_status,
        "selected_model": selected_model,
        "quota_scope_key": quota_scope_key,
        "recommendation": recommendation,
        "observations": observations,
        "available": available,
        "unknown_bucket_available": [
            obs for obs in observations
            if obs["state"] == "available" and not obs["bucket_known"]
        ],
    }


def load_quota_observations(path: Path, data: dict, *, source_label: str | None = None) -> dict[str, Any]:
    """Read and validate a precheck report from disk (see normalize_quota_report).

    `data` is the loaded model catalog: bucket/model bindings are checked against
    it here, so a malformed report is rejected before it can become evidence.
    `route_model()` re-validates the same content at the point of use, because
    the returned dict is not itself a credential.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RouteError(f"quota_evidence_unreadable: cannot read quota observations from {path}: {exc}") from exc
    return normalize_quota_report(payload, data, source_label=source_label or str(path))


def _resolve_identity(data: dict, requested: str) -> tuple[str, str] | None:
    """Return (provider, model_family) for a catalog model, or None if unknown."""
    model, provider = _resolve_model(data, requested)
    if model is None:
        return None
    family = model.get("model_family")
    return (str(provider), str(family) if family else "")


def check_independence(data: dict, role: str | None, reviewer_model: str | None, executor_model: str | None, policy: str = "different_family") -> dict[str, Any] | None:
    """Independence Gate. Returns an evidence dict, or raises for a conflict.

    Only applies to gated roles (currently `reviewer`). A reviewer must be
    told which model produced the work under review (`executor_model`);
    without it there is no way to prove independence, so the gate blocks
    rather than assuming. The default policy rejects the same provider/family;
    an explicit different_model policy permits distinct canonical model IDs.
    Both policies reject the same canonical model.
    """
    if policy not in ("different_family", "different_model"):
        raise IndependenceGateError(f"independence_gate: unknown independence policy {policy!r}")
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
    reviewer_entry, _ = _resolve_model(data, reviewer_model)
    executor_entry, _ = _resolve_model(data, executor_model)
    same_model = reviewer_entry.get("model_id") == executor_entry.get("model_id")
    if same_model or (policy == "different_family" and reviewer_identity == executor_identity):
        raise IndependenceGateError(
            f"independence_gate: reviewer model {reviewer_model!r} and executor model "
            f"{executor_model!r} share provider={reviewer_identity[0]!r} and "
            f"model_family={reviewer_identity[1]!r}; reviewer conflicts with policy={policy!r}"
        )
    return {
        "dispatch_role": role,
        "independence": "independent",
        "policy": policy,
        "executor_model": executor_model,
        "executor_model_family": executor_identity[1],
        "reviewer_model_family": reviewer_identity[1],
    }


def _require_quota_evidence(data: dict, quota_evidence: dict[str, Any] | None, executor: str) -> dict[str, Any]:
    """Re-validate quota evidence for this call and return the trusted record.

    `kind` is a shape marker, not a credential: any dict can copy that string.
    Every field that can authorize a selection is therefore re-derived from the
    evidence's own observation records through `normalize_quota_report()`, so a
    hand-built dict carrying `kind="quota_precheck/1"` still has to survive the
    same auth/source/time/model/bucket checks as a report read from disk.
    """
    if quota_evidence is None:
        raise RouteError(
            "quota_evidence_missing: routing requires the live-quota precheck report; pass "
            "--quota-observations <precheck-report.json>. A model id alone, or no report at all, never authorizes a selection."
        )
    if not isinstance(quota_evidence, dict):
        raise RouteError(
            "quota_evidence_missing: quota evidence must be the validated object returned by "
            "load_quota_observations()/normalize_quota_report(); a raw dict skips the report checks and is not accepted"
        )
    observations = quota_evidence.get("observations")
    if quota_evidence.get("kind") != EVIDENCE_KIND or not isinstance(observations, list):
        raise RouteError(
            "quota_evidence_missing: quota evidence must be the object returned by "
            "load_quota_observations()/normalize_quota_report(). A dict with a copied kind string is not a "
            "credential and skips the report checks; the observation content is re-validated here, not trusted."
        )
    payload = {
        "executor": quota_evidence.get("executor"),
        "auth_status": quota_evidence.get("auth_status"),
        "selected_model": quota_evidence.get("selected_model"),
        "quota_scope_key": quota_evidence.get("quota_scope_key"),
        "recommendation": quota_evidence.get("recommendation"),
        "quota_observations": [
            {key: item.get(key) for key in ("bucket", "model", "state", "source", "probed_at", "reset_at")}
            if isinstance(item, dict) else item
            for item in observations
        ],
    }
    validated = normalize_quota_report(
        payload, data, source_label=_text(quota_evidence.get("source")) or "<inline evidence>"
    )
    if validated["executor"] != executor:
        raise RouteError(
            f"quota_binding_conflict: precheck report executor {validated['executor']!r} does not match routed executor {executor!r}"
        )
    return validated


def _authorizing_observations(available: list[dict[str, Any]], model_id: str | None) -> list[dict[str, Any]]:
    """Available observations whose own model id is this model's id.

    Intersection by model identity is deliberate: another bucket's `available`
    state, an alias of another model, or a bucket name inferred from the
    catalog must never be promoted to this model.
    """
    if not model_id:
        return []
    return [obs for obs in available if obs.get("model_id") == model_id]


def _unknown_bucket_note(evidence: dict[str, Any]) -> str:
    """Diagnostic suffix for available observations that name no concrete bucket."""
    rows = evidence.get("unknown_bucket_available") or []
    if not rows:
        return ""
    labels = sorted({f"{obs['model']}@{obs['scope_key']}" for obs in rows})
    return (
        " Observation(s) recorded with bucket='unknown': " + ", ".join(labels)
        + "; an unknown bucket name proves no bucket availability and authorizes nothing."
    )


def _scope_keys_for(executor: str, model: dict[str, Any], authorizing: list[dict[str, Any]]) -> list[str]:
    """Quota scope keys that belong to the selected model and this precheck.

    Keys come only from the observations that authorized the selection. Catalog
    `quota_scope_keys` are declarations, not observations: adding them here
    would let a catalog bucket the probe never saw appear as the scope a live
    precheck authorized. An observation whose bucket is `unknown` is never
    authorizing, so the `executor:model` fallback is defensive only and never
    stands in for an observed scope.
    """
    keys = {obs["scope_key"] for obs in authorizing if obs.get("scope_key")}
    if not keys:
        keys.add(f"{executor}:{model.get('model_id')}")
    return sorted(keys)


def route_model(data: dict, executor: str, complexity: str, requested_model: str | None = None, requested_reasoning: str | None = None, role: str | None = None, executor_model: str | None = None, quota_evidence: dict[str, Any] | None = None, independence_policy: str = "different_family") -> dict[str, Any]:
    """Select a model/effort pair authorized by a validated live-quota precheck.

    `quota_evidence` must come from `load_quota_observations()` /
    `normalize_quota_report()`, and is re-validated here from its observation
    content rather than trusted by its `kind` marker. There is no fallback
    path: auto-routing and explicit selection both require `auth_status=ok` and
    an available observation bound to the selected model's own concrete bucket.
    A report that already declares `selected_model`/`quota_scope_key` is treated
    as a binding: auto-routing may only confirm that model, never return a
    different one.
    """
    if complexity not in PREFERRED_EFFORTS:
        raise RouteError(f"invalid complexity {complexity!r}")

    # Resolve the request first: contract violations that do not depend on
    # quota (unknown model, wrong executor, no verified candidate) keep their
    # own diagnostics instead of being masked by the quota gate.
    explicit = requested_model is not None
    model: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] = []
    if explicit:
        model, provider = _resolve_model(data, requested_model)
        if model is None:
            raise RouteError(f"model {requested_model!r} not found in catalog")
        if _provider_executor(data, provider) != executor:
            raise RouteError(f"model {requested_model!r} does not belong to executor {executor!r}")
    else:
        candidates = [
            candidate for candidate in _models_for_executor(data, executor)
            if complexity in (candidate.get("routing_profile") or [])
            and candidate.get("discovered_at") and candidate.get("discovery_evidence")
            and candidate.get("supported_reasoning_levels")
            and candidate.get("reasoning_levels_confidence") in {"smoke_tested", "verified"}
        ]
        if not candidates:
            raise RouteError(f"no verified {complexity!r} routing candidate for executor {executor!r}")

    evidence = _require_quota_evidence(data, quota_evidence, executor)
    available = evidence["available"]

    # A report that names the model it is bound to is a binding, not a hint.
    declared_id: str | None = None
    declared_model = evidence.get("selected_model")
    declared_scope = evidence.get("quota_scope_key")
    if declared_model:
        declared_entry, declared_provider = _resolve_model(data, declared_model)
        if declared_entry is None:
            raise RouteError(
                f"quota_binding_conflict: precheck selected_model {declared_model!r} is not in the catalog, "
                "so the binding cannot be checked against an observation"
            )
        declared_id = str(declared_entry.get("model_id"))
        if _provider_executor(data, declared_provider) != executor:
            raise RouteError(
                f"quota_binding_conflict: precheck selected_model {declared_model!r} does not belong to executor {executor!r}"
            )
        bound_all = [
            obs for obs in evidence["observations"]
            if obs["model_id"] == declared_id and obs["scope_key"] == declared_scope
        ]
        bound_available = [
            obs for obs in bound_all if obs["state"] == "available" and obs["bucket_known"]
        ]
        if not bound_available:
            if bound_all:
                details = ", ".join(
                    f"state={obs['state']} bucket_known={obs['bucket_known']}" for obs in bound_all
                )
                raise RouteError(
                    f"quota_unavailable: report binds selected_model={declared_model!r} to quota_scope_key={declared_scope!r}, "
                    f"but that observation cannot authorize a selection ({details}); exhausted, unknown-state or "
                    "unknown-bucket observations never authorize a selection"
                )
            observed = sorted({f"{obs['model_id'] or obs['model']}@{obs['scope_key']}" for obs in available})
            raise RouteError(
                f"quota_binding_conflict: report declares selected_model={declared_model!r} quota_scope_key={declared_scope!r}, "
                f"but no available observation binds that model to that scope (available: {observed or 'none'}); "
                "a conflicting binding is never normalized into a valid one"
            )
        if explicit and str(model.get("model_id")) != declared_id:
            raise RouteError(
                f"quota_binding_conflict: requested model {requested_model!r} contradicts the precheck binding "
                f"selected_model={declared_model!r}; routing does not override a filled-in binding"
            )

    excluded_models: list[str] = []
    if explicit:
        authorizing = _authorizing_observations(available, str(model.get("model_id")))
        if not authorizing:
            observed = sorted({f"{obs['model_id'] or obs['model']}@{obs['scope_key']}" for obs in available})
            raise RouteError(
                f"quota_unavailable: {model.get('model_id')!r} has no observation with state=available and a model/bucket "
                f"binding that matches it in this precheck (available: {observed or 'none'}); exhausted, unknown or "
                "other-model buckets are never substituted for the selected model" + _unknown_bucket_note(evidence)
            )
        effort, effort_status = _choose_effort(model, complexity, requested_reasoning)
        selection_status = effort_status if effort_status == "explicit_unverified" else "explicit"
        if declared_id:
            reason = (
                f"precheck report is bound to selected_model={declared_model!r} quota_scope_key={declared_scope!r}; "
                "the binding is confirmed by its own available observation"
            )
        else:
            reason = "explicit model/reasoning selection takes precedence"
        reason += "; authorized by the matching live quota precheck observation"
    else:
        verified_ids = sorted(str(candidate.get("model_id")) for candidate in candidates)
        excluded_models = sorted(
            str(candidate.get("model_id")) for candidate in candidates
            if not _authorizing_observations(available, str(candidate.get("model_id")))
        )
        candidates = [
            candidate for candidate in candidates
            if _authorizing_observations(available, str(candidate.get("model_id")))
        ]
        if declared_id:
            bound_candidates = [candidate for candidate in candidates if str(candidate.get("model_id")) == declared_id]
            if not bound_candidates:
                raise RouteError(
                    f"explicit_required: report is bound to selected_model={declared_model!r}, which is not a verified "
                    f"{complexity!r} auto-routing candidate; confirm it explicitly with --model {declared_model!r} "
                    "(reported explicit_unverified) or re-run the precheck without the binding"
                )
            candidates = bound_candidates
        if not candidates:
            raise RouteError(
                f"quota_unavailable: no verified {complexity!r} routing candidate for executor {executor!r} has a matching "
                f"available observation in this precheck (verified candidates: {verified_ids}); refusing to select a bucket "
                "that is exhausted, unknown or bound to another model. An available bucket without verified routing evidence "
                "must be requested explicitly with --model and is then reported as explicit_unverified." + _unknown_bucket_note(evidence)
            )
        candidates.sort(key=lambda item: item.get("model_id", ""))
        model = candidates[0]
        effort, selection_status = _choose_effort(model, complexity, None)
        reason = f"catalog routing_profile={complexity}; discovery and reasoning evidence are present"
        reason += "; restricted to the observation-bound bucket observed 'available' in the live quota precheck"
        if declared_id:
            reason += f"; restricted further by the report binding selected_model={declared_model!r}"

    authorizing = _authorizing_observations(available, str(model.get("model_id")))
    quota_scope_keys = _scope_keys_for(executor, model, authorizing)
    # The receipt must show the observation that actually authorized the
    # selected model+scope, not merely the first available row for that model.
    # A declared binding names the scope; otherwise the first observed scope in
    # sorted key order is the selected one.
    selected_scope = (
        declared_scope if declared_scope in quota_scope_keys
        else (quota_scope_keys[0] if quota_scope_keys else None)
    )
    selected_observation = next(
        (obs for obs in authorizing if obs["scope_key"] == selected_scope), None
    )
    independence = check_independence(data, role, model.get("model_id"), executor_model, independence_policy)
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
        "quota_scope_keys": quota_scope_keys,
        "quota_filter": {
            "applied": True,
            "report": evidence.get("source"),
            "auth_status": evidence.get("auth_status"),
            "available_inputs": sorted({obs["model"] for obs in available}),
            "available_buckets": sorted({obs["bucket"] for obs in available}),
            "authorized_models": sorted({obs["model_id"] for obs in available if obs["model_id"]}),
            "selected_observation": (
                {key: selected_observation.get(key) for key in (
                    "bucket", "model", "model_id", "state", "source", "probed_at", "reset_at", "scope_key",
                )}
                if selected_observation else None
            ),
            "excluded_models": excluded_models,
            "note": (
                "selection is authorized by the live quota precheck observation bound to the selected model's own bucket; "
                "exhausted, unknown-state or other-model buckets are not selectable, and an observation whose bucket is "
                "'unknown' names no concrete bucket and authorizes nothing"
            ),
        },
    }


def run_selftest() -> int:
    data = catalog_lib.load_catalog(Path(__file__).resolve().parents[1] / "references" / "model-catalog.yml")
    checks: list[tuple[str, bool]] = []

    def observation(model: str, bucket: str, state: str = "available", source: str = "selftest fixture probe", probed_at: str = "2026-09-14 10:00:00") -> dict[str, Any]:
        return {"bucket": bucket, "model": model, "state": state, "source": source, "probed_at": probed_at}

    def evidence(executor: str, observations: list[dict[str, Any]], *, auth_status: str = "ok", selected_model: str | None = None, quota_scope_key: str | None = None, recommendation: str | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "executor": executor,
            "auth_status": auth_status,
            "quota_observations": [dict(item) for item in observations],
        }
        if selected_model is not None:
            payload["selected_model"] = selected_model
        if quota_scope_key is not None:
            payload["quota_scope_key"] = quota_scope_key
        if recommendation is not None:
            payload["recommendation"] = recommendation
        if extra:
            payload.update(extra)
        return normalize_quota_report(payload, data, source_label="selftest fixture")

    def normalize_error(payload: Any) -> str | None:
        try:
            normalize_quota_report(payload, data, source_label="selftest fixture")
        except RouteError as exc:
            return str(exc)
        return None

    def route(*args: Any, **kwargs: Any) -> tuple[dict[str, Any] | None, str | None]:
        """Route with the mandatory quota evidence, returning (receipt, error)."""
        try:
            return route_model(data, *args, **kwargs), None
        except RouteError as exc:
            return None, str(exc)
        except TypeError as exc:
            return None, f"{type(exc).__name__}: {exc}"

    codex_luna = evidence("codex", [observation("gpt-5.6-luna", "codex")])
    codex_terra = evidence("codex", [observation("gpt-5.6-terra", "codex")])
    codex_sol = evidence("codex", [observation("gpt-5.6-sol", "codex")])
    codex_spark = evidence("codex", [observation("gpt-5.3-codex-spark", "codex_bengalfox")])
    codex_terra_and_spark = evidence("codex", [
        observation("gpt-5.6-terra", "codex"),
        observation("gpt-5.3-codex-spark", "codex_bengalfox"),
    ])
    pi_flash = evidence("pi", [observation("deepseek-flash", "deepseek")])
    pi_vision = evidence("pi", [observation("deepseek-v4-flash-vision-exp", "deepseek")])
    claude_sonnet = evidence("claude", [observation("claude-sonnet-5", "claude")])
    claude_opus_4_8 = evidence("claude", [observation("claude-opus-4-8", "claude")])
    claude_opus_5 = evidence("claude", [observation("claude-opus-5", "claude")])

    # --- selection with valid precheck evidence ---
    luna_easy, luna_easy_error = route("codex", "easy", quota_evidence=codex_luna)
    checks.append((
        "codex easy with luna's bucket observed available -> luna low",
        luna_easy is not None and luna_easy.get("selected_model") == "gpt-5.6-luna"
        and luna_easy.get("selected_reasoning_effort") == "low"
        and luna_easy.get("selection_status") == "verified_auto",
    ))
    checks.append((
        "luna receipt carries the observation-bound quota scope",
        luna_easy is not None and luna_easy.get("quota_scope_keys") == ["codex"]
        and (luna_easy.get("quota_filter") or {}).get("selected_observation", {}).get("bucket") == "codex"
        and (luna_easy.get("quota_filter") or {}).get("auth_status") == "ok",
    ))
    medium_with_terra, medium_with_terra_error = route("codex", "medium", quota_evidence=codex_terra)
    checks.append((
        "codex medium with terra's bucket observed available -> terra medium",
        medium_with_terra is not None
        and medium_with_terra.get("selected_model") == "gpt-5.6-terra"
        and medium_with_terra.get("selected_reasoning_effort") == "medium"
        and medium_with_terra.get("quota_scope_keys") == ["codex"]
        and (medium_with_terra.get("quota_filter") or {}).get("applied") is True,
    ))
    hard_sol, hard_sol_error = route("codex", "hard", quota_evidence=codex_sol)
    checks.append((
        "codex hard with sol's bucket observed available -> sol high",
        hard_sol is not None and hard_sol.get("selected_model") == "gpt-5.6-sol"
        and hard_sol.get("selected_reasoning_effort") == "high",
    ))
    medium_spark_only, medium_spark_error = route("codex", "medium", quota_evidence=codex_spark)
    checks.append((
        "codex medium with only spark's bucket available never selects terra",
        medium_spark_only is None and "quota_unavailable" in (medium_spark_error or ""),
    ))
    medium_exhausted = evidence("codex", [observation("gpt-5.6-terra", "codex", state="exhausted")])
    medium_none, medium_none_error = route("codex", "medium", quota_evidence=medium_exhausted)
    checks.append((
        "codex medium with terra exhausted blocks instead of force-picking",
        medium_none is None and "quota_unavailable" in (medium_none_error or ""),
    ))
    explicit_unavailable, explicit_unavailable_error = route(
        "codex", "hard", "gpt-5.6-sol", quota_evidence=codex_terra
    )
    checks.append((
        "explicit model on an unavailable bucket is refused, not silently swapped",
        explicit_unavailable is None and "quota_unavailable" in (explicit_unavailable_error or ""),
    ))
    spark_explicit, spark_explicit_error = route(
        "codex", "medium", "gpt-5.3-codex-spark", quota_evidence=codex_spark
    )
    checks.append((
        "spark is selectable when its own bucket is observed available (explicit, unverified reasoning)",
        spark_explicit is not None
        and spark_explicit.get("selection_status") == "explicit_unverified"
        and spark_explicit.get("quota_scope_keys") == ["codex_bengalfox"],
    ))
    pi_easy, pi_easy_error = route("pi", "easy", quota_evidence=pi_flash)
    checks.append((
        "pi easy with deepseek-flash observed available -> deepseek-flash low",
        pi_easy is not None and pi_easy.get("selected_model") == "deepseek-flash"
        and pi_easy.get("selected_reasoning_effort") == "low"
        and pi_easy.get("selection_status") == "verified_auto",
    ))
    checks.append((
        "pi easy auto-route never selects a retired deepseek id",
        pi_easy is not None and pi_easy.get("selected_model") not in {"deepseek-v4-flash", "deepseek-v4-flash-vision-exp"},
    ))
    pi_flash_no_reasoning, _ = route("pi", "easy", "deepseek-flash", quota_evidence=pi_flash)
    checks.append((
        "pi deepseek-flash explicit model without reasoning selects verified low",
        pi_flash_no_reasoning is not None
        and pi_flash_no_reasoning.get("selected_model") == "deepseek-flash"
        and pi_flash_no_reasoning.get("selected_reasoning_effort") == "low"
        and pi_flash_no_reasoning.get("selection_status") == "explicit",
    ))
    _, pi_flash_medium_error = route("pi", "easy", "deepseek-flash", "medium", quota_evidence=pi_flash)
    checks.append(("pi deepseek-flash medium (absent from provider level map) blocks", pi_flash_medium_error is not None))
    pi_deprecated_evidence = evidence("pi", [observation("deepseek-v4-flash", "deepseek")])
    pi_explicit, _ = route("pi", "easy", "deepseek/deepseek-v4-flash", "low", quota_evidence=pi_deprecated_evidence)
    checks.append((
        "pi deprecated provider-qualified explicit model still resolves",
        pi_explicit is not None and pi_explicit.get("selected_model") == "deepseek-v4-flash"
        and pi_explicit.get("selection_status") == "explicit",
    ))
    pi_vision_low, _ = route("pi", "easy", "deepseek-v4-flash-vision-exp", "low", quota_evidence=pi_vision)
    checks.append((
        "pi vision-exp low is explicit with Pi JSONL smoke evidence",
        pi_vision_low is not None and pi_vision_low.get("selected_model") == "deepseek-v4-flash-vision-exp"
        and pi_vision_low.get("selected_reasoning_effort") == "low"
        and pi_vision_low.get("selection_status") == "explicit",
    ))
    for unverified_level in ("off", "high", "max"):
        _, level_error = route("pi", "easy", "deepseek-v4-flash-vision-exp", unverified_level, quota_evidence=pi_vision)
        checks.append((f"pi vision-exp {unverified_level} blocks as unverified", level_error is not None))
    pi_vision_no_reasoning, _ = route("pi", "easy", "deepseek-v4-flash-vision-exp", quota_evidence=pi_vision)
    checks.append((
        "pi vision-exp explicit model without reasoning selects only verified low",
        pi_vision_no_reasoning is not None
        and pi_vision_no_reasoning.get("selected_reasoning_effort") == "low"
        and pi_vision_no_reasoning.get("selection_status") == "explicit",
    ))
    pi_easy_both = evidence("pi", [
        observation("deepseek-flash", "deepseek"),
        observation("deepseek-v4-flash-vision-exp", "deepseek"),
    ])
    pi_auto, _ = route("pi", "easy", quota_evidence=pi_easy_both)
    checks.append((
        "pi easy auto-route never selects the UI-only-observed vision model",
        pi_auto is not None and pi_auto.get("selected_model") != "deepseek-v4-flash-vision-exp",
    ))
    codex_unverified_evidence = evidence("codex", [observation("gpt-5.5", "codex")])
    codex_unverified, _ = route("codex", "easy", "gpt-5.5", "high", quota_evidence=codex_unverified_evidence)
    checks.append((
        "explicit reasoning listed with unverified confidence stays explicit_unverified",
        codex_unverified is not None and codex_unverified.get("selection_status") == "explicit_unverified"
        and codex_unverified.get("selected_reasoning_effort") == "high",
    ))
    explicit, _ = route("codex", "easy", "gpt-5.6-sol", "xhigh", quota_evidence=codex_sol)
    checks.append((
        "explicit model/effort wins",
        explicit is not None and explicit.get("selected_model") == "gpt-5.6-sol"
        and explicit.get("selected_reasoning_effort") == "xhigh"
        and explicit.get("selection_status") == "explicit",
    ))
    _, pi_medium_error = route("pi", "medium", quota_evidence=pi_flash)
    checks.append(("pi medium blocks without task-quality evidence", pi_medium_error is not None))
    _, claude_hard_error = route("claude", "hard", quota_evidence=claude_sonnet)
    checks.append(("no verified claude hard candidate blocks", claude_hard_error is not None))
    _, agy_error = route("agy", "easy")
    checks.append(("agy blocks without verified catalog candidate", agy_error is not None))
    _, agy_gemini_error = route("agy", "easy", "gemini-3.5-flash")
    checks.append(("agy rejects Gemini API catalog ids even when explicitly requested", agy_gemini_error is not None))
    _, unknown_model_error = route("codex", "medium", "gpt-9-unknown", quota_evidence=codex_terra)
    checks.append(("explicit model outside the catalog blocks", unknown_model_error is not None))
    _, bad_complexity_error = route("codex", "extreme", quota_evidence=codex_terra)
    checks.append(("invalid complexity blocks", bad_complexity_error is not None))

    # --- mandatory quota evidence: the two reported blockers ---
    _, no_quota_auto_error = route("codex", "medium")
    checks.append((
        "auto-routing without any quota evidence blocks",
        no_quota_auto_error is not None and "quota_evidence_missing" in no_quota_auto_error,
    ))
    _, no_quota_explicit_error = route("codex", "medium", "gpt-5.6-terra")
    checks.append((
        "explicit selection without any quota evidence blocks",
        no_quota_explicit_error is not None and "quota_evidence_missing" in no_quota_explicit_error,
    ))
    raw_evidence_error = None
    try:
        route_model(data, "codex", "medium", quota_evidence={
            "executor": "codex", "auth_status": "ok",
            "quota_observations": [observation("gpt-5.6-terra", "codex")],
        })
    except RouteError as exc:
        raw_evidence_error = str(exc)
    checks.append((
        "an unvalidated raw evidence dict cannot stand in for the report",
        raw_evidence_error is not None and "quota_evidence_missing" in raw_evidence_error,
    ))

    def forged_evidence(**overrides: Any) -> dict[str, Any]:
        """Hand-built 'validated-looking' evidence: copied kind, never checked by normalize.

        `available[]` claims a ready terra bucket exactly as a bypass would; the
        fixed route re-derives availability from `observations` instead of
        trusting it, so every forged variant below must still block.
        """
        base: dict[str, Any] = {
            "kind": EVIDENCE_KIND,
            "source": "forged dict",
            "executor": "codex",
            "auth_status": "ok",
            "selected_model": None,
            "quota_scope_key": None,
            "recommendation": "proceed",
            "observations": [observation("gpt-5.6-terra", "codex")],
            "available": [{
                "bucket": "codex", "model": "gpt-5.6-terra", "model_id": "gpt-5.6-terra",
                "state": "available", "source": "forged dict", "probed_at": "2026-09-14 10:00:00",
                "scope_key": "codex",
            }],
        }
        base.update(overrides)
        return base

    _, forged_expired_error = route("codex", "medium", quota_evidence=forged_evidence(auth_status="expired"))
    checks.append((
        "forged kind object: expired auth cannot ride on a copied kind string",
        forged_expired_error is not None and "auth_not_ok" in forged_expired_error,
    ))
    _, forged_binding_error = route(
        "codex", "medium",
        quota_evidence=forged_evidence(observations=[observation("gpt-5.6-terra", "codex_bengalfox")]),
    )
    checks.append((
        "forged kind object: an observation re-validated as a bucket/model conflict still blocks",
        forged_binding_error is not None and "quota_binding_conflict" in forged_binding_error,
    ))
    _, forged_provenance_error = route(
        "codex", "medium",
        quota_evidence=forged_evidence(observations=[observation("gpt-5.6-terra", "codex", source="", probed_at="")]),
    )
    checks.append((
        "forged kind object: empty source/probed_at blocks instead of authorizing",
        forged_provenance_error is not None and "quota_evidence_incomplete" in forged_provenance_error,
    ))
    _, forged_time_error = route(
        "codex", "medium",
        quota_evidence=forged_evidence(observations=[observation("gpt-5.6-terra", "codex", probed_at="not-a-time")]),
    )
    checks.append((
        "forged kind object: an unparseable probed_at blocks instead of authorizing",
        forged_time_error is not None and "quota_evidence_malformed" in forged_time_error,
    ))
    forged_available_claim = forged_evidence(
        observations=[observation("gpt-5.6-terra", "codex", state="exhausted")],
        available=[{
            "bucket": "codex", "model": "gpt-5.6-terra", "model_id": "gpt-5.6-terra",
            "state": "available", "source": "forged dict", "probed_at": "2026-09-14 10:00:00",
            "scope_key": "codex",
        }],
    )
    _, forged_available_error = route("codex", "medium", quota_evidence=forged_available_claim)
    checks.append((
        "forged kind object: a hand-written available[] list is re-derived, not trusted",
        forged_available_error is not None and "quota_unavailable" in forged_available_error,
    ))
    _, forged_unknown_model_error = route(
        "codex", "medium",
        quota_evidence=forged_evidence(observations=[
            observation("gpt-5.6-terra", "codex"),
            observation("gpt-9-unknown", "codex"),
        ]),
    )
    checks.append((
        "forged kind object: an unknown catalog model inside otherwise valid rows still blocks",
        forged_unknown_model_error is not None and "quota_binding_conflict" in forged_unknown_model_error,
    ))
    misbound_payload = {
        "executor": "codex",
        "auth_status": "ok",
        "selected_model": "gpt-5.3-codex-spark",
        "quota_scope_key": "codex_bengalfox",
        "recommendation": "proceed",
        "quota_observations": [observation("gpt-5.6-terra", "codex_bengalfox")],
    }
    misbound_error = normalize_error(misbound_payload)
    checks.append((
        "reported blocker: selected_model=spark + quota_scope_key=codex_bengalfox + observation.model=terra blocks",
        misbound_error is not None and "quota_binding_conflict" in misbound_error,
    ))
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        report_path = Path(tmp) / "misbound.json"
        report_path.write_text(json.dumps(misbound_payload), encoding="utf-8")
        try:
            load_quota_observations(report_path, data)
        except RouteError as exc:
            load_misbound_error = str(exc)
        else:
            load_misbound_error = None
    checks.append((
        "load_quota_observations rejects the mis-bound report file, so it never reaches a receipt",
        load_misbound_error is not None and "quota_binding_conflict" in load_misbound_error,
    ))
    unbound_misbound_error = normalize_error({**misbound_payload, "selected_model": None, "quota_scope_key": None})
    checks.append((
        "bucket/model conflict blocks even without a report-level binding",
        unbound_misbound_error is not None and "quota_binding_conflict" in unbound_misbound_error,
    ))
    wrong_bucket_error = normalize_error({
        "executor": "codex", "auth_status": "ok",
        "quota_observations": [observation("gpt-5.3-codex-spark", "codex")],
    })
    checks.append((
        "observation binding spark to the wrong bucket blocks",
        wrong_bucket_error is not None and "quota_binding_conflict" in wrong_bucket_error,
    ))
    scope_mismatch_evidence = evidence(
        "codex", [observation("gpt-5.3-codex-spark", "codex_bengalfox")],
        selected_model="gpt-5.3-codex-spark", quota_scope_key="codex",
    )
    _, scope_mismatch_error = route("codex", "medium", quota_evidence=scope_mismatch_evidence)
    checks.append((
        "quota_scope_key that disagrees with the observation bucket blocks",
        scope_mismatch_error is not None and "quota_binding_conflict" in scope_mismatch_error,
    ))
    half_bound_error = normalize_error({
        "executor": "codex", "auth_status": "ok", "selected_model": "gpt-5.6-terra",
        "quota_observations": [observation("gpt-5.6-terra", "codex")],
    })
    checks.append((
        "half-bound report (selected_model without quota_scope_key) blocks",
        half_bound_error is not None and "quota_binding_conflict" in half_bound_error,
    ))
    alias_conflict_evidence = evidence(
        "codex", [observation("sol", "codex")],
        selected_model="terra", quota_scope_key="codex",
    )
    _, alias_conflict_error = route("codex", "medium", quota_evidence=alias_conflict_evidence)
    checks.append((
        "alias normalization cannot wash a conflicting model binding",
        alias_conflict_error is not None and "quota_binding_conflict" in alias_conflict_error,
    ))
    whitespace_conflict_error = normalize_error({
        "executor": "codex", "auth_status": "ok",
        "quota_observations": [observation("  gpt-5.6-terra  ", "  codex_bengalfox  ")],
    })
    checks.append((
        "whitespace normalization cannot wash a conflicting bucket binding",
        whitespace_conflict_error is not None and "quota_binding_conflict" in whitespace_conflict_error,
    ))
    _, executor_mismatch_error = route("codex", "medium", quota_evidence=pi_flash)
    checks.append((
        "precheck report for another executor blocks",
        executor_mismatch_error is not None and "quota_binding_conflict" in executor_mismatch_error,
    ))
    auth_expired_error = normalize_error({
        "executor": "codex", "auth_status": "expired",
        "quota_observations": [observation("gpt-5.6-terra", "codex")],
    })
    checks.append((
        "auth_status != ok blocks even with an available observation",
        auth_expired_error is not None and "auth_not_ok" in auth_expired_error,
    ))
    no_auth_error = normalize_error({
        "executor": "codex", "quota_observations": [observation("gpt-5.6-terra", "codex")],
    })
    checks.append((
        "missing auth_status blocks",
        no_auth_error is not None and "quota_evidence_malformed" in no_auth_error,
    ))
    no_source_error = normalize_error({
        "executor": "codex", "auth_status": "ok",
        "quota_observations": [observation("gpt-5.6-terra", "codex", source="")],
    })
    checks.append((
        "available observation without source blocks",
        no_source_error is not None and "quota_evidence_incomplete" in no_source_error,
    ))
    no_probed_at_error = normalize_error({
        "executor": "codex", "auth_status": "ok",
        "quota_observations": [observation("gpt-5.6-terra", "codex", probed_at="   ")],
    })
    checks.append((
        "available observation without probed_at blocks",
        no_probed_at_error is not None and "quota_evidence_incomplete" in no_probed_at_error,
    ))
    unparseable_probed_at_error = normalize_error({
        "executor": "codex", "auth_status": "ok",
        "quota_observations": [observation("gpt-5.6-terra", "codex", probed_at="not-a-time")],
    })
    checks.append((
        "probed_at that is not a parseable timestamp blocks",
        unparseable_probed_at_error is not None and "quota_evidence_malformed" in unparseable_probed_at_error,
    ))
    iso_time_evidence = evidence("codex", [
        observation("gpt-5.6-terra", "codex", probed_at="2026-09-14T10:00:00+08:00"),
    ])
    iso_time_route, _ = route("codex", "medium", quota_evidence=iso_time_evidence)
    checks.append((
        "an ISO-8601 probe timestamp (T separator, offset and Z) is still accepted",
        iso_time_route is not None and iso_time_route.get("selected_model") == "gpt-5.6-terra"
        and (iso_time_route.get("quota_filter") or {}).get("selected_observation", {}).get("probed_at")
        == "2026-09-14T10:00:00+08:00",
    ))
    z_time_evidence = evidence("codex", [
        observation("gpt-5.6-terra", "codex", probed_at="2026-09-14T02:00:00Z"),
    ])
    z_time_route, _ = route("codex", "medium", quota_evidence=z_time_evidence)
    checks.append(("a trailing-Z UTC probe timestamp is accepted", z_time_route is not None))
    exhausted_no_source_error = normalize_error({
        "executor": "codex", "auth_status": "ok",
        "quota_observations": [observation("gpt-5.6-terra", "codex", state="exhausted", source="")],
    })
    checks.append((
        "every observation needs probe provenance, not just available ones",
        exhausted_no_source_error is not None and "quota_evidence_incomplete" in exhausted_no_source_error,
    ))
    bad_state_error = normalize_error({
        "executor": "codex", "auth_status": "ok",
        "quota_observations": [observation("gpt-5.6-terra", "codex", state="plenty")],
    })
    checks.append((
        "unknown observation state blocks",
        bad_state_error is not None and "quota_evidence_malformed" in bad_state_error,
    ))
    empty_observations_error = normalize_error({"executor": "codex", "auth_status": "ok", "quota_observations": []})
    checks.append((
        "empty quota_observations blocks",
        empty_observations_error is not None and "quota_evidence_incomplete" in empty_observations_error,
    ))
    bare_list_error = normalize_error([observation("gpt-5.6-terra", "codex")])
    checks.append((
        "bare-list report cannot prove auth_status and blocks",
        bare_list_error is not None and "quota_evidence_malformed" in bare_list_error,
    ))
    hold_error = normalize_error({
        "executor": "codex", "auth_status": "ok", "recommendation": "hold",
        "quota_observations": [observation("gpt-5.6-terra", "codex")],
    })
    checks.append((
        "recommendation=hold blocks",
        hold_error is not None and "recommendation_blocked" in hold_error,
    ))
    approval_evidence = evidence(
        "codex", [observation("gpt-5.6-terra", "codex", state="exhausted")],
        extra={"customer_approval": "owner approved the cost", "recommendation": "proceed"},
    )
    _, approval_auto_error = route("codex", "medium", quota_evidence=approval_evidence)
    _, approval_explicit_error = route("codex", "medium", "gpt-5.6-terra", quota_evidence=approval_evidence)
    checks.append((
        "customer approval cannot rewrite an exhausted bucket into an available one",
        approval_auto_error is not None and "quota_unavailable" in approval_auto_error
        and approval_explicit_error is not None and "quota_unavailable" in approval_explicit_error,
    ))
    approval_auth_error = normalize_error({
        "executor": "codex", "auth_status": "expired",
        "customer_approval": "owner approved the cost",
        "quota_observations": [observation("gpt-5.6-terra", "codex")],
    })
    checks.append((
        "customer approval cannot bypass auth_status != ok",
        approval_auth_error is not None and "auth_not_ok" in approval_auth_error,
    ))
    unknown_model_error = normalize_error({
        "executor": "codex", "auth_status": "ok",
        "quota_observations": [observation("gpt-9-unknown", "codex")],
    })
    checks.append((
        "an observation whose model is not in the catalog is rejected, not kept as inert evidence",
        unknown_model_error is not None and "quota_binding_conflict" in unknown_model_error,
    ))
    mixed_unknown_model_error = normalize_error({
        "executor": "codex", "auth_status": "ok",
        "quota_observations": [
            observation("gpt-5.6-terra", "codex"),
            observation("gpt-9-unknown", "codex"),
        ],
    })
    checks.append((
        "an unknown catalog model mixed into an otherwise valid report is rejected per row",
        mixed_unknown_model_error is not None and "quota_binding_conflict" in mixed_unknown_model_error
        and "gpt-9-unknown" in mixed_unknown_model_error,
    ))
    bound_terra = evidence(
        "codex", [observation("gpt-5.6-terra", "codex")],
        selected_model="gpt-5.6-terra", quota_scope_key="codex", recommendation="proceed",
    )
    bound_terra_route, _ = route("codex", "medium", quota_evidence=bound_terra)
    checks.append((
        "a consistent report binding is confirmed, not overridden",
        bound_terra_route is not None and bound_terra_route.get("selected_model") == "gpt-5.6-terra"
        and bound_terra_route.get("quota_scope_keys") == ["codex"],
    ))
    bound_spark = evidence(
        "codex", [observation("gpt-5.3-codex-spark", "codex_bengalfox"), observation("gpt-5.6-terra", "codex")],
        selected_model="gpt-5.3-codex-spark", quota_scope_key="codex_bengalfox", recommendation="proceed",
    )
    _, bound_spark_auto_error = route("codex", "medium", quota_evidence=bound_spark)
    bound_spark_explicit, _ = route("codex", "medium", "gpt-5.3-codex-spark", quota_evidence=bound_spark)
    checks.append((
        "an auto-route never overrides the report binding with a different available model",
        bound_spark_auto_error is not None and "explicit_required" in bound_spark_auto_error
        and bound_spark_explicit is not None and bound_spark_explicit.get("selected_model") == "gpt-5.3-codex-spark",
    ))
    _, bound_conflict_error = route("codex", "medium", "gpt-5.6-terra", quota_evidence=bound_spark)
    checks.append((
        "an explicit model that contradicts the report binding blocks",
        bound_conflict_error is not None and "quota_binding_conflict" in bound_conflict_error,
    ))
    _, bound_exhausted_error = route("codex", "medium", quota_evidence=evidence(
        "codex", [observation("gpt-5.6-terra", "codex", state="exhausted")],
        selected_model="gpt-5.6-terra", quota_scope_key="codex", recommendation="proceed",
    ))
    checks.append((
        "a binding whose own observation is exhausted blocks",
        bound_exhausted_error is not None and "quota_unavailable" in bound_exhausted_error,
    ))
    mixed_report = evidence("codex", [
        observation("gpt-5.6-sol", "codex", state="exhausted"),
        observation("gpt-5.6-terra", "codex"),
    ])
    mixed_selection, _ = route("codex", "medium", quota_evidence=mixed_report)
    checks.append((
        "a mixed report selects the available model and not the exhausted one",
        mixed_selection is not None and mixed_selection.get("selected_model") == "gpt-5.6-terra",
    ))

    # --- rework vectors: unknown bucket, scope provenance, receipt selection ---
    spark_unknown_only = evidence("codex", [observation("gpt-5.3-codex-spark", "unknown")])
    _, spark_unknown_auto_error = route("codex", "medium", quota_evidence=spark_unknown_only)
    _, spark_unknown_explicit_error = route(
        "codex", "medium", "gpt-5.3-codex-spark", quota_evidence=spark_unknown_only
    )
    checks.append((
        "an unknown bucket for a known-bucketed model (spark) authorizes neither auto nor explicit routing",
        spark_unknown_auto_error is not None and "quota_unavailable" in spark_unknown_auto_error
        and spark_unknown_explicit_error is not None and "quota_unavailable" in spark_unknown_explicit_error,
    ))
    spark_unknown_mixed = evidence("codex", [
        observation("gpt-5.3-codex-spark", "unknown"),
        observation("gpt-5.6-terra", "codex"),
    ])
    spark_unknown_mixed_route, _ = route("codex", "medium", quota_evidence=spark_unknown_mixed)
    spark_unknown_selected = (spark_unknown_mixed_route or {}).get("quota_filter", {}).get("selected_observation") or {}
    checks.append((
        "an unknown-bucket row is excluded from available inputs and receipt scopes",
        spark_unknown_mixed_route is not None
        and spark_unknown_mixed_route.get("selected_model") == "gpt-5.6-terra"
        and spark_unknown_mixed_route.get("quota_scope_keys") == ["codex"]
        and spark_unknown_selected.get("bucket") == "codex"
        and "gpt-5.3-codex-spark" not in (spark_unknown_mixed_route.get("quota_filter") or {}).get("available_inputs", []),
    ))
    bound_spark_unknown_first = evidence(
        "codex",
        [
            observation("gpt-5.3-codex-spark", "unknown"),
            observation("gpt-5.3-codex-spark", "codex_bengalfox"),
        ],
        selected_model="gpt-5.3-codex-spark", quota_scope_key="codex_bengalfox", recommendation="proceed",
    )
    bound_spark_unknown_first_route, _ = route(
        "codex", "medium", "gpt-5.3-codex-spark", quota_evidence=bound_spark_unknown_first
    )
    bound_spark_selected = (
        (bound_spark_unknown_first_route or {}).get("quota_filter", {}).get("selected_observation") or {}
    )
    checks.append((
        "a bound report ignores an unknown-bucket decoy and shows the concrete-bucket observation",
        bound_spark_unknown_first_route is not None
        and bound_spark_unknown_first_route.get("quota_scope_keys") == ["codex_bengalfox"]
        and bound_spark_selected.get("bucket") == "codex_bengalfox"
        and bound_spark_selected.get("scope_key") == "codex_bengalfox",
    ))
    order_bound_report = evidence(
        "codex",
        [
            observation("gpt-5.6-terra", "codex_backup"),
            observation("gpt-5.6-terra", "codex"),
        ],
        selected_model="gpt-5.6-terra", quota_scope_key="codex", recommendation="proceed",
    )
    order_route, _ = route("codex", "medium", quota_evidence=order_bound_report)
    order_selected = (order_route or {}).get("quota_filter", {}).get("selected_observation") or {}
    checks.append((
        "a bound report shows the first row matching its declared model+scope, not the first same-model row",
        order_route is not None and order_route.get("selected_model") == "gpt-5.6-terra"
        and order_selected.get("model_id") == "gpt-5.6-terra"
        and order_selected.get("bucket") == "codex" and order_selected.get("scope_key") == "codex",
    ))
    import copy
    injected_catalog = copy.deepcopy(data)
    for injected_provider in (injected_catalog.get("providers") or {}).values():
        injected_models = injected_provider.get("models") or [] if isinstance(injected_provider, dict) else []
        for injected_model in injected_models:
            if injected_model.get("model_id") == "gpt-5.6-terra":
                injected_model["quota_scope_keys"] = ["codex", "codex_never_observed"]
    injected_evidence = normalize_quota_report({
        "executor": "codex", "auth_status": "ok",
        "quota_observations": [observation("gpt-5.6-terra", "codex")],
    }, injected_catalog, source_label="selftest fixture")
    try:
        injected_route = route_model(injected_catalog, "codex", "medium", quota_evidence=injected_evidence)
    except RouteError:
        injected_route = None
    checks.append((
        "catalog quota_scope_keys are declarations, never injected as observed receipt scopes",
        injected_route is not None and injected_route.get("quota_scope_keys") == ["codex"],
    ))

    # --- Independence Gate (dispatch_role) ---
    distinct, distinct_error = route("codex", "medium", "gpt-5.6-terra", role="reviewer", executor_model="gpt-5.6-luna", quota_evidence=codex_terra, independence_policy="different_model")
    checks.append(("project different_model policy accepts Luna to Terra", distinct_error is None and distinct["independence_gate"]["policy"] == "different_model"))
    _, same_policy_error = route("codex", "medium", "gpt-5.6-terra", role="reviewer", executor_model="gpt-5.6-terra", quota_evidence=codex_terra, independence_policy="different_model")
    checks.append(("different_model policy still rejects identical models", same_policy_error is not None))
    _, default_family_error = route("codex", "medium", "gpt-5.6-terra", role="reviewer", executor_model="gpt-5.6-luna", quota_evidence=codex_terra)
    checks.append(("default policy preserves same-family rejection", default_family_error is not None))
    _, missing_quota_policy_error = route("codex", "medium", "gpt-5.6-terra", role="reviewer", executor_model="gpt-5.6-luna", independence_policy="different_model")
    checks.append(("different_model policy never bypasses quota evidence", missing_quota_policy_error is not None))
    _, same_model_error = route("claude", "medium", "claude-sonnet-5", role="reviewer", executor_model="claude-sonnet-5", quota_evidence=claude_sonnet)
    checks.append(("reviewer with the same model as the executor blocks", same_model_error is not None))
    _, same_family_error = route("claude", "medium", "claude-opus-4-8", role="reviewer", executor_model="claude-opus-4-7", quota_evidence=claude_opus_4_8)
    checks.append(("reviewer in the same model_family as the executor blocks", same_family_error is not None))
    _, no_executor_model_error = route("claude", "medium", "claude-sonnet-5", role="reviewer", quota_evidence=claude_sonnet)
    checks.append(("reviewer without --executor-model blocks", no_executor_model_error is not None))
    cross_provider, _ = route(
        "claude", "medium", "claude-opus-4-8", role="reviewer",
        executor_model="deepseek-v4-flash-vision-exp", quota_evidence=claude_opus_4_8,
    )
    checks.append((
        "reviewer from a different provider passes the gate",
        cross_provider is not None and cross_provider["independence_gate"]["independence"] == "independent",
    ))
    cross_generation, _ = route(
        "claude", "medium", "claude-opus-5", role="reviewer", executor_model="claude-opus-4-8",
        quota_evidence=claude_opus_5,
    )
    checks.append((
        "opus-5 reviewing opus-4-8 is independent (distinct model_family)",
        cross_generation is not None and cross_generation["independence_gate"]["independence"] == "independent",
    ))
    non_gated, _ = route("claude", "medium", role="executor", quota_evidence=claude_sonnet)
    checks.append((
        "non-reviewer roles are recorded but not gated",
        non_gated is not None and non_gated["independence_gate"]["independence"] == "not_gated",
    ))
    no_role, _ = route("claude", "medium", quota_evidence=claude_sonnet)
    checks.append(("omitting --role leaves the receipt unchanged", no_role is not None and "independence_gate" not in no_role))
    _, unknown_role_error = route("claude", "medium", role="auditor", quota_evidence=claude_sonnet)
    checks.append(("unknown dispatch_role blocks", unknown_role_error is not None))

    receipt = medium_with_terra
    checks.append(("route receipt has fixed fields", receipt is not None and all(key in receipt for key in ("selected_model", "selected_reasoning_effort", "task_complexity", "selection_reason", "estimated_cost_range", "catalog_version", "selection_status"))))
    checks.append((
        "route receipt records the quota evidence it consumed",
        receipt is not None and (receipt.get("quota_filter") or {}).get("applied") is True
        and (receipt.get("quota_filter") or {}).get("selected_observation", {}).get("source") == "selftest fixture probe",
    ))

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
    parser.add_argument("--independence-policy", choices=["different_family", "different_model"], default="different_family", help="user/project review policy; never bypasses same-model or quota gates")
    parser.add_argument(
        "--quota-observations",
        dest="quota_observations",
        help=(
            "path to this run's live-quota precheck report (JSON object with executor, auth_status and "
            "quota_observations[]). Required: it is the only evidence that can authorize a selection."
        ),
    )
    # Removed in 2.0.0; kept only so an older command line fails with guidance
    # instead of silently routing on an unproven bucket.
    parser.add_argument("--available-model", dest="available_model", action="append", default=None, help=argparse.SUPPRESS)
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
        if args.available_model:
            raise RouteError(
                "quota_evidence_missing: --available-model was removed in 2.0.0 because a bare model id carries no "
                "auth_status, bucket, source or probed_at. Pass the full precheck report with "
                "--quota-observations <precheck-report.json>."
            )
        if not args.quota_observations:
            raise RouteError(
                "quota_evidence_missing: --quota-observations <precheck-report.json> is required; auto-routing and "
                "explicit selection both need an auth_status=ok report with an available observation bound to the selected model."
            )
        evidence = load_quota_observations(Path(args.quota_observations), data)
        result = route_model(
            data, args.executor, args.complexity, args.model, args.reasoning,
            role=args.role, executor_model=args.executor_model, quota_evidence=evidence, independence_policy=args.independence_policy,
        )
    except (OSError, catalog_lib.CatalogError, RouteError) as exc:
        print(json.dumps({"selection_status": "blocked", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
