---
name: soia-dev-github-ops
description: GitHub gh CLI 运维、PR 合规审查与修复。触发：「查 CI 挂了」「发 release」「加协作者权限」
version: 2.2.0
created_at: 2026-07-09 07:45:34
updated_at: 2026-09-08 16:25:00
created_by: claude opus 4.6
updated_by: gpt-5
dependencies:
  optional: [soia-dev-review-code, soia-dev-implement-task]
---

# soia-dev-github-ops

Use this skill when the user asks to inspect or operate GitHub state: issues,
pull requests, checks, reviews, workflow run logs, labels, releases, or PR
lifecycle actions.

Do not use it for local-only git work such as commits, rebases, branch cleanup,
or worktree management unless a GitHub operation is also required.

## 客户可读说明

### 这个技能可以做什么

Use gh CLI for GitHub issue, PR, checks, review, workflow run, release, and collaborator-permission operations, plus a pre-merge rule-review procedure and an author-side "address a review and fix it" procedure, with structured JSON output and safety gates

| 客户想要 | 技能会做 | 客户能看到 |
|---|---|---|
| 完成本技能覆盖的工作 | 读取用户请求、必要上下文和本技能正文流程，执行最小可靠步骤 | 客户会看到执行计划、命令输出摘要、代码/文档变更、验证结果和风险说明。 |
| 给某个人加/查/撤仓库协作者权限 | 先确认目标仓库、用户名、权限级别，再执行 `gh api` 写操作并核实生效 | 权限级别说明、确认清单、生效核实结果 |
| 合并前想知道这个 PR 符不符合规则 | 拉 diff + 这个仓库自己的规则文件，交叉核对后给分档建议；不自动合并 | 一句话结论、按阻断/应改/无异议分档的发现清单、CI 与 mergeable 状态 |
| 收到评审意见（贴 PR/评审 URL 说"帮我修复"）| 拉取评审（含行内 + 会话评论）→ 确认分支 → implement-task 逐条修；push 和请求重审分别按授权执行，不自动合并 | 每条意见的处理状态、验证证据、已授权远端操作结果 |
| 缺少依赖、权限、配置或 key | 停止需要外部状态的动作，明确指出缺什么 | 安装命令、申请地址、配置路径或需要客户确认的问题 |
| 执行完成 | 汇总成功、跳过、失败、文件变更和验证结果 | 一段可复制进工单/日志的完成回执 |

### 客户如何使用

1. 用自然语言说明目标，并提供必要输入：文件、URL、repo、workspace、proposal、vault 或平台账号状态。
2. 能 dry-run 或预览的动作先给预览；涉及删除、覆盖、发送、发布、写远端状态时先征求客户确认。

### 依赖与安装

