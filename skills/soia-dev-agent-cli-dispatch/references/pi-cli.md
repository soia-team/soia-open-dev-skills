# Pi 执行规范 / pi (pi-coding-agent) rules

> 实际命令是 `pi`（npm 包 `@earendil-works/pi-coding-agent`）。非交互执行必须加 `-p/--print`，否则进入交互式 TUI 等待输入。

## 模式选择

- **非交互单轮执行**：`pi -p ...`，处理 prompt 后退出。
- **结构化证据**：派发与矩阵验收使用 `--mode json`；最终 `message_end` 提供实际 `provider`、`model` 和 `usage`。
- **指定模型**：同时传 `--provider <provider>` 与 `--model <model>`，避免同名模型或用户默认配置造成歧义。
- **控制推理深度**：`--thinking <level>`，实际支持值以 `pi --help` 和模型目录为准。
- **限制工具面**：`--no-tools`（纯文本回答）或 `--tools read,bash,...`（白名单）。
- **隔离会话**：一次性派发使用 `--no-session`，不污染主会话历史。

## 推荐命令模板

先把 prompt 写入按 task-id 隔离的 UTF-8 文件。Pi 原生支持 `@file` 参数，应传文件路径而不是把正文展开进 shell argv：

```bash
prompt_file="${TMPDIR:-/tmp}/soia-dev-agent-cli-dispatch/<task-id>/prompt.txt"
mkdir -p "$(dirname "$prompt_file")"
cat > "$prompt_file" <<'PROMPT_EOF'
你的 prompt 内容，可以包含引号、`---` 和其他特殊字符。
PROMPT_EOF
```

### 1. 标准受控执行

```bash
command -v pi >/dev/null || { echo "CLI missing: pi" >&2; exit 9; }
cd <project-path>
pi -p --mode json --no-session "@$prompt_file"
```

### 2. 固定 Provider、模型与推理深度

```bash
cd <project-path>
pi -p --mode json --no-session \
  --provider deepseek \
  --model deepseek-v4-flash \
  --thinking low \
  "@$prompt_file"
```

### 3. 纯文本任务，不开放工具

```bash
cd <project-path>
pi -p --mode json --no-session --no-tools \
  --provider deepseek \
  --model deepseek-v4-flash \
  --thinking low \
  "@$prompt_file"
```

## Model Integrity 与用量证据

- `exit 0` 只表示进程成功结束，不足以证明实际模型正确。
- `scripts/run_matrix.py` 只在 Pi JSONL 最终 assistant `message_end` 中取得 `message.model` 后验证模型；文本模式缺少该证据，状态必须是 `actual_model_unverified`。
- JSONL `usage` 中的 `input`、`cacheRead`、`cacheWrite`、`output`、`totalTokens` 和 `cost.total` 分别记录，不把总 token 冒充 output token。
- 请求模型可以写成 `deepseek-flash` 或 provider-qualified 形式；实际回显按 `message.model` 的模型叶子名比较。

## 当前验证边界

### `deepseek-flash`（DeepSeek V4.1 Flash）：当前 easy 自动路由

provider 元数据（pi 0.85.1 于 2026-09-11 从 `api.deepseek.com` 同步）声明
`deepseek-flash` 的 thinking 档位映射为 `low`/`high`/`max`（无 `minimal`/`medium`）、
输入模态 text+image、context 1M、max output 384K，USD/1M 价格为 input 0.30 /
cache-hit 0.006 / output 1.20、cache write 0。

运行证据与边界：

- 2026-09-10 的 SoiaDeck pi 会话在 `--thinking high` 下，每次 assistant `message_end`
  回显 `provider=deepseek`、`model=deepseek-flash`，结构化 usage 可解析（例：input 197 /
  cacheRead 32256 / output 334 / reasoning 172 / total 32787），订阅口径 `cost.total=0`；
- 2026-09-11 的 pi 最小验证同样回显 `actual_model=deepseek-flash`，该次档位未单独留档；
- 同日 dsh headless 用 `deepseek-flash` 完成四个真实编码/文档任务（11 文件/1520 行、
  17 文件主机页、W-C.1 收尾、0.17.7 补测批），产物全部过门禁并入主干；dsh 没有模型回显
  实现，这部分只能算任务产物证据，不能单独支撑 `actual_model`。

`references/model-catalog.yml` 以 `supported_reasoning_levels: [low, high, max]` +
`reasoning_levels_confidence: smoke_tested` + `routing_profile: [easy]` 记录：只有 `high`
有逐次 JSONL 回显，`low`/`max` 属 provider 声明级，easy 自动路由落在 `low`。
medium/hard、image-input、逐档 JSONL 记录与全任务类型质量仍未验证，不得扩张为 `verified`。
完整证据边界见 `reports/deepseek-flash-verification-2026-09-11.md`。

