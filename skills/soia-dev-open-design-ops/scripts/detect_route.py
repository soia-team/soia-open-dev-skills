#!/usr/bin/env python3
"""判定本机该走哪条 Open Design 接入路线。

存在的理由：同一台机器上「CLI 源码 checkout」「桌面版 App」「MCP」是三条彼此
独立的路线，装了哪条完全看客户怎么安装。上层技能如果不先判定就直接跑
`check_env.py`（那是 CLI 路线的检查），在只装了桌面版的机器上必然拿到
`status=error`，从而误判成「环境坏了」而停下——实际上桌面版 + MCP 都是好的。

本脚本只探测、不修改：不启停 daemon、不改任何 agent 配置、不打印凭据。

用法：
    python3 scripts/detect_route.py            # 人读摘要
    python3 scripts/detect_route.py --json     # 机读，供上层技能分流

退出码：
    0  至少一条路线可用
    1  三条都不可用（此时 suggestions 给出修复方向）

0.18.1 实测(2026-08-07)：`APP_BUNDLE`/`HELPER`/`DAEMON_CLI` 不再是模块级常量，
改为每次运行时经 `desktop_ctl.resolve_launcher_payload()` 动态解析——版本号
会随桌面版自动升级变化，写死会连到不存在或过期的路径。详见该函数的 docstring。

0.19.2 实测(2026-08-18)：`probe_mcp()` 的 `workspace_gap` 证据块改按活着的
daemon 版本判断（`desktop_ctl.meets_minimum_version()`），不再对所有版本一律
报 `affected=true`——0.18.1 上这道 workspace 门确有其事，但同一套配置在
0.19.2 上已经不再出现，继续无条件报「受影响」会把已经修好的机器也拖进不必要的
降级路径。详见 `probe_mcp()` 的 docstring。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check_env  # noqa: E402
import desktop_ctl  # noqa: E402

IPC_ROOT = "/tmp/open-design/ipc"


def _resolved_payload() -> dict:
    """当前 launcher payload 解析结果。每次调用重新探测，不缓存——桌面版可能
    在两次调用之间升级或切换 namespace。"""
    return desktop_ctl.resolve_launcher_payload()


# 供 install_od_mcp.py 等旧调用方以 `detect_route.HELPER` / `detect_route.DAEMON_CLI`
# 形式读取的模块级快照：取一次当前解析结果。同一进程内多次探测应使用
# `_resolved_payload()` 而不是这两个快照，避免长生命周期进程里版本变化不生效。
_PAYLOAD_SNAPSHOT = _resolved_payload()
APP_BUNDLE = _PAYLOAD_SNAPSHOT["app_bundle"]
HELPER = _PAYLOAD_SNAPSHOT["helper"]
DAEMON_CLI = _PAYLOAD_SNAPSHOT["daemon_cli"]

# 各家 agent 的 MCP 落点。**键名与条目结构逐个实测过，不要按 Claude 的格式套**：
#   json-claude   mcpServers.<name> = {command: str, args: [...], env: {...}}
#   json-opencode mcp.<name>        = {command: [argv...], type: "local", enabled: bool}
#                 —— command 是 argv 数组而非字符串，且未见 env 字段
#   toml-codex    [mcp_servers.<name>] command/args + [mcp_servers.<name>.env]
#   unknown       结构没验证过，只报告、不自动写
#
# pi (v0.83.0) 核心不带 MCP：无 mcp 子命令、settings.json 无 MCP 字段。但第三方扩展
# `pi-mcp-adapter`（2026-08-05 实测 v2.20.1）能补上，装完后 ~/.pi/agent/mcp.json 就是
# json-claude 同构（mcpServers.<name> = {command, args, env}），可以直接复用这条判定。
# **不要用它的 imports 模式**（把其它宿主全部 MCP server 借过来）——实测会把 codex
# 里 enabled=false 的 computer-use、cursor/opencode 命名冲突的 pencil 之类无关配置也
# 带进来导致连接失败；应该只在 mcpServers 里直接定义 open-design 这一条，imports 留空。
# 见 references/mcp-hosts.md「pi」一节。
# qwen 的 ~/.qwen/settings.json 里没有任何 MCP 键；~/.qwen/shells/init-mcp.sh 是个
# 改 ~/.claude/settings.json 的管理脚本，不是 qwen 自己的 MCP 配置，故不列为目标。
AGENT_CONFIGS: tuple[tuple[str, str, str, str], ...] = (
    ("claude-code", "~/.claude.json", "json-claude", "mcpServers"),
    ("codex", "~/.codex/config.toml", "toml-codex", "mcp_servers"),
    ("cursor", "~/.cursor/mcp.json", "json-claude", "mcpServers"),
    ("opencode", "~/.config/opencode/opencode.json", "json-opencode", "mcp"),
    ("pi", "~/.pi/agent/mcp.json", "json-claude", "mcpServers"),
    ("workbuddy", "~/.workbuddy", "unknown", ""),
)


def probe_cli() -> dict[str, Any]:
    """CLI / 源码 checkout 路线：要 checkout + Node 24 + pnpm 10.33 + 7456 端口。"""
    env = check_env.check_environment()
    blockers = list(env.get("missing") or [])
    daemon_up = desktop_ctl.probe(7456) is not None
    if not daemon_up:
        blockers.append("daemon_7456_unreachable")
    return {
        "available": env.get("status") == "ok" and daemon_up,
        "evidence": {
            "check_env_status": env.get("status"),
            "daemon_7456": daemon_up,
        },
        "blockers": blockers,
    }


def probe_desktop() -> dict[str, Any]:
    """桌面版路线：App 装了、数据目录在、daemon API 端口活着。

    0.18.1 起 `desktop_ctl.detect()` 用 `/api/health` 判活（不再是
    `/api/projects` 的返回形状），并且能在一台机器上同时报出多个活的
    daemon 端口（实测桌面版会起不止一个 daemon 进程）。
    """
    payload = _resolved_payload()
    port, ports = desktop_ctl.detect()
    namespaces: list[str] = []
    ns_root = os.path.join(desktop_ctl.APP_SUPPORT, "namespaces")
    if os.path.isdir(ns_root):
        namespaces = sorted(
            n for n in os.listdir(ns_root) if os.path.isdir(os.path.join(ns_root, n))
        )
    identity = desktop_ctl.resolve_workspace_identity()
    return {
        "available": bool(port),
        "evidence": {
            "app_bundle": os.path.isdir(payload["app_bundle"]),
            "resolved_version": payload["version"],
            "resolved_source": payload["source"],
            "api_port": port,
            "listening_ports": ports,
            "namespaces": namespaces,
            "workspace_id_resolved": bool(identity.get("workspace_id")),
            "workspace_member_id_resolved": bool(identity.get("workspace_member_id")),
        },
        # 端口每次启动都变，别把它写进任何配置或文档
        "blockers": [] if port else ["no_live_daemon_api_port"],
    }


def _json_has_open_design(path: str, mcp_key: str) -> bool | None:
    """在 JSON 配置的 MCP 段里精确查 open-design；解析失败返回 None。

    mcp_key 因 agent 而异（Claude/Cursor 是 mcpServers，opencode 是 mcp），
    传错键名会把「未配」误判成「已配」或反之。
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    found = False

    def walk(node: Any) -> None:
        nonlocal found
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            # 只认该 agent 自己的 MCP 注册表，别处出现同名字符串一律不算
            if key == mcp_key and isinstance(value, dict):
                if any("open-design" in name for name in value):
                    found = True
            walk(value)

    walk(data)
    return found


