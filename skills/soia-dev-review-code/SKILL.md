---
name: soia-dev-review-code
description: 对固定代码候选或技能包做一次只读审查，区分规格符合性与工程标准，报告可核实问题。触发：审查这次改动、review 代码、检查技能包
version: 1.1.0
created_at: 2026-09-08 16:25:00
updated_at: 2026-09-12 12:00:00
created_by: gpt-5
updated_by: deepseek-flash
---

# soia-dev-review-code

## 客户可读说明

**能做什么：** 判断给定改动是否满足请求、是否引入具体风险；只读，不修复、不提交、不评论到远端、不合并。

**如何使用：** 提供 diff/PR/技能目录及目标。先确认候选版本或本地快照、范围和项目规则；材料不足只说明缺口，不猜版本，也不声称已审。

## 一次审查

1. **先看规格符合性。** 对照请求、已批准设计和验收行为读实际实现，不只看 diff 摘要；找漏做、做错或越界。已有架构是约束，不借审查另选一套。
2. **再看工程标准。** 沿直接调用边界检查正确性、输入安全、错误处理、兼容性和测试断言。只扩展与本次风险有关的视角，不按固定数量凑检查项。
3. **核实候选问题。** 回到原文和调用上下文，检查触发条件、反例与实际影响；能安全运行的聚焦检查可运行，外部副作用不作为审查手段。无法确认的疑点放到未验证项，不包装成缺陷。
4. **交付后停止。** 只报告会改变下一步动作的问题；按严重度给位置、触发条件、影响和依据。没有新 diff、新证据或显式要求，不循环复审。

默认单次审查；只有用户或项目明确要求时使用独立多视角/panel。自查不能冒称独立审查，换一句角色宣言也不是独立证据。升级到独立审查时的执行形态见[独立审查](references/independent-review.md)：两隔离评估、降级横幅与 `Method:` 单行溯源，并与 `soia-dev-agent-cli-dispatch` 的 Independence Gate 显式挂钩。

## 技能包分支

审技能时读取其正文和受影响资源：核对命令/接口、授权门、跨宿主可用性、元数据与依赖一致性。涉及行为变化，检查自检和实际输入的前向测试证据；目录存在或静态校验通过不等于有效。命令核实使用无副作用方式或官方文档，不运行发布、发送或安装来“验证”。

## 结果与边界

**日志与完成回执：** 先给建议，再列可行动问题与覆盖/未验证范围。无问题可以写“未发现可确认问题”，但不保证没有缺陷。可用“建议通过 / 建议先改 / 建议拒绝”；结论不是合并许可。

### 依赖与安装

无强依赖；使用目标项目已有工具，不自动安装依赖。安装与发布分别确认，默认项目、明确宿主、单技能。
项目安装：`npx skills add soia-team/soia-open-dev-skills -a <agent> -s soia-dev-review-code`；执行前核实当前 CLI 参数。
整域需明确选择：先接入市场 `soia-team/soia-open-skills`，Claude Code 用 `claude plugin marketplace add` / `claude plugin install soia-dev@soia`，Codex 用 `codex plugin marketplace add` / `codex plugin add soia-dev@soia`；完整步骤见[官方安装说明](https://github.com/soia-team/soia-open-skills#安装)。
WorkBuddy 使用[专家安装说明](https://github.com/soia-team/soia-open-skills/blob/main/docs/install/workbuddy.md)，不由 npx 代装；上述命令不构成安装授权。

**私密信息与中间数据：** 只读约定范围；不展示秘密或无关源码。检查可能生成缓存时使用临时目录；不改源码、规范、测试或工作树状态。审查前后核对候选未变，变化时把结论限定到已审版本。
