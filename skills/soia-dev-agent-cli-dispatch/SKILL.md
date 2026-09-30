---
name: soia-dev-agent-cli-dispatch
description: 派任务给外部 AI CLI 进程并核验模型、额度与产物；宿主内置 subagent 不用本技能。触发：派给 Codex/Pi 等外部 CLI、多 CLI 分工、外部自动选模
dependencies:
  optional: [soia-meta-sync-skills]
version: 2.6.1
created_at: 2026-07-10 11:28:32
updated_at: 2026-09-30 13:14:57
created_by: claude opus 4.6
updated_by: claude opus 5.5
---

# soia-dev-agent-cli-dispatch

把编码、审查、分析、研究、文档或内容任务交给**外部 AI Agent CLI 进程**，统一约束工作目录、权限、实际模型、用量、成本与结果验收。不调度宿主内置子代理，不替代普通 shell 命令；任务边界、工作目录或验收标准还不明确时先补齐再派。

## 客户可读说明

### 这个技能可以做什么

- **派给指定 CLI：** 检查 CLI、认证、工作目录与权限，按该执行器规范启动；回报请求/实际模型、状态与验证结果。
- **自动选模：** 只在本次预检报告里 `available` 且有验证证据的候选桶中选；报告缺失、错绑或畸形时阻断。
- **批量或断点执行：** 串行跑 case，逐项原子更新脱敏 manifest。
- **查支持哪些 CLI：** 读 `references/supported-agents.yml`。

进程退出码 0 不等于模型或任务质量已验证；没有证据不开放新的自动路由。

### 客户如何使用

说明任务与验收标准、目标工作目录、执行器/模型/推理档（或允许自动选择），以及是否允许改文件、联网、建 worktree、提交或其他高影响动作。例：「把这个小修复派给 Pi，允许改当前项目、不许提交；跑相关测试并回报实际模型和 Token。」

### 依赖与安装

运行需要 Python 3 与本次选定的外部 CLI；缺目标 CLI 时停止，不静默换执行器。可选 `soia-meta-sync-skills` 只用于把技能同步到客户选定的其他宿主。各 CLI 的认证、模型与套餐归其官方登录态或 provider 配置，本技能不代管凭据。

