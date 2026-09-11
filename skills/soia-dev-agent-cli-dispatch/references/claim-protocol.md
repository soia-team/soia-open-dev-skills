# 认领协议（claim protocol）

派单制下，**认领是开工的前置动作**：执行者在动手前先把自己登记为任务的认领者。本文件定义任务书头部的 `claimed_by` 字段、可抓取前沿（frontier）判据、每会话上限，以及与 `dispatch-contract.md` 状态枚举的对齐方式，并给出本仓 `claim_cli` 的三步实照。

主文件按需一跳加载本文件；任务书其余字段见 `task-brief.md`。

## 内容导航

- `claimed_by`：认领即一个字段
- 可抓取前沿：open + unblocked + unclaimed
- 每会话最多解一票
- 与状态枚举对齐
- `claim_cli` 三步实照

## `claimed_by`：认领即一个字段

任务书头部保留一个显式字段：

```yaml
claimed_by: <executor-id>     # 留空 = 尚未被认领
gate_tier: A | B | C          # 复审强度档，见 execution-policy §5.3
```

**填写 `claimed_by` 这个动作本身就是认领。** 不需要额外的标签、状态库或第二套记账：字段有值即已认领，无值即可抓取。字段是任务书的一部分，与任务书同源、同生命周期，因此不引入需要单独同步的状态副本。

同一任务同时只有一个 `claimed_by`。认领范围发生实质变化时，先更新该字段再写新增范围；权限、发布或破坏性动作另取明确授权，不由认领自动覆盖。

## 可抓取前沿：open + unblocked + unclaimed

一个任务可被当前执行者抓取，当且仅当三个条件同时成立：

| 条件 | 判据 | 在哪看 |
|---|---|---|
| **open** | 任务未完成、未取消 | 任务书自身的存在与状态行 |
| **unblocked** | 它声明的前置任务全部完成 | 任务书的依赖/阻塞字段 |
| **unclaimed** | `claimed_by` 为空 | 任务书头部 |

三者交集就是**前沿（frontier）**——当下真正可以开工的那一批任务。按这个判据选任务，执行者不必询问「我现在做哪个」，也不会出现两人同时改同一片。

依赖未满足时任务留在 frontier 之外：它仍是有效的计划，只是还没轮到。这条让我们能提前把任务书写全，而不必等前置完成才动笔。

## 每会话最多解一票

**一个会话最多解决一个任务。** 完成一个任务后，执行者交出回执并结束；下一个任务由主控重新派发或由同一执行者在新的会话里重新认领。

这条上限服务于两件事：其一，单个会话的上下文预算与一个任务的验收边界对齐，任务书可以按「一个上下文窗口装得下」来裁尺寸；其二，认领与回执一一对应，主控核对证据时不必在一个会话里分辨哪段输出来自哪张票。

## 与状态枚举对齐

认领不新造状态词。运行的每个阶段映射到 `dispatch-contract.md` 的状态枚举全集（`pending` / `running` / `passed` / `failed` / `unsupported` / `blocked_auth` / `blocked_quota` / `blocked_paid_api` / `blocked_independence` / `pending_quota` / `timeout` / `fallback_or_downgrade` / `actual_model_unverified` / `interrupted` / `not_tested`）：

| 认领阶段 | 对应状态 | 说明 |
|---|---|---|
| 任务已写入、`claimed_by` 为空、未派发 | `pending` | 在前沿等待被抓取 |
| 已认领，执行中 | `running` | 持有有效 Claim/Lease/fencing |
| 完成且模型证据满足该执行器门禁 | `passed` | 只表示调用成功，产物质量仍由主控独立验收 |
| 执行失败 | `failed` | 附失败分类与可复跑命令 |
| 执行器明确表示不支持该模型或参数 | `unsupported` | 与「我们没测过」的 `not_tested` 分开 |
| 认证、额度或付费确认未满足 | `blocked_auth` / `blocked_quota` / `blocked_paid_api` | 调用没有发生 |
| Independence Gate 拒绝本次 reviewer 派发 | `blocked_independence` | 调用没有发生，不降级成 `not_tested` |
| 租约到期或主动释放 | `interrupted` | 证据保留，不丢弃 |
| 缺少可信的实际模型证据 | `actual_model_unverified` | 不拿请求值填实际值 |
| 从未派发 | `not_tested` | 与 `unsupported` 分开 |