默认按项目、明确宿主、单技能安装；整域仅在客户明确选择后使用。安装与发布单独确认，见[官方安装说明](https://github.com/soia-team/soia-open-skills#安装)。

普通 GitHub 查询和平台操作无需加载实现或审查技能；进入对应分支时才按需使用 `soia-dev-review-code` 或 `soia-dev-implement-task`。缺失只暂停该分支，报告所缺依赖，不自动安装。

客户已选择整域插件时：

```bash
claude plugin marketplace add soia-team/soia-open-skills
```

```bash
claude plugin install soia-dev@soia
```

只要这一个技能时，可用 npx 路线。注意技能会落进共享真源 `~/.agents/skills`；若同时装了插件，同一技能会出现两份索引且各自漂移，建议二选一：

```bash
npx skills add soia-team/soia-open-dev-skills -g -a '*' -s soia-dev-github-ops -y
```

复制 [`assets/config.example.yml`](assets/config.example.yml) 后按需填写非秘密默认值。配置约定：

```text
~/.config/soia-skills/soia-dev-github-ops/config.yml
SOIA_DEV_GITHUB_OPS_CONFIG_FILE=<custom-config-path>
```

- 如果本技能不需要私有配置，可以不创建 `config.yml`。
- 普通 `config.yml` 只保存非秘密默认值，例如仓库名或 profile 指针。GitHub token、cookie 和 session 必须留在 `gh auth login` 管理的官方凭据存储或系统凭据库，不能写进配置、仓库、正文或日志。
- 第三方 skill 只能声明依赖和安装方式，不直接修改第三方 skill 文件。

**WorkBuddy** 的装载单位是角色化专家而不是插件，`npx skills add -a '*'` 覆盖不到它，需要单独安装，见 [docs/install/workbuddy.md](https://github.com/soia-team/soia-open-skills/blob/main/docs/install/workbuddy.md)。

### 私密信息与中间数据

- `gh` 查询结果可能包含私有仓库名、issue/PR 正文、成员信息和日志；只读取本次操作所需字段，默认通过结构化 stdout 处理，不持久保存完整响应。
- GitHub 凭据只由 `gh auth login` 的官方存储或系统凭据库管理；不得把 token、cookie、session、完整认证输出或秘密环境变量写入普通配置、命令参数、issue、PR、评论或日志。
- 远端 issue、PR、review、release 和权限是 GitHub 产品状态，不是本技能私有缓存；任何创建或修改都按 Safety Model 取得授权并在完成后查询远端复核。
- 本技能默认不创建本地 state 或 cache。客户明确要求导出报告时写入其指定路径；临时响应放操作系统临时目录并在任务结束后清理。
- 回执只记录 repo、对象编号、状态、URL 和必要错误摘要；私有正文、协作者信息和日志内容按最小披露原则脱敏。

### 日志与完成回执

每次执行都要让客户看见过程和结果。最低回执格式：

```markdown
完成：<一句话说明本次完成了什么>。

日志摘要：
- started: <检查到的输入/配置/依赖，不打印秘密值>
- processed: <数量或范围>
- created/updated: <数量或路径>
- skipped/failed: <数量和原因>

文件变化：
- <绝对路径或“未改动文件”>

验证：
- <运行过的检查、命令或人工核对点>

问题与下一步：
- <缺 key / 缺依赖 / 需要客户确认 / 建议下一条命令；没有则写“无”>
```

## Safety Model

- Read-only `gh` queries may run once the target repo is known.
- Mutating operations require clear user intent in the current request.
- High-impact operations require an explicit final confirmation before running:
  `gh pr merge`, `gh release create`, branch deletion, label deletion, workflow
  dispatch against production, granting/revoking a collaborator's permission,
  or any action that closes public work or changes who can write to a repo.
- Collaborator permission changes are the single most sensitive operation this
  skill performs — more sensitive than `gh pr merge`. A bad merge affects one
  change; a wrong permission grant is a standing capability the person keeps
  using until someone notices and revokes it. Never infer the target repo,
  username, or permission level from prior conversation turns alone — restate
  all three and get explicit confirmation in the current exchange before the
  write call. See "Collaborator Access Management" below for the full gate.
- Use `gh auth status` before operations. If auth is missing or expired, stop
  and tell the user what needs to be configured.
- Never put GitHub tokens in `SKILL.md`, shell history, scripts, issue bodies,
  PR bodies, or comments. Use `gh auth login` for credentials; keep only non-token
  defaults in the skill-specific private config.

## Repo Resolution

Resolve the target repository in this order:

1. Explicit command argument: `--repo <owner>/<repo>`.
2. Current git remote if the command runs inside a GitHub checkout.
3. Environment variable: `GITHUB_REPOSITORY=<owner>/<repo>`.
4. Optional private config: `~/.config/soia-skills/soia-dev-github-ops/config.yml`.
5. Ask the user if the repo is still ambiguous.

The optional config file is a user-owned YAML file with an `env:` mapping, for example:

```yaml
env:
  GITHUB_REPOSITORY: "<owner>/<repo>"
```

Do not hardcode maintainer-specific repositories in reusable commands.

## Query Patterns

Prefer `--json` and `--jq` for agent-readable output.

```bash
# Auth and repo sanity checks
gh auth status
gh repo view --json nameWithOwner,defaultBranchRef,isPrivate

# Open PRs
gh pr list --repo <owner>/<repo> --state open \
  --json number,title,state,author,headRefName,baseRefName,updatedAt

# Single PR status
gh pr view <number> --repo <owner>/<repo> \
  --json number,title,state,mergeable,mergeStateStatus,reviewDecision,headRefName,baseRefName

# PR checks
gh pr checks <number> --repo <owner>/<repo> \
  --json name,state,bucket,startedAt,completedAt,link

# Issues
gh issue list --repo <owner>/<repo> --state open \
  --json number,title,state,labels,assignees,updatedAt

# Workflow runs
gh run list --repo <owner>/<repo> --limit 20 \
  --json databaseId,status,conclusion,workflowName,headBranch,createdAt,url
```

When reporting results, include:

- repo: `<owner>/<repo>`
- object: PR / issue / run / release
- identifier: number, run id, or tag
- status: open / closed / merged / passing / failing / cancelled
- next action or blocker

## PR Lifecycle

Create PRs with a concise body containing summary and verification evidence.

```bash
gh pr create --repo <owner>/<repo> \
  --base <base-branch> \
  --head <feature-branch> \
  --title "<type>: <short change>" \
  --body "$(cat <<'EOF'
## Summary
- <what changed>

## Verification
- <command>: <result>
EOF
)"
```

Review operations:

```bash
gh pr review <number> --repo <owner>/<repo> --approve --body "<review note>"
gh pr review <number> --repo <owner>/<repo> --request-changes --body "<required changes>"
gh pr comment <number> --repo <owner>/<repo> --body "<comment>"
```

Before merge:

```bash
gh pr view <number> --repo <owner>/<repo> \
  --json mergeable,mergeStateStatus,reviewDecision,statusCheckRollup \
  --jq '{mergeable, mergeStateStatus, reviewDecision, checks: .statusCheckRollup}'
```

Only merge after explicit confirmation:

```bash
gh pr merge <number> --repo <owner>/<repo> --squash --delete-branch
```

## CI Failure Triage

Use this order:

1. Identify the failing run and job.
2. Read the first actionable error in the failed log.
3. Classify the failure.
4. Reproduce locally only if the repo has enough context and the command is safe.
5. Report the exact failing command, file, or external blocker.

```bash
gh run view <run-id> --repo <owner>/<repo> --json status,conclusion,workflowName,jobs,url
gh run view <run-id> --repo <owner>/<repo> --log-failed
```

Common classes:

| Class | Signal | Next step |
|---|---|---|
| Compile | compiler, typecheck, or lint error | Read the first error and map to file/line |
| Test | assertion failure or failing test name | Reproduce that test locally if possible |
| Environment | missing tool, package, or cache | Check setup steps and runner image |
| Permission | `Resource not accessible` or denied secret | Check workflow permissions and fork context |
| Quota/timeout | quota message or cancelled after timeout | Report external limit or split work |

## Release Operations

Release creation is a publish action. Prepare the command, show the tag/name/body
summary, and ask for explicit confirmation before running:

```bash
gh release create <tag> --repo <owner>/<repo> \
  --title "<release title>" \
  --notes-file <notes-file>
```

After release, verify:

```bash
gh release view <tag> --repo <owner>/<repo> \
  --json tagName,name,isDraft,isPrerelease,publishedAt,url
```

## Output Checklist

Before final response:

- State the resolved repo and how it was resolved.
- Separate facts from inference when summarizing failures.
- Include exact PR/issue/run/release identifiers.
- For mutating operations, say what changed and include the resulting URL or id.
- For blocked auth or permission, say which `gh` command failed and what the user
  must configure.

## 真实前向验收

对已知仓库中的真实对象执行只读查询，并核对输出内容而不只看退出码：

```bash
gh pr view <number> --repo <owner>/<repo> \
  --json number,state,mergeable,baseRefName,headRefName,url
```

验收至少确认：编号与目标一致、URL 属于目标仓库、base/head 分支符合请求、状态字段可解释，且输出不含 token 或认证详情。对不存在的编号补一条预期失败检查，确认错误没有被包装成成功。

写操作仅在客户明确授权后测试；完成后必须用独立的只读 `gh view`/`gh api GET` 查询远端对象，逐字段核对预期状态。权限变更还要按协作者手册复查实际 role，release 要复查 tag、draft/prerelease 和发布时间，不能把写命令退出 0 当作验收。

## 分流程手册

以下流程互斥，一次任务只会走其中一条；按需读取对应文件即可。

- **Pre-Merge Rule Review** — [pre-merge-rule-review.md](references/pre-merge-rule-review.md)
- **Address Review Feedback (author side)** — [address-review-feedback.md](references/address-review-feedback.md)
- **Collaborator Access Management** — [collaborator-access.md](references/collaborator-access.md)
