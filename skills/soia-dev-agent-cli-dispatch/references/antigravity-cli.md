# Antigravity CLI 执行规范 / Antigravity CLI rules

> 现状核对：2026-11-18，本机 `agy --version` = `1.5.10`（`agy changelog` 最新条目为 1.5.9）。
> 下文版本号、参数与模型名都会变；执行时重新跑 `agy --help`、`agy models`、`agy changelog`，以现场输出为准。

## 通道边界

- Antigravity CLI 的命令是 `agy`，承接 Gemini CLI 的消费者 Google OAuth 用户；它不是 `gemini` 的
  alias，也不是 npm 包。
- 保留 `gemini`：Gemini Code Assist Standard/Enterprise、Gemini API Key 和 Vertex AI 仍是独立通道。
  `agy` 自己也能走 `GEMINI_API_KEY`、Application Default Credentials（`AGY_ADC_AUTH`）或企业模型网关，
  这些通道的模型列表与消费者 OAuth 不同。不得静默改变供应商、账号、认证通道、模型或计费。
- 不读取、复制或打印 Gemini/Antigravity 的 token、cookie、API key、OAuth URL/state、keyring 条目或完整认证文件。

官方入口：

- 消费者账号弃用：<https://developers.google.com/gemini-code-assist/docs/deprecations/code-assist-individuals>
- 迁移指南：<https://antigravity.google/docs/gcli-migration>
- CLI 文档：<https://antigravity.google/docs/cli-overview>
- 模型与套餐：<https://antigravity.google/docs/models>、<https://antigravity.google/docs/plans>
- 官方仓库：<https://github.com/google-antigravity/antigravity-cli>

## 安装、版本与升级

```bash
command -v agy
agy --version
agy changelog      # 本地发布说明，只读，不调模型
agy update
```

- macOS/Linux 官方安装器来自 `https://antigravity.google/cli/install.sh`，默认二进制 `~/.local/bin/agy`。
- 官方安装器可能配置 shell PATH/alias（`agy install` 同样会改环境路径与 shell 设置）。需要无 profile
  副作用时，用 `soia-dev-ai-cli-upgrade` 的隔离安装流程。
- 已安装版本用 `agy update`；重新运行 bootstrap installer 可能只报告已存在，不等于升级。

## 登录与首次迁移

首次运行必须使用 PTY：`agy`。可能出现的用户动作：系统浏览器账号选择与 Google 授权、旧 Gemini
配置/扩展/技能迁移清单、企业用户的 GCP project 连接。遇到即返回 `blocked_user_action`，让客户本人确认；
不代选账号，不把授权 URL/code 写进日志。无浏览器或 SSH 场景可用 `agy acp --login` 在终端登录后退出。

显式导入旧扩展：`agy plugin import gemini`（写配置，客户批准导入范围后才运行）。不要手工复制认证文件。

## 技能与配置路径

- 全局 skills：`~/.gemini/antigravity-cli/skills/`；workspace skills：`.agents/skills/`
- 继续读取 workspace 的 `AGENTS.md` / `GEMINI.md`。
- MCP 全局配置：`~/.gemini/config/mcp_config.json`；workspace：`.agents/mcp_config.json`
- 单次会话设置可用 `--settings '<json 或文件路径>'`，不落盘。

旧 workspace `.gemini/skills/` 由客户确认后迁到 `.agents/skills/`；不要删除旧目录来“消除警告”。

## 模型发现

```bash
agy models
```

- 不发送模型 prompt，但会用当前登录态访问服务；需要登录或账号选择时返回 `blocked_user_action`。
- 每行 `<id>\t<显示名>`，顺序不固定。派发时把第一列 id 原样传给 `--model`；不要把显示名自行转换成 id，
  也不要把 id 当成 Gemini API model id。带档位后缀的 id（如 `-high`）已经钉住推理档。
- 结果是账号、套餐、认证通道和服务端状态范围内的列表，不是全量目录。

