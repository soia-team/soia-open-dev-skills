# dsh 执行规范 / dsh (DeepSeek Harness) rules

> 实际命令是 `dsh`，按 profile 启动（profile 位于 `$DSH_HOME/profiles`）。**没有 `dsh run` 子命令**：headless 一次性执行是 `dsh --profile headless "<task>"`，处理一个任务、打印最终 assistant 消息后退出。以下命令形态已对照 `dsh --help` 与各 profile `--help`（0.1.0-rc.7，2026-08-20）核实。

## 模式选择

- **非交互单轮执行**：`dsh --profile headless "<task>"`；task 是位置参数，多个词按空格拼接。
- **可视化观察台**：`dsh web`（等价 `dsh --profile web`），默认 `127.0.0.1:3080`（`--host`/`--port` 可覆盖），可查看会话轨迹、工具调用树和每轮 LLM 调用，是派活可观察性利器。
- **注入 provider/模型配置**：`--patch <yaml>`（可重复），在 profile 层之后叠加 patch 覆盖层。
- **核对生效配置**：`dsh --profile <name> --dump-config` 打印合成后的配置树；派发前用它确认 patch 已生效。
- **恢复会话**：`dsh --profile tui --resume <session>`；launcher 自身选项之后的参数原样透传给被启动的 app。

## 本地 OpenAI 兼容端点接入

patch 文件是顶层 YAML 数组，两个 patch 项按插件 id 定位：`llm-pi-ai` 往 `config.providers` 加 provider，`agent-default-model` 设默认模型（形态取自 2026-08-20 实测可用的 patch）：

```yaml
- id: llm-pi-ai
  config:
    providers:
      mlx:
        displayName: "<display-name>"
        api: openai-completions
        baseURL: http://127.0.0.1:<port>/v1
        apiKeyEnv: OPENAI_API_KEY
        models:
          - id: <local-model-path>
            name: <display-name>
- id: agent-default-model
  config:
    provider: mlx
    model: <local-model-path>
```

- **`apiKeyEnv` 是唯一合法凭据字段**，值是环境变量名而不是 key 本体。在 patch 里写字面量 `apiKey` 不在 provider schema 内，实测导致 `PI_AI_ERROR` 秒败。
- **环境变量必须显式传入且非空**（如 `OPENAI_API_KEY=mlx dsh ...`）：本地端点不校验 key，但 dsh 框架要求非空，headless 和 web 模式都需要。

## 推荐命令模板

先把 prompt 写入按 task-id 隔离的 UTF-8 文件（同 Pi/OpenCode 约定）。

### 1. headless 单次派发（本地端点）

```bash
command -v dsh >/dev/null || { echo "CLI missing: dsh" >&2; exit 9; }
cd <project-path>
OPENAI_API_KEY=mlx dsh --profile headless --patch <patch-file> \
  "$(cat "${TMPDIR:-/tmp}/soia-dev-agent-cli-dispatch/<task-id>/prompt.txt")"
```

### 2. web 观察台（人工观察长任务）

```bash
OPENAI_API_KEY=mlx dsh web --patch <patch-file>
```

## web 界面两个误导点（必须警惕）

1. 任务「已停止」状态显示可能误导——实际仍在运行；以进程状态和模型服务器日志为准，不以 UI 状态判定结束。
2. 右下角模型标签是用户自己在 UI 里选的显示项，**不是**运行时实际模型的证据。

## Model Integrity 与用量证据

- 验证 `actual_model` 的唯一可靠证据是模型服务器日志（如 `mlx_lm.server` 的请求日志）；web UI 标签与「已停止」状态都不算证据。
- headless 输出只有最终 assistant 消息，CLI 侧不回显结构化 usage；tokens 分项按 `unavailable` 记录（不留空、不编数），实际 tokens 可从模型服务器侧日志采集。
- `scripts/run_matrix.py` 未实现 dsh 的模型回显检测：经 dsh 的调用默认 `actual_model_unverified`，除非派发者补充模型服务器日志证据。

## 效率特征（2026-08-20 本地端点实测）

- 同一修复任务：dsh 65s（仅 2 轮 LLM 调用，单轮批量并行约 50 个工具调用）vs pi 522s（4 轮）vs opencode 673s（8 轮）。
- prompt cache 命中率实测 91%（309K 输入 token 场景）。
- 适用场景：**长 prompt + 工具组合类任务优先派 dsh**；pi 该形态在本地端点上实测挂死（见 `references/dispatch-contract.md` 派发纪律）。

## 当前验证边界

2026-08-20 在 dsh `0.1.0-rc.7` + 本地 mlx OpenAI 兼容端点上以 7 个真实任务实测：headless 派发、`--patch` 接入、web 观察台可用。云端 provider、矩阵化验收和自动路由未验证，不得自动扩张为已验证支持。

## 关键约束

- 每次派发前执行 `command -v dsh` 与 `dsh --version`；缺失立即显性失败。
- patch 注入后先 `--dump-config` 核对 provider 与默认模型已生效，再发真实任务。
- `dsh` 是 coding harness：派发前必须进入目标工作目录，不要把 `$DSH_HOME`、`~/.claude/` 等 AI 工具配置目录作为工作目录。
- 本地模型条目形态（cost=0、tokens unavailable 约定）见 `references/model-catalog.yml` 的 `mlx` provider 模板。
