# 外部 CLI 调度契约参考

这是 `soia-dev-agent-cli-dispatch` 的详细调用契约。正文只保留选择和执行主流程；需要编排外部 CLI、恢复批量任务、核对模型或执行收尾门禁时再加载本文件。

## 内容导航

- 统一调用契约、输入输出字段与未知值处理
- 预检、模型完整性、断点恢复与完成回执
- 派发纪律、危险目录与反虚假修复门禁

## 统一调用契约 / Unified invocation contract

本节定义每一次外部 CLI 调度的输入/输出字段，供你自己的编排层和 `scripts/` 下的脚本共用。术语先对齐：

| 术语 | 含义 |
|---|---|
| `host_ai` | 调用本技能的宿主（任意兼容 Agent；可以是 Claude Code，也可以不是——本技能不绑定单一宿主） |
| `executor_cli` | 被调度的外部 CLI 进程；支持清单与验证状态以 `references/supported-agents.yml` 为准，不在 Markdown 重复维护 |
| `requested_model` | 本次调用要求使用的模型标识（可以是别名，见 `scripts/catalog_lib.py::find_model` 的宽松匹配规则） |
| `actual_model` | 执行器实际使用的模型标识；只有执行器自己在输出里回显时才能拿到，拿不到就是 `null`，不得编造 |
| `requested_reasoning_effort` | 请求的推理深度/强度参数（不同执行器命名不同） |
| `actual_reasoning_effort` | 执行器实际回显的推理档位；无法可靠读取时为 `null`，不得用请求值冒充 |
| `billing_mode` | `api`（按 token 计费）\| `subscription`（订阅额度）\| `unknown`。决定 `scripts/estimate_cost.py` 的输出是否等于真实扣费——订阅制下永远不等于 |

**输入字段：**

| 字段 | 必填 | 说明 |
|---|---|---|
| `case_id` | 是 | 本次调用在批次内的唯一标识 |
| `provider` | 是 | `openai` / `anthropic` / `google` / `deepseek` / `antigravity` / 其他；`agy` 使用 `antigravity`，不要按底层模型厂商套 API 价 |
| `executor` | 是 | 见上文 `executor_cli` |
| `model` | 是 | `requested_model`；未显式指定时按「自动路由」选型后再填入 |
| `reasoning` | 否 | `requested_reasoning_effort`；未指定时参考 catalog 的 `default_reasoning_level` |
| `cmd_template` | 是 | 实际执行的 shell 命令（已按「Prompt 注入防护」写好 temp 文件引用） |
| `timeout_seconds` | 否 | 默认 600 秒（见 `scripts/run_matrix.py --timeout-seconds`） |

**输出字段：**

| 字段 | 说明 |
|---|---|
| `status` | 见下方状态枚举 |
| `exit_code` | 子进程退出码；超时未取到时为 `null` |
| `input_tokens` / `cached_input_tokens` / `cache_write_tokens` / `output_tokens` | 分项 Token；执行器不提供时为 `null` |
| `total_tokens` | 已知分项之和；只有总量时可单独填写总量并把 `usage_status` 标为 `partial` |
| `usage_status` / `usage_source` | `measured` / `partial` / `unavailable`，以及数据来自哪个 CLI JSON/stdout |
| `actual_model` | 见上文；解析不到为 `null` |
| `requested_reasoning_effort` / `actual_reasoning_effort` | 请求档位与实际回显档位分开记录 |
| `estimated_api_equivalent_usd` | 由结构化价格和分项 Token 计算；缺少 input/output 拆分时为 `null`，不能把总 Token 全算成 output |
| `provider_reported_cost_usd` | CLI JSON 自报成本，仅作观测值，不自动等同真实账单扣费 |
| `actual_charge_usd` | 只有可靠账单证据时填写；订阅制通常为 `null` |
| `pricing_source` / `pricing_date` | catalog 来源和生效日期 |
| `notes` | 字符串数组，记录本次调用的例外情况（降级、无法解析、计费 tier 回退等） |

**状态枚举全集**（与 `scripts/run_matrix.py` 的 `ALL_STATUSES` 一致）：

