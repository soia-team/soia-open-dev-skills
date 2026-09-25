# dsh 执行规范 / dsh (DeepSeek Harness) rules

> 实际命令是 `dsh`，按 profile 启动（profile 位于 `$DSH_HOME/profiles`）。**没有 `dsh run` 子命令**：headless 一次性执行是 `dsh --profile headless "<task>"`，处理一个任务、打印最终 assistant 消息后退出。以下命令形态已对照 `dsh --help` 与各 profile `--help`（0.1.0-rc.7，2026-08-20）核实。

> `route_model.py --executor` 的 `choices` 不含 `dsh`（结构性不支持），所以 dsh 派发一律不经过 `SKILL.md` 第 3–4 步的通用 `route_model.py --quota-observations` 流水线，也一律不产出 `verified_auto`——但云端/本地的判定不看是否传了 `--patch`，只看派发前 `--dump-config` 解出的实际生效 provider/model/端点类型（`--patch` 可能被 `settings.yaml` 覆盖，见下方「settings.yaml 持久化」一节的实测），核对时只取非秘密的 provider/model 字段，不打印含密钥的整份配置：
>
> - **`--dump-config` 解出生效 provider 为云端时**，是真实计费、真实额度的桶，**不是** `local_only`：本文件「模型证据提取」一节记录的 session 落盘证据（如某次实测的 `"provider":"deepseek-official"`、`"model":"deepseek-flash"`）是那次部署的真实观测，但 `deepseek-official`/`deepseek-flash` 只是已实测机器上的一个部署示例，不是所有机器的默认云端 provider——实际生效的 provider/model 以当次 `--dump-config` 为准。派发前必须对该实际生效的 provider/选定模型单独取一条实时余额观测（字段比照 `SKILL.md`「执行前预检」的 `quota_observations[]`：`state`/`source`/`probed_at`），且这条观测须由调用方提供已核实的官方来源，只有 `state=available` 才可派；`unknown`（含缺失来源）或 `exhausted` 一律 `hold`，不得用「有登录态/凭据」替代余额观测。本仓库当前未收录一个已核实的 DeepSeek 官方只读余额查询命令，这是未处理项——需要调用方提供已核实的 provider/model 余额观测（含 `source`/`probed_at`/`state`），缺失时记 `unknown` 并 `hold`，本技能不内置全 provider 余额探测器。
> - **只有 `--dump-config` 确认生效端点确为下方「本地 OpenAI 兼容端点接入」所配置的本地 OpenAI 兼容端点时**，才落入 `references/model-catalog.yml` 里 `mlx` provider 下 `availability: local_only` 的条目（cost 恒为 0，没有真实配额/订阅）——这时才是 `SKILL.md`「执行前预检」里那条额度流水线豁免（门禁本身没有对象可绑定），才**始终显式指定模型**（`auto_routing: []`）。命令行里看到 `--patch` 或 `mlx` 字样不构成本地端点证据，仍须以 `--dump-config` 的生效配置核实。
>
> 两条路径共同、不能省的检查：派发前的 `command -v dsh`/`dsh --version`/`--dump-config`，以及本文件「模型证据提取」一节的 session 落盘取证（认 assistant 记录的 `provider`/`model` 字段，不认 `titleProvider`）——它们替代的是通用流水线里的额度绑定与模型回显核验，不是免检。

## 模式选择

- **非交互单轮执行**：`dsh --profile headless "<task>"`；task 是位置参数，多个词按空格拼接。
- **可视化观察台**：`dsh web`（等价 `dsh --profile web`），默认 `127.0.0.1:3080`（`--host`/`--port` 可覆盖），可查看会话轨迹、工具调用树和每轮 LLM 调用，是派活可观察性利器。
- **注入 provider/模型配置**：`--patch <yaml>`（可重复），作为 profile 配置之后的候选覆盖层；`settings.yaml` 持久化值可能优先，最终只以 `--dump-config` 为准。
- **核对生效配置**：`dsh --profile <name> --dump-config` 打印合成后的配置树；派发前用它确认 patch 已生效。
- **恢复会话**：`dsh --profile tui --resume <session>`；launcher 自身选项之后的参数原样透传给被启动的 app。
- **headless 续接**：`dsh --profile headless --session-id session-<uuid> "<task>"`。ID 必须带 `session-` 前缀，即会话目录名；只传裸 UUID 会报 `session "<uuid>" does not exist`。会话按启动时的 cwd 归档，会话头还记录了原 cwd，所以必须在原会话的同一工作目录下续接：换目录会找不到会话，或因会话头与所在目录不符被判为损坏。2026-09-25 在隔离 `DSH_HOME` 下复现了这两种失败（无凭据，未发起模型调用）；成功续接的完整路径尚未实测。

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