2026-11-18（agy 1.5.10，消费者 Google OAuth）现场列出：

| id 前缀 / id | 显示名 | 档位 |
|---|---|---|
| `gemini-4-argon-<level>` | Gemini 4 Argon | low / medium / high |
| `gemini-4-hydrogen-<level>` | Gemini 4 Hydrogen | low / medium / high / xhigh |
| `gemini-pro-orchestrator-g1-pro` | Orchestrator (Argon) | — |
| `gemini-3.8-flash-<level>` | Gemini 3.8 Flash | low / medium / high |
| `claude-opus-5-5-<level>` | Claude Opus 5.5 | low / medium / high |
| `claude-sonnet-5-5-<level>` | Claude Sonnet 5.5 | low / medium / high |
| `gpt-oss-120b-medium` | GPT-OSS 120B (Medium) | — |

- **Gemini 4 Carbon**（low/medium/high）按 changelog 在 `GEMINI_API_KEY`（1.5.8）、ADC `AGY_ADC_AUTH`
  （1.5.5）和企业模型网关通道出现；消费者 OAuth 账号是否列出因账号而异（2026-11-18：默认账号未列，
  另两个槽位账号列出）。只对 `agy models` 里列出 Carbon 的账号/槽位派 Carbon。
- 旧 Gemini 3.x Flash 多代、Gemini 3.1 Pro、Claude 4.6 已不在本账号列表中；历史文档里的这些名字不再作派发依据。

`references/model-catalog.yml` 的 `antigravity` 段只登记 agy 派单默认与证据边界，价格全为 null；
其他段的 Gemini/Claude API 价格与 model id 不得复用为 `agy` 的扣费、alias 或路由候选。

## 派单默认（Owner policy，2026-11-18）

- 代码单默认 `gemini-4-argon-high`；日常小单用 `gemini-4-hydrogen-<level>`（未指定时 medium，按难度在 low–high 间选，xhigh 留给难单）。
- 依据是 Owner 决定（外部执行改走 agy 调谷歌模型），不是本技能的任务质量评测；两者都只能**显式派发**，
  `route_model.py` 不自动选 agy。
- 调用方首单：2026-11-18 以 `gemini-4-argon-high` + `--mode auto` + `--dangerously-skip-permissions` 派出；
  执行结果本技能未核验。
- 订阅通道：回执标 `billing_class=subscription`，费用写 `unavailable`；额度用 `agy -p "/usage"` 预检（见下），
  多账号逐槽位看用 `scripts/agy_quota.py`。

## 多账号（账号槽位）

- 同机多个 agy 账号用独立 `HOME` 隔离（2026-11-18 实测）：`HOME=~/.agy-profiles/<槽位>` 下单独登录，之后该
  `HOME` 下的 `agy` 就是那个账号。槽位登记、选择（指定或轮流，不按余量自动调度）、派单与用量记录见
  `references/account-slots.md`。
- 各槽位的套餐、5 小时 / 7 天窗口剩余与重置时间、AI credits、可用模型：`python3 scripts/agy_quota.py`
  （只跑上面的只读斜杠命令与 `agy models`；套餐名 CLI 不提供）。
- 不同账号的模型列表可以不同（当日槽位账号能看到 `gemini-4-carbon-*`、Claude 4.6，默认账号看到 Claude 5.5）；
  派单前在**该槽位下**重跑 `agy models`，不要拿默认账号的列表推断别的槽位。

## 权限模式（headless 行为已变）

| 参数 | 含义 |
|---|---|
| 不传 `--mode` | **1.5.7 起默认 Agent Mode 为 Auto**（含 headless `-p`）；Auto 不可用的环境回落 Default |
| `--mode auto` | 自动批准 workspace 内编辑与沙箱内命令；离开终端沙箱的命令先由独立 reviewer 审，不确定再询问；不可逆动作仍询问 |
| `--mode accept-edits` | 自动接受文件编辑，其余按权限设置询问 |
| `--mode plan` | 只规划不改；只读分析配 `--sandbox` |
| `--dangerously-skip-permissions` | 自动批准全部工具权限；1.5.2 起系统命令黑名单仍拦截，企业管理员要求审查的 workspace 外访问在 `-p` 下拒绝；显式 deny 规则仍生效 |

