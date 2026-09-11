---
name: soia-dev-test-draft-doc
description: 从需求或变更设计测试计划、用例与验收对照，不冒充测试执行。触发：写测试用例、出测试计划、整理回归清单
version: 2.2.0
created_at: 2026-07-23 00:03:56
updated_at: 2026-09-12 12:00:00
created_by: gpt-5.6-luna
updated_by: deepseek-flash
---

# soia-dev-test-draft-doc

## 客户可读说明

**能做什么：** 将需求、规格或变更转为可执行的测试设计。按需要交付计划、用例、回归清单或验收对照，不默认填满所有模板。

**如何使用：** 提供授权材料、目标端、角色和变更范围。规则缺失时列待确认项；不把假设变成通过标准。

## 测试设计

1. 将需求拆为可观察行为：前置状态、动作、结果和不可变约束；沿用已有需求/用例标识，便于追溯。
2. 按影响与风险选择正常、边界、失败和数据流用例。权限、幂等、并发、依赖失败与恢复只在相关时加入；数据变化要检查失败后的一致性。
3. 每例给出可执行前提、步骤和明确预期，不写“系统正常”。高风险行为需有对应负向证据路径；环境或数据前提未知时明确阻塞。
4. 回归范围从共享组件、调用方和关键任务路径推导，不机械复制全量清单。需求到验收之间没有证据的项保持未执行/待确认。

用例草稿的三种反模式（实现耦合、同义反复、横向切片）与 mock 边界见[测试反模式](references/anti-patterns.md)；写用例与交付前自检时按需加载。

## 交付边界

测试计划说明范围、环境/数据、主要风险和准入准出；用例按客户已有字段组织，缺规则单列。只有实际执行记录才能把状态改为通过，本技能生成用例不等于运行测试，也不接管 TDD 实现。

默认在对话交付；要求保存时写指定位置。交付前选关键用例走读其输入、结果和失败后的数据状态，确认能够独立判定。

## 使用边界

### 依赖与安装

无强制软件或第三方技能依赖；使用已授权的项目材料。
默认项目单技能：`npx skills add soia-team/soia-open-dev-skills -a <agent> -s soia-dev-test-draft-doc`，执行前核实当前参数。
整域需明确选择：Claude Code 使用 `claude plugin marketplace add` / `claude plugin install soia-dev@soia`，Codex 使用 `codex plugin marketplace add` / `codex plugin add soia-dev@soia`；市场为 soia-team/soia-open-skills，完整步骤见[官方安装说明](https://github.com/soia-team/soia-open-skills#安装)。
WorkBuddy 使用[专家安装说明](https://github.com/soia-team/soia-open-skills/blob/main/docs/install/workbuddy.md)，不由 npx 代装。上述命令不构成安装或发布授权。

**私密信息与中间数据：** 只使用授权材料并对引用脱敏；不需要凭据、不默认建立配置/state/cache。要求保存的交付物写批准位置，临时数据用 OS 临时目录；不将客户原文写进技能仓库。

**日志与完成回执：** 结果本身是主要交付；说明实际变更或未改动、关键依据与未验证部分，不强制额外报告。
