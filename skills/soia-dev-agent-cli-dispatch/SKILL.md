---
name: soia-dev-agent-cli-dispatch
description: 受控调度外部 AI Agent CLI，选择已验证模型、隔离工作目录并回传模型、用量、费用与验证证据。触发：「派活给外部 AI」「调用 DeepCode/Pi/agy」「多 CLI 派发」
dependencies:
  optional: [soia-meta-sync-skills]
version: 1.6.1
created_at: 2026-07-10 11:28:32
updated_at: 2026-09-05 09:07:18
created_by: claude opus 4.6
updated_by: claude (fable 5.1 主控 / anthropic/claude-opus-5 实现，模型名自报未验证)
---

# soia-dev-agent-cli-dispatch

把编码、审查、分析、研究、文档或内容任务交给**外部 AI Agent CLI 进程**，并对工作目录、权限、实际模型、用量、成本和结果质量做统一约束。它不调度宿主内置子代理，也不替代普通的一次性 shell 命令。

## 客户可读说明

### 这个技能可以做什么

| 客户想要 | 技能会做 | 客户能看到 |
|---|---|---|
| 派一个任务给指定 AI CLI | 检查 CLI、认证、工作目录和权限，按该执行器规范启动 | 执行器、请求/实际模型、状态与验证结果 |
| 让系统自动选择模型档位 | 只从已有验证证据的候选中选择；无候选时阻断 | 选择理由、推理档、价格区间与证据状态 |
| 批量或断点执行 | 串行运行 case，逐项原子更新脱敏 manifest | 成功、失败、降级、超时、剩余任务与恢复状态 |
| 查看支持哪些 AI Agent | 读取 `references/supported-agents.yml` | 支持状态、使用方式、自动路由范围和对应规范 |

本技能不会把“进程退出码为 0”直接当成模型或任务质量已验证，也不会在没有证据时开放新的自动路由。

### 客户如何使用

客户至少说明：

1. 要完成的任务和验收标准；
2. 目标项目或工作目录；
3. 指定执行器/模型/推理档，或允许自动选择；
4. 是否允许修改文件、联网、创建 worktree、提交或执行其他高影响动作。

示例请求：

```text
把这个小范围修复派给 Pi，允许改当前项目，不允许提交；运行相关测试并回报实际模型和 Token。
```

### 依赖与安装

- 运行依赖：Python 3，以及本次选择的外部 AI CLI。缺少目标 CLI 时停止，不静默换成另一个执行器。
- 可选依赖：`soia-meta-sync-skills`，仅用于把已安装技能同步到客户明确选择的其他宿主。
- 各 CLI 的认证、模型和套餐由其官方登录态或 provider 配置管理；本技能不代管凭据。

安装整个 dev 插件：

```bash
claude plugin marketplace add soia-team/soia-open-skills
claude plugin install soia-dev@soia
```

只安装本技能：

```bash
npx skills add soia-team/soia-open-dev-skills -g -a '*' -s soia-dev-agent-cli-dispatch -y
```

不要同时维护插件副本和 `~/.agents/skills` 共享副本，以免同名技能漂移。