## 云端 provider：Xiaomi / MiMo

- Xiaomi provider 使用 `api: openai-responses`，目录包含 `mimo-v2.6-pro`、`mimo-v2.6-flash` 和 `mimo-v2.6-pro-ultraspeed`。超高速档仅有实时价格，不支持批量；实时和批量价格见 `references/model-catalog.yml`。
- 全局 `~/.dsh/settings.yaml` 的 `agent-default-model` 可以指向 `provider: xiaomi`、`model: mimo-v2.6-flash`。`headless`、`tui`、`web` profile 可能各自固定另一默认模型；本机检查到的 profile 默认是 `deepseek-flash`，这只描述 profile 默认值，不表示全局没有 MiMo provider。
- 凭据留在 dsh 使用的凭据文件中。只核对该文件存在，不读取、复制或打印其内容。
- 2026-09-23 曾以 `--profile headless --patch <mimo-patch>` 发起探测，唯一匹配的会话记录为 `provider=xiaomi`、`model=mimo-v2.6-flash`。当时全局 settings 默认模型也已经是该 MiMo 模型，所以探测不能区分这次结果来自 patch 还是 settings；这与 2026-08-21「settings 可压过 patch」的单变量观察不矛盾。不要据此宣称 `--patch` 可以切换到 MiMo；以 `--dump-config` 的非秘密 provider/model 字段和对应会话记录为准。
- 2026-09-23 的另一项 headless 观察：`--patch` 请求 `reasoningEffort: low`，但会话 `request/header` 记录的实际档位为 `max`，与全局 settings 一致。这进一步表明 settings 优先于 patch；headless 模式下不能用 `--patch` 更改思考档位。要改档位，应更新 settings，或在 web/tui 界面中选择。
- dsh 的 DeepSeek 与 Xiaomi 都是按量 API，不是订阅。DeepSeek 另有北京时区高峰和平时两档价格，具体数值以模型目录为准。
- 本节的会话证据只证明当次模型身份及可服务，不证明任务质量，也不证明 patch 优先级。

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

- 验证 `actual_model` 的可靠路径包括模型服务器日志（如 `mlx_lm.server` 请求日志）与会话落盘文件；web UI 标签与「已停止」状态都不算证据。
- headless 输出只有最终 assistant 消息，CLI 侧不回显结构化 usage。模型与档位、token 分项、重试、审批和上下文压缩等记录可从会话文件提取，见下方「模型证据提取」。
- `scripts/run_matrix.py` 未实现 dsh 的模型回显检测：经 dsh 的调用默认 `actual_model_unverified`，除非派发者补充模型服务器日志或会话落盘文件证据。

## 模型证据提取（session v3/v4 取证法，2026-09-25 核对）

dsh headless 的 stdout 无模型回显：它只打印最终 assistant 消息，既不带 `model`/`provider`，也不带结构化 usage。真实证据在会话落盘文件：

```
~/.dsh/sessions/<项目>/session-<id>/session.v4.jsonl.zstd   # 本机 dsh 0.1.7-alpha.2 写入的格式
~/.dsh/sessions/<项目>/session-<id>/session.v3.jsonl.zstd   # 旧格式
```

`<项目>` 是 cwd 编码后的目录名，`<id>` 是会话 UUID。该文件是 zstd 压缩的 JSONL，每行一个事件，常见字段为 `type`、`seq`、毫秒时间 `time` 和 `data`。首行是不带 `data` 的会话头（`type=session`，含 `version`、`id`、`createdAt`、`cwd` 等）；会话标题来自 `session/title`。

**v4 格式差异（2026-09-25 只读核对本机 dsh 0.1.7-alpha.2 会话结构）：**

