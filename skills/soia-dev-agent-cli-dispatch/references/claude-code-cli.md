# Claude Code 执行规范 / Claude Code rules

## 模式选择

- **批处理 / 自动化**：优先 `claude --print`
- **结构化结果**：优先 `--output-format json` 或 `stream-json`
- **权限模式**：默认 `--permission-mode auto`（自动模式：常规操作免确认，危险操作自动回退询问）；`bypassPermissions` 仅在明确接受工作目录改动风险时使用
- **交互式会话**：仅在确需人工连续交互时才直接进入 TUI

## 已实测 ID 表（2026-09-02，CLI 2.1.257）

> ⚠️ **以实时探测为准，但不为每次真实任务单独加一次收费探测。** 下表是一次性快照，不是长期承诺：
> 模型代号随时间变化，可用性还取决于你的账号与套餐；运行时真源是 `references/model-catalog.yml`。
> 每次真实派发本身就产出模型身份证据，但读法有精确边界（见下节「fallback 与辅助模型」及
> `references/dispatch-contract.md` 的 Model Integrity Gate，`scripts/run_matrix.py::detect_claude_model_evidence`
> 是可核对的实现）：`--output-format json` 的 `modelUsage` 先排除 CLI 自身辅助模型
> （`providers.anthropic.auxiliary_models` 前缀匹配），剩余**唯一**一个键才是 `actual_model`，
> 剩 0 个或多于 1 个一律 `actual_model_unverified`；`stream-json` 下可信的事件只有两类——
> `type=system`/`subtype=model_refusal_fallback` 的 `fallback_model`（出现即判
> `fallback_or_downgrade`）与 `assistant.message.model`。同一条流起始的
> `type=system`/`subtype=init` 事件里的 `model` 字段只是**本次请求值的回显**，不是实际身份
> 证据，不得据此判定 `actual_model`（`detect_claude_model_evidence` 对 `type=system` 的事件
> 显式跳过顶层 `model` 字段读取，正是为了避免误读这个字段）。不需要在它之前再调用一次
> `python3 scripts/probe_claude_models.py --models <ids>` 来"预先回显"身份：那是另一次真实付费
> 模型调用，本身不能替代第 3 步的额度门（`quota_observations[]` 仍必须逐桶探测并绑定到本次要用
> 的模型）。识别不到或降级（`unrecognized_model` / `fallback_or_downgrade` /
> `actual_model_unverified`）仍必须在回执里如实写出，不得因为省掉了预先探测就默认"就是请求的模型"。
> `probe_claude_models.py` 留给排查目录是否过期、某个 id 是否仍可服务等场景，不是常规派发前置步骤。

探测方式：`claude -p --model <id> --output-format json`，单轮、无工具、无 MCP、无 settings。

| requested id | rc | 结果 |
|---|---|---|
| `claude-fable-5-1` | 0 | 精确匹配 |
| `claude-fable-5` | 0 | **fallback 到 opus**（见下节） |
| `claude-opus-5` | 0 | 精确匹配 |
| `claude-opus-4-8` | 0 | 精确匹配 |
| `claude-opus-4-7` | 0 | 精确匹配 |
| `claude-opus-4-6` | 0 | 精确匹配 |
| `claude-sonnet-5` | 0 | 精确匹配 |
| `claude-sonnet-4-6` | 0 | 精确匹配 |
| `claude-sonnet-4-8` | 1 | `unrecognized_model` |
| `claude-sonnet-4-7` | 1 | `unrecognized_model` |

本次探测**只**证明"这个 id 能不能被服务"。它不构成任何价格、上下文窗口、推理档或
能力分级证据——prompt 是单词回显。因此不要据此排任务分级；分级仍需按任务类型
单独取证。完整原始摘要见 `reports/claude-model-probe-2026-09-02.md`。

### Claude Opus 5.5 模型证据与订阅成本口径

调用示例：

```bash
claude -p --model claude-opus-5-5 --output-format json
```

2026-09-23 的 JSON 冒烟中，`modelUsage` 的业务模型键为 `claude-opus-5-5`，`canonicalModel` 也为 `claude-opus-5-5`（2026-09-25 在 CLI 2.1.282 上核对：`canonicalModel` 位于 `modelUsage.<模型键>` 之内，不在顶层）；这两项是本次模型身份和可服务证据，不是任务质量证据。按 `modelUsage` 键读取模型身份，并继续应用下方辅助模型剔除规则。

