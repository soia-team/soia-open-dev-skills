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
- 请求模型可以写成 `deepseek-v4-flash` 或 provider-qualified 形式；实际回显按 `message.model` 的模型叶子名比较。

## 当前验证边界

2026-08-04 在 Pi `0.83.0` 上实测：

- `deepseek/deepseek-v4-flash` + `--thinking low` 能通过 `@prompt-file` 完成非交互调用；
- `--mode json` 的 assistant `message_end` 回显 `provider=deepseek`、`model=deepseek-v4-flash` 与结构化 usage；
- 该证据只支持 easy 自动路由。medium/hard、其他 thinking 档和 `deepseek-v4-pro` 未测试，不得自动扩张为已验证支持。

## 已知限制：中文×工具任务死循环（2026-08-21，本地 mlx 端点实测）

pi 挂本地 mlx 端点（Ornith-1.5-35B-A3B，OpenAI 兼容 21001）派**中文且需要工具调用**的任务时进入死循环：服务日志高频短请求打转（1-2 秒一个 POST 秒回 200），60/300 秒超时零产物。二分锁定条件：英文同任务 7s 完成 ✓、中文纯问答 2s ✓、中文×工具（含去掉特殊字符版）稳定复现 ✗。规避：给 pi 派英文任务，或中文任务改派 dsh；触发器：pi 或模型 chat template 更新后复测。机理未溯源（疑 tool call 格式在中文语境下不被 pi 接受触发重试循环，未验证）。

## 关键约束

- `pi` 是 coding harness，不是纯聊天 CLI。派发前必须进入目标工作目录，并设置与任务风险匹配的工具白名单。
- 每次派发前执行 `command -v pi` 与 `pi --version`；缺失立即显性失败。
- 默认会加载 `AGENTS.md`/`CLAUDE.md` 与 skills。任务明确不需要这些上下文时，可加 `--no-context-files --no-skills`，但不得因此绕过目标项目必须遵守的规则。
- 模型由用户配置决定，派发需要可复现时必须显式指定 provider、model 和 thinking。
- 模型目录中的价格是 API 等价值估算；不能据此声称实际订阅或账户扣费。
- 不要把 `~/.claude/`、`~/.codex/`、`~/.pi/agent/` 等 AI 工具配置目录作为工作目录。
