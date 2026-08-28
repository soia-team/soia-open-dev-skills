# DeepSeek V4 Flash Vision (Experimental) — DSH UI 观察记录 / 2026-08-28

> **用途**：记录 owner 在 2026-08-28 提供的 DeepSeek Harness (DSH) web UI 证据，为
> `references/model-catalog.yml` 中 `deepseek-v4-flash-vision-exp` 条目提供可追溯来源。

> **诚实边界（务必先读）**：本文件转述的是一次 UI 观察，不是自动化测试，也不是
> `scripts/run_matrix.py` 或 Pi `--mode json` 产出的结构化证据。凡本文件未明确写出的字段
> （定价、上下文窗口、实际 usage、image-input 行为、Pi 侧 provider/model 回显）一律未知，
> 不得据此推测或填充。

## 观察内容

- **来源**：owner 提供的 DSH（DeepSeek Harness）web UI 证据描述，非结构化 JSON/JSONL 输出。
- **观察日期**：2026-08-28。
- **模型 ID**：`deepseek-v4-flash-vision-exp`（DSH UI 模型选择器中可选）。
- **推理档位选项**：UI 展示可选 `off` / `low` / `high` / `max` 四档（注意：与已验证的
  `deepseek-v4-flash` 仅 `low` 一档不同，也和 codex/claude 系常见的
  `low/medium/high/xhigh/max` 不同——少 `medium`/`xhigh`，是一套新的档位组合，原样记录，
  不做归一化或补全）。
- **截图所示会话**：使用了 `high` 档。

## 明确排除（本次证据不能证明的事项）

- **不是 Pi 结构化证据**：没有 `pi --mode json` 的最终 assistant `message_end`，因此不构成
  `references/pi-cli.md` 定义的 Model Integrity 验证；对 Pi 而言 `actual_model`、
  `actual_reasoning_effort` 仍是未知。
- **不是运行时模型身份的独立证据**：按 `references/dsh-cli.md`「web 界面两个误导点」，DSH
  web UI 的模型/档位显示是用户在 UI 里的选择项，不是运行时实际调用模型的独立证据；本记录
  只证明"UI 展示了这四个选项、且这次会话选了 high"，不证明"这次调用真的由该模型应答"。
- **未验证**：usage（input/cache/output/total tokens）、cost、pricing、context window、
  image-input（图片输入）行为、任务产出质量。未观察到的数值字段在 `model-catalog.yml`
  中保持 `null`，不得从相邻模型推断。

## 与 catalog 字段的对应关系

- `supported_reasoning_levels: [off, low, high, max]` 原样记录 DSH UI 的可见选项；
  `reasoning_levels_confidence: unverified` 明确表示这不是 Pi 运行证据。
- `scripts/route_model.py` 同时检查档位和置信度；显式请求该模型/档位仍返回
  `explicit_unverified`，不会因列表存在而升级为已验证。
- `routing_profile: null`：不参与任何自动路由（易/中/难任一档位都不选中）。
- `discovered_at: "2026-08-28"`，`discovery_evidence` 指回本文件。
- 价格字段全部保持 `null`：不得从 `deepseek-v4-flash` / `deepseek-v4-pro` 的已知定价推断。

## Pending：升级为已验证所需的证据

只有以下真实 Pi `--mode json` smoke 全部满足后，才能把该模型的 Pi 侧状态从
`explicit_unverified` / `pending_smoke` 升级：

1. `pi -p --mode json --no-session --provider deepseek --model deepseek-v4-flash-vision-exp --thinking <level> "@<prompt-file>"` 实际执行成功；
2. 最终 assistant `message_end` 回显 `provider=deepseek`、`model=deepseek-v4-flash-vision-exp`；
3. 结构化 `usage`（input/cacheRead/cacheWrite/output/totalTokens/cost）被解析；
4. 至少一个 image-input（图片输入）case，验证多模态行为而不仅是文本 prompt。

在此之前：`supported-agents.yml` 的 `agents.pi.auto_routing` 不得把这个模型纳入自动路由
范围；`route_model.py` 对该模型的任何显式请求都必须返回 `explicit_unverified`，不能包装成
`explicit` 或已验证的自动推荐。
