# DeepSeek V4.1 Flash（deepseek-flash）— 验证证据登记 / 2026-09-11

> **用途**：为 `references/model-catalog.yml` 中新增的 `deepseek-flash` 条目、
> 旧 `deepseek-v4-flash` / `deepseek-v4-flash-vision-exp` 的 deprecated 标记，以及
> `deepseek-v4-pro` 的 2026-09-14 路由备注，提供可追溯来源。catalog 头部 `sources`
> 以 `deepseek-flash-verification-2026-09-11` 指向本文件。

> **诚实边界（务必先读）**：本文件混合三类证据，强度不同，正文逐条标注：
> ① **provider 元数据**（机器同步，声明级事实）；② **pi 结构化回显**（Model Integrity
> Gate 认可的运行证据）；③ **dsh 任务产物**（有产物与门禁记录，但 dsh 没有模型回显实现，
> 属任务结果证据而非模型身份证据）。三类都不能互相冒充；未测到的字段一律不填。

## 1. Provider 元数据（2026-09-11，机器同步）

本机 pi 0.85.1 的 provider 模型目录（`models-store`，`checkedAt` 为 2026-09-11，源为
`api.deepseek.com`）对 DeepSeek 家族给出：

| 字段 | `deepseek-flash` | `deepseek-v4-pro`（同次同步） |
|---|---|---|
| 显示名 | **DeepSeek V4.1 Flash** | DeepSeek V4 Pro |
| context window | 1,000,000 | 1,000,000 |
| max output | 384,000 | 384,000 |
| 输入模态 | **text + image** | text |
| thinking 档位映射 | `low` / `high` / `max`（`minimal`、`medium` 无映射） | `high` / `max`（`low` 无映射） |
| 价格 USD/1M | input 0.30 / cache-hit 0.006 / output 1.20 | input 1.32 / cache-hit 0.044 / output 3.96 |
| cache write | 显式 0（不单独计费） | 显式 0 |

- 该目录**不再列出** `deepseek-v4-flash` 与 `deepseek-v4-flash-vision-exp`；旧 id 已从
  provider 目录退场（本机 pi 用户级补丁目录里仍留 `deepseek-flash` 与
  `deepseek-v4-flash-vision-exp` 两条自定义条目，那是本机配置，不是 provider 现状）。
- 同一台机器 2026-08-18 的旧目录快照中，`deepseek-v4-flash` 为 input 0.14 / cache-hit
  0.0028 / output 0.28，与 catalog 的 `pricing-2026-07-10` 完全一致；本次 0.30/0.006/1.20
  是 prompt 缓存同步后的**当前** Flash 价，不是从旧价推算的。
- `pi --offline --list-models deepseek`（只读、离线、不产生调用）同时给出
  `deepseek-flash  context 1M  max-out 384K  thinking yes  images yes`。

**这一类证据能证明**：模型 id、显示名、上下文/输出上限、输入模态声明、档位映射、当前价格。
**不能证明**：任何一次真实调用真的由该模型应答，也不能证明 image-input 端到端可用。

## 2. Pi 结构化回显（2026-09-10，运行证据）

SoiaDeck 项目的一次真实 pi 会话（2026-09-10 14:32–14:43 +08，1 个用户任务、3 轮
assistant、3 次工具调用）：

- `model_change`：`provider=deepseek`、`modelId=deepseek-flash`；
  `thinking_level_change`：`thinkingLevel=high`。
- 每次 assistant `message_end` 均回显 `provider=deepseek`、`model=deepseek-flash`，
  并带结构化 usage，例如：input 197 / cacheRead 32256 / cacheWrite 0 / output 334 /
  reasoning 172 / totalTokens 32787，`cost.total = 0`（订阅口径，各分项显式为 0）。

这是本技能 Model Integrity Gate 认可的形态：请求 id 与最终 assistant `message_end`
的 `message.model` 一致，且 usage 可解析。它证明 **pi + deepseek-flash 在 `high` 档真实
可调用、可回显、可跑工具**。

2026-09-11 由任务书转述的 pi「最小验证」同样回显 `actual_model=deepseek-flash`；该次运行的
thinking 档位没有单独留档，因此**不计入**逐档证据，只作为同日第二次身份回显记录。

## 3. dsh 四任务产物证据（2026-09-11，任务结果）

dsh headless + `deepseek-flash`（本机 dsh 的 `agent-default-model` 即
`deepseek-flash`，`reasoningEffort: max`）当日完成四个真实任务并全部并入主干：

| 任务 | 产物规模/性质 | 结果 |
|---|---|---|
| W-B spike | 11 文件 / 1520 行 | 过门禁、并入 |
| M1 主机页 | 17 文件 | 过门禁、并入 |
| W-C.1 rAF 合帧收尾 | 收尾片 | 过门禁、并入 |
| 0.17.7 补测批 | 重打装机与补测 | 过门禁、并入 |

配套治理记录（同日）：「M1 主机页、W-C.1、W-B spike 三节点当日完成→验收→并入→销账；
DMG 0.17.7 重打装机拉起」，执行侧标注为 dsh/pi + deepseek-flash（订阅口径）。