单技能 `npx skills add soia-team/soia-open-dev-skills -a <agent> -s soia-dev-agent-cli-dispatch`（`-g` 全局、`-a '*'` 全部 Agent 须客户明确选择）；整域 `claude plugin install soia-dev@soia` 或 `codex plugin add soia-dev@soia`（先接入市场 soia-team/soia-open-skills）。同一宿主同一范围不同时保留插件副本和 skills 目录副本。WorkBuddy 见[专家安装说明](https://github.com/soia-team/soia-open-skills/blob/main/docs/install/workbuddy.md)；完整步骤见[官方安装说明](https://github.com/soia-team/soia-open-skills#安装)。命令不构成安装授权，发现技能缺失也不自动安装。

可选私有配置：模板 `assets/config.example.yml`，位置 `~/.config/soia-skills/soia-dev-agent-cli-dispatch/config.yml` 或 `SOIA_DEV_AGENT_CLI_DISPATCH_CONFIG_FILE`，只放 host 标识与 state/temp 根；优先级为 CLI 参数 → 进程环境 → config → 跨平台默认。API key、cookie、token、session 不进配置。

### 私密信息与中间数据

- prompt 写系统临时目录下按 task-id 隔离的文件，任务结束清理；客户要求才长期保存。
- run manifest 默认写 `<state>/soia-skills/soia-dev-agent-cli-dispatch/runs/<run-id>/manifest.json`；用量记录按需追加到同根的 `usage/records.jsonl`（字段与脱敏见 `references/usage-records.md`）。两者只存脱敏状态、CLI 版本、请求/实际模型、Token、费用、时间与恢复信息，不存 prompt、响应正文、凭据、账号、会话 ID 原值或私有绝对路径。
- 平台允许时 state 目录 `0700`、文件 `0600`。默认最多保留 50 个 run，满了阻断新 run、不自动删除；清理前让客户确认范围。
- 仓库 checkout 不作运行时 config/state/cache/temp。路径解析：`python3 scripts/resolve_storage.py --json`。

### 日志与完成回执

```markdown
完成：<本次派发结果>。

调用：
- executor: <外部 AI CLI>
- requested/actual model: <值或 unknown>
- requested/actual reasoning: <值或 unknown>
- billing_class: <subscription | metered_api | local | unknown>
- status: <passed / failed / blocked / fallback_or_downgrade / actual_model_unverified>

用量与费用：
- input/cache/output/total tokens: <分项值或 unavailable>
- provider-reported / API-equivalent cost: <值、口径或 unavailable>

验证：<实际运行的检查及结果>
状态记录：<泛化 state 位置或“纯 stdout”>
问题与下一步：<阻塞、未验证边界或“无”>
```

回执不打印凭据、账号、完整响应正文或本机私有绝对路径。因技能规则暂停或留下未完成项时，点名实际读到的 `SKILL.md` 与相关原句（链接用客户可访问、不泄露私有目录的形式），说明为何适用、已完成与受阻部分；区分规则要求与派发者推断，只在现有授权确实覆盖不到时补请确认。

## 输入契约

```yaml
task:
  title: <short-title>
  objective: <observable-result>
  acceptance: [<evidence>]
  applicable_skills: []   # 无匹配技能时可为空；只列本任务确实需要的技能
executor: <agent-id-or-auto>
model: <model-id-or-auto>
reasoning: <level-or-auto>
workdir: <project-path>
permissions:
  file_write: false
  network: false
  worktree: false
  commit: false
  remote_write: false
```

未明确授权的权限保持 `false`。显式指定的执行器、模型、推理档优先，但未验证组合标 `explicit_unverified`，不包装成自动推荐。Coordinator/Executor/Verifier/Reviewer/Advisor 的模型分工是调用方策略，作为本次输入传入；未提供时才按复杂度和验证证据给候选。`applicable_skills` 可为 `[]`；已点名的技能必须实际读取，缺失时只阻断依赖它的动作并说明影响。

## 核心流程

### 1. 定义任务与证据

写清目标、输入、可改范围、禁区和验收命令；按可独立验证的边界拆分，每个子任务一个唯一 task ID。复杂或批量派发读 `references/task-brief.md`；接入任务认领系统才读 `references/claim-protocol.md`。遵循目标仓 `AGENTS.md`，不把本技能的治理术语或无关文件塞进 prompt。

### 2. 选执行器（只定 CLI 与任务档，不定模型）

读 `references/supported-agents.yml` 确认 `dispatch_supported`、验证状态与对应 reference，之后只加载选中执行器的 reference。显式指定按指定执行，不静默替换；允许自动路由时按 `references/executor-routing.md` 判 easy/medium/hard。模型留到第 4 步，由预检结果决定。

### 3. 执行前预检（额度观测先于选型）

- `command -v <cli>`、`<cli> --version` 记实际版本。只在用 CLI 默认模型或排查配置覆盖时读其非秘密模型字段，记 `executor_config_default_model`（未读记 `unknown`）；默认值和请求参数都不是实际模型证据。
- 用官方只读状态检查认证/套餐；检查本身会调用付费模型时先取得客户确认。
- **实时额度逐桶探测并绑定模型**，产出 `quota_observations[]`（每项 `bucket`/`model`/`state`/`source`/`probed_at`/`reset_at`）；第 4 步选定后把 `selected_model`、`quota_scope_key`、`recommendation` 回填同一份报告。`auth_status=ok` 只证明凭据有效。可派的必要条件：认证可用，且选定模型那条 observation 为 `available`；选定桶 `exhausted`、`unknown`（含缺失）或 `auth_status != ok` 任一成立即不得 `proceed`。客户批准只覆盖费用与等待偏好，不能把 `unknown`/`exhausted` 改写成可用。字段、取值与探测来源顺序见 `references/dispatch-contract.md`「额度预检」，分桶执行的 CLI 见其 reference（如 `references/codex-cli.md` 额度分桶一节）。
- **dsh 与 `availability: local_only` 条目**不走第 4 步的 `route_model.py`（其 `--executor` 不含 dsh），也不产出 `verified_auto`。云端还是本地只认派发前 `--dump-config` 解出的生效 provider/端点（只读非秘密字段；`--patch` 可能被 `settings.yaml` 覆盖，不作判据）：确认为本地 OpenAI 兼容端点才免额度门，仍须显式指定模型；云端是真实额度桶，必须有调用方提供、官方来源的 `state=available` 余额观测，否则 `hold`。两条分支与模型取证见 `references/dsh-cli.md` 开头。
- 检查 workdir 存在、不是凭据/配置目录、有无未提交改动、是否与其他任务重叠。不可服务、认证阻断、额度不足或目录不安全即停，并给明确状态。
- Antigravity 消费者通道与 Gemini 企业/API Key/Vertex 通道分开，不复制认证状态、不静默 alias。

### 4. 选模型与推理档（消费第 3 步的可用桶）

显式指定按指定执行，不静默替换；自动路由或确认报告里已绑定的选择运行：

```bash
python3 scripts/route_model.py --executor <agent-id> --complexity <easy|medium|hard> \
  --quota-observations <第 3 步预检报告.json> [--model <显式模型>] [--reasoning <档位>]
```

- 预检报告是唯一可用性证据：缺失、错绑、畸形（含旧式裸模型名 `--available-model`）或 `auth_status != ok` 时脚本以 `quota_evidence_missing` / `quota_binding_conflict` / `auth_not_ok` / `quota_evidence_incomplete` 非 0 退出；报告已填 `selected_model`/`quota_scope_key` 时按该绑定确认，不改选别的桶。
- 只在 `state=available` 且观测绑定到候选自己那个桶的 verified candidate 中选；选中桶不可用（含显式指定或报告绑定）写 `quota_unavailable` 并拒绝，不静默换桶。没有可用的 verified candidate 就停；不从 `pending_benchmark` 或 `command_help_verified` 条目自动选，可用但未验证的桶只能显式 `--model` 并记 `explicit_unverified`。
- 把 `selected_model`、`selected_reasoning_effort` 与 `quota_scope_keys`（取授权该模型的 observation 桶名，取不到回退 `executor:model`；同时作 `scripts/run_matrix.py` 的 `quota_scope_key`）写进调用契约。
- 审核角色另传 `--role reviewer --executor-model <实现模型> --independence-policy <different_family|different_model>`。政策来自用户/项目，未指定用 `different_family`；同一实际模型在任何政策下都不自审。路由只验证候选，执行后仍核实际模型；切换政策不放宽额度、认证或权限门。

### 5. 隔离与权限门

- 每个写任务用独立 workdir，多任务不同时写同一文件。
- 建 `git worktree` 前展示目标路径、分支和用途并等客户明确批准；任务书已批准的目标不重复确认，新增、移动、删除或改变 worktree/分支/路径仍须单独批准。
- 删除、覆盖（替换未知内容、他人改动或授权外目标；已授权文件集内的常规补丁不算）、提交、push、发布、发送、授权变更及其他远端写入，各需当前任务授权。
- 工作区已有未知改动时不提交、不清理、不覆盖，把冲突范围回报客户。

### 6. 安全传递 prompt

先写入按 task-id 隔离的 UTF-8 临时文件，经 stdin 或执行器原生文件参数传入，不把不可信正文拼进 shell；具体命令、参数终止符与结构化输出方式以执行器 reference 为准。prompt 只含目标、必要上下文、目标文件/范围、权限边界、验收命令和回执要求。

### 7. 派发与监控

短任务前台跑；长任务用可观察的后台方式定期查退出状态、日志摘要与资源信号，判活与有界等待见 `references/executor-watch.md`。多 case 用 `scripts/run_matrix.py`，每个 case 完成后原子更新 manifest。失败先分类原因再决定重试，同一命令同一假设不无变化重跑。执行器自报「完成」只是待验证输入。

### 8. 验证与收口

1. 比对 `requested_model` 与结构化或可信回显中的 `actual_model`；缺证据写 `actual_model_unverified`，不以请求值代填。
2. Token 分项记 input、cache read/write、output、total，缺项保持 `unavailable`。
3. provider 报告费用与 API 等价估算分开，订阅套餐不伪装成按 Token 扣费。
4. 在目标 workdir 跑验收命令并检查真实 diff/产物；退出码与模型回显不替代任务质量验证。再查同类问题、未授权改动与残余风险，然后出回执。

统一字段、状态机、恢复与 Model Integrity Gate 见 `references/dispatch-contract.md`。

## 证据与状态规则

- manifest 的 `passed`：执行器成功且模型证据满足该执行器门禁；不代表产物质量已验收。
- 客户回执的“完成”：还须主控独立验证任务产物。
- `fallback_or_downgrade`：实际模型与请求不符。
- `actual_model_unverified`：可能有输出，但缺可信实际模型证据。
- `blocked_*`：认证、额度、权限或付费确认未满足，对应调用未执行。
- `partial_coverage`：只有部分模型/档位或聚合报告，不能声称全矩阵完成。要声称“全模型 × 全推理档已验证”，须保留发现快照、完整 case 清单、逐 case manifest、模型回显和聚合报告。

## 按需资源

主文件之外最多再读一跳，只读当前需要的：

| 需要 | 资源 |
|---|---|
| 支持的 CLI、用法、验证状态；单个执行器命令 | `references/supported-agents.yml` 及其中该 agent 的 `reference` |
| 路由判据与推荐组合 | `references/executor-routing.md` |
| 调用字段、状态、派发纪律与恢复规则 | `references/dispatch-contract.md` |
| 任务书模板（含「适用技能」）与正向约束写法 | `references/task-brief.md`、`references/writing-positive-constraints.md` |
| 认领字段与可抓取前沿 | `references/claim-protocol.md` |
| 模型与价格运行时事实源 | `references/model-catalog.yml` |
| 长任务判活、有界等待与退出归类 | `references/executor-watch.md`、`scripts/executor_watch.py` |
| 用量记录、本地聚合与 Jev 推荐输入 | `references/usage-records.md`、`scripts/usage_record.py`、`scripts/usage_aggregate.py` |
| codex 会话 ID、实际模型、用量与续接 | `references/codex-cli.md`「会话取证与续接」、`scripts/codex_session_info.py` |
| dsh 会话模型、子代理与用量取证（会话格式 v3/v4，需系统 `zstd`） | `scripts/dsh_session_usage.py` |
| 重新探测 Claude 实际服务的模型 ID（真实调用、消耗额度） | `scripts/probe_claude_models.py --models <ids>` |
| 按需一次 Jev 类型化判断（不自动派发、不作门禁） | `references/jev-integration.md`、`scripts/jev_check.py` |
| 带日期的价格、基准与模型探测快照 | `reports/`、`examples/`：只作历史证据，不是运行时真源 |

## 维护本技能

普通派发只做上面的预检与产物验收，不跑维护自检。改脚本、路由或额度契约时，跑受影响脚本的 `python3 scripts/<name>.py --selftest`（每个脚本都有）与对应失败夹具；复杂行为再跑一个脱敏真实前向实例，核对产物或 manifest 内容而非只看退出码。仅正文调整核对链接、契约与相关行为。系统无 `zstd` 时 `dsh_session_usage.py --selftest` 打印 `SKIPPED: zstd unavailable` 并以 EC=3 退出，表示夹具未运行，不是通过。仓库 CI 与正式发布门禁照常完整执行。
