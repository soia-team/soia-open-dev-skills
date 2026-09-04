#!/usr/bin/env python3
"""Generate a deterministic, offline visual review of one code scope."""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


SKILL_NAME = "soia-dev-show-task-html"
FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "task.json"
VALID_SCOPES = ("task", "change_set", "project")
VALID_VIEWS = ("auto", "progress", "overview", "call_chain", "data_flow", "boundary", "conformance", "full")
SCOPE_LABELS = {"task": "当前任务", "change_set": "变更集", "project": "项目"}
VIEW_LABELS = {
    "auto": "自动最小视图",
    "progress": "阶段进度",
    "overview": "概览",
    "call_chain": "核心调用链",
    "data_flow": "数据流",
    "boundary": "模块边界",
    "conformance": "规范符合性",
    "full": "完整证据视图",
}
CLAIM_LABELS = {"observed": "已观察", "inferred": "推断", "unknown": "未知"}
STATUS_LABELS = {
    "done": "已完成", "active": "进行中", "blocked": "阻塞", "pending": "待处理",
    "pass": "通过", "fail": "失败", "unknown": "未知",
}


def text(value: Any, fallback: str = "—") -> str:
    """Convert arbitrary JSON values to safe, deterministic display text."""
    if value is None or value == "":
        return fallback
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def esc(value: Any, fallback: str = "—") -> str:
    return html.escape(text(value, fallback), quote=True)


def nonempty(value: Any) -> bool:
    return value not in (None, "", [], {})


