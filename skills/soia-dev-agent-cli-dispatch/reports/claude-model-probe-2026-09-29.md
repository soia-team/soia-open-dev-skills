# Claude Code 模型探测报告 / claude model probe — 2026-09-29

历史证据快照，不是运行时真源。运行时事实见 `references/model-catalog.yml`
与 `references/supported-agents.yml`；本文件只记录这一次探测的方法、原始摘要
和证据边界。本次只探测 `claude-sonnet-5-5`（Claude Sonnet 5.5）。

## 探测环境

| 项 | 值 |
|---|---|
| 日期 | 2026-09-29 |
| CLI | Claude Code `2.1.284 (Claude Code)`（`claude --version`；stream-json `init` 事件的 `claude_code_version` 同值） |
| 调用形态 | ① `claude -p --model claude-sonnet-5-5 --output-format json`；② `python3 scripts/probe_claude_models.py --models claude-sonnet-5-5`（stream-json）；③ `claude -p --model claude-sonnet-5-5 --effort <level> --output-format stream-json --verbose`，level 取 `claude --help` 列出的 `low`/`medium`/`high`/`xhigh`/`max` 各一次 |
| 隔离参数 | `--tools "" --max-turns 1 --setting-sources "" --mcp-config '{"mcpServers":{}}' --strict-mcp-config`，并 `env -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT`；工作目录为空临时目录 |
| prompt | ①③ `回答一个词：ok`；② 脚本默认 `Reply with exactly the single word OK.` |
| 计费口径 | 订阅登录态（`init.apiKeySource=none`），非 API 按量计费；`costUSD` 只是 API 等价估算 |

原始 JSON/JSONL 保存在主控本机临时目录，未入库（含 session_id 等会话标识）。
下表是逐条摘要，数值直接来自那批文件。

## 逐调用结果

| 调用 | rc | 秒 | `modelUsage` 键 | `assistant.message.model` | fallback 事件 | 输入/输出/缓存读/缓存写 tokens | 判定 |
|---|---|---|---|---|---|---|---|
| ① json | 0 | 6 | `claude-sonnet-5-5` | —（json 模式无此事件） | —（json 模式不可见） | 2 / 4 / 531 / 2117 | 精确匹配；`result="ok"`，API 等价 `costUSD` 0.0086182 |
| ② probe 脚本 | 0 | 5.8 | `claude-sonnet-5-5` | `claude-sonnet-5-5` | 无 | 未单列 | `outcome=exact` |
| ③ `--effort low` | 0 | 9 | `claude-sonnet-5-5` | `claude-sonnet-5-5` | 无 | 2 / 4 / 2211 / 437 | 精确匹配 |
| ③ `--effort medium` | 0 | 9 | `claude-sonnet-5-5` | `claude-sonnet-5-5` | 无 | 2 / 4 / 2648 / 0 | 精确匹配 |
| ③ `--effort high` | 0 | 9 | `claude-sonnet-5-5` | `claude-sonnet-5-5` | 无 | 2 / 4 / 2211 / 437 | 精确匹配 |
| ③ `--effort xhigh` | 0 | 10 | `claude-sonnet-5-5` | `claude-sonnet-5-5` | 无 | 2 / 4 / 2211 / 437 | 精确匹配 |
| ③ `--effort max` | 0 | 9 | `claude-sonnet-5-5` | `claude-sonnet-5-5` | 无 | 2 / 4 / 2211 / 437 | 精确匹配 |

7 次调用全部 rc=0、`result` 为 `ok`；stream-json 事件流里没有任何
`model_refusal_fallback` 或其他含 fallback 的 `type=system` 事件。

## 与 2026-09-02 探测相比的现象

1. **辅助模型键本次未出现**：7 次调用的 `modelUsage` 都只有 `claude-sonnet-5-5`
   一个键，没有 `claude-haiku-4-5-20251001`。与 2026-09-25 CLI 2.1.282 的 haiku
   单键观察一致：辅助模型键不是每次都有。剔除规则（多键时按
   `providers.anthropic.auxiliary_models` 前缀排除、单键不排除）保持不变。
2. **`--effort` 五档均被接受**：每档 rc=0、无 fallback、模型身份不变。
   stream-json 的 `init` 事件带 `per_turn_effort_active: true`，但**不回显**
   具体 effort 档位；单词回显 prompt 下各档输出均为 4 tokens，所以本次只证明
   "该 CLI 版本对该模型接受这五个档位参数"，不证明档位产生了可测差异。

## 本次证据不覆盖的范围

- **价格**：订阅调用不产生 per-token 价格证据。catalog 中 Sonnet 5.5 的价格
  取自 Anthropic 官方公开价（与 Claude Sonnet 5 同价：输入 $2、输出 $10、
  缓存读 $0.20 / 1M tokens），来源是 Claude Code 2.1.284 内置 `claude-api`
  技能所带的官方价目缓存（标注 cached 2026-09-25）与
  `https://platform.claude.com/docs/en/about-claude/pricing`；5m 缓存写价未在该
  来源列出，按 null 处理。
- **上下文窗口 / 最大输出**：本次未单独探测。catalog 的 1M / 128K 取自同一官方
  模型表，不是本次调用的实测。
- **任务质量**：prompt 是单词回显，不构成能力或分级证据。Sonnet 5.5 进入
  `routing_profile: [medium]` 的依据是 Owner 2026-09-29 的发版授权
  （`routing_basis: owner_policy`），不是本报告的测量结论。
- **稳定性**：json、脚本、每档 effort 各一次；fallback 是否与账号、额度、时段
  相关，未验证。每次真实派发仍须按 Model Integrity Gate 读取实际模型。
