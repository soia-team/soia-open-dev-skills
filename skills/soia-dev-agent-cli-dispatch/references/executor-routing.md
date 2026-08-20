# 执行器派发与推荐组合（按需加载）

本文件承载执行器派发决策树、快速查表、推荐组合与自动路由运行机制。主 `SKILL.md` 只保留路由摘要；每次派发时先核对 `supported-agents.yml` 的实际支持状态，再决定执行器。

## 执行器派发决策树

> 模型名称、版本号和档位命名仅供参考，以各 CLI 的 `--version` / `models` / `--help` 实际输出为准。

```
任务类型判断
├── 简单且非破坏性任务（写配置/简单脚本；删除、覆盖等破坏性动作不得归入此类）
│   └── opencode run "..."  或  cd <wt> && kimi --plan -p "..."（kimi ≥0.28 已移除 -w/--print，见 references/kimi-cli.md）
│       详见 references/opencode-qwen-cli.md / references/kimi-cli.md / references/qoder-cli.md
│
├── 中等任务（rsync/build/verify/小范围重构）
│   └── opencode run "..."  或  cd <wt> && kimi -m kimi-k2.6 -y -p "..."
│       详见 references/opencode-qwen-cli.md / references/kimi-cli.md / references/qoder-cli.md
│
├── 经济型编码 / 轻分析（DeepSeek 系按量计费）
│   └── pi -p "..."（非交互必须 -p，否则进 TUI 挂起；详见 references/pi-cli.md）
│       详见 references/pi-cli.md
│
├── DeepSeek 生态显式派发（DeepCode）
│   └── cd <wt> && deepcode -p "$(< "$PROMPT_FILE")"
│       详见 references/deepcode-cli.md；当前仅命令模板验证，不自动路由
│
├── 文档/内容写作
│   ├── 消费者 Google 账号：agy -p "..."（需先确认额度；显式派发）
│   ├── Gemini 企业/API Key/Vertex：gemini -p "..."
│   └── qwen "..." / qwen -m qwen-max "..."
│       详见 references/antigravity-cli.md / references/gemini-cli.md / references/opencode-qwen-cli.md
│
├── 中等复杂度编码 / 快速迭代
│   └── cd <wt> && kimi -m kimi-k2.6 -y --skills-dir <your-skills-dir> -p "..."
│       详见 references/kimi-cli.md
│
├── 复杂代码编辑（常见默认候选）
│   └── codex exec --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check
│       详见 references/codex-cli.md
│
├── 代码审核 / diff review / evidence 验证
│   └── codex exec ...
│       详见 references/codex-cli.md
│
├── 新增/难任务/高风险变更
│   └── codex exec -m <model> -c model_reasoning_effort="high" ...
│       详见 references/codex-cli.md
│
├── 调度 / 代码审查 / 计划拆分 / 复杂推理
│   └── Claude Code — 高阶推理档（thinking=high）
│       适用：派发子 agent / 审 PR / 规划提案 / 复杂 bug 定位
│       详见 references/claude-code-cli.md
│
├── 代码编写 / 中等任务（高阶档节流替代）
│   └── Claude Code — 中阶档
│       适用：UI 编辑 / 文档改写 / 中型重构
│       详见 references/claude-code-cli.md
│
├── 轻量 Edit / Read / Grep（超轻量）
│   └── Claude Code — 轻量档
│       适用：一次性小改 / 快速查阅
│       详见 references/claude-code-cli.md
│
├── 大上下文分析 / 结构化输出
│   ├── 消费者 Google 账号：agy --model "<agy models 显示名>" -p "..."
│   ├── Gemini 非消费者通道：gemini -p "..." --output-format json
│   ├── Gemini 非消费者通道：gemini -p "..." --output-format stream-json
│   └── claude --permission-mode auto --print --output-format json
│       详见 references/antigravity-cli.md / references/gemini-cli.md / references/claude-code-cli.md
│
├── 高隔离分析（沙箱）
│   ├── 消费者 Google 账号：agy --sandbox --mode plan -p "..."
│   └── Gemini 非消费者通道：gemini --sandbox -y -p "..."
│       详见 references/antigravity-cli.md / references/gemini-cli.md
│
└── Qwen 生态编码/评审
    └── qwen / qwen -i / qwen -m qwen-max
        详见 references/opencode-qwen-cli.md
```