- 升级会把旧会话迁移为 v4，并在同一会话目录保留原 v3 文件；v4 是迁移后的超集，此后只有 v4 继续写入。两者并存时以 v4 为准。
- `assistant/message` 的用量位于 `data.usage`（v3 夹具在 `data.message.usage`），并新增 `data.message.source`：`kind=model` 时带该条消息实际的 `provider`/`model`。它比按时间归属请求头更直接，用量按它归属，标 `attribution=message_source`；档位只在当时请求头指向同一模型时沿用请求头的 `reasoningEffort`。
- `compaction/summary` 带独立的 `provider`/`model`/`usage`，是压缩摘要的真实调用用量，单列 `attribution=compaction_summary`；`assistant/attempt` 的流中若有 `usage` 块，是未被保留的尝试，单列 `attribution=aborted_attempt`。
- `request/context` 的 `contextWindow` 直接在 `data` 下；`turn/end.data.reason` 记录 `kind`（`completed`/`interrupted`/`error`）与错误码（如 `AUTH`、`INVALID_REQUEST`），脚本只输出 kind 与错误码计数及最后一轮的结束方式，不输出错误消息。
- 用户输入除 `user/message` 外，还可能经 `agent/inbox/spliced.data.inserted[]`（`role=user`）进入会话；标记定位两处都查。
- 会话头的 `cwd`、`agent/inbox/spliced` 的正文、`tool/call` 参数和 `replayState` 响应 ID 都不进入报告。

- **定位**：`<cwd-encoded>` 是工作目录编码后的会话目录。用 prompt 中的唯一标记在 `user/message`（v4 另含 `agent/inbox/spliced`）事件里找会话；不要按修改时间取最新文件。常驻的 `dsh web` 可能并发写入其他会话，按时间选择会取错。
- **格式识别**：脚本只读 `session.v3`/`session.v4`，同目录并存时取 v4；只有其他版本（如 `session.v5`）或会话头版本与文件名不符时输出 `status=unsupported_format` 并以退出码 4 结束，不猜测字段。遇到该退出码先核对 dsh 版本与新格式结构，再扩展脚本。
- **实际请求模型与档位**：以 `request/header.data.header.config` 的 `{provider, model, reasoningEffort, maxTokens}` 为准。这是该次请求实际发出的配置，证据强于界面选择。`model/selection.data` 记录 UI 选择，只作辅助；dsh web 切换一次模型可能连续落下多条选择事件（例如先记录 high、再记录 max），因此不能用最后一条 UI 选择替代请求头。
- **用量归属**：每条 `assistant/message` 用量的 `inputTokens` 是未命中缓存输入，另有 `outputTokens`、`cacheReadTokens`、`cacheWriteTokens`、可选 `reasoningTokens` 和 `totalTokens`。v4 优先按消息自带的 `message.source` 归属；v3 用量事件自身不提供模型字段，只按时间顺序归到最近一次 `request/header`；后续 `model/selection` 只进入 UI 选择时间线，不改变用量归属。只有还没有任何请求头时，才以最近的 UI 选择作兜底，并在输出标记 `attribution=ui_fallback`。用量估价要把缓存命中和缓存写入分项传入，不能把 `totalTokens` 全按普通输入或输出计费。若缓存计数缺失，脚本只有在 `totalTokens` 与已记录的输入、输出及缓存计数完全相符时才将缺项视为零；无法核实时成本为 `null`。
- **按需提取**：运行 `python3 scripts/dsh_session_usage.py --session <uuid-or-prefix>`，或用 prompt 唯一标记定位：`python3 scripts/dsh_session_usage.py --marker <unique-prompt-marker>`。标题默认不输出；只有显式加 `--with-title` 才输出经过路径与 token 脱敏的标题。脚本需要系统 `zstd`，只读解压；不写入 dsh 目录，不输出对话、工具参数或结果正文。成本按本仓 `model-catalog.yml` 估算；无价格或必要用量字段时返回 `null` 并说明原因。DeepSeek 价格时段会在每个模型估算中注明使用的目录标量档位。
- **子代理**：读取 `subagent/model-selection-policy.data.allowedModels` 作为允许模型策略，并统计 `tool/call` 中 `name=subagent` 的次数与显式模型参数。若调用参数没有模型，仅当允许列表只有一个模型时才把它标为策略推断；这不是子代理的运行时回显。主会话切换模型不会自动改变子代理策略；回执要分开记录主会话和子代理模型，并标明推断来源。
- **重试与审批**：按 `llm/retry.data.provider` 与 `failure.code` 汇总具体失败类别，并保留事件顶层 `policyKey` 作为重试策略标签；这两个值可能不同。常见标签包括 `EMPTY_RESPONSE`、`RATE_LIMIT`、`SERVER`、`TIMEOUT`、`TRANSPORT`。用 `approval/asked` 和 `approval/decided` 统计拒绝与理由类别，不复制命令正文；dsh 可能拒绝未引用 glob 或不兼容 grep 方言的命令并说明原因。
- **压缩与窗口**：统计 `compaction/start`、`compaction/summary`、`compaction/end`；`request/context.data.contextWindow` 记录窗口信息。
- **模型 ID 与档位**：Xiaomi/MiMo ID 一律使用小写，例如 `mimo-v2.6-flash`、`mimo-v2.6-pro` 和 `mimo-v2.6-pro-ultraspeed`；曾观察到大写 `MiMo-V2.6-Flash` 的思考档为空，不要用大写 ID。当前目录记录的 MiMo 实际档位见 `references/model-catalog.yml`。
- **长会话费用**：常驻 web 的长会话中缓存命中可能占总 token 的大部分，忽略 `cacheReadTokens` 会明显低估按量费用。长任务应分段执行或更早压缩上下文；使用按量通道前检查预计缓存命中与缓存写入成本，并谨慎处理长会话费用。
- **证据边界**：会话事件证明框架发出的请求配置和记录的用量，不证明任务质量，也不等同 provider 账单。会话文件只在本机按需检查，不把会话正文或具体用量样本写入仓库。
- **派发纪律**：每次 dsh 派发后按 cwd 定位 session 文件，把提取到的 `actual_model`/`provider` 写入
  验收回执，替代 `unavailable`/`actual_model_unverified` 的默认标注。