## `claim_cli` 三步实照

本仓协调器用 `plugins/ai-workbench/backend/ai_workbench/goals/claim_cli.py` 在 daemon 记账中登记 Claim。实施 worktree 在**第一次写入前**走完三步：

```bash
CLI=plugins/ai-workbench/backend/ai_workbench/goals/claim_cli.py

# 1. 创建可领取的 TaskRun；--resource 声明本次要写的受保护资源
python3 "$CLI" create-task \
  --task-definition-id <TASK-ID> \
  --goal-id <GOAL-ID> \
  --resource <protected-resource-key> \
  --scope "<人读范围说明>"

# 2. 领取：--resource 必须与 create-task 一致；--scope 记入 task.claimed 事件
python3 "$CLI" claim \
  --task-definition-id <TASK-ID> \
  --executor <executor-id> \
  --resource <protected-resource-key> \
  --scope "<人读范围说明>" \
  --lease-seconds 7200 \
  --grace-seconds 1800 \
  --worktree <worktree-root>

# 3. 完成：三个凭据都来自 claim 的回执
python3 "$CLI" complete \
  --task-definition-id <TASK-ID> \
  --claim-id <CLAIM-ID> \
  --lease-id <LEASE-ID> \
  --fencing-token <FENCING-TOKEN>
```

配套动作：`heartbeat` 续租；`release` 主动释放；`recover` 人工恢复 `recovery_required` 的 TaskRun；`checkpoint` 把生成区写回 `runtime-status.md`。Claim 的资源范围变化时先更新 Claim 再写新增范围。

**只有资源范围不相交、且各持有效 Claim/Lease/fencing 的写任务才并行。** 互不写文件的 reviewer/advisor 不占写入 Claim。Claim 超过 Host 的 `effective_capacity` 时直接失败，容量由协调者用 `capacity --set N --reason TEXT` 设置。

## 来源与承接说明

- **「assignee 即 claim」、frontier = open + unblocked + unclaimed、每会话最多解一票、按名字引用**：承接自 `mattpocock` 仓 `wayfinder` 技能的地图/票体例（外部概念）；原文依赖 issue tracker 的 assignee 字段与原生阻塞关系，本仓按「不建立第二套状态库」的边界改造为任务书头部一个显式 `claimed_by` 字段 + 「未填写即可抓取」的最简形态，不引入 tracker、标签体系或第二套依赖图。
- **状态枚举对齐**：以本仓 `references/dispatch-contract.md` 的 15 状态全集为唯一真源，认领各阶段映射其上，不新增状态词——同一可变列表在全仓只保留一份机器可读真源。
- **实战素材**：三步协议、`--resource` 一致性、`--scope` 人读说明、租约与 fencing 凭据、写任务并行条件、容量门，全部取自本仓 `soiadeck` 仓 `docs/governance/goals/execution-policy.md` §4 与 `plugins/ai-workbench/backend/ai_workbench/goals/claim_cli.py` 的实际命令签名（`create-task` / `claim` / `complete` / `heartbeat` / `release` / `recover` / `checkpoint` / `capacity`）。
- **实战素材（指令号）**：`owner-directives` 指令 164（主控不生产、生产性动作派执行者、主控只裁决验收记账）为「先认领后开工」的分工依据；指令 219③（每单验收时未解决问题逐条定去向后才销账）为「完成必须交出可核回执」的依据；指令 222（图状态回写必须逐条附一手证据）为「`passed` 只表示调用成功、产物质量另由主控独立验收」的依据。