**WorkBuddy** 的装载单位是角色化专家而不是插件，`npx skills add -a '*'` 覆盖不到它，需要单独安装，见 [docs/install/workbuddy.md](https://github.com/soia-team/soia-open-skills/blob/main/docs/install/workbuddy.md)。

### 配置文件

本技能目录中有两类 YAML，职责不同：

| 文件 | 性质 | 用途 |
|---|---|---|
| `references/supported-agents.yml` | 随技能发布的公共配置 | 支持哪些 AI Agent、适合什么工作、如何调用、验证到什么程度 |
| `assets/config.example.yml` | 私有配置模板 | 配置 host 标识及 state/temp 根目录；复制后由客户持有 |

可选私有配置位置与覆盖变量：

```text
~/.config/soia-skills/soia-dev-agent-cli-dispatch/config.yml
SOIA_DEV_AGENT_CLI_DISPATCH_CONFIG_FILE=<custom-config-path>
```

配置优先级：本次 CLI 参数 → 进程环境 → 私有 `config.yml` → 跨平台默认值。API key、cookie、token、session 不得写进该配置；它们留在 provider 登录态或系统凭据库。

### 私密信息与中间数据

- prompt：写入 OS 临时目录下按 task-id 隔离的目录；任务结束后清理。除非客户明确要求，不把 prompt 长期保存。
- run manifest：默认写入 `<state>/soia-skills/soia-dev-agent-cli-dispatch/runs/<run-id>/manifest.json`。
- manifest 只保存脱敏状态、CLI 版本、请求/实际模型、Token、费用、时间和恢复信息；不保存 prompt、响应正文、凭据、账号或私有绝对路径。
- 平台允许时，state 目录使用 `0700`、manifest 使用 `0600`。默认最多保留 50 个 run；达到上限时阻断新 run，不自动删除。清理前先让客户查看范围并确认。
- 仓库 checkout 不得作为运行时 config、state、cache 或临时目录。

路径解析：

```bash
python3 scripts/resolve_storage.py --json
```

### 日志与完成回执

最终回执固定包含：

```markdown
完成：<本次派发结果>。

调用：
- executor: <外部 AI CLI>
- requested/actual model: <值或 unknown>
- requested/actual reasoning: <值或 unknown>
- status: <passed / failed / blocked / fallback_or_downgrade / actual_model_unverified>

用量与费用：
- input/cache/output/total tokens: <分项值或 unavailable>
- provider-reported / API-equivalent cost: <值、口径或 unavailable>

验证：<实际运行的检查及结果>
状态记录：<泛化 state 位置或“纯 stdout”>
问题与下一步：<阻塞、未验证边界或“无”>
```

不在客户回执中打印凭据、账号、完整响应正文或本机私有绝对路径。

## 触发与边界

命中以下任一场景时使用：

- 明确要求“派给 Codex / Claude / Pi / DeepCode / agy / 其他外部 AI CLI”；
- 需要多 CLI 分工、外部模型路由、额度预检或统一用量回执；
- 需要把长任务放入独立外部进程并可恢复地跟踪。

不要使用：

- 当前宿主直接完成任务，没有外部 AI 进程；
- 只需普通 shell 命令；
- 任务边界、目标工作目录或验收标准仍不明确。

## 输入契约

执行前把请求归一化为：

```yaml
task:
  title: <short-title>
  objective: <observable-result>
  acceptance: [<evidence>]
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

未明确授权的权限保持 `false`。显式指定的执行器、模型和推理档优先；但未验证组合必须标记 `explicit_unverified`，不能包装为自动推荐。
Coordinator、Executor、Verifier、Reviewer、Advisor 的具体模型分工属于调用方项目/用户策略，不由本通用技能写死；派发者必须把该策略作为本次输入，未提供时才按任务复杂度和现有验证证据给出候选。

## 核心流程

### 1. 定义任务与证据

写清目标、输入、允许修改范围、禁区和验收命令。任务拆分按可独立验证的边界进行；每个子任务分配唯一 task ID。

先读取目标仓适用的 `AGENTS.md`、贡献说明和测试约定。目标仓规则优先；不要把本技能自己的历史治理术语或无关文件塞进派发 prompt。

### 2. 选择执行器

1. 读取 `references/supported-agents.yml`，确认 `dispatch_supported`、验证状态和对应 reference。
2. 用户显式指定时按指定值执行，不做静默替换。
3. 用户允许自动路由时，先判定 easy/medium/hard，再运行：

```bash
python3 scripts/route_model.py --executor <agent-id> --complexity <easy|medium|hard>
```

4. 没有 verified candidate 时停止；不得从 `pending_benchmark` 或 `command_help_verified` 条目自动选模。
5. 确定执行器后只加载其 reference；需要路由判据时再加载 `references/executor-routing.md`。

### 3. 执行前预检

- 运行 `command -v <cli>` 和 `<cli> --version`，记录实际版本。
- 使用官方只读状态检查认证/套餐；如果检查本身会调用付费模型，先取得客户确认。
- 检查 workdir 是否存在、是否是凭据/配置目录、是否有未提交改动以及是否与其他任务重叠。
- 不可服务、认证阻断、额度不足或目录不安全时停止并给出明确状态。
- Antigravity 消费者通道与 Gemini 企业/API Key/Vertex 通道必须分开，禁止复制认证状态或静默 alias。

### 4. 建立隔离与权限门

- 每个写任务使用独立 workdir；多任务不得同时写同一文件。
- 创建 `git worktree` 前展示目标路径、分支和用途，并等待客户明确批准；已在当前任务书中明确批准的目标不重复确认。新增、移动、删除或改变 Worktree/分支/目标路径仍须单独批准。
- “覆盖”指替换未知内容、他人改动或授权范围外目标，不包括已授权文件集内的常规补丁编辑。
- 删除、覆盖、提交、push、发布、发送、授权变更及其他远端写入必须单独获得当前任务授权。
- 工作区已有未知改动时不提交、不清理、不覆盖；把冲突范围回报给客户。

### 5. 安全传递 prompt

prompt 必须先写入按 task-id 隔离的 UTF-8 临时文件。不要把不可信正文直接拼进 shell；优先 stdin 或执行器原生文件参数。具体命令、参数终止符和结构化输出方式以选中执行器的 reference 为准。

prompt 只包含：任务目标、必要上下文、目标文件/范围、权限边界、验收命令和回执要求。排除无关仓库、私有路径、凭据和其他任务上下文。

### 6. 派发与监控

- 简短任务前台执行；长任务使用可观察的后台方式并定期检查退出状态、日志摘要和资源信号。
- 多 case 使用 `scripts/run_matrix.py`；每个 case 完成后原子更新 manifest。
- 失败后先分类原因再决定是否重试；同一命令、同一假设不得无变化重复运行。
- 外部 Agent 自报“完成”只是待验证输入，不能直接作为主控结论。

### 7. 验证与收口

1. 比对 `requested_model` 与结构化或可信回显中的 `actual_model`。
2. 缺少实际模型证据时写 `actual_model_unverified`；不以请求值填充实际值。
3. 分开记录 input、cache read/write、output 和 total Token；缺少分项时保持 `unavailable`。
4. provider 报告费用与 API 等价估算分开，订阅套餐不得伪装成真实按 Token 扣费。
5. 在目标 workdir 运行验收命令，并检查真实 diff/产物；退出码与模型回显不能替代任务质量验证。
6. 检查同类问题、未授权改动和残余风险，再输出完成回执。

统一字段、状态机、恢复与 Model Integrity Gate 见 `references/dispatch-contract.md`。

## 证据与状态规则

- manifest 中的 `passed`：执行器成功且模型证据满足该执行器门禁；它不代表任务产物质量已验收。
- 客户回执中的“完成”：除上述调用状态外，还必须由主控独立验证任务产物。
- `fallback_or_downgrade`：实际模型与请求不符。
- `actual_model_unverified`：任务可能有输出，但缺少可信实际模型证据。
- `blocked_*`：认证、额度、权限或付费确认未满足，未执行对应调用。
- `partial_coverage`：只有部分模型/档位或聚合报告，不能声称全矩阵完成。

要声称“全模型 × 全推理档已验证”，必须保留发现快照、完整 case 清单、逐 case manifest、模型回显和聚合报告。

## 按需资源

| 需要 | 资源 |
|---|---|
| 支持哪些 AI Agent、用法和验证状态 | `references/supported-agents.yml` |
| 路由判据与推荐组合 | `references/executor-routing.md` |
| 统一调用字段、状态、派发纪律与恢复规则 | `references/dispatch-contract.md` |
| 单个执行器命令 | `references/supported-agents.yml` 中该 agent 的 `reference` |
| 模型与价格运行时事实源 | `references/model-catalog.yml` |
| 价格目录的带日期来源快照 | `reports/model-pricing-2026-07-10.md` |
| 历史证据边界 | `reports/benchmark-2026-07-10.md` |
| Pi + DeepSeek V4 Flash 实例 | `examples/pi-deepseek-v4-flash-easy.md` |
| Claude 模型 ID 实测快照与 fallback/辅助模型现象 | `reports/claude-model-probe-2026-09-02.md` |
| 重新探测 Claude 实际服务的模型 ID | `scripts/probe_claude_models.py --models <ids>`（真实调用，消耗额度；`--selftest` 只跑 fixture） |
| 私有运行配置模板 | `assets/config.example.yml` |

加载原则：主文件 → 所选执行器 reference，最多一跳；不要一次性加载全部 references。

## 验证

修改本技能后至少运行：

```bash
python3 scripts/resolve_storage.py --selftest
python3 scripts/validate_supported_agents.py --selftest
python3 scripts/catalog_lib.py --selftest
python3 scripts/estimate_cost.py --selftest
python3 scripts/route_model.py --selftest
python3 scripts/run_claude_prompt.py --selftest
python3 scripts/run_matrix.py --selftest
python3 scripts/probe_claude_models.py --selftest
```

复杂行为还要运行一个脱敏的真实前向实例，并核对产物或 manifest 内容，不能只核对退出码。
