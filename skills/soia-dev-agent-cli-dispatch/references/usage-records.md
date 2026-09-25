# 统一用量记录与本地聚合

本文件定义与执行器无关的用量记录格式、各 CLI 取证结果到该格式的映射，以及供模型推荐使用的本地聚合摘要。只有在需要沉淀派发用量、比较执行器/模型或为 Jev 准备推荐输入时加载；单次派发的回执仍按 `references/dispatch-contract.md`「调用总结回执」输出。

## 目标与边界

- 一次派发对应一条记录，字段名优先沿用 run manifest 的 case 记录，便于直接从 manifest 转换。
- 记录只保存脱敏的结构化字段：不保存 prompt、响应或工具正文、stdout/stderr、`notes` 自由文本、凭据、账号、会话 ID 原值、`case_id` 原值或本机绝对路径。
- 记录与聚合都只在本机完成。发给 Jev 的只有聚合后的摘要，见下文「Jev 输入」。
- 用量记录是事后观测，不是额度证据：它不能替代派发前的实时额度观测，也不能作为 `route_model.py` 的输入。

## 记录格式 `soia.dispatch.usage-record/v1`

| 字段 | 必填 | 说明 |
|---|---|---|
| `schema` | 是 | 固定为 `soia.dispatch.usage-record/v1` |
| `record_id` | 是 | 来源键（manifest 的 `run_id`+`case_id`、dsh 会话 ID 等）加开始时间的 SHA-256 前 16 位；用于去重，不可逆 |
| `source` | 是 | `run_manifest` / `dsh_session` / `cli_output` |
| `executor` | 是 | 执行器标识，如 `codex`、`claude`、`pi`、`dsh` |
| `provider` | 否 | 与 manifest 相同；dsh 取主模型的 provider |
| `dispatch_role` | 否 | 与调用契约同名字段相同 |
| `task_class` | 否 | 调用方给出的任务类别短标签（如 `implement`、`review`、`docs`），供按任务类别比较 |
| `requested_model` / `actual_model` | 是 / 否 | 与 manifest 相同；拿不到实际模型写 `null` |
| `actual_model_source` | 是 | `cli_echo` / `cli_json` / `session_file` / `unverified` |
| `model_verified` | 是 | 只有实际模型来自执行器回显、结构化输出或会话落盘时为 `true` |
| `requested_reasoning_effort` / `actual_reasoning_effort` | 否 | 与 manifest 相同 |
| `billing_class` | 是 | `subscription` / `metered_api` / `local` / `unknown` |
| `input_tokens` | 否 | 未命中缓存的输入 |
| `cached_input_tokens` / `cache_write_tokens` | 否 | 缓存读取、缓存写入 |
| `output_tokens` / `reasoning_tokens` / `total_tokens` | 否 | 执行器不提供时为 `null`，不补 0 |
| `usage_status` / `usage_source` | 是 | 与 manifest 相同：`measured` / `partial` / `unavailable` |
| `provider_reported_cost_usd` | 否 | 执行器自报费用；只作观测 |
| `estimated_api_equivalent_usd` | 否 | 本仓目录价格计算的 API 等价估算 |
| `actual_charge_usd` | 否 | 只有可靠账单证据时填写 |
| `pricing_source` / `pricing_date` | 否 | 估算所用的目录来源与日期 |
| `started_at` / `completed_at` | 是 | UTC ISO 8601；`completed_at` 即结束时间，沿用 manifest 字段名 |
| `duration_seconds` | 否 | 墙钟耗时 |
| `status` | 是 | manifest 状态枚举中的终态 |
| `outcome` | 是 | `passed` / `failed` / `blocked`，映射见下表 |
| `outcome_basis` | 是 | `execution`（按执行状态推出）或 `acceptance`（主控验收后覆盖） |
| `failure_category` | 条件 | `outcome` 不是 `passed` 时必填，取值见下表 |
| `model_breakdown` | 否 | 同一次派发用了多个模型时的逐模型用量与估算，字段为上面 token/费用字段的子集加 `provider`、`model`、`usage_kind` |