**强度限制**：`references/supported-agents.yml` 中 dsh 的 `model_integrity: unimplemented`，
dsh 输出没有可核验的模型回显。因此这四条是**任务产物与吞吐证据**，不能单独支撑
`actual_model` 断言；把它们与第 2 节的身份证据合看，组成「身份（pi）+ 多任务产物（dsh）」
的组合证据。

## 4. 价格与峰谷口径

- 结构化价格字段采用第 1 节的 provider 当前价：input 0.30 / cache-hit 0.006 /
  output 1.20（USD/1M），cache-write 显式 0；无 Batch/Priority/长上下文档位。
- 峰谷计费：**北京工作日 09:00–12:00 与 14:00–18:00 为高峰**，按上表标准价；其余时段
  半价。由此推算的 off-peak 价（input 0.15 / cache-hit 0.003 / output 0.6）是**算术推导**，
  已在该条目 `billing_mode_notes` 中标注 derived；catalog 结构化字段保持高峰/标准价，
  不新增第二套数值字段。
- pi 回执在订阅口径下 `cost.total = 0`，实际扣费不可由 catalog 推导。
  catalog 数字只能作为 API 等价估算（与文件头 `notes` 的既有口径一致）。

## 5. 与 catalog 字段的对应关系

- `supported_reasoning_levels: [low, high, max]`：`low`/`max` 为 provider 档位映射声明
  （`max` 另经 dsh 批量任务实际使用），`high` 有第 2 节的 pi 结构化回显；`minimal`/
  `medium` 无映射，刻意不收。catalog 只有一个标量置信度字段，无法按档位分别记录，
  因此 `reasoning_levels_confidence: smoke_tested` 表示**已存在 smoke 级运行证据**，
  不表示三档都做过结构化回显——逐档差异以本文件为准。
- `default_reasoning_level: low`：与既有 pi easy 路由的定位一致；`routing_profile: [easy]`
  使 `route_model.py --executor pi --complexity easy` 选 `deepseek-flash @ low`。
  旧 `deepseek-v4-flash` 因此**撤出自动路由**（`routing_profile: null`），避免发版后
  自动派发继续指向已下线的 id。
- `model_family: deepseek-v4`（**不是** v4.1）：旧 v4 名称的请求现被路由到同一 V4.1 Flash
  后端，reviewer Independence Gate 只比对 provider + model_family，若把新条目单列
  `deepseek-v4.1`，就会出现「用 deepseek-v4-flash 审 deepseek-flash 判为独立」的假独立。
  这是刻意保守选择；等旧条目彻底删除后，可再把家族改名为 v4.1。
- `context_window: 1000000` / 多模态：来自第 1 节 provider 元数据；多模态按
  `deepseek-v4-flash-vision-exp` 的既有写法落在 `billing_mode_notes` 与
  `discovery_evidence` 文本里（catalog 没有独立的模态字段），并明确 image-input 未实测。
- `availability`：新条目 `available`；`deepseek-v4-flash`、`deepseek-v4-flash-vision-exp`
  改为 `deprecated`，两者原验证证据保留在 `discovery_evidence` 前缀说明中。
- `deepseek-v4-pro`：`availability` 暂保持 `available`（09-14 12:00 前仍是自身），
  `billing_mode_notes` 记录 09-14 12:00（北京）起全部请求路由到 V4.1 Flash。
  **没有**写 `future_pricing`：官方只说明「路由」，未明示路由后的账单口径，按
  「未确认事实必须为 null，不得猜数」的编辑规则，不把推测写进会自动影响估算的结构化字段。

## 6. 明确排除（本文件与 catalog 条目都不能声称的事）

- **image-input 未实测**：`input: [text, image]` 只是 provider 声明；没有真实图片派发 case。
- **逐档覆盖不完整**：只有 `high` 有 pi 结构化回显；`low`/`max` 是声明级（`max` 另有 dsh
  任务使用记录），没有各自的 JSONL `message_end` 存档。
- **dsh 身份不可验证**：第 3 节四任务无法独立证明实际模型，不能包装成 `actual_model` 证据。
- **无账单核对**：0.30/1.20 未经官方账单或用量页对账，属 provider 元数据口径。
- **单会话样本**：第 2 节只有一个 pi 会话，不能据此声称全任务类型质量基准。
- **v4-pro 09-14 后计费口径未确认**：见第 5 节最后一条。

## 7. 升级到 `verified` 还差什么

catalog 从未有任何条目使用 `verified`；按 `SKILL.md`「要声称全模型 × 全推理档已验证，
必须保留发现快照、完整 case 清单、逐 case manifest、模型回显和聚合报告」，本条目升级需要：

1. `low` / `high` / `max` 三档各自的 pi `--mode json` 记录，逐档核对 `message.model` 与 usage；
2. 至少一个 image-input case 的端到端证据（否则多模态只能继续标声明级）；
3. 覆盖编码、文档两类任务的 case 清单 + 逐 case manifest + 聚合报告（现在的四任务是
   dsh 侧产物记录，缺模型身份）；
4. 若要进入 medium/hard 自动路由，另需对应难度的产物质量证据与成本对照。

在此之前：`routing_profile` 只开放 `easy`，显式请求按 `explicit` 处理；自动路由状态为
`verified_auto`，档位按 easy 的优先序落在 `low`（provider 声明支持，逐档 JSONL 回显仍缺）。