def pick(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in data and nonempty(data[key]):
            return data[key]
    return default


def normalize_scope(value: Any) -> str:
    aliases = {"current_task": "task", "current-task": "task", "changeset": "change_set", "changes": "change_set"}
    result = aliases.get(str(value).lower(), str(value).lower())
    if result not in VALID_SCOPES:
        raise ValueError(f"scope must be one of: {', '.join(VALID_SCOPES)}")
    return result


def normalize_view(value: Any) -> str:
    aliases = {"call-chain": "call_chain", "data-flow": "data_flow"}
    result = aliases.get(str(value).lower(), str(value).lower())
    if result not in VALID_VIEWS:
        raise ValueError(f"view must be one of: {', '.join(VALID_VIEWS)}")
    return result


def as_items(value: Any) -> list[Any]:
    if not nonempty(value):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [{"label": key, "value": value[key]} for key in sorted(value)]
    return [value]


def item_title(item: Any, fallback: str = "条目") -> str:
    if isinstance(item, dict):
        for key in ("title", "name", "label", "path", "check", "rule", "stage", "step"):
            if nonempty(item.get(key)):
                return text(item[key])
    return text(item, fallback)


def details(item: Any, keys: tuple[str, ...]) -> str:
    if not isinstance(item, dict):
        return ""
    values = [text(item[key]) for key in keys if nonempty(item.get(key))]
    return " · ".join(values)


def status_value(item: Any) -> str:
    if not isinstance(item, dict):
        return "pending"
    raw = str(item.get("status", item.get("state", "pending"))).lower()
    if raw in {"passed", "pass", "通过"}:
        return "pass"
    if raw in {"done", "complete", "completed", "verified", "success", "完成"}:
        return "done"
    if raw in {"failed", "fail", "阻塞", "失败"}:
        return "blocked"
    if raw in {"in_progress", "in-progress", "active", "running", "进行中"}:
        return "active"
    if raw in {"unknown", "未知"}:
        return "unknown"
    return "pending"


def claim_type(item: Any) -> str:
    raw = str(item.get("claim_type", item.get("certainty", "unknown"))).lower() if isinstance(item, dict) else "unknown"
    return raw if raw in CLAIM_LABELS else "unknown"


def reference_items(item: Any) -> list[Any]:
    if not isinstance(item, dict):
        return []
    raw = pick(item, "references", "evidence_refs", "sources", default=[])
    if isinstance(raw, dict) and any(key in raw for key in ("file", "path", "source", "line", "line_number")):
        refs = [raw]
    else:
        refs = as_items(raw)
    if not refs and (nonempty(item.get("file")) or nonempty(item.get("path"))):
        refs = [{"file": pick(item, "file", "path"), "line": item.get("line")}]
    return refs


def reference_text(ref: Any) -> str:
    if isinstance(ref, dict):
        file_name = pick(ref, "file", "path", "source", default="")
        line = pick(ref, "line", "line_number", default=None)
        if nonempty(file_name) and nonempty(line):
            return f"{text(file_name)}:{text(line)}"
        if nonempty(file_name):
            return text(file_name)
        return text(ref)
    return text(ref)


def evidence_meta(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    kind = claim_type(item)
    refs = reference_items(item)
    ref_html = " ".join(f'<code class="ref">{esc(reference_text(ref))}</code>' for ref in refs)
    if not ref_html:
        ref_html = '<span class="ref missing">出处未提供</span>'
    return f'<div class="evidence-meta"><span class="claim claim-{kind}">{CLAIM_LABELS[kind]}</span>{ref_html}</div>'


def card_list(items: list[Any], detail_keys: tuple[str, ...]) -> str:
    if not items:
        return ""
    cards = []
    for item in items:
        state = status_value(item)
        status = f'<span class="status status-{state}">{STATUS_LABELS[state]}</span>' if isinstance(item, dict) and ("status" in item or "state" in item) else ""
        cards.append(
            '<article class="card">'
            f'<div class="card-title">{esc(item_title(item))}</div>'
            f'<div class="card-detail">{esc(details(item, detail_keys), "")}</div>'
            f'{status}{evidence_meta(item)}'
            "</article>"
        )
    return "".join(cards)


def compact_cards(items: list[Any], detail_keys: tuple[str, ...]) -> str:
    cards = []
    for item in items:
        state = status_value(item)
        cards.append(
            '<article class="card">'
            f'<div class="card-title">{esc(item_title(item))}</div>'
            f'<div class="card-detail">{esc(details(item, detail_keys), "")}</div>'
            f'<span class="status status-{state}">{STATUS_LABELS[state]}</span>'
            '</article>'
        )
    return "".join(cards)


def section(key: str, heading: str, content: str) -> str:
    if not content:
        return ""
    return f'<section class="section" data-section="{key}"><h2>{heading}</h2>{content}</section>'


def render_files(items: list[Any]) -> str:
    rows = []
    for item in items:
        if isinstance(item, dict):
            refs = " ".join(f'<code class="ref">{esc(reference_text(ref))}</code>' for ref in reference_items(item))
            rows.append(
                "<tr>"
                f"<td><code>{esc(pick(item, 'path', 'file', 'scope', default='未提供'))}</code>{refs}</td>"
                f"<td>{esc(pick(item, 'owner', 'responsible', default='未提供'))}</td>"
                f"<td>{esc(pick(item, 'layer', 'module', default='未提供'))}</td>"
                f"<td>{esc(pick(item, 'role', 'summary', 'description', 'change', default='未提供'))}</td>"
                "</tr>"
            )
        else:
            rows.append(f"<tr><td colspan=\"4\"><code>{esc(item)}</code></td></tr>")
    if not rows:
        return ""
    return '<div class="table-wrap"><table><thead><tr><th>文件或范围</th><th>Owner</th><th>Layer</th><th>职责/变更</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>"


def relation_rows(items: list[Any], *, data_flow: bool = False) -> str:
    rows = []
    for item in items:
        if isinstance(item, dict):
            source = pick(item, "from", "source", "input", "caller", default="?")
            target = pick(item, "to", "target", "output", "callee", default="?")
            label = pick(item, "label", "relation", "via", "transform", default="流转" if data_flow else "调用")
            claim = evidence_meta(item)
            rows.append(f'<div class="relation"><strong>{esc(source)}</strong><span class="arrow">→</span><strong>{esc(target)}</strong><span class="relation-label">{esc(label)}</span>{claim}</div>')
        else:
            rows.append(f'<div class="relation"><span>{esc(item)}</span></div>')
    return "".join(rows)


def render_call_chain(value: Any) -> str:
    if not nonempty(value):
        return ""
    overview = nodes = edges = None
    if isinstance(value, dict):
        overview = pick(value, "overview", "summary", "description", default=None)
        nodes = as_items(pick(value, "nodes", "components", default=[]))
        edges = as_items(pick(value, "edges", "calls", "relations", default=[]))
    else:
        edges = as_items(value)
    parts = [f'<p class="overview">{esc(overview)}</p>' if nonempty(overview) else ""]
    if nodes:
        parts.append('<div class="node-row">' + "".join(f'<div class="node">{esc(item_title(node, "组件"))}</div>' for node in nodes) + "</div>")
    if edges:
        parts.append('<div class="relations">' + relation_rows(edges) + "</div>")
    return "".join(parts)


def render_data_flow(value: Any) -> str:
    if not nonempty(value):
        return ""
    if isinstance(value, dict):
        overview = pick(value, "overview", "summary", "description", default=None)
        items = as_items(pick(value, "steps", "stages", "edges", "flow", default=[]))
    else:
        overview, items = None, as_items(value)
    parts = [f'<p class="overview">{esc(overview)}</p>' if nonempty(overview) else ""]
    if items:
        parts.append('<div class="flow">' + relation_rows(items, data_flow=True) + "</div>")
    return "".join(parts)


def render_boundaries(items: list[Any]) -> str:
    if not items:
        return ""
    cards = []
    for item in items:
        if isinstance(item, dict):
            body = details(item, ("responsibility", "depends_on", "direction", "finding", "summary", "detail"))
            cards.append(f'<article class="card"><div class="card-title">{esc(item_title(item, "模块边界"))}</div><div class="card-detail">{esc(body, "")}</div>{evidence_meta(item)}</article>')
        else:
            cards.append(f'<article class="card"><div class="card-title">{esc(item)}</div></article>')
    return '<div class="grid">' + "".join(cards) + "</div>"


def render_conformance(items: list[Any]) -> str:
    if not items:
        return ""
    rows = []
    for item in items:
        if isinstance(item, dict):
            state = str(pick(item, "status", "state", default="unknown")).lower()
            state = "pass" if state in {"pass", "passed", "符合", "compliant"} else "fail" if state in {"fail", "failed", "偏离", "noncompliant"} else "unknown"
            rows.append(f'<tr><td>{esc(pick(item, "rule", "name", "title", default="未提供"))}</td><td>{esc(pick(item, "expected", "requirement", default="未提供"))}</td><td>{esc(pick(item, "observed", "actual", default="未提供"))}</td><td><span class="status status-{state}">{STATUS_LABELS[state]}</span>{evidence_meta(item)}</td></tr>')
        else:
            rows.append(f'<tr><td colspan="4">{esc(item)}</td></tr>')
    return '<div class="table-wrap"><table><thead><tr><th>项目规范</th><th>应符合</th><th>实际观察</th><th>结论与出处</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>"


def render_evidence(task: dict[str, Any]) -> str:
    facts = as_items(pick(task, "facts", "findings", default=[]))
    verification = as_items(pick(task, "verification", "verification_evidence", "evidence", "checks", default=[]))
    risks = as_items(pick(task, "risks", "risk", default=[]))
    blockers = as_items(pick(task, "blockers", "blocking", default=[]))
    next_steps = as_items(pick(task, "next_steps", "next", default=[]))
    parts = []
    if facts:
        parts.append("<h3>事实与判断</h3><div class=\"grid\">" + card_list(facts, ("detail", "summary", "finding")) + "</div>")
    if verification:
        parts.append("<h3>验证证据</h3><div class=\"grid\">" + card_list(verification, ("evidence", "detail", "summary", "command")) + "</div>")
    if risks or blockers:
        columns = []
        if risks:
            columns.append("<div><h3>风险</h3>" + card_list(risks, ("detail", "summary", "impact", "mitigation")) + "</div>")
        if blockers:
            columns.append("<div><h3>阻塞</h3>" + card_list(blockers, ("detail", "summary", "reason", "owner")) + "</div>")
        parts.append('<div class="grid">' + "".join(columns) + "</div>")
    if next_steps:
        parts.append("<h3>下一步</h3><div class=\"grid\">" + card_list(next_steps, ("detail", "summary", "owner", "due")) + "</div>")
    return "".join(parts)


def render_progress(task: dict[str, Any]) -> str:
    metrics = as_items(pick(task, "metrics", "stats", default=[]))
    tasks = as_items(pick(task, "steps", "tasks", "stages", "phase_steps", default=[]))
    blockers = as_items(pick(task, "blockers", "blocking", default=[]))
    next_steps = as_items(pick(task, "next_steps", "next", default=[]))
    parts = []
    if metrics:
        cards = []
        for item in metrics:
            if isinstance(item, dict):
                label = pick(item, "label", "name", "title", default="指标")
                value = pick(item, "value", "count", default="—")
                tone = str(pick(item, "tone", "status", default="pending")).lower()
                tone = tone if tone in {"done", "pass", "active", "blocked", "fail", "pending"} else "pending"
                cards.append(f'<div class="stat stat-{tone}"><strong>{esc(value)}</strong><span>{esc(label)}</span></div>')
            else:
                cards.append(f'<div class="stat"><strong>{esc(item)}</strong></div>')
        parts.append('<div class="stats">' + "".join(cards) + "</div>")
    if tasks:
        rows = []
        for item in tasks:
            state = status_value(item)
            owner = pick(item, "owner", "agent", default="") if isinstance(item, dict) else ""
            next_action = pick(item, "next", "next_action", "gate", default="") if isinstance(item, dict) else ""
            detail = details(item, ("detail", "summary", "description"))
            rows.append(
                '<div class="progress-row">'
                f'<div class="progress-main"><strong>{esc(item_title(item))}</strong>'
                f'<span>{esc(detail, "")}</span></div>'
                f'<span class="progress-owner">{esc(owner, "")}</span>'
                f'<span class="status status-{state}">{STATUS_LABELS[state]}</span>'
                f'<span class="progress-next">{esc(next_action, "")}</span>'
                '</div>'
            )
        parts.append('<h3>任务</h3><div class="progress-list">' + "".join(rows) + "</div>")
    if blockers:
        parts.append('<h3>阻塞</h3><div class="compact-grid">' + compact_cards(blockers, ("detail", "reason", "owner")) + "</div>")
    if next_steps:
        parts.append('<h3>下一步</h3><div class="compact-grid">' + compact_cards(next_steps, ("detail", "owner", "due")) + "</div>")
    return "".join(parts)


def normalize_task(raw: dict[str, Any], scope_override: str | None = None, view_override: str | None = None) -> dict[str, Any]:
    task = dict(raw)
    task["scope"] = normalize_scope(scope_override if scope_override is not None else task.get("scope", "task"))
    task["view"] = normalize_view(view_override if view_override is not None else task.get("view", "auto"))
    if not nonempty(pick(task, "title", "name", default=None)):
        raise ValueError("input JSON must include a non-empty title")
    return task


def present_sections(task: dict[str, Any]) -> dict[str, bool]:
    files = as_items(pick(task, "files", "changed_files", "file_matrix", "changes", "code_changes", default=[]))
    return {
        "overview": bool(
            files
            or as_items(pick(task, "steps", "stages", "phase_steps", default=[]))
            or nonempty(pick(task, "call_chain", "architecture", "architecture_calls", "call_graph", default=None))
            or nonempty(pick(task, "data_flow", "dataflow", "flow", default=None))
            or as_items(pick(task, "boundaries", "modules", "module_boundaries", default=[]))
            or as_items(pick(task, "conformance", "architecture_conformance", "standards", default=[]))
        ),
        "files": bool(files),
        "call_chain": nonempty(pick(task, "call_chain", "architecture", "architecture_calls", "call_graph", default=None)),
        "data_flow": nonempty(pick(task, "data_flow", "dataflow", "flow", default=None)),
        "boundary": bool(as_items(pick(task, "boundaries", "modules", "module_boundaries", default=[]))),
        "conformance": bool(as_items(pick(task, "conformance", "architecture_conformance", "standards", default=[]))),
        "evidence": bool(render_evidence(task)),
    }


def selected_sections(task: dict[str, Any]) -> list[str]:
    available = present_sections(task)
    view = task["view"]
    order = ["overview", "files", "call_chain", "data_flow", "boundary", "conformance", "evidence"]
    if view in {"auto", "full"}:
        return [key for key in order if available[key]]
    if view == "progress":
        return ["progress"] if render_progress(task) else []
    wanted = {"overview": ["overview"], "call_chain": ["overview", "files", "call_chain"], "data_flow": ["overview", "files", "data_flow"], "boundary": ["overview", "files", "boundary"], "conformance": ["overview", "files", "conformance"]}[view]
    return [key for key in wanted if available[key]]


def render_document(raw_task: dict[str, Any], scope_override: str | None = None, view_override: str | None = None) -> str:
    task = normalize_task(raw_task, scope_override, view_override)
    title = pick(task, "title", "name")
    objective = pick(task, "objective", "goal", "target", default="未提供目标")
    parts = [f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} · 代码变更视图</title>
<style>
:root {{ color-scheme:light; --ink:#172033; --muted:#526174; --line:#d5dde7; --panel:#fff; --bg:#f3f6fa; --accent:#1d5fd0; --good:#087443; --warn:#8a5b00; --bad:#b42318; }}
* {{ box-sizing:border-box; }} body {{ margin:0; background:var(--bg); color:var(--ink); font:14px/1.45 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; user-select:text; }}
main {{ width:min(1320px,100% - 24px); margin:0 auto; padding:20px 0 36px; }} h1 {{ margin:0 0 7px; font-size:clamp(24px,4vw,40px); line-height:1.12; overflow-wrap:anywhere; }} h2 {{ margin:0 0 10px; font-size:18px; line-height:1.3; }} h3 {{ margin:10px 0 7px; font-size:14px; line-height:1.35; }}
.hero {{ background:linear-gradient(135deg,#1e3a8a,#2563c9); color:#fff; border:1px solid #1e4faa; border-radius:12px; padding:18px; box-shadow:0 6px 18px #17255420; }} .objective,.overview {{ margin:0; overflow-wrap:anywhere; }} .objective {{ font-size:15px; max-width:92ch; }} .meta {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:12px; }} .meta span {{ border:1px solid #ffffff4d; border-radius:999px; padding:2px 8px; font-size:12px; line-height:1.35; }}
.section {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:14px; margin-top:10px; }} .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,230px),1fr)); gap:10px; }} .card {{ border:1px solid var(--line); border-radius:10px; padding:10px 12px; background:#fbfcfe; min-width:0; }} .card-title {{ font-weight:700; overflow-wrap:anywhere; }} .card-detail {{ color:var(--muted); overflow-wrap:anywhere; }} .card-detail:empty {{ display:none; }}
.stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(96px,1fr)); gap:8px; }} .stat {{ border:1px solid var(--line); border-radius:10px; padding:8px 10px; background:#fbfcfe; }} .stat strong {{ display:block; font-size:20px; line-height:1.15; }} .stat span {{ color:var(--muted); font-size:11px; }} .stat-done,.stat-pass {{ border-color:#a9dec4; }} .stat-active {{ border-color:#a9c4fa; }} .stat-blocked,.stat-fail {{ border-color:#f3b4af; }}
.progress-list {{ border-top:1px solid var(--line); }} .progress-row {{ display:grid; grid-template-columns:minmax(0,1fr) minmax(80px,.42fr) 76px minmax(110px,.62fr); gap:8px; align-items:center; padding:7px 8px; border-bottom:1px solid var(--line); }} .progress-row:nth-child(even) {{ background:#f8fafc; }} .progress-main {{ min-width:0; }} .progress-main strong,.progress-main span {{ display:block; }} .progress-main span,.progress-owner,.progress-next {{ color:var(--muted); font-size:12px; overflow-wrap:anywhere; }} .compact-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,190px),1fr)); gap:8px; }}
.status,.claim {{ display:inline-block; margin:6px 6px 0 0; border-radius:999px; padding:2px 7px; font-size:11px; font-weight:700; line-height:1.3; white-space:nowrap; }} .progress-row .status {{ justify-self:start; margin:0; }} .status-done,.status-pass,.claim-observed {{ color:var(--good); background:#e7f6ee; }} .status-active,.claim-inferred {{ color:var(--accent); background:#e8f0ff; }} .status-blocked,.status-fail {{ color:var(--bad); background:#feebea; }} .status-pending,.status-unknown,.claim-unknown {{ color:var(--warn); background:#fff4d6; }}
.evidence-meta {{ margin-top:5px; color:var(--muted); overflow-wrap:anywhere; }} .ref {{ display:inline-block; margin:4px 5px 0 0; padding:1px 5px; border:1px solid var(--line); border-radius:4px; background:#f7f9fc; }} .ref.missing {{ font-size:11px; }} code {{ font:0.9em ui-monospace,SFMono-Regular,Menlo,monospace; overflow-wrap:anywhere; }}
.table-wrap {{ max-width:100%; overflow-x:auto; }} table {{ width:100%; border-collapse:collapse; }} th,td {{ text-align:left; vertical-align:top; border-bottom:1px solid var(--line); padding:7px 8px; min-width:110px; }} th {{ color:var(--muted); font-size:12px; }}
.node-row {{ display:flex; flex-wrap:wrap; gap:7px; align-items:center; margin:10px 0; }} .node {{ border:1px solid #9db9f9; background:#eef4ff; border-radius:10px; padding:6px 9px; font-weight:650; overflow-wrap:anywhere; }} .relations,.flow {{ display:grid; gap:6px; }} .relation {{ background:#f7f9fc; border-left:3px solid var(--accent); padding:7px 9px; overflow-wrap:anywhere; }} .arrow {{ color:var(--accent); padding:0 7px; }} .relation-label {{ color:var(--muted); margin-left:7px; }}
footer {{ color:var(--muted); text-align:center; margin-top:16px; font-size:12px; }} @media (max-width:700px) {{ main {{ width:min(100% - 16px,1320px); padding-top:10px; }} .hero,.section {{ padding:14px; border-radius:10px; }} .grid,.compact-grid {{ grid-template-columns:1fr; }} .progress-row {{ grid-template-columns:minmax(0,1fr) auto; }} .progress-owner,.progress-next {{ grid-column:1 / -1; }} th,td {{ min-width:104px; }} }}
</style></head><body><main><header class="hero"><h1>{esc(title)}</h1><p class="objective">{esc(objective)}</p><div class="meta"><span>范围：{SCOPE_LABELS[task['scope']]}</span><span>视图：{VIEW_LABELS[task['view']]}</span>{f'<span>阶段：{esc(pick(task, "stage", "phase", default="未提供"))}</span>' if nonempty(pick(task, "stage", "phase", default=None)) else ''}</div></header>''']
    sections = selected_sections(task)
    if "progress" in sections:
        parts.append(section("progress", "进度总览", render_progress(task)))
    if "overview" in sections:
        steps = as_items(pick(task, "steps", "stages", "phase_steps", default=[]))
        files = as_items(pick(task, "files", "changed_files", "file_matrix", "changes", "code_changes", default=[]))
        call_chain = nonempty(pick(task, "call_chain", "architecture", "architecture_calls", "call_graph", default=None))
        data_flow = nonempty(pick(task, "data_flow", "dataflow", "flow", default=None))
        stats = []
        if files:
            stats.append(f"文件 {len(files)} 个")
        if call_chain:
            stats.append("调用链已提供")
        if data_flow:
            stats.append("数据流已提供")
        summary = f'<p class="overview">{"；".join(stats)}</p>' if stats else ""
        if steps:
            summary += '<h3>阶段与步骤</h3><div class="grid">' + card_list(steps, ("detail", "summary", "description")) + "</div>"
        parts.append(section("overview", "概览", summary))
    if "files" in sections:
        parts.append(section("files", "文件 / Owner / Layer 矩阵", render_files(as_items(pick(task, "files", "changed_files", "file_matrix", "changes", "code_changes", default=[])))))
    if "call_chain" in sections:
        parts.append(section("call_chain", "核心调用链", render_call_chain(pick(task, "call_chain", "architecture", "architecture_calls", "call_graph", default=None))))
    if "data_flow" in sections:
        parts.append(section("data_flow", "数据流：输入 → 转换 → Domain / Service / Port → Adapter / Storage / External → View", render_data_flow(pick(task, "data_flow", "dataflow", "flow", default=None))))
    if "boundary" in sections:
        parts.append(section("boundary", "模块边界与依赖方向", render_boundaries(as_items(pick(task, "boundaries", "modules", "module_boundaries", default=[])))))
    if "conformance" in sections:
        parts.append(section("conformance", "架构 / 技术规范符合矩阵", render_conformance(as_items(pick(task, "conformance", "architecture_conformance", "standards", default=[])))))
    if "evidence" in sections:
        parts.append(section("evidence", "验证、风险、阻塞与下一步", render_evidence(task)))
    parts.append('<footer>离线代码变更视图 · 仅展示调用方提供的已核实信息 · 可直接选择和复制文字</footer></main></body></html>')
    return "".join(parts)


def read_task(source: str) -> dict[str, Any]:
    raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("input JSON must be an object")
    return data


def write_atomic(target: Path, content: str, force: bool = False) -> Path:
    target = target.expanduser()
    if target.exists() and target.is_dir():
        raise ValueError(f"output is a directory: {target}")
    if target.is_symlink():
        raise ValueError("refusing to write through a symlink output path")
    if target.exists() and not force:
        raise FileExistsError(f"output exists; pass --force to replace: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, target)
    finally:
        temp_path.unlink(missing_ok=True)
    return target


def run_selftest() -> None:
    task = read_task(str(FIXTURE))
    full = render_document(task)
    minimal = render_document({"title": "Minimal scope", "objective": "只展示一个最小主题。"})
    dict_ref = render_document({"title": "Reference shape", "verification": [{"check": "one", "evidence": "direct", "references": {"file": "src/one.py", "line": 9}}]})
    progress = render_document({"title": "Progress", "view": "progress", "metrics": [{"label": "进行中", "value": 2, "tone": "active"}], "steps": [{"name": "Slice A", "status": "running", "owner": "Terra", "next": "review"}], "blockers": [{"title": "Owner decision", "detail": "waiting"}], "next_steps": [{"name": "Review"}]})
    for scope in VALID_SCOPES:
        render_document({"title": "scope", "scope": scope})
    for view in VALID_VIEWS:
        render_document({"title": "view", "view": view})
    if full != render_document(task):
        raise AssertionError("rendering is not deterministic")
    for marker in ("变更集", "文件 / Owner / Layer 矩阵", "核心调用链", "数据流", "架构 / 技术规范符合矩阵", "src/api/routes.ts:42", "&lt;script&gt;"):
        if marker not in full:
            raise AssertionError(f"selftest marker missing: {marker}")
    if "src/one.py:9" not in dict_ref:
        raise AssertionError("single-object file:line reference was not rendered")
    if '<span class="claim claim-unknown">' not in dict_ref or '<span class="claim claim-observed">' in dict_ref:
        raise AssertionError("missing claim_type did not default to unknown")
    if "<script" in full or "<link" in full or "<img" in full:
        raise AssertionError("selftest found a non-self-contained external/resource tag")
    if full.count("Observed call path") != 1 or ".node:not(:last-child)" in full:
        raise AssertionError("overview duplicated facts or implied an unverified node order")
    if any(f'data-section="{key}"' in minimal for key in ("overview", "files", "call_chain", "data_flow", "boundary", "conformance", "evidence")):
        raise AssertionError("auto view rendered an empty section")
    if 'data-section="progress"' not in progress or 'data-section="files"' in progress or "Slice A" not in progress or "出处未提供" in progress:
        raise AssertionError("progress view did not stay compact")
    for invalid in ({"scope": "workspace"}, {"view": "diagram"}):
        try:
            render_document({"title": "invalid", **invalid})
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid input was accepted: {invalid}")
    with tempfile.TemporaryDirectory(prefix=f"{SKILL_NAME}-selftest-") as directory:
        target = write_atomic(Path(directory) / "task.html", full)
        if not target.is_file() or target.read_text(encoding="utf-8") != full:
            raise AssertionError("selftest output round-trip failed")
    print("selftest: passed (scope/view validation, minimal auto view, escaping, refs, deterministic output)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="-", help="JSON file, or - for stdin.")
    parser.add_argument("--scope", choices=VALID_SCOPES, help="Override input scope.")
    parser.add_argument("--view", choices=VALID_VIEWS, help="Override input view.")
    parser.add_argument("--output", help="Explicit deliverable path; omitted uses an OS temp directory.")
    parser.add_argument("--force", action="store_true", help="Allow replacing an existing explicit output file.")
    parser.add_argument("--selftest", action="store_true", help="Run the bundled generic fixture self-test.")
    args = parser.parse_args(argv)
    try:
        if args.selftest:
            run_selftest()
            return 0
        content = render_document(read_task(args.input), args.scope, args.view)
        if args.output:
            target = write_atomic(Path(args.output), content, force=args.force)
        else:
            directory = Path(tempfile.mkdtemp(prefix=f"{SKILL_NAME}-"))
            os.chmod(directory, 0o700)
            target = write_atomic(directory / "task.html", content)
        print(f"created: {target}")
        return 0
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
