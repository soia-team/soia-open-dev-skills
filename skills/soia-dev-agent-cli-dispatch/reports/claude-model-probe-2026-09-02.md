# Claude Code 模型探测报告 / claude model probe — 2026-09-02

历史证据快照，不是运行时真源。运行时事实见 `references/model-catalog.yml`
与 `references/supported-agents.yml`；本文件只记录这一次探测的方法、原始摘要
和证据边界。

## 探测环境

| 项 | 值 |
|---|---|
| 日期 | 2026-09-02 |
| CLI | Claude Code `2.1.257 (Claude Code)` |
| 调用形态 | `claude -p --model <M> --output-format json`（另对 fable 两个 id 各跑一次 `--output-format stream-json --verbose`） |
| 隔离参数 | `--tools "" --max-turns 1 --setting-sources "" --mcp-config '{"mcpServers":{}}' --strict-mcp-config`，并 `env -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT` |
| prompt | `Reply with exactly the single word OK and nothing else.` |
| 计费口径 | 订阅登录态，非 API 按量计费；本次不产出价格证据 |

原始 JSON/JSONL 保存在主控本机临时目录，未入库（含 session_id 等会话标识）。
下表是逐条摘要，数值直接来自那批文件。

## 逐模型结果

| requested | rc | 秒 | `modelUsage` 键 | `assistant.message.model` | 判定 |
|---|---|---|---|---|---|
| `claude-fable-5-1` | 0 | 6 | `claude-haiku-4-5-20251001`, `claude-fable-5-1` | `claude-fable-5-1` | 精确匹配 |
| `claude-fable-5` | 0 | 5 | `claude-haiku-4-5-20251001`, `claude-opus-5` | `claude-opus-4-8` | **fallback** |
| `claude-opus-5` | 0 | 5 | `claude-haiku-4-5-20251001`, `claude-opus-5` | — | 精确匹配 |
| `claude-opus-4-8` | 0 | 5 | `claude-haiku-4-5-20251001`, `claude-opus-4-8` | — | 精确匹配 |
| `claude-opus-4-7` | 0 | 6 | `claude-haiku-4-5-20251001`, `claude-opus-4-7` | — | 精确匹配 |
| `claude-opus-4-6` | 0 | 5 | `claude-haiku-4-5-20251001`, `claude-opus-4-6` | — | 精确匹配 |
| `claude-sonnet-5` | 0 | 5 | `claude-haiku-4-5-20251001`, `claude-sonnet-5` | — | 精确匹配 |
| `claude-sonnet-4-8` | 1 | 5 | — | — | **CLI 不认识该 id** |
| `claude-sonnet-4-7` | 1 | 4 | — | — | **CLI 不认识该 id** |
| `claude-sonnet-4-6` | 0 | 5 | `claude-haiku-4-5-20251001`, `claude-sonnet-4-6` | — | 精确匹配 |

## 三个必须被技能处理的现象

### 1. fallback 事件（stream-json 才可见）

`--output-format stream-json --verbose` 下，`claude-fable-5` 的事件序列里出现：

```json
{"type":"system","subtype":"model_refusal_fallback","original_model":"claude-fable-5","fallback_model":"claude-opus-4-8"}
```

同一次运行中 `assistant.message.model` 是 `claude-opus-4-8`，而 `result.modelUsage`
的业务键是 `claude-opus-5`。两次独立运行结果一致。

边界：这是**这一次、这一个账号、这一个 prompt** 的观察。它证明"请求
`claude-fable-5` 不保证由 `claude-fable-5` 服务"，**不能**据此断言该模型
"已停止"或"不可用"——它 rc=0 并正常返回了结果。因此 catalog 中
`claude-fable-5` 保持 `availability: available`，只追加 `routing_notes`，
要求每次派发逐次读取 stream 的 `fallback_model`，而不是把观察固化成结论。

同时注意：json 模式看不到这个 system 事件，只能看到 `modelUsage` 的键与请求
不同。stream-json 是本现象的唯一直接证据来源。

### 2. `modelUsage` 恒含辅助模型

10 次调用无一例外，`modelUsage` 都额外含 `claude-haiku-4-5-20251001`
（`canonicalModel: claude-haiku-4-5`，`provider: firstParty`）。这是 Claude Code CLI
自身的辅助模型开销，不是本次派发请求的模型。

后果：`modelUsage` 的"第一个键"不再等于实际模型。技能必须先排除辅助模型
（前缀 `claude-haiku-4-5`，登记在 catalog 的 `providers.anthropic.auxiliary_models`）
再取剩余唯一键；剩余 0 个或多于 1 个时判 `actual_model_unverified`，不猜。

副作用（未处理，仅记录）：派 `claude-haiku-4-5` 本身时，业务模型与辅助模型
同名，排除后剩 0 键，会判 `actual_model_unverified`。这是保守方向的误判，
不会把错误模型当成正确模型。

### 3. `unrecognized_model`

`claude-sonnet-4-8` / `claude-sonnet-4-7` 均 rc=1，stderr 为：

```text
[claude-code:unrecognized_model] {"model":"claude-sonnet-4-8","query_source":"sdk"}
```

技能把它判为状态 `unsupported`（"执行器明确表示不支持该模型"），并把 stderr
原文写进 `notes`。这两个 id 因此以 `availability: unrecognized_by_cli` 入 catalog，
且不进入任何 `routing_profile`。

## 本次证据不覆盖的范围

- **价格**：本次为订阅登录态调用，没有产生任何 per-token 价格证据。新增的
  `claude-fable-5-1`、`claude-opus-5` 的价格字段全部为 `null` +
  `pricing_source: unknown`，不从同族模型推断。
- **上下文窗口 / 推理档**：未探测，保持 `null` / 空列表。
  （`result.modelUsage` 里出现的 `contextWindow` 是该次会话的运行时数值，
  不作为模型规格事实录入。）
- **任务质量**：prompt 是单词回显，不构成任何能力或分级证据。因此新增模型
  一律 `routing_profile: []`，不开放自动路由。
- **稳定性**：每个 id 一次（fable 系两次）。fallback 是否稳定复现、是否与
  账号/额度/时段相关，未验证。