`pending` / `running` / `passed` / `failed` / `unsupported` / `blocked_auth` / `blocked_quota` / `blocked_paid_api` / `pending_quota` / `timeout` / `fallback_or_downgrade` / `actual_model_unverified` / `interrupted` / `not_tested`

**unknown / unsupported 约定：**

- 解析不到的字段一律写 `null`（JSON）或字符串 `"unknown"`，**禁止用 0、空字符串或猜测值填充**——那会被下游误读成"确实是 0"或"确实是这个值"。
- `unsupported` 专指执行器明确表示"不支持该模型/参数"（stdout/stderr 命中 `not supported` / `invalid model` / `unknown model`），不要和"我们没测过"的 `not_tested` 混用。
- 任何标记为 `unknown` / `unsupported` / `unavailable` 的字段，禁止在客户可见的总结文字里被复述成确定结论（不能说"token 用量为 0"，只能说"token 用量未知，原因是 xxx"）。

## 额度预检 / Quota precheck

对某个 executor 发起**第一次真实调用**之前（尤其是新会话、或距上次调用较久之后），先跑一次预检并向客户展示报告，字段固定：

| 字段 | 说明 |
|---|---|
| `executor` | 目标执行器 |
| `cli_installed` | `true` / `false`（`which <command>` 或等效检测） |
| `cli_version` | 实际探测到的版本字符串，或 `"unavailable"` |
| `auth_status` | `ok` / `expired` / `unknown` / `blocked_user_action`；优先本地 auth-status。没有该命令时，不得未经确认用模型调用代替 |
| `last_known_quota_state` | 上一次派发记录里的额度状态；没有记录就是 `"unknown"` |
| `recommendation` | `proceed` / `hold` / `skip`，附一句理由 |

预检默认不消耗真实模型调用额度（只做版本探测与官方本地状态检查）。浏览器登录、账号选择或任何 `-p` 模型调用不属于默认预检；前者进入 `blocked_user_action`，后者必须先确认可能的额度/费用。`recommendation` 为 `hold` 或 `skip` 时，不得继续派发，除非客户明确批准。

`scripts/run_matrix.py` 在每次运行开始时会对本批次涉及的 executor 做只读版本探测（`<executor> --version`）并写入 manifest 的 `cli_versions` 字段；`--resume` 时会重新探测并在版本变化时打印警告。**当前脚本不做认证状态检查**——`auth_status` 仍需派发者在预检报告里人工核实或另行探测，脚本本身不会为了验证登录态而发起真实模型调用。

## Model Integrity Gate

保证"客户以为用的模型"和"实际用的模型"一致；出现偏差必须如实报告，不能包装成"任务成功"。

1. **requested vs actual**：每次调用后比对 `requested_model` 与 `actual_model`。
2. **降级判定**：
   - `codex`：stdout 头部若有 `model: xxx` 行，与 `requested_model` 不一致时，状态标记为 `fallback_or_downgrade`（`scripts/run_matrix.py::detect_actual_model` 已实现，只扫描 stdout 前 2000 字符内的 `model:` 行）。
   - `claude`：**P4（2026-07-10）更新**——纯文本模式（`cmd_template` 不含 `--output-format json`）下 headless 输出仍然**没有**可靠的模型回显机制，任何成功调用一律标记 `actual_model_unverified`，**不允许**因为"看起来跑成功了"就报告为 `passed`。但当 `cmd_template` 显式带 `--output-format json`（或 `--output-format=json`）时，`scripts/run_matrix.py::detect_actual_model` 会解析 stdout JSON 的 `modelUsage`（键名即模型 id）或顶层 `model` 字段作为 `actual_model`，与 `requested_model` 比对后可以正常判定 `passed` / `fallback_or_downgrade`，不再一律 `actual_model_unverified`。比对前会先剥离两种已在真实 CLI（2.1.206，2026-07-10 实测验证，非猜测）上观察到的修饰后缀：不带 `--model` 时回显可能带方括号执行模式后缀（如 `claude-opus-4-8[1m]`）；用短别名（如 `haiku`）请求时回显可能带日期后缀（如 `claude-haiku-4-5-20251001`）；显式传完整 catalog `model_id`（如 `claude-haiku-4-5`）时回显通常精确匹配、无后缀。stdout 不是合法 JSON 时仍然回退到 `actual_model_unverified`，不假装已验证。细节与原始验证 payload 见 `reports/benchmark-2026-07-10.md`。
   - `pi`：调用必须使用 `--mode json`。`scripts/run_matrix.py` 从最终 assistant `message_end` 读取 `message.model` 和结构化 `usage`；模型叶子名与请求不一致时标记 `fallback_or_downgrade`，缺少 JSONL 模型证据时标记 `actual_model_unverified`。2026-08-04 已用 Pi 0.83.0 + `deepseek-v4-flash@low` 实测，边界见 `references/pi-cli.md`。
   - 其他执行器（agy/gemini/kimi/opencode/qwen）：Phase 1 未实现模型回显检测，`notes` 会如实写明"model-echo verification is not implemented for this executor"，不假装已覆盖。