### `deepseek-v4-flash`：历史 easy 路由（id 已于 2026-09-11 下线）

该 id 已退役，请求被路由到 `deepseek-flash`（V4.1 Flash）并按 Flash 价计费；以下
2026-08-04 证据仅作历史边界保留，新派发请使用 `deepseek-flash`：

- `deepseek/deepseek-v4-flash` + `--thinking low` 能通过 `@prompt-file` 完成非交互调用；
- `--mode json` 的 assistant `message_end` 回显 `provider=deepseek`、`model=deepseek-v4-flash` 与结构化 usage；
- 该证据只支持 easy 自动路由。medium/hard、其他 thinking 档和 `deepseek-v4-pro` 未测试，不得自动扩张为已验证支持。

### `deepseek-v4-flash-vision-exp`：DSH UI 观察与 Pi 低档文本证据（id 已下线）

该实验 id 已于 2026-09-11 退役（请求路由到 `deepseek-flash`）；以下为历史证据。

owner 于 2026-08-28 提供的初始证据来自 DeepSeek Harness（DSH）web UI，不是 Pi `--mode json` 的
结构化 `message_end`：DSH UI 显示该模型可选，推理档位选项为 `off`/`low`/`high`/`max`，截图
所示会话使用了 `high`。这只证明"DSH UI 里存在这个选项"，不构成 Pi 侧的 Model Integrity
证据——按 `references/dsh-cli.md`「web 界面两个误导点」，UI 模型/档位显示本身不是运行时实际
调用模型的独立证据。完整观察范围与排除项见
`reports/deepseek-v4-flash-vision-exp-2026-08-28.md`。

2026-08-30 又完成了一次 Pi 侧的受控文本任务：

```bash
pi -p --mode json --no-session --provider deepseek \
  --model deepseek-v4-flash-vision-exp --thinking low "@<prompt-file>"
```

- 真实对抗式设计复核任务正常完成；最终 assistant `message_end` 结构化回显
  `provider=deepseek`、`model=deepseek-v4-flash-vision-exp`。
- JSONL `usage` 可解析，`totalTokens` 约为 `80258`、`cost.total=0`；这只是 provider
  报告的本次结构化用量/费用字段，不推断账户实际扣费。
- 协调者独立逐项核验了该任务的两条 `REFUTED` 结论，均可由对应 `file:line` 证据证实。
  这构成该单次文本复核的产物质量证据，不是全任务类型质量基准。

对 Pi 派发而言，当前机器真源刻意只收录已实测的 `low`：

- `references/model-catalog.yml` 以 `supported_reasoning_levels: [low]` 与
  `reasoning_levels_confidence: smoke_tested` 记录上述 Pi 证据；目录字段不能按档位保存不同
  置信度，所以不把 DSH UI 观察到但未实测的 `off`/`high`/`max` 混入可验证档位列表。
- `routing_profile: null` 保持不变，因此此证据不会把模型纳入 easy/medium/hard 自动路由；显式
  `--thinking low` 可作为有证据的显式选择，其他档位仍应拒绝为未验证。
- 本次范围**仅**是 `--thinking low`、`--mode json` 的文本任务。`off`/`high`/`max`、image-input、
  其他任务类型与可泛化的任务质量仍未验证；补 image-input 及对应档位的真实 JSONL
  `message_end`/usage 证据后才能分别扩张。

## 已知限制：中文×工具任务死循环（2026-08-21，本地 mlx 端点实测）

pi 挂本地 mlx 端点（Ornith-1.5-35B-A3B，OpenAI 兼容 21001）派**中文且需要工具调用**的任务时进入死循环：服务日志高频短请求打转（1-2 秒一个 POST 秒回 200），60/300 秒超时零产物。二分锁定条件：英文同任务 7s 完成 ✓、中文纯问答 2s ✓、中文×工具（含去掉特殊字符版）稳定复现 ✗。规避：给 pi 派英文任务，或中文任务改派 dsh；触发器：pi 或模型 chat template 更新后复测。机理未溯源（疑 tool call 格式在中文语境下不被 pi 接受触发重试循环，未验证）。

## 关键约束

- `pi` 是 coding harness，不是纯聊天 CLI。派发前必须进入目标工作目录，并设置与任务风险匹配的工具白名单。
- 每次派发前执行 `command -v pi` 与 `pi --version`；缺失立即显性失败。
- 默认会加载 `AGENTS.md`/`CLAUDE.md` 与 skills。任务明确不需要这些上下文时，可加 `--no-context-files --no-skills`，但不得因此绕过目标项目必须遵守的规则。
- 模型由用户配置决定，派发需要可复现时必须显式指定 provider、model 和 thinking。
- 模型目录中的价格是 API 等价值估算；不能据此声称实际订阅或账户扣费。
- 不要把 `~/.claude/`、`~/.codex/`、`~/.pi/agent/` 等 AI 工具配置目录作为工作目录。
