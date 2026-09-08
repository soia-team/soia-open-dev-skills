---
name: soia-dev-implement-task
description: 在明确授权内实现需求、诊断修复或处理 findings，合并执行与修复流程。触发：实现这个任务、修复这个 bug、处理审查发现
version: 1.0.0
created_at: 2026-09-08 16:25:00
updated_at: 2026-09-08 16:25:00
created_by: gpt-5
updated_by: gpt-5
---

# soia-dev-implement-task

## 客户可读说明

**能做什么：** 把一个工程需求、缺陷或 finding 做到可验证的完成；代码、配置和文档都可用。不把“只诊断”变成改代码。

**如何使用：** 提供目标、所在项目及已知约束。有足够信息就推进；只有会改变结果、权限或安全的歧义才暂停对应动作。

## 实施

1. **找到最小工作边界。** 读目标项目规则、相关实现与直接调用方，确认现有改动和验收行为。复用项目已有任务记录；普通局部修改不另建治理系统。
2. **沿一条可验证行为推进。** 需求先写或选一个具体验收例；适合自动化时，测试失败 → 最小实现 → 测试通过，再做必要整理。不先批量写完所有测试或改完整个模块。
3. **缺陷先定位。** 从输入、日志或失败测试复现，沿数据和调用路径找到首个偏离预期的位置；验证一个具体假设再修改。只要求诊断时，交付原因、证据与修复建议后停止。
4. **Findings 逐条决策。** 按当前候选核实问题，标为 fix、reject 或 defer 并给理由。只修已授权且成立的项；不靠编号全部消失冒充完成。
5. **验证并收口。** 跑最靠近改动的检查，核对真实结果与最终 diff；高风险边界补直接消费者和失败路径。测试失败只推进相关修复，有新证据才扩大验证。停止无进展重试，报告还缺什么。

普通接口只检查它实际承诺的输入、输出和消费者；**仅修改 AI Provider 适配时**读取 [AI Provider 验收](references/ai-provider.md)。不要把消息、工具或计费检查套到所有 adapter。

## 交付与边界

- 沿用已批准架构和样式；出现跨组件契约或不可逆迁移决策时，先说明需要确认的选择，局部实现不重开架构设计。
- 不吞错、不削弱断言或静默降级来变绿；保留历史失败，区分本次通过与未覆盖的全局问题。
- 不自动调用 review、panel 或外部 Agent；有明确要求时才安排。提交、合并、发布、部署、安装或扩大修复范围，不由“实现完成”自动授权。
- **日志与完成回执：** 结果在前，附关键改动、真实检查与残余风险；finding 输入另列 fix/reject/defer。没有实际运行的检查直说未验证，不凑固定字段。
### 依赖与安装

无强依赖；使用目标项目已有工具，不自动安装依赖。安装与发布分别确认，默认项目、明确宿主、单技能。
项目安装：`npx skills add soia-team/soia-open-dev-skills -a <agent> -s soia-dev-implement-task`；执行前核实当前 CLI 参数。
整域需明确选择：先接入市场 `soia-team/soia-open-skills`，Claude Code 用 `claude plugin marketplace add` / `claude plugin install soia-dev@soia`，Codex 用 `codex plugin marketplace add` / `codex plugin add soia-dev@soia`；完整步骤见[官方安装说明](https://github.com/soia-team/soia-open-skills#安装)。
WorkBuddy 使用[专家安装说明](https://github.com/soia-team/soia-open-skills/blob/main/docs/install/workbuddy.md)，不由 npx 代装；上述命令不构成安装授权。
- **私密信息与中间数据：** 最小范围读写，保留他人改动；秘密不进源码、日志或回执。临时复现用系统临时目录，客户交付物用确认的路径。