- **判活与退出归类**：dsh 在 `NO_ADAPTER`、会话不存在、沙箱拒绝写 `.git` 等情况下退出码仍为 0。长任务用 `scripts/executor_watch.py wait --log <会话文件>` 判活，结束后用 `classify --executor dsh` 归类，见 `references/executor-watch.md`。
- **统一用量记录**：需要沉淀用量或为模型推荐积累样本时，把报告交给 `scripts/usage_record.py from-dsh --report <report.json>`，生成与执行器无关的记录；dsh 默认 `billing_class=metered_api`（本地 `mlx` 为 `local`），`provider_reported_cost_usd` 为 `null`，费用只有目录价估算。格式、结果映射与存储见 `references/usage-records.md`。

## 效率特征（2026-08-20 本地端点实测）

- 同一修复任务：dsh 65s（仅 2 轮 LLM 调用，单轮批量并行约 50 个工具调用）vs pi 522s（4 轮）vs opencode 673s（8 轮）。
- 长 prompt 场景中观察到显著的 prompt cache 命中；核算用量时应查看缓存命中分项。
- 适用场景：**长 prompt + 工具组合类任务优先派 dsh**；pi 该形态在本地端点上实测挂死（见 `references/dispatch-contract.md` 派发纪律）。

## 当前验证边界

2026-08-20 在 dsh `0.1.0-rc.7` + 本地 mlx OpenAI 兼容端点上以 7 个真实任务实测：headless 派发、`--patch` 接入、web 观察台可用。云端 provider、矩阵化验收和自动路由未验证，不得自动扩张为已验证支持。

### DeepSeek V4 Flash Vision Experimental 诊断与补丁草案试点（2026-08-30）

SoiaDeck 项目中，协调者亲验 DSH + `deepseek-v4-flash-vision-exp` 完成首个**诊断 + 补丁草案**类试点，结果合格。任务范围限于只读仓库分析与临时目录实验：定位 macOS Python 3.14 pty 文件描述符竞争根因；修复前 40 次试验中稳定复现 26–33 次；随后给出语义零变化的 unified diff 补丁草案。协调者落库后独立复核，40 次连续运行零复现且全量回归通过。

这项证据仅覆盖诊断和补丁草案产出；它不等同于 DSH 直接修改仓库文件的完整实现任务验证，也不覆盖大切片任务或图片输入。`routing_profile` 继续保持 `null`，不得据此开启自动路由；模型身份和用量证据按本文件前述 Model Integrity 门禁与「模型证据提取」一节处理——`actual_model`/`provider` 可经 session 落盘文件验证（见取证法一节）。

## 关键约束

