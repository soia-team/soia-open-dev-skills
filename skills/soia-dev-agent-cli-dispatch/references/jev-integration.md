# TypeSafe System One（Jev）按需调用

## 用途与边界

Jev 由调用方按需发起一次类型化判断，可回答是非题、选择题或按文字准则评分。结果只能作为旁证；不会自动进入 agent CLI 派发流程，也不是额度、权限、发布或质量门禁。

适用于候选材料已固定、答案类型明确，且无法用确定性规则直接判定的情况，例如对照 diff 与一条明确的文字条款。若能用脚本确定、需要 diff 以外的信息、材料不能离开本机，或需要判断材料本身是否敏感，就不要调用。敏感性判断必须先在本机完成，不能交给 Jev。

## 官方模型、价格与限制

当前固定模型为 `jev-1.13.0`；官方别名 `jev-latest` 当前指向该版本。每百万输入 token 收费 `$0.042`，输出 token 免费。限速为每分钟 1,200 个请求、每秒 250,000 个 token；官方注明限速会动态调整。每请求上下文预算为 64k token；`state` 与最长的一道题合计最多 32k token，且 `state` 与所有题目合计仍须处于每请求预算内。[TypeSafe Models](https://docs.typesafe.ai/models.md)（官方文档，2026-09-23 核对）。

## 请求与响应

官方接口为 `POST https://api.typesafe.ai/v1/systemone`，通过 `Authorization: Bearer <API_KEY>` 与 `Content-Type: application/json` 传输。请求 JSON 顶层包含 `model`、`state`、`questions`；问题类型为 `noul`、`choice` 或 `score`，答案按请求中的题目 ID 返回。官方字段分别为：`noul` 答案的 `type` / `noul`；`choice` 答案的 `type` / `choice` / `probabilities` / `confidence`；`score` 答案的 `type` / `score` / `legend` / `probabilities` / `confidence`；用量字段为整数 `input_tokens` 和 `output_tokens`。[TypeSafe API Reference](https://docs.typesafe.ai/api.md)（官方文档，2026-09-23 核对）。

脚本的 `--model` 只接受匹配 `^jev-[0-9]+\.[0-9]+\.[0-9]+$` 的版本 ID，或 `jev-latest`、`jev-preview`。这两个官方别名当前均指向 `jev-1.13.0`；默认请求固定使用该版本 ID。[TypeSafe Models](https://docs.typesafe.ai/models.md)（官方文档，2026-09-23 核对）。

脚本拒绝任何 HTTP 重定向，收到 3xx 会返回 `api_error` / `redirect_refused`，不会向重定向目标发送第二个请求。默认目标主机和唯一允许的目标主机是 `api.typesafe.ai`。`TYPESAFE_BASE_URL` 可改路径前缀以匹配官方网关，但主机仍须为 `api.typesafe.ai`；userinfo、非默认端口、IDN 或百分号编码主机均会以 `input_error` 拒绝。不能配置任意目标主机。

脚本按 API 响应 schema 重建结果，只输出请求中存在的题目 ID 和官方字段；usage 仅保留响应中实际返回且类型正确的 `input_tokens`、`output_tokens` 数值字段，因此部分 usage 或空 usage 仍可接受。响应主体结构不合规时返回 `api_error` / `invalid_response`。输出中的字符串仍会经密钥脱敏。

## 启用、配置与数据边界

默认关闭。没有 `--enable-jev` 时输出 `status: disabled` 并以非零状态退出，不读题目材料、不查密钥、不联网。`--dry-run` 读取并扫描候选材料、改写正文中的本机路径、组装请求，只输出字节数和题目数，不查密钥、不发送请求。

启用后按以下顺序查找密钥，找到即停止：

1. macOS 钥匙串：`security find-generic-password -s <service> -a <account> -w`。service/account 可配置，默认 `typesafe` / `api-key`；非 macOS 或没有 `security` 命令时跳过。
2. 私有配置 `~/.config/soia-skills/soia-dev-agent-cli-dispatch/config.yml` 中 `jev.credential_file` 指向的文件，或环境变量 `SOIA_DEV_AGENT_CLI_DISPATCH_JEV_CREDENTIAL_FILE` 指定的文件。文件按 `KEY=VALUE` 逐行读取 `TYPESAFE_API_KEY`，忽略注释；不执行文件内容、不 source 文件，也不把密钥写回环境变量。权限宽于 `0600` 时只输出不含路径的警告。
3. 环境变量 `TYPESAFE_API_KEY` 作为兼容回退。

私有配置示例仅包含非秘密设置：

```yaml
jev:
  credential_file: "<credential-file-path>"
  keychain_service: typesafe
  keychain_account: api-key
  extra_block_patterns: ["<additional-regular-expression>"]
```

外发前必定扫描 `state` 与全部题目内容，检查常见 API key/token、Bearer、JWT、PEM 私钥头、`password=` / `secret=` / `token=` 赋值、个人识别信息、联系信息、claim/lease/fencing 标记、高熵长串和私有配置附加正则。扫描命中时整单拦截，只报告类别与数量，不查密钥、不发请求、不回显命中内容。扫描通过后才把 `/Users/<name>/`、`/home/<name>/`、`C:\Users\<name>\` 及对应正斜杠形式改写为 `~/`。题目 ID 若含本机路径则直接拒绝，不改写 ID。

在向服务发送任何材料前，调用方须确认材料可以外发。TypeSafe 的 Master Customer Agreement § 2.3(b) 禁止用服务或输出蒸馏模型、训练模仿服务输出的模型，或开发相似/竞争产品；§ 2.3(f) 禁止发布关于服务的基准测试或性能信息。[Master Customer Agreement](https://typesafe.ai/legal/mca)（官方文档，2026-09-23 核对）。本仓库和其他公开位置不得发布任何 Jev 性能或评测数据。

TypeSafe 的 Data Processing Addendum 说明客户数据处理条款；服务托管在美国。零数据保留（ZDR）仅向企业客户提供。[Data Processing Addendum](https://typesafe.ai/legal/data-processing)、[Privacy Policy](https://typesafe.ai/legal/privacy-policy)、[Legal overview](https://docs.typesafe.ai/legal.md)（官方文档，2026-09-23 核对）。

## 模型推荐的本地输入

在「Agent/模型推荐」场景中，Jev 只判断任务语义与候选执行器/模型的匹配。它能读取的本地使用数据只有 `scripts/usage_aggregate.py` 产出的聚合摘要：按 `executor`/模型分组的样本数与 `low_sample`、`success_rate`、`blocked_rate`、`acceptance_samples`、平均 token 分项、API 等价估算与自报费用的平均值、计费类别，以及最近失败的原因类别计数。单条用量记录、`record_id`、具体时间、会话或 case 标识不外发。

- 聚合在本机完成：`usage_aggregate.py --jev-state <state.txt>` 写出前先按本文件的外发扫描规则（含私有配置 `extra_block_patterns`）和本机路径规则自检，命中即不写文件、以退出码 2 结束。
- 写出的 state 与调用方另行脱敏的任务摘要一起，仍走本脚本的 `--dry-run` 与 `--enable-jev` 流程；外发扫描、密钥查找与数据边界不因输入来自聚合脚本而放宽。
- 推荐结果只作旁证，不是门禁：不改写额度观测、不绕过 `route_model.py` 的预检校验，也不替代 Independence Gate 与 Model Integrity Gate。额度、健康、权限与真实派发仍由本地流程决定。
- 聚合摘要是本机数据，不提交到仓库；仍不得发布 Jev 自身的性能或评测数据。

记录格式、状态映射与聚合字段定义见 `references/usage-records.md`。

## 输出与退出码

成功 JSON 包含 `status`、服务响应的 `model`、重建后的 `answers` 与 `usage`，以及按官方输入价格计算的 `cost_usd_estimate`；它是 API 价格估算，不是实际账单。若 usage 缺少有效的 `input_tokens`（包括空 usage），`cost_usd_estimate.value` 为 `null`，并由 `reason` 说明输入用量缺失，不能把缺失计为零。

| 退出码 | 状态 | 含义 |
|---:|---|---|
| 0 | `ok` / `dry_run` | 请求成功或完成离线组包 |
| 2 | `blocked_by_scan` | 外发扫描命中 |
| 3 | `skipped_no_key` | 所有密钥来源均未找到密钥 |
| 4 | `api_error` | HTTP、重定向、无效响应或网络错误 |
| 5 | `disabled` | 没有显式启用 |
| 6 | `input_error` | 输入、题目、模型 ID 或目标 URL 无效 |

```bash
python3 scripts/jev_check.py --state-file <state-file> --questions-file <questions.json> --dry-run
python3 scripts/jev_check.py --enable-jev --state-file <state-file> --questions-file <questions.json>
python3 scripts/jev_check.py --selftest
```