def _toml_has_open_design(path: str) -> bool | None:
    """TOML 只认 [mcp_servers.<name>] 段；解析失败或无 tomllib 返回 None。"""
    try:
        import tomllib
    except ModuleNotFoundError:
        return None
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except (OSError, ValueError):
        return None
    servers = data.get("mcp_servers")
    if not isinstance(servers, dict):
        return False
    return any("open-design" in name for name in servers)


def probe_mcp() -> dict[str, Any]:
    """MCP 路线：sidecar 可执行文件在不在，哪些 agent 已经配了 open-design。

    注意四点：
    1. 本脚本探测的是「配置里装没装」。当前这个 agent 手里到底有没有
       mcp__open-design__* 工具，只有它自己知道——脚本无法代答。
    2. 判定必须按格式解析到 MCP 注册表那一段。裸用子串匹配会被骗：codex 的
       config.toml 里有 [projects."…/upstream/open-design"]，那是项目路径，
       不是 MCP 配置，子串匹配会误报「已配」。
    3. **「配置装好了」不等于「MCP 能看见项目」——但这是有版本边界的，不能
       无条件下结论。** 0.18.1 实测(2026-08-07)：MCP sidecar（打包内
       `chunks/chunk-*.mjs` 里的 MCP server 实现，用 `list_projects`/
       `get_project` 等工具时）内部直接 `fetch()` daemon 的 `/api/projects`、
       `/api/projects/:id`，从不附带 `x-od-workspace-id` /
       `x-od-workspace-member-id` header，也不读任何环境变量（穷举 `OD_*`
       环境变量、以及专供 daemon 自身请求校验用的 `OD_DEV_WORKSPACE_CONTEXT`
       / `OD_WORKSPACE_CONTEXT_SOURCE`，逐个通过 stdio 直起 sidecar 实测，均
       无效）。已绑定 workspace 的项目——桌面版创建的项目几乎全部如此，且
       未绑定的项目只要 App 还开着，通常一分钟内就会被自动绑定——因此对
       `list_projects`/`get_project`/`get_file`/`list_files`/`start_run`
       等工具全部不可见，报 `no projects on this daemon` 或
       `daemon 400 ... WORKSPACE_CONTEXT_REQUIRED`。**0.19.2 实测(2026-08-18，
       stdio 直连与 Claude Code 长连接两条路径均验证)：同一套配置下这道门已经
       不再出现**——`list_projects` 返回全部真实项目并带 `workspaceId` 字段，
       `start_run` 正常返回 `runId` 且 `get_run` 能拿到 `pluginId`/
       `appliedPluginSnapshotId`。没有验证是上游哪个改动修复的，也没有重新
       测过 0.19.0/0.19.1 是否已经修好，只确认了 0.18.1（受影响）与 0.19.2
       （不受影响）这两个点。
    4. 因此下面的 `workspace_gap` 证据块**按 daemon 版本判断**，不再对所有
       版本一律报 `affected=true`：判据是活着的 daemon 自己在 `/api/health`
       里报的 `version`（`desktop_ctl.probe_health()`，最权威，反映的是当前
       真正在跑的那份代码，见 `desktop_ctl.py` 模块文档字符串「launcher 版本化
       路径」一节里"两处路径不能相互替代"的说明）；daemon 没起来时退化用
       `resolve_launcher_payload()` 解析到的安装版本；两者都拿不到就是版本
       未知，按旧版本的保守假设处理（可能受影响），不能悄悄报「没问题」。
       版本比较用 `desktop_ctl.meets_minimum_version()`。
    """
    payload = _resolved_payload()
    sockets: list[str] = []
    if os.path.isdir(IPC_ROOT):
        for ns in sorted(os.listdir(IPC_ROOT)):
            sock = os.path.join(IPC_ROOT, ns, "daemon.sock")
            if os.path.exists(sock):
                sockets.append(sock)

    agents: dict[str, dict[str, Any]] = {}
    for name, raw_path, fmt, mcp_key in AGENT_CONFIGS:
        path = os.path.expanduser(raw_path)
        exists = os.path.exists(path)
        configured: bool | None = False
        if exists and os.path.isfile(path):
            if fmt.startswith("json"):
                configured = _json_has_open_design(path, mcp_key)
            elif fmt.startswith("toml"):
                configured = _toml_has_open_design(path)
            else:
                configured = None  # 格式没验过，不猜
        elif exists:
            configured = None  # 是目录，落点未知
        agents[name] = {
            "config": raw_path,
            "format": fmt,
            "mcp_key": mcp_key,
            "installed": exists,
            # None = 无法判定，不要当成「未配」去覆盖客户配置
            "has_open_design": configured,
        }

    launchable = os.path.exists(payload["helper"]) and os.path.exists(payload["daemon_cli"])
    identity = desktop_ctl.resolve_workspace_identity()
    has_bound_projects = identity.get("workspace_id") is not None

    # 版本判据：活着的 daemon 自己报的 /api/health version 最权威，daemon 没
    # 起来时退化用 launcher 解析到的安装版本；都拿不到就是 version_known=False，
    # 按旧版本的保守假设处理（详见上面 docstring 第 4 点）。
    live_port, _ = desktop_ctl.detect()
    live_health = desktop_ctl.probe_health(live_port) if live_port else None
    daemon_version = (live_health or {}).get("version") or payload["version"]
    version_source = (
        "api_health" if live_health and live_health.get("version")
        else "launcher_runtime" if payload["version"]
        else None
    )
    workspace_gap_fixed = desktop_ctl.meets_minimum_version(daemon_version, "0.19.2")
    affected = launchable and has_bound_projects and not workspace_gap_fixed

    return {
        "available": launchable,
        "evidence": {
            "helper": os.path.exists(payload["helper"]),
            "daemon_cli": os.path.exists(payload["daemon_cli"]),
            "resolved_version": payload["version"],
            "resolved_source": payload["source"],
            "ipc_sockets": sockets,
            "agents": agents,
            "workspace_gap": {
                "affected": affected,
                "daemon_version": daemon_version,
                "daemon_version_source": version_source,
                "reason": (
                    "0.18.x 的 MCP sidecar 不附带 workspace header，已绑定的项目"
                    "对 list_projects/get_project/get_file/start_run 等工具不可见"
                    if affected else None
                ),
                "workaround": "改走 HTTP + x-od-workspace-id/x-od-workspace-member-id（见 desktop_ctl.py）"
                if affected else None,
                "fixed_in": (
                    "阈值 0.19.2，实测 2026-08-18：stdio 直连与 Claude Code 长连接"
                    "均验证 list_projects/start_run 已恢复"
                    if workspace_gap_fixed else None
                ),
            },
        },
        "blockers": [] if launchable else ["mcp_sidecar_binary_missing"],
    }