## 派发矩阵（快速查表）

| 场景 | 执行器 | 模式 | 详细规则 |
|------|-------|------|---------|
| 简单任务 | opencode / kimi | `run` / `--plan` 确认后 `--print` | `references/opencode-qwen-cli.md` / `references/kimi-cli.md` |
| 简单任务 | qodercli | `--yolo` 或 `--model auto` | `references/qoder-cli.md` |
| 中等任务 | opencode / kimi | `run` / `kimi-k2.6 --thinking --print` | `references/opencode-qwen-cli.md` / `references/kimi-cli.md` |
| 中等任务 | qodercli | `--dangerously-skip-permissions` | `references/qoder-cli.md` |
| 经济型编码 / 轻分析 | pi | `pi -p`（非交互必须加 `-p`） | `references/pi-cli.md` |
| DeepSeek 生态显式派发 | deepcode | `deepcode -p` | `references/deepcode-cli.md`（无结构化模型/usage 证据，不自动路由） |
| 中等复杂度编码 / 快速迭代 | kimi | `--thinking` | `references/kimi-cli.md` |
| Antigravity 消费者账号 | agy | 显式派发；当前不自动选模 | `references/antigravity-cli.md` |
| 文档/内容 | agy（消费者）/ gemini（非消费者）/ qwen | agy 显式运行时显示名 / `gemini -p --yolo` / `qwen-max` | `references/antigravity-cli.md` / `references/gemini-cli.md` / `references/opencode-qwen-cli.md` |
| 复杂代码（常见默认） | codex | high reasoning | `references/codex-cli.md` |
| 代码审核 | codex | high reasoning | `references/codex-cli.md` |
| 新增/高风险 | codex | high reasoning | `references/codex-cli.md` |
| 调度 / 审查 / 规划 / 复杂推理 | Claude Code | 高阶推理档（thinking=high） | `references/claude-code-cli.md` |
| 代码编写 / 中等任务 | Claude Code | 中阶档 | `references/claude-code-cli.md` |
| 轻量 Edit / Read / Grep | Claude Code | 轻量档 | `references/claude-code-cli.md` |
| 大上下文分析 | agy（消费者）/ gemini（非消费者）/ claude | agy 显式派发 / Gemini JSON 或 stream-json | `references/antigravity-cli.md` / `references/gemini-cli.md` / `references/claude-code-cli.md` |
| 高隔离沙箱 | agy（消费者）/ gemini（非消费者） | `agy --sandbox --mode plan -p` / `gemini --sandbox -y -p` | `references/antigravity-cli.md` / `references/gemini-cli.md` |
| headless agent | opencode | `run` / `serve` | `references/opencode-qwen-cli.md` |
| Qwen 栈 | qwen | `qwen` / `qwen -i` | `references/opencode-qwen-cli.md` |

**排除**：`Ollama` 不是编码代理执行器，属于本地模型运行时 / OpenAI-compatible provider，应放在你自己的 provider/runtime 层，不属于本技能的派发范围。

## 推荐组合（部分实证路由）

Codex 6 个型号的 35-case 与 Claude 3 个型号的 15-case 来自 2026-07-10 smoke 聚合记录，但原始 manifest 未随交接提供，且未覆盖 catalog 中全部型号，因此标记 `partial_coverage`；Pi 的 easy 路由来自 2026-08-04 单模型 JSONL 实测。表内推荐只对已覆盖组合有效。Gemini 本轮为 `blocked_auth`，Antigravity 未获准运行付费/额度模型评测，Kimi/OpenCode/Qwen 仍是 `pending_benchmark`。不得把部分实证包装成全量完成，Codex/Claude 证据边界见 `reports/benchmark-2026-07-10.md`，Pi 边界见 `references/pi-cli.md`。

