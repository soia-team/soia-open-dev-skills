#!/usr/bin/env python3
"""为本机各家 agent 生成 / 安装 Open Design 的 MCP 配置。

存在的理由：Open Design 桌面版把自己暴露成 MCP server，但**装不进客户端 UI**
——Claude 桌面版的 Add custom connector 只接受 Remote MCP server URL，本地
stdio server 加不进去；那个 Connectors 菜单列的也只是托管型连接器。所以只能写
配置文件，而各家 agent 的文件位置和格式互不相同（JSON / TOML / 未知）。

安全边界：改的是客户其它工具的配置，属于有副作用的动作。
- 默认只打印，不落盘；`--apply` 才写。
- 写之前先展示 diff，并把原文件备份成 `<file>.bak-od`。
- 格式没验证过的 agent（workbuddy）一律拒绝自动写，只打印片段让人工处理。
- 不打印任何凭据；本配置本身只含本机路径与标志位，无 token。

用法：
    python3 scripts/install_od_mcp.py                    # 报告现状 + 打印配置
    python3 scripts/install_od_mcp.py --agent codex      # 只看某一家
    python3 scripts/install_od_mcp.py --agent codex --apply   # 真正写入
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import shutil
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import detect_route  # noqa: E402

SERVER_NAME = "open-design"


def build_config(namespace: str) -> dict[str, Any]:
    """推导 MCP server 配置。namespace 必须来自实际探测，不写死。

    0.18.1 实测(2026-08-07)两处不兼容，均已修复：

    1. `command`/`args` 不再是 `/Applications/Open Design.app` 下的固定路径，
       改经 `detect_route._resolved_payload()` 动态解析 launcher 的
       `versions/<version>/payload/` ——版本号随自动升级变化，写死会连到不
       存在或过期的可执行文件（旧配置正是这样连到了空 daemon）。
    2. 新增 `OD_MCP_BOOTSTRAP_COMMAND` / `OD_MCP_BOOTSTRAP_ARGS`：daemon 不可
       达时，sidecar 用它们以 `/usr/bin/open -g -j <launchPath> --args
       --headless` 拉起一个 headless App 自举。`<launchPath>` 读
       launcher 自己的 `install.json`（`_resolved_payload()["launch_path"]`），
       实测它是 launcher 维护的 OS 级启动入口，**不一定等于** `command`/`args`
       指向的 `versions/<version>/payload`——本机实测前者落后于后者一个版本
       （0.18.0 vs 0.18.1），两者必须分别解析，不能相互替代或只解析一个。
       `OD_MCP_BOOTSTRAP_ARGS` 的值本身是一段 JSON 数组文本，用
       `separators=(",", ":")` 生成紧凑形式，与官方已验证可用的配置逐字节一致。
    """
    payload = detect_route._resolved_payload()
    bootstrap_args = json.dumps(
        ["-g", "-j", payload["launch_path"], "--args", "--headless"],
        separators=(",", ":"),
    )
    return {
        "command": payload["helper"],
        "args": [payload["daemon_cli"], "mcp"],
        "env": {
            "OD_DATA_DIR": os.path.join(
                detect_route.desktop_ctl.APP_SUPPORT, "namespaces", namespace, "data"
            ),
            "OD_SIDECAR_IPC_PATH": os.path.join(
                detect_route.IPC_ROOT, namespace, "daemon.sock"
            ),
            "OD_MCP_BOOTSTRAP_COMMAND": "/usr/bin/open",
            "OD_MCP_BOOTSTRAP_ARGS": bootstrap_args,
            "ELECTRON_RUN_AS_NODE": "1",
        },
    }


def pick_namespace(mcp_evidence: dict[str, Any], desktop_evidence: dict[str, Any]) -> str | None:
    """优先选有活 socket 的 namespace；否则退回磁盘上唯一的那个。"""
    for sock in mcp_evidence.get("ipc_sockets") or []:
        parts = sock.split(os.sep)
        if "ipc" in parts:
            index = parts.index("ipc")
            if index + 1 < len(parts):
                return parts[index + 1]
    namespaces = desktop_evidence.get("namespaces") or []
    return namespaces[0] if len(namespaces) == 1 else None


def to_opencode_entry(config: dict[str, Any]) -> dict[str, Any]:
    """opencode 的 MCP 条目是 argv 数组 + type/enabled，且未见 env 字段。

    环境变量改用 `/usr/bin/env K=V ... cmd` 前缀注入——这对任何只接受 argv 数组、
    不支持 env 映射的 agent 都成立，比赌它支持某个未验证的字段安全。
    """
    envs = [f"{key}={value}" for key, value in config["env"].items()]
    return {
        "command": ["/usr/bin/env", *envs, config["command"], *config["args"]],
        "type": "local",
        "enabled": True,
    }


def render_json_snippet(config: dict[str, Any], mcp_key: str, fmt: str) -> str:
    entry = to_opencode_entry(config) if fmt == "json-opencode" else config
    return json.dumps({mcp_key: {SERVER_NAME: entry}}, ensure_ascii=False, indent=2)


def render_toml_snippet(config: dict[str, Any]) -> str:
    def quote(value: str) -> str:
        return json.dumps(value, ensure_ascii=False)

    lines = [
        f"[mcp_servers.{SERVER_NAME}]",
        f"command = {quote(config['command'])}",
        "args = [" + ", ".join(quote(a) for a in config["args"]) + "]",
        "",
        f"[mcp_servers.{SERVER_NAME}.env]",
    ]
    lines += [f"{k} = {quote(v)}" for k, v in config["env"].items()]
    return "\n".join(lines)


def apply_json(path: str, config: dict[str, Any], mcp_key: str, fmt: str) -> tuple[str, str]:
    """返回 (原文, 新文)。保留原有内容，只往该 agent 自己的 MCP 键里加一条。"""
    before = ""
    data: dict[str, Any] = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            before = handle.read()
        data = json.loads(before) if before.strip() else {}
    entry = to_opencode_entry(config) if fmt == "json-opencode" else config
    data.setdefault(mcp_key, {})[SERVER_NAME] = entry
    return before, json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def apply_toml(path: str, config: dict[str, Any]) -> tuple[str, str]:
    """TOML 用追加而非重写：标准库只有 tomllib（只读），重写会丢注释与顺序。"""
    before = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            before = handle.read()
    if f"[mcp_servers.{SERVER_NAME}]" in before:
        return before, before  # 已存在，交给上层判定为无需改动
    tail = "" if before.endswith("\n") or not before else "\n"
    return before, before + tail + "\n" + render_toml_snippet(config) + "\n"


def show_diff(path: str, before: str, after: str) -> None:
    diff = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"{path} (现状)",
        tofile=f"{path} (写入后)",
        n=2,
    )
    body = "".join(diff)
    print(body if body else "  （无变化）")


def main() -> int:
    parser = argparse.ArgumentParser(description="为各家 agent 安装 Open Design MCP")
    parser.add_argument("--agent", help="只处理某一家；默认列出全部")
    parser.add_argument("--apply", action="store_true", help="真正写入（默认只打印）")
    args = parser.parse_args()

    result = detect_route.decide()
    mcp = result["routes"]["mcp"]
    if not mcp["available"]:
        print("Open Design MCP sidecar 不可用：", ", ".join(mcp["blockers"]))
        print("先装 Open Design 桌面版，再运行本脚本。")
        return 1

    namespace = pick_namespace(mcp["evidence"], result["routes"]["desktop"]["evidence"])
    if not namespace:
        print("无法确定 namespace（磁盘上有多个且没有活着的 socket）。")
        print("先启动 Open Design 桌面版，让它建立 IPC socket，再运行本脚本。")
        return 1

    config = build_config(namespace)
    agents = mcp["evidence"]["agents"]
    exit_code = 0

    for name, info in agents.items():
        if args.agent and name != args.agent:
            continue
        if not info["installed"]:
            continue

        path = os.path.expanduser(info["config"])
        print(f"\n══ {name}  ({info['config']}, {info['format']}) ══")

        if info["has_open_design"] is True:
            print("  已配置 open-design，无需改动。")
            continue
        if info["has_open_design"] is None:
            print("  配置格式未经验证，**不自动写入**。先人工确认该 agent 的 MCP 键名与条目结构，")
            print("  再参照下面的值手动添加（键名和字段名很可能不是这个）：")
            print("\n" + render_json_snippet(config, "mcpServers", "json-claude") + "\n")
            exit_code = max(exit_code, 2)
            continue

        fmt = info["format"]
        if fmt.startswith("json"):
            before, after = apply_json(path, config, info["mcp_key"], fmt)
        elif fmt.startswith("toml"):
            before, after = apply_toml(path, config)
        else:
            print("  未知格式，跳过。")
            continue

        if before == after:
            print("  已包含同名配置段，无需改动。")
            continue

        show_diff(path, before, after)
        if not args.apply:
            print(f"  ↑ 预览。确认无误后加 --apply --agent {name} 真正写入。")
            continue

        backup = path + ".bak-od"
        if os.path.exists(path):
            shutil.copy2(path, backup)
            print(f"  已备份 → {backup}")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(after)
        print(f"  已写入 {path}")

    print("\n提示：Claude Code 可用 `claude mcp list` 验证；其它 agent 需重启后生效。")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