- headless 没人应答询问：询问即被拒或等待。要无人值守写入，只能在客户明确授权写入且 workdir 隔离后用
  `--dangerously-skip-permissions`；不得作为默认参数。
- `settings.json` 的 `Tool Permission` 为 `strict` 时优先于 Auto 与 accept-edits。
- 派单命令里**显式写 `--mode`**，不要依赖默认值随版本漂移。

## 推理档

- `--effort low|medium|high|xhigh|max`。模型实际支持哪些档以 `agy models` 列出的后缀为准：
  当前只有 Hydrogen 列出 xhigh，没有模型列出 max；未列出的档不要传。
- 1.3.4 起 `--model` 可传不带后缀的基础名，CLI 取该模型默认档；派单仍传带后缀的完整 id，免得默认档漂移。
- CLI 日志会记录所给模型名被解析成别的模型（alias、`--effort` 变体、已弃用模型替换）的情况，核对时查。

## 结构化输出与多轮

```bash
# 一次性单：NDJSON 事件流，便于盯进度、判早停
agy -p "<prompt>" --model gemini-4-argon-high --mode auto \
    --output-format stream-json --log-file <task-dir>/agy.log > <task-dir>/agy.ndjson

# 多轮：stdin 每行一条 NDJSON 消息，每条跑一轮，同一会话；必须配 stream-json 输出
agy -p --input-format stream-json --output-format stream-json --model <id> --mode <mode> < turns.ndjson
```

- `--output-format text|json|stream-json`（默认 text）。`stream-json` 是强类型 NDJSON：`init`、`step_update`
  （`step_type` 为闭合词表）和最终 `result` 事件；`json` 只在结束时给一个结果对象。
- 结果含 `conversation_id`、`status`、`num_turns`、`duration_seconds` 与
  `usage{input_tokens, output_tokens, thinking_tokens, cache_read_tokens, total_tokens}`；没有费用字段，
  token 记 `measured`，费用记 `unavailable`。
- 1.4.11 起结果在提前结束时带 `finished_reason`：`print_timeout`（部分回答）、`interrupted`、`error`；
  正常完成时省略该字段。判早停看它和退出码，不看 stdout 是否非空。
- `--json-schema <inline|path>` 约束结构化输出；stream-json 下只作用于最终 `result`。
- `--input-format stream-json` 的输入消息字段本技能未实测，按官方文档写；多轮 stream-json 会话中某轮出错会告警并继续。
- `agy models` / `agy agents` 也接受 `--output-format json|stream-json`（本次只读核对未拿到 JSON 输出，用文本即可）。
- 只读斜杠命令在 print 模式不起模型轮次、不耗额度：`agy -p "/usage"`、`/quota`、`/credits`、`/model`、`/effort`、
  `/skills`；配 `--output-format json` 得结构化结果（`agy -p "/help"` 列出 print 模式能答的命令）。
  2026-11-18 实测 `/usage` 的 JSON：`command.data.groups[]` 每组有 `name`、`description`（多为
  `Models within this group: ...`）和 `buckets[]{id, window: 5h|weekly, remaining_fraction, reset_time(UTC)}`；
  `/credits` 给 `command.data.remaining_credits`。没有套餐/tier 字段。`agy models` 不接受 `--output-format`（1.5.10 报错），用文本。

退出与超时：