| 执行器家族 | easy 候选 | medium 候选 | hard 候选 | 状态 |
|---|---|---|---|---|
| codex | `gpt-5.6-luna` @ low | `gpt-5.6-terra` @ medium（token 最省，已覆盖组合内实证） | `gpt-5.6-sol` @ high，穷尽才升到 xhigh（已覆盖组合内实证） | `partial_coverage` — 6 个型号有聚合记录，缺全 catalog 覆盖与原始 manifest |
| claude | `claude-haiku-4-5`（比 opus 便宜约 18 倍；未按 effort 拆分数据） | `claude-sonnet-5` @ medium | *(暂无 hard 档实证推荐，见下方反模式警示)* | `partial_coverage` — 3 个型号有聚合记录，缺全 catalog 覆盖与原始 manifest |
| pi | `deepseek-v4-flash` @ low | — | — | `smoke_tested` — Pi 0.83.0 以 `--mode json` 实测模型回显、usage 与 `@prompt-file`；只开放 easy 自动路由 |
| agy | — | — | — | `availability_discovered`（`agy models` 已无 prompt 验证；账号级显示名见 `references/antigravity-cli.md`，但未做真实模型 benchmark，禁止自动路由） |
| gemini | gemini-2.5-flash-lite | gemini-2.5-flash | gemini-2.5-pro / gemini-3.1-pro-preview | `blocked_auth`（2026-07-10 实测：消费者 OAuth 浏览器回调成功后被服务端以弃用策略拒绝；Standard/Enterprise、API Key、Vertex AI 仍是受支持的独立通道，本轮未测） |
| kimi | kimi-k2.6（默认档） | kimi-k2.6 --thinking | kimi-k2.6 --thinking（更长上下文/更多轮次） | `pending_benchmark`（未测） |
| opencode / qwen | 默认模型 | qwen-max 或等效中阶模型 | 项目已配置的最强可用模型 | `pending_benchmark`（未测）；⚠️ 实测本机 opencode 默认模型可能是弱模型（曾见 qwen3-27b），派发前先确认其实际模型配置，客户明确否决弱模型时不得使用 |

### 反模式警示（实证）

- **`claude-opus-4-8` 在简单任务上对 effort 无响应**：同一 fixture 上五档 effort（low/medium/high/xhigh/max）的 output token 数和 cost 完全相同（22 tokens / $0.0677）——五档都被 CLI 接受（非 unsupported），只是没有测量到差异。**这只在本次简单固定算术任务上成立**，难任务未测试，不要泛化成"opus 的 effort 参数整体无用"。因此本表 hard 档没有给 claude 侧推荐。依据：2026-07-10 smoke matrix。
- **`gpt-5.6-luna` 的 `xhigh` 档烧钱不产出**：旧的「同题 8 跑深度调研」对照里，`xhigh` 档烧到 933k tokens（terra 的约 4.6 倍），产出体积却没有相应变大，因此 luna 只推荐 easy 档 + low 效力，不建议升到高档。依据：2026-07-10 同题 8 跑深度调研（见 `reports/benchmark-2026-07-10.md`）。
- **结论：高 effort 是否有回报，取决于「这个模型」和「这个任务难度」两个变量共同作用，不是只看任务难度。** 同一个简单任务上，`claude-sonnet-5` 的 output 随 effort 单调增长（low 22 tokens → max 410 tokens），说明它确实在用 effort 换更多思考；`claude-opus-4-8` 完全不为所动。不要无脑对所有模型都开最高档，先确认该模型在类似任务上是否已有「effort 有效」的实证。依据：2026-07-10 smoke matrix。

## codex 5.6 系实测分级（2026-07-10，同题对照 8 跑）

> 本节收录 2026-07-10 的「同题 8 跑深度调研」数据，回答"深度调研任务上哪个模型/档位物有所值"，与 smoke matrix 的可调用性/回显维度互补。**单任务单日期对照，样本有限**，不是长期基准。

