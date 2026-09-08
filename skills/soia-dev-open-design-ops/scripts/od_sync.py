#!/usr/bin/env python3
"""在 Open Design 项目与客户代码仓之间建立双向契约。

存在的理由：Open Design 的数据目录是桌面版自己的，客户重装、换机或 daemon 出问题
就可能看不到；更要紧的是——**设计稿和生产实现会各自漂移，而没人会发现**。稿子里
写的行内距 10px，实现里可能是 13px，两边都「看起来没错」。

本脚本做两件事：

    archive  把 OD 项目的 pages/ 与 specs/ 归档进仓库，让设计资产进 git
    check    对比稿与实现的 CSS 令牌，把漂移逐条列出来

安全边界：archive 只写客户明确指定的仓库子目录，且写前展示文件清单；
check 是纯只读。两者都不碰 Open Design 的数据目录。

用法：
    python3 scripts/od_sync.py --project <id> --repo <repo-root> --check \\
        --design pages/kid-worksheet.html --impl web/index.html
    python3 scripts/od_sync.py --project <id> --repo <repo-root> --archive
    # 红线词表可选，一行一个正则：
    python3 scripts/od_sync.py ... --check --redlines docs/design/redlines.txt
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import desktop_ctl  # noqa: E402

# --var: value；只取到分号或右花括号，避免把整段 CSS 吞进来
TOKEN_RE = re.compile(r"(--[a-zA-Z0-9_-]+)\s*:\s*([^;}]+)")
ROOT_RE = re.compile(r":root[^{]*\{([^}]*)\}")
# :root 之外出现的裸色值——设计系统通常明令禁止
BARE_COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\([\d.,\s%]+\)")


def project_dir(project: str) -> str | None:
    """按 id 或 name 找项目在磁盘上的目录。

    0.18.1 实测(2026-08-07)：桌面版创建的项目基本都已绑定 workspace，
    `desktop_ctl.probe()`（老接口）看不到它们；改用 `list_all_projects()`
    合并未绑定/已绑定两份列表按 id/name 匹配，再用 `project_detail()`
    （带 workspace header）取 `resolvedDir`——列表路由的返回体里没有这个字段，
    只有单项目详情路由才给。
    """
    port, _ = desktop_ctl.detect()
    if not port:
        return None
    result = desktop_ctl.list_all_projects(port)
    match = next(
        (item for item in result["projects"] if project in (item.get("id"), item.get("name"))),
        None,
    )
    if not match:
        # daemon 完全看不到这个项目（可能确实不存在，也可能 workspace 身份
        # 解析失败导致已绑定项目不可见）——退回按 id 猜磁盘默认布局。
        guess = os.path.join(desktop_ctl.data_dir(), "projects", project)
        return guess if os.path.isdir(guess) else None
    headers = desktop_ctl.workspace_headers(result["identity"]) if match.get("bound") else {}
    detail = desktop_ctl.project_detail(port, match["id"], headers)
    resolved = detail.get("resolvedDir") if detail else None
    if resolved and os.path.isdir(resolved):
        return resolved
    # daemon 不给 resolvedDir 时退回默认布局
    guess = os.path.join(desktop_ctl.data_dir(), "projects", match["id"])
    return guess if os.path.isdir(guess) else None


def read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


def tokens_of(text: str) -> dict[str, str]:
    """只取 :root 块内的令牌定义，组件里的局部覆盖不算。"""
    found: dict[str, str] = {}
    for block in ROOT_RE.findall(text):
        for name, value in TOKEN_RE.findall(block):
            found[name] = " ".join(value.split())
    return found


def bare_colors_outside_root(text: str) -> list[str]:
    stripped = ROOT_RE.sub("", text)
    return sorted(set(BARE_COLOR_RE.findall(stripped)))


def compare_tokens(design: dict[str, str], impl: dict[str, str]) -> dict[str, Any]:
    shared = sorted(set(design) & set(impl))
    same = [k for k in shared if design[k] == impl[k]]
    drift = [
        {"token": k, "design": design[k], "impl": impl[k]} for k in shared if design[k] != impl[k]
    ]
    return {
        "shared": len(shared),
        "same": len(same),
        "drift": drift,
        "design_only": sorted(set(design) - set(impl)),
        "impl_only": sorted(set(impl) - set(design)),
    }


CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
# 行注释：要求 // 前是行首或空白，避免砍掉 https:// 里的双斜杠
LINE_COMMENT_RE = re.compile(r"(?:(?<=^)|(?<=\s))//[^\n]*")


def strip_comments(text: str) -> str:
    """剥离注释后再扫红线。

    不这样做会得到大量假阳性：写得好的代码库会在注释里写明纪律
    （「绝不做完成率排名」「不显示倒计时」），扫描器会把这些**遵守的证据**
    当成违规报出来。实测某单文件应用 5 类命中里 4 类是注释。
    """
    text = CSS_COMMENT_RE.sub(" ", text)
    text = HTML_COMMENT_RE.sub(" ", text)
    return LINE_COMMENT_RE.sub(" ", text)


def scan_redlines(text: str, patterns: list[str]) -> list[dict[str, Any]]:
    """在剥离注释后的正文里扫红线，并带回上下文。

    只给命中的词无法判断真假——必须带上下文让人能一眼看出这是 UI 文案、
    变量名还是资源文件名。剥离注释也只能消掉大部分噪声，JS 字符串内的
    匹配仍需人工确认，所以本函数永远输出上下文而不是裸词。
    """
    body = strip_comments(text)
    hits = []
    for raw in patterns:
        try:
            found = list(re.finditer(raw, body))
        except re.error:
            continue
        if not found:
            continue
        contexts = [
            "…" + body[max(0, m.start() - 40) : m.end() + 30].replace("\n", " ").strip() + "…"
            for m in found[:3]
        ]
        hits.append({"pattern": raw, "count": len(found), "contexts": contexts})
    return hits


def cmd_archive(src: str, repo: str, dry: bool) -> int:
    dest_root = os.path.join(repo, "docs", "design")
    planned: list[tuple[str, str]] = []
    for sub in ("pages", "specs"):
        src_dir = os.path.join(src, sub)
        if not os.path.isdir(src_dir):
            continue
        for name in sorted(os.listdir(src_dir)):
            if name.endswith(".artifact.json"):
                continue  # OD 内部元数据，不进仓库
            planned.append(
                (os.path.join(src_dir, name), os.path.join(dest_root, sub, name))
            )
    entry = os.path.join(src, "index.html")
    if os.path.isfile(entry):
        planned.append((entry, os.path.join(dest_root, "index.html")))

    if not planned:
        print("没有可归档的文件。")
        return 1

    print(f"归档目标：{dest_root}")
    for source, target in planned:
        state = "覆盖" if os.path.exists(target) else "新建"
        print(f"  [{state}] {os.path.relpath(target, repo)}   ← {os.path.basename(source)}")
    if dry:
        print("\n↑ 预览。确认后加 --apply 真正写入。")
        return 0
    for source, target in planned:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(source, target)
    print(f"\n已归档 {len(planned)} 个文件。记得 git add 后提交。")
    return 0


def cmd_check(design_path: str, impl_path: str, redlines: list[str]) -> int:
    design_text, impl_text = read(design_path), read(impl_path)
    result = compare_tokens(tokens_of(design_text), tokens_of(impl_text))

    print(f"稿   {design_path}")
    print(f"实现 {impl_path}\n")

    total = result["shared"]
    print(f"{'✓' if not result['drift'] else '✗'} 令牌：{result['same']}/{total} 一致")
    for item in result["drift"]:
        print(f"      {item['token']}: 稿 {item['design']} / 实现 {item['impl']}")
    if result["design_only"]:
        print(f"      稿里有、实现没有：{', '.join(result['design_only'][:8])}")
    if result["impl_only"]:
        print(f"      实现有、稿里没有：{', '.join(result['impl_only'][:8])}")

    for label, text in (("稿", design_text), ("实现", impl_text)):
        bare = bare_colors_outside_root(text)
        mark = "✓" if not bare else "✗"
        print(f"{mark} {label}的 :root 外裸色值：{len(bare)} 处" + (f"  {bare[:5]}" if bare else ""))

    if redlines:
        hits = scan_redlines(impl_text, redlines)
        print(f"{'✓' if not hits else '✗'} 红线：{len(hits)} 类命中（已剥离注释）")
        for hit in hits:
            print(f"      /{hit['pattern']}/ ×{hit['count']}")
            for ctx in hit["contexts"]:
                print(f"        {ctx}")
        if hits:
            print("      ↑ 上下文需人工判定：UI 文案才算违规，变量名/资源文件名不算。")
    else:
        print("- 红线：未提供词表（--redlines），跳过")

    # 有漂移就非零退出，方便挂进 CI
    return 1 if result["drift"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Open Design ↔ 代码仓 双向契约")
    parser.add_argument("--project", help="Open Design 项目 id 或名称")
    parser.add_argument("--repo", help="客户代码仓根目录")
    parser.add_argument("--archive", action="store_true", help="归档 OD 产物进仓库")
    parser.add_argument("--apply", action="store_true", help="归档时真正写入（默认预览）")
    parser.add_argument("--check", action="store_true", help="对比稿与实现")
    parser.add_argument("--design", help="稿文件（相对 OD 项目目录，或绝对路径）")
    parser.add_argument("--impl", help="实现文件（相对 repo，或绝对路径）")
    parser.add_argument("--redlines", help="红线正则表，一行一个")
    args = parser.parse_args()

    if not (args.archive or args.check):
        parser.error("至少选一个：--archive 或 --check")

    src = project_dir(args.project) if args.project else None
    if args.project and not src:
        print(f"找不到项目 {args.project}——Open Design 桌面版没在跑，或项目 id 不对。")
        return 1

    if args.archive:
        if not args.repo:
            parser.error("--archive 需要 --repo")
        return cmd_archive(src, args.repo, dry=not args.apply)

    if not args.design or not args.impl:
        parser.error("--check 需要 --design 和 --impl")
    design_path = args.design if os.path.isabs(args.design) else os.path.join(src or "", args.design)
    impl_path = args.impl if os.path.isabs(args.impl) else os.path.join(args.repo or "", args.impl)
    for path in (design_path, impl_path):
        if not os.path.isfile(path):
            print(f"找不到文件：{path}")
            return 1
    patterns: list[str] = []
    if args.redlines and os.path.isfile(args.redlines):
        patterns = [
            line.strip()
            for line in read(args.redlines).splitlines()
            if line.strip() and not line.startswith("#")
        ]
    return cmd_check(design_path, impl_path, patterns)


if __name__ == "__main__":
    raise SystemExit(main())