三种费用互不替代：`provider_reported_cost_usd` 是 CLI 自报值，`estimated_api_equivalent_usd` 是目录价估算，`actual_charge_usd` 是账单值。订阅制下只有估算，`actual_charge_usd` 通常为 `null`。

### 状态到结果的映射

| manifest `status` | `outcome` | `failure_category` |
|---|---|---|
| `passed` | `passed` | — |
| `actual_model_unverified` | `passed` | —（`model_verified=false`） |
| `failed` | `failed` | `task_failed` |
| `timeout` | `failed` | `timeout` |
| `interrupted` | `failed` | `interrupted` |
| `unsupported` | `failed` | `unsupported` |
| `fallback_or_downgrade` | `failed` | `model_mismatch` |
| `blocked_auth` | `blocked` | `auth` |
| `blocked_quota` / `pending_quota` | `blocked` | `quota` |
| `blocked_paid_api` | `blocked` | `paid_api_blocked` |
| `blocked_independence` | `blocked` | `independence` |

`pending`、`running`、`not_tested` 不是终态，不生成记录。manifest 的 `passed` 只表示执行成功且模型证据满足门禁，不代表产物已验收；主控验收后可以用 `--outcome` 与 `--failure-category acceptance_rejected` 覆盖，并把 `outcome_basis` 记为 `acceptance`。

`failure_category` 取值：`task_failed`、`acceptance_rejected`、`timeout`、`interrupted`、`unsupported`、`model_mismatch`、`auth`、`quota`、`paid_api_blocked`、`independence`、`transport`、`rate_limit`、`server`、`empty_response`、`invalid_request`、`approval_denied`、`unknown`。只写类别，不写错误消息原文。

## 各执行器取证到记录的映射

| 执行器 | 现有取证 | 映射 |
|---|---|---|
| codex | stdout 会话头 `model:` 行；`tokens used` 后的总数 | `actual_model_source=cli_echo`；只有 `total_tokens`，`usage_status=partial`，分项与估算为 `null` |
| claude | `--output-format json` 的 `modelUsage`、`usage`、`total_cost_usd` | `cli_json`；分项 `measured`；`total_cost_usd` 写入 `provider_reported_cost_usd`，订阅登录时只是 API 等价值 |
| pi | `--mode json` 最终 `message_end` 的 `model` 与 `usage` | `cli_json`；分项 `measured`；`usage.cost.total` 写入 `provider_reported_cost_usd` |
| dsh | `scripts/dsh_session_usage.py` 读会话落盘（v3/v4） | `session_file`；各行用量相加；`provider_reported_cost_usd=null`；多模型时写 `model_breakdown` |
| 其他 | manifest 中无模型回显 | `unverified`；用量按 manifest 原值 |

dsh 的主模型取 `message_source`/`request_header` 归属行中 token 最多的模型；`aborted_attempt` 与 `compaction_summary` 行计入总量与 `model_breakdown`，不参与主模型判定。provider 为 `mlx` 时 `billing_class=local`，其余 dsh provider 默认为 `metered_api`。会话中出现 `turn/end` 错误时，按错误码归入 `auth`、`quota`、`rate_limit`、`transport`、`server`、`invalid_request` 等类别；以中断结束的记为 `interrupted`。

## 存储

```text
<state>/soia-skills/soia-dev-agent-cli-dispatch/usage/records.jsonl
```

`<state>` 与 manifest 相同，由 `scripts/resolve_storage.py` 解析，`SOIA_DISPATCH_STATE_DIR` 可覆盖。目录 `0700`、文件 `0600`；只追加，按 `record_id` 去重，不自动删除。

```bash
python3 scripts/usage_record.py from-manifest --manifest <manifest.json> --billing-class subscription --append
python3 scripts/dsh_session_usage.py --marker <marker> > <report.json>
python3 scripts/usage_record.py from-dsh --report <report.json> --requested-model deepseek-flash --task-class implement --append
python3 scripts/usage_record.py from-output --executor claude --stdout-file <out.json> --requested-model claude-sonnet-5 \
  --started-at <iso> --completed-at <iso> --exit-code 0 --billing-class subscription --append
python3 scripts/usage_record.py --selftest
```