3. **宿主模型变化**：`host_ai` 自身运行在哪个底层模型上，属于**仅可观测、不可控**的信息——本技能不能对宿主自己的模型完整性做强制门禁。如果宿主环境暴露了自身模型标识，记录下来即可；拿不到就写 `unknown`，不要推断。
4. **能力限制声明**：任何一次 Model Integrity Gate 判定为 `actual_model_unverified` 或 `fallback_or_downgrade` 的调用，最终回执必须包含这次判定，不能只在内部日志里留痕、对客户只报"完成"。
5. **严格版本别名**：方括号执行模式后缀可以剥离；日期版模型标识不得通用截断，只能通过 catalog 的 `actual_model_aliases` 显式映射。未登记的日期版本必须判为 mismatch，防止真实换模被归一化掩盖。

## 可恢复执行 / Resumable execution

面向需要跑一批（多 case、多 executor、多模型）派发矩阵的场景，使用 `scripts/run_matrix.py`（严格串行，一次只跑一个 case，不并发）。

**Manifest 位置**（遵循 `SKILL_SPEC.md`「脚本写盘决策规则」B 类——可追溯、记录状态变化的审计记录，不是一次性临时文件）：

```text
${SOIA_SKILLS_STATE_HOME:-<user-state>}/soia-skills/soia-dev-agent-cli-dispatch/runs/<run_id>/manifest.json
```

**首次运行：**

```bash
python3 scripts/run_matrix.py --cases <cases.json> --run-id <run_id>
```

**断点续跑**（进程被杀、额度耗尽、或手动中断后）：

```bash
python3 scripts/run_matrix.py --cases <cases.json> --run-id <run_id> --resume
```

自定义目录时，两次调用都传同一个 `--manifest-dir <user-state-run-dir>`。manifest
中的 `resume_command` 只保存脱敏命令骨架，私有 cases/state 路径需要调用方重新提供。

行为约定：

- 每个 case 跑完后立即原子写 manifest（临时文件 + `os.replace`），中途被杀不会破坏 manifest 文件本身。
- `run_id` 只允许字母、数字、点、下划线和连字符，防止路径穿越。
- 默认最多保留 50 个 run；达到上限时阻断新 run，不自动删除。客户检查并授权清理后才能释放名额。
- 某个 provider 的某个 case 命中 `blocked_quota` 后，同一 provider 剩余的 case 立即标记 `pending_quota`（不再实际执行子进程），其他 provider 的 case 不受影响、按串行顺序继续跑。
- `--resume` 时，已是终态（`passed` / `unsupported` / `blocked_paid_api` / `fallback_or_downgrade` / `actual_model_unverified`）的 case 直接跳过；残留 `running`（上次进程被杀留下的）会先标记 `interrupted`（证据保留在该 case 记录的 `previous_attempt` 字段里，不丢弃），再重新尝试一次。
- `--resume` 时会重新探测本批次涉及执行器的 CLI 版本，和上次 manifest 里记录的版本不一致会打印警告（结果可能不可比较，但不会阻止运行）。

## 调用总结回执 / Call summary receipt

每次调用（无论成功、失败、超时、额度不足还是降级）结束后，必须输出以下最低回执格式：