JSON 的 `modelUsage` 键是请求用的别名（如 `claude-haiku-4-5`），而会话文件 `~/.claude/projects/<slug>/<session_id>.jsonl` 中 `assistant.message.model` 记录的是日期版 ID（如 `claude-haiku-4-5-20251001`）；两者比对要经 catalog 的 `actual_model_aliases` 映射，不要通用截断。会话文件里同一次响应可能拆成多条 assistant 记录并重复携带同一 `usage`，直接逐条相加会重复计数；用量以 JSON 输出的 `usage` 或会话末尾 `type=cost-state` 记录为准。`<slug>` 由真实路径生成（macOS 临时目录为 `/private/var/...`）。

订阅登录下，JSON 中的 `costUSD` 或 `total_cost_usd` 若带 `costBasis: list`，表示按官网 API 价计算的等价值，不是订阅账户的实际扣费。回执只能写为“API 等价估算”；只有独立账单证据才能填写实际扣费。

## fallback 与辅助模型

三个现象会让"退出码 0 + 有输出"仍然不等于"用了你要的模型"：

1. **fallback 事件（只有 stream-json 看得见）**：请求 `claude-fable-5` 时，
   `--output-format stream-json --verbose` 的事件流里出现
   `type=system` / `subtype=model_refusal_fallback`，带
   `original_model=claude-fable-5` 与 `fallback_model=claude-opus-4-8`；
   同次 `assistant.message.model` 也是 `claude-opus-4-8`。
   `--output-format json` **不含**该事件，只能从 `modelUsage` 的键与请求不同间接看出。
   技能处理：`run_matrix.py` 见到该事件即判 `fallback_or_downgrade`，
   `actual_model` 取 `fallback_model`。需要可靠模型证据时优先用 `stream-json`。
   注意这是单日单账号单 prompt 的观察，**不能**据此宣称该模型已下线——它 rc=0
   且正常返回；catalog 中它仍是 `available`，但派发必须逐次读 `fallback_model`。
2. **`modelUsage` 多键（辅助模型）**：2026-09-02 的 10/10 次调用的 `modelUsage` 都额外含
   `claude-haiku-4-5-20251001`（CLI 自身的辅助模型），所以"取第一个键"已经失效。
   2026-09-25 在 CLI 2.1.282 上的一次 haiku 调用只出现一个键，说明辅助模型键并非每次都有；
   剔除规则保持不变。
   技能处理：多键时先按 `providers.anthropic.auxiliary_models`（前缀匹配
   `claude-haiku-4-5`）排除，剩余唯一键才作为 `actual_model`；剩 0 个或多于 1 个
   判 `actual_model_unverified`。单键 map 不排除，否则直接派发 haiku 会被误判。
3. **`unrecognized_model`**：不认识的 id 让 CLI 退出码 1，stderr 打印
   `[claude-code:unrecognized_model]` 加一个含 `model`/`query_source` 的 JSON。
   技能处理：判 `unsupported`，并把 stderr 原文写进 `notes`；这类 id 以
   `availability: unrecognized_by_cli` 入 catalog，且不进入任何 `routing_profile`。

## 2026-09-25 版本核对（CLI 2.1.282）

一次 `claude -p --model claude-haiku-4-5 --output-format json` 调用退出码 0；`scripts/run_matrix.py` 的 `parse_usage` 与 `detect_claude_model_evidence` 仍能正确解析（分项用量、`total_cost_usd`、模型键）。

- `usage` 另有 `cache_creation.ephemeral_1h_input_tokens` / `ephemeral_5m_input_tokens` 细分、`output_tokens_details.thinking_tokens`、`service_tier`；`modelUsage.<键>` 另有 `costBasis`、`thinkingTokens`、`contextWindow`。
- 会话 ID 在 JSON 顶层 `session_id`；续接用 `claude -p -r <session_id>`（本次未实测）。
- 参数变化：`--effort` 取 `low|medium|high|xhigh|max`；`--permission-mode` 取 `acceptEdits|auto|bypassPermissions|manual|dontAsk|plan`（`manual` 为新增）；新增 `--permission-prompts host|none`、`--restricted`、`--bare`、`--max-budget-usd`、`--no-session-persistence`、`--session-id <uuid>`、可接列表的 `--fallback-model` 和 `--bg`。`-p`、`--output-format`、`--resume`、`--continue` 不变。
- 这些核对只证明 CLI 形态与解析器可用，不证明任务质量。

## 同宿主派发

当主控**本身**就运行在 Claude Code 里时，派发子任务应当用宿主自己的 Agent 工具，
而不是再起一个 `claude -p` 子进程：后者会重复登录态、丢失宿主上下文，并额外计费。