def decide() -> dict[str, Any]:
    routes = {"cli": probe_cli(), "desktop": probe_desktop(), "mcp": probe_mcp()}

    # 优先级来自实测：desktop-mcp 比单纯 desktop 多出 list_agents/list_skills/
    # list_plugins、按 runId 查 get_run 等不受 workspace 门影响的能力；即便是
    # 版本仍卡在 0.18.x、MCP 对已绑定项目的 list_projects/get_project/start_run
    # 还不可用的机器（见 probe_mcp 文档字符串），有它也严格不比没它差；0.19.2+
    # 上这道门本身已经修复，desktop-mcp 更是直接优于单纯 desktop。CLI 在打包
    # 安装的机器上基本用不上（od 不进 PATH）。
    if routes["mcp"]["available"] and routes["desktop"]["available"]:
        route = "desktop-mcp"
    elif routes["desktop"]["available"]:
        route = "desktop"
    elif routes["cli"]["available"]:
        route = "cli"
    else:
        route = "none"

    suggestions: list[str] = []
    if route == "none":
        if not routes["desktop"]["evidence"]["app_bundle"]:
            suggestions.append("装 Open Design 桌面版，或准备 CLI 源码 checkout。")
        else:
            suggestions.append("桌面版已装但 daemon API 不可达：重启 App 即可，数据都在磁盘上。")
    if route in ("desktop", "desktop-mcp"):
        suggestions.append("不要跑 check_env.py / daemon_ctl.py，那是 CLI 路线的检查。")
    agents = routes["mcp"]["evidence"]["agents"]
    missing = [n for n, i in agents.items() if i["installed"] and i["has_open_design"] is False]
    unknown = [n for n, i in agents.items() if i["installed"] and i["has_open_design"] is None]
    if missing:
        suggestions.append(
            "这些 agent 装了但没配 open-design MCP："
            + "、".join(missing)
            + "；用 install_od_mcp.py 补。"
        )
    if unknown:
        suggestions.append(
            "这些 agent 的配置格式还没验证过，装之前必须先打开看："
            + "、".join(unknown)
            + "；不要照 Claude Code 的 JSON 格式硬套。"
        )
    if routes["mcp"]["evidence"]["workspace_gap"]["affected"]:
        version_note = routes["mcp"]["evidence"]["workspace_gap"]["daemon_version"] or "未知"
        suggestions.append(
            f"MCP 已连通，但本机这个 daemon 版本（{version_note}）对已绑定 workspace 的项目 "
            "list_projects/get_project/start_run 等工具不可见（0.18.x 已知的 sidecar 限制，"
            "或版本未知时的保守判断；见 probe_mcp 文档字符串）；要读写既有项目改用 "
            "desktop_ctl.py（自动带 x-od-workspace-id/x-od-workspace-member-id），"
            "MCP 仅对它自己新建、且 App 还没来得及自动绑定的项目短暂可用；"
            "或升级到 0.19.2+，实测这道门已修复。"
        )
    return {"route": route, "routes": routes, "suggestions": suggestions}