写入前逐条校验：未知字段、非法枚举、本机路径、疑似密钥或高熵串会使整条记录被拒绝（退出码 2）。

## 本地聚合 `soia.dispatch.usage-summary/v1`

`scripts/usage_aggregate.py` 读取记录，按 `executor` + 模型分组。模型取 `actual_model`；未验证时取 `requested_model` 并在分组上标 `model_verified=false`，两类不合并。

| 聚合字段 | 计算 |
|---|---|
| `samples` | 窗口内记录数 |
| `outcomes` | `passed` / `failed` / `blocked` 计数 |
| `success_rate` | `passed / (passed + failed)`；`blocked` 不计入分母，单列 `blocked_rate`；分母为 0 时为 `null` |
| `acceptance_samples` | `outcome_basis=acceptance` 的记录数，用于判断成功率是验收口径还是执行口径 |
| `avg_tokens` | 各 token 字段在有值记录上的均值，同时给出 `usage_samples` |
| `avg_estimated_api_equivalent_usd` / `avg_provider_reported_cost_usd` | 各自在有值记录上的均值，分开给出 |
| `avg_duration_seconds` | 有值记录均值 |
| `recent_failure_categories` | 最近 N 条非 `passed` 记录的类别计数（默认 N=5） |
| `billing_classes` | 出现过的计费类别 |
| `last_seen_date` | 最近记录日期，只到日 |
| `low_sample` | `samples` 小于 `--min-samples`（默认 3）时为 `true` |

摘要不含 `record_id`、具体时间、单条记录或任务类别以外的任务信息。`--task-class` 可只聚合某一类任务。

```bash
python3 scripts/usage_aggregate.py --since-days 30 --min-samples 3 > <summary.json>
python3 scripts/usage_aggregate.py --since-days 30 --jev-state <state.txt>
python3 scripts/usage_aggregate.py --selftest
```

## Jev 输入

Jev 在「Agent/模型推荐」中只负责任务语义与候选能力的匹配；额度、健康、权限与真实派发仍由本地流程决定。它读取的本地输入只有上述聚合摘要中的这些字段：每个候选 `executor`/模型的 `samples`、`low_sample`、`success_rate`、`blocked_rate`、`acceptance_samples`、`avg_tokens`、两类平均费用、`billing_classes` 和 `recent_failure_categories`。

- `--jev-state` 把摘要写成紧凑文本，写出前先用 `jev_check.py` 的外发扫描规则自检；命中即不写文件并以退出码 2 结束，只报告类别与数量。
- 生成的 state 仍须经 `jev_check.py --dry-run` 与 `--enable-jev` 流程发送，适用 `references/jev-integration.md` 的启用、扫描、密钥与数据边界；不另开外发通道。
- 任务描述由调用方另行脱敏后放入 state；本脚本不读取任务正文。
- Jev 的推荐只作旁证，不是门禁：不改写额度观测、不绕过 `route_model.py` 的预检校验、不替代 Independence Gate 或 Model Integrity Gate。`low_sample` 的候选应在问题中说明样本不足。
- 聚合摘要是维护者本机数据，不提交到仓库；不得发布任何 Jev 自身的性能或评测数据。

候选以 `executor:model` 作为 `choice` 题的选项，与 state 中的行一一对应；`jev_check.py` 要求 `choice` 题带 `instructions` 与非空 `criteria`：

```json
{
  "candidate": {
    "type": "choice",
    "instructions": "State holds a sanitized task summary and an aggregated local usage summary. Pick the candidate that best fits the task; treat low_sample rows as weak evidence.",
    "criteria": {
      "dsh:deepseek-flash": "<candidate description>",
      "codex:gpt-6-luna": "<candidate description>"
    }
  }
}
```

`--since-days 0` 表示不限窗口。