```text
完成：<一句话说明本次调用做了什么>

执行器与模型：
- executor: <executor_cli>
- requested_model: <requested_model>
- actual_model: <actual_model，或 "unverified"，或 "unknown">
- requested_reasoning_effort: <请求档位，或 "unknown">
- actual_reasoning_effort: <实际回显档位，或 "unverified">

Token 与费用：
- input_tokens: <数字，或 "unknown">
- cached_input_tokens: <数字，或 "unknown">
- cache_write_tokens: <数字，或 "unknown">
- output_tokens: <数字，或 "unknown">
- total_tokens: <数字，或 "unknown">
- usage_status: <measured | partial | unavailable>
- usage_source: <CLI JSON/stdout 来源，或 "unavailable">
- estimated_api_equivalent_usd: <金额，或 "unavailable">
- provider_reported_cost_usd: <金额，或 "unavailable">
- actual_charge_usd: <可靠账单值，或 "unknown">
- pricing_source: <catalog source，或 "unknown">
- pricing_date: <价格生效日期，或 "unknown">
- confidence: <exact | estimated | unavailable>
- 订阅制下实际扣费≠此估算（api_equivalent_estimate）

状态：
- status: <见「统一调用契约」状态枚举全集>
- 降级/异常说明：<Model Integrity Gate 判定结果；没有异常写"无">

问题与下一步：
- <缺 key / 额度不足 / 需要客户确认 / resume_command；没有则写"无">
```

单次调用用这份回执；批量矩阵额外参考 manifest 的 `completed_cases` / `remaining_cases` / `stop_reason` 汇总整批状态。

## 派发纪律 / Dispatch disciplines

以下纪律来自 2026-08-20 本地端点（dsh + mlx OpenAI 兼容端点）真实派发暴露的失败模式；对云端执行器按同样条件适用。

1. **探索型任务必须预填情报**：派发前把文件清单、关键 docstring/接口签名直接放进 prompt，不让执行器自己探索。上下文获取能力弱的模型（尤其本地模型）自行探索会烧掉大量轮次甚至挂死。
2. **pi×本地端点的工具任务限制（2026-08-21 二分细化）**：中文×工具任务稳定死循环（高频短请求打转超时零产物）；长 prompt×工具曾零请求挂死（2026-08-20 两次）。英文短任务×工具实测 7s 可过、中文纯问答可过。纪律：pi 派本地端点只给英文任务或纯问答，中文工具任务改派 dsh（细节见 `references/pi-cli.md` 已知限制节）。
3. **派发到本地/自建端点必须验证请求真到目标端点**：对照目标与非目标端点服务日志的请求计数确认新增请求落点——配置叠加层可能被持久层静默压制（dsh `--patch` 被 `~/.dsh/settings.yaml` 压制的假对照实例见 `references/dsh-cli.md`），执行器"跑成功了"不等于"目标模型跑的"。
4. **自指危险（服务生命周期类任务）**：派发「管理服务启停脚本」类任务时，agent 超范围自验 `start` 命令会先杀掉旧服务——而那可能正是它自己赖以对话的模型端点，导致 TRANSPORT 断连（产物其实已完成但会话死亡）。对策：此类任务的验收命令显式禁止真实执行 start/stop（用 status/dry-run 验收），或给 agent 配独立端点。

## 危险目录 / Dangerous directories

以下目录默认禁止直接执行编码代理：

- `~/.ssh/`
- `~/.aws/`
- `~/.config/`
- 任何含生产凭据、token 的目录，或你自己 AI 工具的私有配置/登录态目录（如 `~/.claude/`、`~/.codex/` 等）

若确需读取，必须只读，不在其中生成代码或临时文件。

## Anti-Fake-Fix Gate

外部 Agent 自报“完成”和退出码 0 都只是待验证输入。主控按任务风险独立验收：

1. 对写任务检查真实 diff/产物，并确认只触及授权范围；只读任务不以“diff 为空”判失败。
2. 运行目标仓规定的最窄相关测试、构建、lint 或内容校验；不固定要求所有任务重复三次。
3. 只有发现不稳定迹象时才重复运行，并把 flaky 作为问题报告，不能标记忽略后继续宣布完成。
4. 组合命令使用 fail-fast 或逐条核对退出码，防止最后一条成功掩盖前序失败。
5. 测试通过后再从另一条路径复核最脆弱假设，例如检查下游消费者、边界输入或生成物内容。

没有任务质量证据时，最多报告“外部调用完成”，不能报告“任务完成”。

---
