---
name: soia-dev-doc-sync
description: 核对代码、发布事实和有效裁决与文档之间的漂移，按授权同步派生内容。触发：文档和代码对不上、同步发布文档、核对状态文档
version: 1.1.0
created_at: 2026-07-20 17:22:49
updated_at: 2026-09-08 17:24:05
created_by: gpt-5.6-terra
updated_by: gpt-5
---

# soia-dev-doc-sync

## 客户可读说明

**能做什么：** 查出文档事实漂移，并在用户要求同步时修复。不是普通写作，也不为消除差异修改代码或有效裁决。

**如何使用：** 指定仓库、文档范围和已知真源。只检查时保持只读；已要求同步时直接修复范围内有证据的偏差，不逐段重新询问。

## 对账方法

- 先区分事实类型：代码、schema、manifest 与可复核运行证据证明现状；用户裁决、ADR 和规格约束目标/授权；发布记录证明实际发布。README 和旧报告不能互相佐证为当前事实。
- 为有差异的声明找真源及消费者，核对状态、版本、数量、命令、术语、链接和多语言。当前与目标冲突要登记偏差，不能把目标偷偷改成现状。
- 优先使用已有生成器；真源冲突未解时暂停该项回填。先更新有效摘要和入口，再同步派生层，不建立第二套状态库。
- 历史证据保留时点并指向当前来源，不把旧失败改成成功，也不把“已合并/任务完成”写成“已发布/Goal 通过”。

## 验证与交付

每个补丁要能回到具体证据或用户裁决；从另一条路径重新计算关键数量、核对版本/链接并搜索相邻旧值。文档检查器通过只证明其检查范围，不能替代事实核验。

交付说明修复的实质漂移、真源、实际检查和剩余冲突。无需固定分类账或多字段回执。保留他人改动；不自动发布、覆盖远端或变更任务状态。

## 使用边界

### 依赖与安装

无强制软件或第三方技能依赖；使用已授权的项目材料。
默认项目单技能：`npx skills add soia-team/soia-open-dev-skills -a <agent> -s soia-dev-doc-sync`，执行前核实当前参数。
整域需明确选择：Claude Code 使用 `claude plugin marketplace add` / `claude plugin install soia-dev@soia`，Codex 使用 `codex plugin marketplace add` / `codex plugin add soia-dev@soia`；市场为 soia-team/soia-open-skills，完整步骤见[官方安装说明](https://github.com/soia-team/soia-open-skills#安装)。
WorkBuddy 使用[专家安装说明](https://github.com/soia-team/soia-open-skills/blob/main/docs/install/workbuddy.md)，不由 npx 代装。上述命令不构成安装或发布授权。

**私密信息与中间数据：** 只使用授权材料并对引用脱敏；不需要凭据、不默认建立配置/state/cache。要求保存的交付物写批准位置，临时数据用 OS 临时目录；不将客户原文写进技能仓库。

**日志与完成回执：** 结果本身是主要交付；说明实际变更或未改动、关键依据与未验证部分，不强制额外报告。