但要接受一个能力边界：宿主 Agent 工具的 model 参数是**家族别名**
（`sonnet` / `opus` / `haiku` / `fable`），不是具体版本号，宿主也不回显它实际
解析到的版本。因此：

- 回执的 `actual_model` 必须写 `host-routed(<alias>)`，例如 `host-routed(opus)`。
- **不得**把别名脑补成具体版本号（不能写 `claude-opus-5`），也不得把请求值当实际值。
- 需要钉死具体版本时，只能改用 `claude -p --model <id> --output-format stream-json`
  子进程路线，用上一节的证据链验证。
- 这条限制属于 Model Integrity Gate 第 3 条"宿主模型仅可观测、不可控"的具体化。

## 推荐命令模板

### 1. 一次性批处理

```bash
claude --permission-mode auto --print "Summarize the refactor plan for this module"
```

适用：

- 单轮任务。
- 需要避免 PTY/TUI 交互。

### 2. 结构化 JSON 输出

```bash
claude --permission-mode auto --print --output-format json "Review this diff and return findings"
```

### 2.1 从文件安全传入长 prompt（推荐）

```bash
python3 scripts/run_claude_prompt.py \
  --prompt-file <prompt-file> \
  --tools Read,Grep,Glob \
  --model <model-id> \
  --effort high \
  --output-format json
```

脚本通过 stdin 传 prompt，正文不会进入 shell 插值、命令行参数或进程列表；`--permission-mode` 默认 `auto`，可显式覆盖。若不用脚本而把文件内容作为位置参数传给 Claude，必须加参数终止符：

```bash
claude --permission-mode auto --print --output-format json -- \
  "$(< "<prompt-file>")"
```

prompt 可能以 YAML `---` 或单个 `-` 开头；省略 `--` 会被 Claude CLI 当成未知选项。长 prompt 优先使用 stdin 脚本，不用位置参数方案。

### 3. 流式 JSON 输出

```bash
claude --permission-mode auto --print --output-format stream-json "Run the tests and explain failures"
```

### 4. 继续当前目录最近会话

```bash
claude --continue
```

适用：

- 需要在同目录续接最近一次 Claude Code 会话。

### 5. 自定义 subagent 终审（2026-07-11 实测约束）

- `--safe-mode` 会禁用 custom agents；需要 `--agents` 时不得同时使用 safe mode。改在中性工作目录运行，配合 `--setting-sources local`、显式工具白名单和空 MCP。
- 空 MCP 的有效 schema 是 `--mcp-config '{"mcpServers":{}}' --strict-mcp-config`；直接传 `{}` 会在进入模型前报 `Invalid MCP configuration`。
- 先做 capability probe：要求每个自定义 agent 返回不同固定 marker，并使用 `--output-format stream-json --verbose`。只有 stream 中出现对应的 `Agent` tool event、`task_started/task_notification` 和 `resolvedModel` 才算真实运行；主模型口头声称“已调用”不算证据。
- 任一 agent 未真实运行时返回 `blocked_subagent_unverified` / `partial_review`，禁止静默退化成主模型单审。
- `--output-format json` 长任务没有中间 stdout；需要观察 subagent 事件时必须用 `stream-json`，否则只用进程存活与最终 exit code 判断。

## 关键约束

- 默认推荐 `--print`，因为它更适合自动化编排、减少 PTY/TUI 交互开销。
- `--permission-mode auto` 是默认：常规操作免确认，危险操作自动回退询问；`--permission-mode bypassPermissions` 只在你已经明确接受该工作目录的改动风险时使用。
- 若任务只需要分析，不应默认放大到可编辑会话。
- 若要结构化消费输出，必须显式带 `--output-format`。
- 从文件传入 prompt 时优先用 `scripts/run_claude_prompt.py`；不得用缺少 `--` 的 `"$(cat prompt.txt)"` 位置参数写法。
- `--output-format json` 会在长任务结束时一次性返回结果，数分钟无 stdout 不等于卡死。设置足够的 timeout（脚本默认 900 秒），并用进程存活/CPU/最终 exit code 判断，不要仅因暂时无输出重复派发。
- `--tools Read,Grep,Glob` 只限制模型可调用的工具，不能禁用 Claude Code 本机 hooks。hooks 仍可能写会话日志；要求“文件系统零写入”时，应先检查 hooks，在中性工作目录运行，并对调用前后 `git status` 做差分，不能只凭 tool allowlist 声称完全只读。
