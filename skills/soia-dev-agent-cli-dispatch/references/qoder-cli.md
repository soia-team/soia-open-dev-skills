# qodercli 执行规范 / qodercli rules

> **注意**：实际命令是 `qodercli`（安装路径 `~/.local/bin/qodercli`）。`qoder` 是一个分派脚本，会转到 `qodercli` 或 IDE，派发时直接调用 `qodercli`。2026-09-25 核对的版本为 1.1.58。

## 模式选择

- **非交互执行**：`qodercli -p "<prompt>"`，加 `-o json` 输出结构化结果。
- **权限模式**：`--permission-mode default|accept_edits|bypass_permissions|dont_ask|auto`。`bypass_permissions` 与 `--dangerously-skip-permissions` 只能在客户明确授权写入且工作目录已隔离后使用。旧的 `--yolo`、`--max-turns` 已不在帮助中列出（当前仍被接受），不要再依赖它们。
- **指定模型**：先运行 `qodercli --list-models`，按输出选名称。当前包括 Auto、Ultimate、Performance、Efficient 四个档位，以及 Qwen3.8-Max/Flash、Kimi-K3、GLM-5.3、DeepSeek-V4-Pro、MiniMax-M3 等具名模型；以现场输出为准。
- **其他常用参数**：`--reasoning-effort`、`--thinking`、`--thinking-budget`、`--tools`、`-w/--cwd`、`--max-output-tokens`、`--config-dir`、`--input-format`。

## 推荐命令模板

```bash
cd <project-path>
qodercli -p "$(cat "${TMPDIR:-/tmp}/soia-dev-agent-cli-dispatch/<task-id>/prompt.txt")" \
  --model <name-from-list-models> -o json --permission-mode <mode> > <task-dir>/qoder.json
```

## 结构化输出与取证（2026-09-25，qodercli 1.1.58）

一次 `qodercli -p --model efficient -o json "<prompt>"` 调用退出码 0。

- **JSON 形状**与 Claude Code 类似：`type: result`、`session_id`、`usage`、`modelUsage`、`total_cost_usd`。但 token 计数与 `total_cost_usd` 全部为 0，**不能当作用量**；真实计量单位是 `total_credits` 与 `modelUsage.<键>.credits`。回执记 credits，token 写 `unavailable`。
- **模型证据只到档位**：`modelUsage` 的键与会话文件 `assistant.message.model` 都是档位别名（如 `efficient`）；运行日志 `~/.qoder/logs/runs/<run>/qodercli.log` 的模型配置里具体模型为空。所以只能证明所选档位，`actual_model` 写档位名并标注 `tier_alias_only`，不得声称底层模型。具名模型的回显尚未实测。
- **会话**：JSON 顶层 `session_id`；会话文件 `~/.qoder/projects/<slug>/<session_id>.jsonl`（另有 `credits`、`original_credits`、`billable`、`context_usage_ratio`）及 `<session_id>/state.json`，运行日志在 `~/.qoder/logs/sessions/<slug>/<session_id>/`。续接用 `-r <session_id>`，`-c` 接最近会话；另有 `--session-id` 与 `--no-session-persistence`（均未实测）。
- `scripts/run_matrix.py` 没有 qodercli 分支。不要复用 claude 分支解析：它会把全 0 的 token 记成 `measured`。
- 运行日志提示 Lite 档已于 9 月 18 日下线，Efficient 档对付费用户免费；计费口径以官方为准。

## 关键约束

- `qodercli` 是 headless CLI agent，不是 GUI 编辑器入口。
- 必须先 `cd` 到目标工作目录（或用 `-w`），并在 prompt 中明确路径。
- 含特殊字符的 prompt 必须通过 temp 文件传入（见 Prompt 注入防护）。
- 不要把 AI 工具配置目录（如 `~/.claude/`、`~/.codex/`）作为工作目录。