def render(result: dict[str, Any]) -> str:
    lines = [f"route = {result['route']}", ""]
    for name, info in result["routes"].items():
        mark = "✓" if info["available"] else "✗"
        lines.append(f"{mark} {name}")
        for key, value in info["evidence"].items():
            if key == "agents":
                for agent, meta in value.items():
                    if not meta["installed"]:
                        continue
                    flag = {True: "已配", False: "未配", None: "格式未验"}[
                        meta["has_open_design"]
                    ]
                    lines.append(f"      {agent:<12} {flag:<6}{meta['config']}")
            elif key == "workspace_gap":
                if value.get("affected"):
                    lines.append(f"      workspace_gap: {value['reason']}")
                    lines.append(f"                     → {value['workaround']}")
                elif value.get("fixed_in"):
                    lines.append(
                        f"      workspace_gap: 未触发（daemon {value.get('daemon_version')}，"
                        f"{value['fixed_in']}）"
                    )
            else:
                lines.append(f"      {key}: {value}")
        if info["blockers"]:
            lines.append(f"      blockers: {', '.join(info['blockers'])}")
    if result["suggestions"]:
        lines.append("")
        for item in result["suggestions"]:
            lines.append(f"- {item}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="判定 Open Design 接入路线")
    parser.add_argument("--json", action="store_true", help="输出 JSON 供上层技能分流")
    args = parser.parse_args()

    result = decide()
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else render(result))
    return 0 if result["route"] != "none" else 1


if __name__ == "__main__":
    raise SystemExit(main())
