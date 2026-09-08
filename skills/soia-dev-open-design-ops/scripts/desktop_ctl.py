#!/usr/bin/env python3
"""Open Design 桌面版 App 的只读诊断入口。

桌面版每次启动都会换端口，且 UI / daemon / 代理各占一个，靠人肉 lsof 逐个试很费事。
本脚本只做探测与诊断，不改客户数据、不重启 App、不打印任何凭据。

0.18.1 实测(2026-08-07)带来两处不兼容，本文件已按此适配：

1. **launcher 版本化路径**：桌面版可执行文件不再固定在 `/Applications/Open
   Design.app`，而在 `<namespace>/versions/<version>/payload/` 下，`version`
   随自动升级变化。`resolve_launcher_payload()` 优先读 launcher 自己维护的
   `runtime.json`（`active.version`，最权威，不是靠排序猜的），找不到再退化为
   扫描 `versions/` 目录取最大语义版本，最后才回退固定路径（兼容非 launcher
   的旧式安装）。`/Applications/Open Design.app` 本身还在，但它是 launcher 的
   "OS 启动入口"（`install.json.launchPath`），版本可能落后于 `versions/` 下
   真正在跑的那个——实测本机前者 0.18.0、后者 0.18.1，两者不能混用。

2. **workspace 上下文门**：0.18.1 起，已绑定 workspace 的项目在多数
   `/api/projects/*`、`/api/workspaces/*` 路由上必须带 `x-od-workspace-id` /
   `x-od-workspace-member-id` header，否则 400 `WORKSPACE_CONTEXT_REQUIRED`。
   `GET /api/projects`（不带 id）不报错，但只返回**从未绑定过 workspace**的
   项目——本机实测桌面版创建的项目无一例外全部已绑定，所以这条老接口在
   0.18.1 上几乎总是回空数组，不能再当"daemon 死了"或"没有项目"的证据。
   `resolve_workspace_identity()` 只读 `app.sqlite` 推导本机 personal
   workspace 的这两个值；`list_all_projects()` 把未绑定（老接口）与已绑定
   （`/api/workspaces/<id>/projects`，带 header）两份列表合并，尽量给出完整
   结果。判定"daemon 活着"改用 `GET /api/health`（返回 `{"ok":true,
   "version":"..."}`，UI 端口返回 HTML，一眼可辨），不再依赖 `/api/projects`
   的返回形状。

用法：
    python3 scripts/desktop_ctl.py detect      # 找出活着的 daemon API 端口
    python3 scripts/desktop_ctl.py projects    # 列项目（含 entryFile 是否配好）
    python3 scripts/desktop_ctl.py doctor      # 「看不到项目」时的一键体检
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request

APP_SUPPORT = os.path.expanduser("~/Library/Application Support/Open Design")
DEFAULT_NAMESPACE = "release-stable"
DEFAULT_CHANNEL = "stable"
# 旧式（非 launcher）安装，或 launcher 元数据读取失败时的最终回退。
FALLBACK_APP_BUNDLE = "/Applications/Open Design.app"
TIMEOUT = 4


def data_dir(namespace: str = DEFAULT_NAMESPACE) -> str:
    return os.path.join(APP_SUPPORT, "namespaces", namespace, "data")


def _read_json(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _first_dir(root: str) -> str | None:
    try:
        names = sorted(n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n)))
    except OSError:
        return None
    return names[0] if names else None


def version_tuple(version: str) -> tuple[int, ...]:
    """`"0.19.2"` → `(0, 19, 2)`，非数字后缀（如 `-beta`）按 0 处理。公开导出，
    供本文件排序与 `detect_route.py` 的版本判据（`meets_minimum_version()`）共用；
    不要在别处重新手写这段解析。"""
    parts = []
    for chunk in version.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def meets_minimum_version(version: str | None, minimum: str) -> bool:
    """`version` 是否 >= `minimum`（如 `meets_minimum_version("0.19.2", "0.19.2")`
    → `True`）。`version` 为 `None`/空字符串时保守返回 `False`——版本未知不能
    当作"已满足"，调用方应保留旧版本的降级假设。

    存在的理由（2026-08-18 实测）：0.18.1 上 MCP sidecar 的 workspace 门是真实
    限制，但同一套配置在 0.19.2 上已恢复（`list_projects`/`start_run` 对已绑定
    项目正常返回，stdio 直连与 Claude Code 长连接两条路径均验证）。`detect_route.py`
    的 `probe_mcp()` 用这个函数判断当前 daemon 版本是否已经修复，不再对 0.19.2+
    误报 `workspace_gap.affected=true`。判据只认版本号，不认安装时间或猜测。
    """
    if not version:
        return False
    return version_tuple(version) >= version_tuple(minimum)


def _payload_paths(app_bundle: str) -> tuple[str, str]:
    helper = os.path.join(
        app_bundle, "Contents", "Frameworks", "Open Design Helper.app", "Contents", "MacOS",
        "Open Design Helper",
    )
    daemon_cli = os.path.join(
        app_bundle, "Contents", "Resources", "app", "prebundled", "daemon", "daemon-cli.mjs",
    )
    return helper, daemon_cli


def _latest_valid_version(versions_root: str) -> str | None:
    try:
        names = [n for n in os.listdir(versions_root) if os.path.isdir(os.path.join(versions_root, n))]
    except OSError:
        return None
    valid = []
    for name in names:
        _, daemon_cli = _payload_paths(os.path.join(versions_root, name, "payload", "Open Design.app"))
        if os.path.isfile(daemon_cli):
            valid.append(name)
    if not valid:
        return None
    valid.sort(key=version_tuple)
    return valid[-1]


def resolve_launcher_payload(
    channel: str = DEFAULT_CHANNEL, namespace: str = DEFAULT_NAMESPACE
) -> dict:
    """动态解析桌面版 launcher 的版本化 payload 路径。**不缓存**，每次调用重新探测。

    解析顺序（命中即用，全部失败才回退固定路径）：
    1. `<namespace>/runtime.json` 的 `active.version`——launcher 自己维护的
       "当前生效版本" 指针，比自己排序目录名更权威（能区分磁盘上残留的旧版本
       目录和真正在跑的那个，例如升级到一半的中间状态）。
    2. `versions/` 目录下按语义版本排序取最大、且确实包含 `daemon-cli.mjs`
       的目录——`runtime.json` 缺失或读不出版本号时的兜底。
    3. 都失败：回退 `/Applications/Open Design.app`（旧式非 launcher 安装，
       或 launcher 目录结构本身不存在）。

    返回 dict：`app_bundle` / `helper` / `daemon_cli` / `launch_path`
    （`install.json.launchPath`，即 `open -j` 应该打开的 OS 级入口，不一定
    等于上面的 `app_bundle`——本机实测前者落后于后者一个版本）/ `channel` /
    `namespace` / `version`（解析不出时为 None）/ `source`
    （`runtime_json` / `versions_scan` / `fallback_fixed_path`，供上层诊断）。
    """
    channels_root = os.path.join(APP_SUPPORT, "launcher", "channels")
    resolved_channel = channel if os.path.isdir(os.path.join(channels_root, channel)) else (
        _first_dir(channels_root) or channel
    )
    ns_root = os.path.join(channels_root, resolved_channel, "namespaces")
    resolved_namespace = namespace if os.path.isdir(os.path.join(ns_root, namespace)) else (
        _first_dir(ns_root) or namespace
    )
    ns_dir = os.path.join(ns_root, resolved_namespace)

    version: str | None = None
    source: str | None = None
    runtime_meta = _read_json(os.path.join(ns_dir, "runtime.json"))
    if runtime_meta:
        active = runtime_meta.get("active")
        if isinstance(active, dict):
            candidate = active.get("version")
            if isinstance(candidate, str) and candidate.strip():
                version = candidate.strip()
                source = "runtime_json"

    versions_root = os.path.join(ns_dir, "versions")
    if version is None:
        version = _latest_valid_version(versions_root)
        if version:
            source = "versions_scan"

    install_meta = _read_json(os.path.join(ns_dir, "install.json"))
    launch_path = FALLBACK_APP_BUNDLE
    if install_meta:
        candidate = install_meta.get("launchPath")
        if isinstance(candidate, str) and candidate.strip():
            launch_path = candidate.strip()

    if version:
        app_bundle = os.path.join(versions_root, version, "payload", "Open Design.app")
        helper, daemon_cli = _payload_paths(app_bundle)
        if os.path.isfile(daemon_cli):
            return {
                "app_bundle": app_bundle,
                "helper": helper,
                "daemon_cli": daemon_cli,
                "launch_path": launch_path,
                "channel": resolved_channel,
                "namespace": resolved_namespace,
                "version": version,
                "source": source,
            }

    helper, daemon_cli = _payload_paths(FALLBACK_APP_BUNDLE)
    return {
        "app_bundle": FALLBACK_APP_BUNDLE,
        "helper": helper,
        "daemon_cli": daemon_cli,
        "launch_path": launch_path,
        "channel": resolved_channel,
        "namespace": resolved_namespace,
        "version": None,
        "source": "fallback_fixed_path",
    }


def resolve_workspace_identity(namespace: str = DEFAULT_NAMESPACE) -> dict:
    """只读查询本机 `app.sqlite`，推导 personal workspace 的
    `x-od-workspace-id` / `x-od-workspace-member-id`。

    0.18.1 实测(2026-08-07)：这两个值不是凭据、不需要云端登录——本机从未
    连接 Vela 账户的纯本地项目一样会被自动绑定到一个本地生成的 personal
    workspace（`workspace_projects.workspace_id`），且 daemon 默认信任请求
    header 自证的身份（除非显式设置 `OD_WORKSPACE_CONTEXT_SOURCE=vela` 走云端
    校验，桌面版默认不设）。member id 优先取
    `workspace_projects.created_by_workspace_member_id` /
    `updated_by_workspace_member_id`；本机实测这两列在桌面版历史项目上是
    NULL（"unattributed"，daemon 一样接受），这时退回
    `workspace_resources.created_by_workspace_member_id`（同一 workspace 下
    其它资源——如本机装的设计系统——记录的建立者）。

    因人而异，**不写死进任何配置或文档**；每次运行本函数临时读取，用只读
    URI 打开 sqlite，不常驻连接、不写库。失败一律返回软错误（`error` 字段），
    不抛异常，方便上层照常降级为"不带 header"的旧行为。
    """
    db_path = os.path.join(data_dir(namespace), "app.sqlite")
    if not os.path.isfile(db_path):
        return {
            "workspace_id": None, "workspace_member_id": None, "source": None,
            "ambiguous": False, "error": "app_sqlite_not_found",
        }
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=3)
    except sqlite3.Error as exc:
        return {
            "workspace_id": None, "workspace_member_id": None, "source": None,
            "ambiguous": False, "error": f"sqlite_open_failed:{type(exc).__name__}",
        }
    try:
        cur = con.cursor()
        try:
            cur.execute(
                "SELECT DISTINCT workspace_id FROM workspace_projects WHERE workspace_id IS NOT NULL;"
            )
            ws_ids = sorted({row[0] for row in cur.fetchall() if row[0]})
        except sqlite3.Error as exc:
            return {
                "workspace_id": None, "workspace_member_id": None, "source": None,
                "ambiguous": False, "error": f"sqlite_query_failed:{type(exc).__name__}",
            }
        if not ws_ids:
            return {
                "workspace_id": None, "workspace_member_id": None, "source": None,
                "ambiguous": False, "error": "no_bound_projects",
            }
        workspace_id = ws_ids[0]
        member_id: str | None = None
        source: str | None = None
        cur.execute(
            "SELECT created_by_workspace_member_id, updated_by_workspace_member_id "
            "FROM workspace_projects WHERE workspace_id = ? "
            "AND (created_by_workspace_member_id IS NOT NULL "
            "OR updated_by_workspace_member_id IS NOT NULL) LIMIT 1;",
            (workspace_id,),
        )
        row = cur.fetchone()
        if row and (row[0] or row[1]):
            member_id = row[0] or row[1]
            source = "workspace_projects"
        if member_id is None:
            cur.execute(
                "SELECT created_by_workspace_member_id FROM workspace_resources "
                "WHERE workspace_id = ? AND created_by_workspace_member_id IS NOT NULL LIMIT 1;",
                (workspace_id,),
            )
            row = cur.fetchone()
            if row and row[0]:
                member_id = row[0]
                source = "workspace_resources"
    finally:
        con.close()

    return {
        "workspace_id": workspace_id,
        "workspace_member_id": member_id,
        "source": source,
        "ambiguous": len(ws_ids) > 1,
        "error": None if member_id else "member_id_not_found",
    }


def workspace_headers(identity: dict) -> dict[str, str]:
    """把 `resolve_workspace_identity()` 的结果转成可直接传给
    `urllib.request.Request(headers=...)` 的 dict；缺哪个值就整体不带
    （daemon 对"只给一个"的 header 组合判定为 `WORKSPACE_CONTEXT_INCOMPLETE`，
    还不如干脆不带、退化为只看未绑定项目）。"""
    ws_id = identity.get("workspace_id")
    member_id = identity.get("workspace_member_id")
    if not ws_id or not member_id:
        return {}
    return {"x-od-workspace-id": ws_id, "x-od-workspace-member-id": member_id}


def listening_ports() -> list[int]:
    """桌面版进程当前监听的本地端口（去重、有序）。"""
    try:
        out = subprocess.run(
            ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    ports: list[int] = []
    for line in out.splitlines():
        if not re.match(r"^Open", line, re.I):
            continue
        match = re.search(r":(\d+)\s*\(LISTEN\)", line)
        if match:
            port = int(match.group(1))
            if port not in ports:
                ports.append(port)
    return ports


def _get_json(url: str, headers: dict[str, str] | None = None) -> tuple[int | None, object | None]:
    """GET 一个 URL，返回 (http_status, parsed_json)；网络/解析失败给 (None, None)
    或 (status, None)。从不抛异常——调用方按返回值分支，不靠 try/except 控流。"""
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as reply:
            status = getattr(reply, "status", 200)
            body = reply.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace") if exc.fp else ""
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, None
    except (urllib.error.URLError, OSError, TimeoutError):
        return None, None
    try:
        return status, json.loads(body)
    except json.JSONDecodeError:
        return status, None


def probe_health(port: int) -> dict | None:
    """GET /api/health。返回 `{"ok": bool, "version": str}` 或 None（非 daemon
    端口/超时/UI 端口返回的 HTML 解析失败）。

    0.18.1 起这是判定"这是不是一个活的 daemon API 端口"的主判据——
    `/api/projects` 在 workspace 为空/未带 header 时也会返回合法的
    `{"projects":[]}`，不能再用返回值形状区分"死了"还是"活着但看不到东西"。
    """
    status, data = _get_json(f"http://127.0.0.1:{port}/api/health")
    if status != 200 or not isinstance(data, dict):
        return None
    return data if "ok" in data else None


def probe(port: int) -> dict | None:
    """返回 `/api/projects`（不带 workspace header）的 JSON；不是 daemon API
    就返回 None。

    0.18.1 实测：这条老接口只返回**从未绑定过 workspace** 的项目——桌面版
    创建的项目基本都会在打开 App 后不久被自动绑定，所以这里长期返回空数组
    是**正常现象，不代表 daemon 坏了或没有项目**。要看完整列表用
    `list_all_projects()`。保留本函数是为了兼容仍在直接调用它的旧代码
    （如未升级的调用方）。
    """
    status, data = _get_json(f"http://127.0.0.1:{port}/api/projects")
    if status != 200 or not isinstance(data, dict) or "projects" not in data:
        return None
    return data


def probe_workspace_projects(port: int, workspace_id: str, headers: dict[str, str]) -> dict | None:
    """GET /api/workspaces/<workspace_id>/projects，today（0.18.1）能看到
    已绑定 workspace 项目的路由。要求调用方已备好 `x-od-workspace-id` /
    `x-od-workspace-member-id` header（见 `workspace_headers()`），否则 daemon
    返回 400 `WORKSPACE_CONTEXT_REQUIRED`，本函数按"看不到"处理返回 None。
    """
    if not headers:
        return None
    status, data = _get_json(
        f"http://127.0.0.1:{port}/api/workspaces/{workspace_id}/projects", headers=headers
    )
    if status != 200 or not isinstance(data, dict) or "projects" not in data:
        return None
    return data


def project_detail(port: int, project_id: str, headers: dict[str, str] | None = None) -> dict | None:
    """GET /api/projects/<id>，取单个项目详情（含 `resolvedDir`——列表路由不带
    这个字段）。项目已绑定 workspace 时同样需要 header，否则 400。"""
    status, data = _get_json(
        f"http://127.0.0.1:{port}/api/projects/{project_id}", headers=headers or {}
    )
    if status != 200 or not isinstance(data, dict):
        return None
    return data


def list_all_projects(port: int, namespace: str = DEFAULT_NAMESPACE) -> dict:
    """合并「未绑定」（老接口）与「已绑定 workspace」（新接口 + header）两份
    项目列表，尽量给出 0.18.1 上完整的项目视图。

    返回 dict：`projects`（去重合并后的列表，逐项带 `bound` 标记）、
    `identity`（`resolve_workspace_identity()` 的原始结果，供上层判断"为什么
    可能不全"）、`bound_source`（`workspace_endpoint` 命中 / `unresolved`
    身份解析失败或本机压根没有已绑定项目）。
    """
    identity = resolve_workspace_identity(namespace)
    headers = workspace_headers(identity)

    unbound = (probe(port) or {}).get("projects") or []
    by_id: dict[str, dict] = {}
    for item in unbound:
        pid = item.get("id")
        if pid:
            by_id[pid] = {**item, "bound": False}

    bound_source = "unresolved"
    if headers:
        bound_payload = probe_workspace_projects(port, identity["workspace_id"], headers)
        if bound_payload is not None:
            bound_source = "workspace_endpoint"
            for item in bound_payload.get("projects") or []:
                pid = item.get("id")
                if pid:
                    by_id[pid] = {**item, "bound": True}

    return {
        "projects": list(by_id.values()),
        "identity": identity,
        "bound_source": bound_source,
    }


def detect() -> tuple[int | None, list[int]]:
    ports = listening_ports()
    daemon_ports = [p for p in ports if probe_health(p) is not None]
    return (daemon_ports[0] if daemon_ports else None), ports


def orphan_dirs(namespace: str) -> list[str]:
    """磁盘上有目录、但库里没有记录的项目（daemon 建到一半崩溃的残骸）。"""
    projects_dir = os.path.join(data_dir(namespace), "projects")
    if not os.path.isdir(projects_dir):
        return []
    port, _ = detect()
    if port is None:
        return []
    known = {str(item.get("id")) for item in list_all_projects(port, namespace)["projects"]}
    if not known:
        return []
    return sorted(
        name for name in os.listdir(projects_dir)
        if os.path.isdir(os.path.join(projects_dir, name)) and name not in known
    )


def cmd_detect(args: argparse.Namespace) -> int:
    ports = listening_ports()
    daemon_ports = [p for p in ports if probe_health(p) is not None]
    payload = resolve_launcher_payload(namespace=args.namespace)
    print(json.dumps({
        "daemon_api_port": daemon_ports[0] if daemon_ports else None,
        "daemon_api_ports": daemon_ports,
        "listening_ports": ports,
        "data_dir": data_dir(args.namespace),
        "status": "ok" if daemon_ports else "daemon-unreachable",
        "resolved_app": {
            "version": payload["version"],
            "source": payload["source"],
            "channel": payload["channel"],
            "namespace": payload["namespace"],
        },
    }, ensure_ascii=False, indent=1))
    return 0 if daemon_ports else 1


def cmd_projects(args: argparse.Namespace) -> int:
    port, _ = detect()
    if port is None:
        print(json.dumps({"status": "daemon-unreachable",
                          "hint": "重启 Open Design App；数据都在磁盘上，没有丢失"},
                         ensure_ascii=False, indent=1))
        return 1
    result = list_all_projects(port, args.namespace)
    rows = []
    for item in result["projects"]:
        metadata = item.get("metadata") or (item.get("project") or {}).get("metadata") or {}
        rows.append({
            "id": item.get("id"),
            "name": item.get("name"),
            "bound": item.get("bound", False),
            # entryFile 埋在 metadata 里；缺它则项目卡片没有预览
            "entryFile": metadata.get("entryFile"),
            "renders": bool(metadata.get("entryFile")),
        })
    identity = result["identity"]
    note = None
    if result["bound_source"] == "unresolved":
        note = (
            "无法解析本机 workspace 身份（"
            + str(identity.get("error"))
            + "），只列出了从未绑定 workspace 的项目；桌面版创建的项目多数已绑定，"
            "实际项目数可能更多。"
        )
    print(json.dumps({
        "status": "ok", "port": port, "projects": rows,
        **({"note": note} if note else {}),
    }, ensure_ascii=False, indent=1))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    port, ports = detect()
    root = data_dir(args.namespace)
    findings: list[str] = []
    if port is None:
        findings.append(
            "daemon API 没有响应（/api/health 探测全部端口均未通过）：UI 可能还活着，"
            "所以界面能开但项目列表空白。重启 Open Design App 即可，数据都在磁盘上。"
        )
    if not os.path.isdir(root):
        findings.append(f"数据目录不存在：{root}（namespace 是否写对？）")

    result = list_all_projects(port, args.namespace) if port else None
    identity = result["identity"] if result else resolve_workspace_identity(args.namespace)
    if identity.get("error") == "app_sqlite_not_found":
        findings.append("app.sqlite 不存在，无法解析 workspace 身份（App 是否首次启动还没建库？）")
    elif identity.get("error") and identity.get("error") != "no_bound_projects":
        findings.append(f"workspace 身份解析失败：{identity['error']}（已绑定项目会看不到）")
    elif identity.get("ambiguous"):
        findings.append(
            f"发现多个 workspace（{identity.get('workspace_id')} 等），"
            "本脚本只用了第一个，多用户/多账户场景需要人工确认。"
        )

    orphans = orphan_dirs(args.namespace) if port else []
    for name in orphans:
        path = os.path.join(root, "projects", name)
        empty = os.path.isdir(path) and not os.listdir(path)
        findings.append(
            f"孤儿项目目录 {name}（{'空目录，可删' if empty else '有内容，先人工确认再处理'}）"
        )
    missing_entry = []
    if result:
        for item in result["projects"]:
            metadata = item.get("metadata") or (item.get("project") or {}).get("metadata") or {}
            if not metadata.get("entryFile"):
                missing_entry.append(item.get("name"))
    for name in missing_entry:
        findings.append(f"项目「{name}」没有 metadata_json.entryFile，卡片不会有预览")

    print(json.dumps({
        "status": "ok" if port and not findings else "attention",
        "daemon_api_port": port,
        "listening_ports": ports,
        "data_dir": root,
        "logs_dir": os.path.join(APP_SUPPORT, "namespaces", args.namespace, "logs"),
        "workspace_identity_resolved": bool(identity.get("workspace_id") and identity.get("workspace_member_id")),
        "findings": findings or ["未发现问题"],
    }, ensure_ascii=False, indent=1))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Open Design 桌面版只读诊断")
    parser.add_argument("--namespace", default=DEFAULT_NAMESPACE)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("detect", help="找出活着的 daemon API 端口")
    subparsers.add_parser("projects", help="列项目并检查 entryFile")
    subparsers.add_parser("doctor", help="「看不到项目」体检")
    args = parser.parse_args()
    return {"detect": cmd_detect, "projects": cmd_projects, "doctor": cmd_doctor}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