| 模型 | 定位 | 关键实测数据 | 推荐场景 |
|------|------|------|------|
| `gpt-5.6-sol` | 深度审计王 | `xhigh` 档产出最深（行号级锚点、独有交叉校验动作）；`low` 档性价比极高（43 处实证标注 + 抓到真实漂移，耗时 43%）| 架构审查 / 深度调研；日常用 `medium`，重活才上 `xhigh`（996s / 246k tokens）|
| `gpt-5.6-terra` | 实证与成本王 | 全程 token 最省（`medium` 档 87k tokens）；`xhigh` 档"看到 : 推断 = 38 : 1"最克制 | 事实核查 / 状态盘点 / 验证类任务 |
| `gpt-5.6-luna` | 本轮未获独有优势 | 同题无独有发现；`xhigh` 档烧 933k tokens（terra 的 4.6 倍），产出体积却未相应变大 | 重推理任务暂不推荐；定位留待后续创意/发散类任务再评估 |
| `gpt-5.5` | 速度优先 | 最快（190s）；结构完整但发现深度弱 | 轻量摘要 / 快速核查 / 生图（`soia-pkm-cover-image` 后端）|

**强度（reasoning effort）经验**：
- `xhigh` 只对 `sol` 产生质变（更深的行号级锚点 + 独有交叉校验动作）；对 `terra` / `luna` 只是更贵，没有对应的产出质变。
- 默认档位用 `medium`。
- 需要快速核查：`sol@low`（性价比极高）或 `terra@medium`（token 最省、最克制）都可以。

## 自动路由 / Auto-routing

**显式指定始终绝对优先**——本节只在没有显式指定模型/推理深度时才生效。

### 判据（十项，用于把任务落到 easy / medium / hard）

| # | 判据 | easy 倾向 | hard 倾向 |
|---|------|-----------|-----------|
| 1 | 改动文件数 | 1-2 个 | 跨模块多文件 |
| 2 | 是否涉及并发 / 一致性 / 安全边界 | 否 | 是 |
| 3 | 是否需要新增架构决策 | 否，照抄既有模式 | 是，需要设计取舍 |
| 4 | 失败代价 | 可回退、易重试 | 不可逆或对外可见 |
| 5 | 上下文窗口需求 | 单文件 / 局部 | 跨仓库 / 长历史 |
| 6 | 是否需要多轮工具调用相互验证 | 一次编辑即可 | 需要反复读结果再改 |
| 7 | 是否涉及安全 / 权限 / 凭据代码 | 否 | 是 |
| 8 | 任务描述是否已给出精确 before/after | 是 | 否，需要探索式推理 |
| 9 | 是评审 / 证据核验类还是编写类 | 简单核对 | 复杂 diff review 倾向 hard |
| 10 | 预算 / 时间敏感度 | 需要快出结果 | 可以换更长运行时间 |

### 可执行路由与固定回执

确定 easy/medium/hard 后调用 `scripts/route_model.py`；自动路由只选择同时具备 `routing_profile`、`discovered_at`、`discovery_evidence` 和已验证 reasoning levels 的模型。显式指定模型/档位始终优先，但未验证组合必须标记 `explicit_unverified`。

```bash
python3 scripts/route_model.py --executor codex --complexity hard
python3 scripts/route_model.py --executor claude --complexity medium --model claude-sonnet-5 --reasoning high
```

每次路由必须输出 `selected_model`、`selected_reasoning_effort`、`task_complexity`、`selection_reason`、`estimated_cost_range`、`catalog_version` 和 `selection_status`，再把结果写入统一调用契约；没有 verified candidate 时返回阻断状态，不得从 `pending_benchmark` 候选中静默挑一个。

### 与 model-catalog.yml 的关系

`references/model-catalog.yml` 每个模型条目预留了 `routing_profile`、`discovered_at`、`discovery_evidence` 三个字段。P4（2026-07-10）只回填参与 smoke matrix 的真实可调用型号：`gpt-5.6-sol`/`gpt-5.6-terra`/`gpt-5.6-luna`/`claude-sonnet-5`/`claude-opus-4-8`/`claude-haiku-4-5`；未来价格时期只作为同一模型的 `future_pricing`，不得伪装成第二个 model ID。`gpt-5.5`/`gpt-5.4`/`gpt-5.4-mini` 有运行记录但仍缺 reasoning 生效证据，`routing_profile` 保持 `[]`。未参与矩阵的型号保持未知，不得包装成已验证推荐。