- 模型或 agent API 失败：stderr 一行 `AGY_ERROR: {...}`，退出码 `3`；流式输出了一部分后失败也是 3，JSON 含部分回答。
- `--print-timeout` 默认 `0`（等到本轮结束）。1.5.0 起不设超时时会等后台任务结束；设了且被截断时退出码 3、
  打印 `AGY_ERROR` 列出被终止的任务，stderr 有 `[agy] print timeout after ...`。
- 良性工具错误与权限拒绝不会导致非 0 退出；退出码只反映整轮级失败。

## ACP 服务（长会话、权限回传）

```bash
agy acp [--agent <name>] [--add-dir <dir>] [--log-file <file>] [--process-per-session]
```

- 1.5.0 起 `agy acp` 以 Agent Client Protocol 在 stdio 上跑 JSON-RPC 服务（`--stdio` 为默认传输），供编辑器或
  自写驱动把 agy 当 agent 用。
- 能力（据 changelog）：会话模式 `default` / `accept-edits` / `plan`，1.5.4 起加 `auto`；运行中再发 prompt 可纠偏；
  `session/resume` 恢复会话不重放历史；每个会话独立模型与推理档；工具权限请求回传给客户端审批
  （1.5.4 修了二次审批卡死）；`session/update` 推送进度，1.5.8 起推送上下文窗口占用。
- `agy acp` 没有 `--model`，模型与推理档按会话在协议里设；`--dangerously-skip-permissions` 在 acp 下同样可用；`--process-per-session` 让每个会话独立 worker 进程。
- 本技能尚未实测 ACP 驱动；需要时先写最小客户端做一次只读握手，再派真实任务。

## 派单选择

| 需求 | 用法 |
|---|---|
| 一次性单，无人值守 | `agy -p ... --output-format stream-json --mode <auto/accept-edits/plan> --log-file ...`；盯 `step_update` 看进度，以 `result` 的 `status` / `finished_reason` 与退出码判完成或早停 |
| 中途要人审批、多轮续做、长会话 | `agy acp`：权限请求回传驱动方，可纠偏、可 resume |
| 早停后续做（一次性单） | `agy --conversation <conversation_id> --model <same-id> -p "继续…"`；不新开会话 |
| 只读分析 | `agy --sandbox --mode plan -p ...` |

print 模式仍可能早停：模型说“等待”后本回合结束而没有提交或回执。派单要求长命令转后台、退出码写日志，
看到退出码前不得结束回合；`text` 输出分不出早停，所以一次性单用 `stream-json`。

## 证据与已知开销（2026-09，agy 1.2.9 实测，仍作参考）

- 实际模型：JSON 不回显服务端模型。证据取本次调用的 `--log-file`，核对
  `Propagating selected model override to backend: label="<显示名>"`；它证明所选模型已下发，不是服务端回显。
  不要按修改时间取共享日志目录里最新的文件。
- 会话落盘：`~/.gemini/antigravity-cli/conversations/<id>.db`（SQLite）、`brain/<id>/`、`annotations/<id>.pbtxt`；
  其中模型元数据未解码核实，不作证据。
- 每次调用有万级 input token 的固定系统提示开销；单次墙钟约 48 秒，其中约 30 秒是启动与认证。
- CLI 日志含已登录账号邮箱明文，只在本机核对，不进回执或记录。
- 交互界面支持 `@<子代理>` 私信与中途纠偏；`agy agents` 列出 agent，`--agent <name>` 指定。

## 诊断回执

至少报告：`command_path`、`cli_version`、`update_status`；`auth_status`（`unknown` / `blocked_user_action` / `ok`）
与认证通道（消费者 OAuth / API key / ADC / 企业网关，只写类别）；`model_source=runtime_account_scoped` 与本次
`agy models` 的 id；`--mode` 与是否 `--dangerously-skip-permissions`；`output_format`、`conversation_id`、
`status`、`finished_reason`、退出码；`actual_model`、token、费用的证据强度；是否发生浏览器登录、迁移提示或
PATH shadowing；`gemini` 旧 CLI 与非消费者通道是否保持不变。