- 每次派发前执行 `command -v dsh` 与 `dsh --version`；缺失立即显性失败。
- patch 注入后先 `--dump-config` 核对 provider 与默认模型已生效，再发真实任务。
- `dsh` 是 coding harness：派发前必须进入目标工作目录，不要把 `$DSH_HOME`、`~/.claude/` 等 AI 工具配置目录作为工作目录。
- 本地模型条目形态（cost=0、tokens unavailable 约定）见 `references/model-catalog.yml` 的 `mlx` provider 模板。

## settings.yaml 持久化与 NO_ADAPTER 诊断（2026-08-20 实测）

- dsh web 里选择模型会把默认模型**持久化写进 `~/.dsh/settings.yaml`**（`agent-default-model` 键）——但 **provider 定义不会**随之写入。此后不带 `--patch` 的 headless 调用报 `NO_ADAPTER: no adapter registered for provider "<名>"`。
- **2026-09-25 复现于 headless 切 MiMo**：provider 定义按 profile 注册。只在 web profile 的 patch 里注册了 xiaomi、headless 与 tui profile 的 patch 仍为空数组时，`--patch` 只改 `agent-default-model` 指向 xiaomi 同样报 `NO_ADAPTER: no adapter registered for provider "xiaomi"`。已实测可行的做法：headless 派单用的 patch 同时包含 `llm-pi-ai` 下的 xiaomi provider 块（从 web patch 按原文截取，只含 `apiKeyEnv` 变量名，不含密钥值）和 `agent-default-model`。截取时按文本复制，不要用 PyYAML 读出再写回：模型的 `reasoningEfforts` 里有未加引号的 `off` 键，YAML 1.1 解析器会把它变成布尔 `false`，写回后 provider 注册失败，仍报 `NO_ADAPTER`。若该机的 headless/tui profile patch 已按原文注册了 xiaomi provider，派单 patch 只需改 `agent-default-model`；否则须带上 provider 块。派发后用会话文件核对 `provider=xiaomi`。凭据文件（如 `$DSH_HOME/.credentials.yaml`）只核对存在，不读取、不打印。
- 修复二选一：把 provider 定义也写进 settings.yaml（键结构 = plugin id 为顶层键，`llm-pi-ai:` 下放 `providers:`，与 patch 的 `- id/config` 一一对应），或把 `agent-default-model` 改回云端 provider。
- settings.yaml 与 `--patch` 双轨并存：settings 是本机持久层，patch 是本次叠加层。凭据仍必须显式传环境变量（如 `OPENAI_API_KEY=mlx`），settings 不能免除。
- **优先级修正（2026-08-21 单变量实验推翻旧断言）**：本文档曾写"patch 覆盖 settings"——**实测相反**：settings.yaml 存在 `agent-default-model` 时，`--patch` 里的同名条目**不生效**，请求仍打到 settings 指定的 provider。旧断言成立的环境是 settings 尚无该键（patch 独占生效）。切换模型的可靠做法：把目标 provider 写进 settings.yaml 的 `providers:` 并临时改 `agent-default-model`，用完改回。
- **派发后必须验证请求真到目标端点**（与评测的"对照条件生效验证"同源）：对照目标与非目标端点的服务日志请求计数（如 `grep -c POST <各端点日志>`）确认新增请求落在目标端点。真实事故：patch 指 21001 的"实测成绩"实为 settings 默认的 21000 模型跑出（假对照），靠请求计数识破。

## 会话触发陷阱

在 dsh web 的**历史任务会话**里发送任何消息——包括闲聊（"你是什么模型"）——都会被当作继续执行任务的指令：agent 会带着旧任务上下文直接开工改文件（实测把知识库里的实验描述误当规格写进了脚本）。纪律：已完成的会话不要再发消息；要新对话就开新会话。

## 模型身份验证阶梯（从模型嘴里问永远不可靠）

system prompt 会让任何模型自称 harness 预设的身份（实测本地 Qwen 一口咬定自己是 deepseek-v4-flash）。按可靠性从高到低：
1. **拔线测试**：停掉本地模型服务再发消息——报错=走本地，正常回答=走云端；
2. **服务器日志时间戳对照**：发消息的时刻本地端点有无对应请求记录；
3. **物理特征**：本地大上下文冷 prefill 首字十几秒起，云端不会；
4. `--dump-config` 核对生效 provider；
5. 对话侧能力指纹（最弱，仅无服务器权限时）。
