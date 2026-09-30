---
name: soia-dev-draft-feature-spec
description: 把产品想法或需求整理成可验收的功能规格，按需拆成纵向交付切片。触发：起草功能规格、把需求写成 PRD、补验收标准
version: 3.2.2
created_at: 2026-07-23 00:02:50
updated_at: 2026-09-30 13:14:57
created_by: gpt-5
updated_by: claude opus 5.5
---

# soia-dev-draft-feature-spec

## 客户可读说明

**能做什么：** 从想法或已有材料起草功能规格/PRD；需要实施计划时再按可独立验证的用户结果拆分。交付是草稿与待确认项，不是立项、排期或实现承诺。

**如何使用：** 描述用户、问题、用途与已知约束，或给已有需求。只追问会改变范围、权限或验收的缺口；其余标明假设继续。

## 写清功能

- 从问题与证据出发，写目标用户、成功信号、包含与排除范围。没有研究或指标基线就写未知，不编造数值。
- 写主要场景、用户动作、系统反馈与状态/权限边界；异常、重试、取消和数据变化只覆盖真实相关路径。
- 每项必需能力对应可判定、可独立验证的验收：前置条件、动作、结果及关键失败/边界，权限、数据或失败路径补反例；不提前锁死技术实现。项目要求正式验收条目或设计守卫时读[验收标准起草](references/acceptance-authoring.md)。
- 标明依赖、风险、假设与待决事项；用户明确要求与可选建议分开，保留已批准约束，不擅自删减必需范围。
- 复用产品已有功能与规范真源，不另建一套 PRODUCT/DESIGN 文档或治理系统。

## 按需拆分

只有用户要计划或范围确需分阶段时才拆。每个切片尽量贯通一个用户结果及其数据/API/UI 与验收，标出前置依赖和集成接缝；不要仅按“先全后端、再全前端”分层，也不强制每片都跨三层。

一次机械改动横跨全库、没有纵向切片能单独保持绿时，按[横向重构例外](references/wide-refactor.md)出 expand–contract 三段与阻塞链。

日期、人力、优先级和发布窗口没依据就留待定。切片草稿不等于已建立或授权 Goal/Task，由目标项目的准入流程承接。

## 交付

用客户模板或最短完整结构写问题、范围、行为、验收与开放项，矛盾当场暴露。提示词起草归 `soia-meta-prompt-clarity`，技术架构归 `soia-dev-govern-architecture`；本技能不做实现、部署或远端写入。默认在对话里交草稿，要求保存时只写指定位置。

## 使用边界

### 依赖与安装

无强制技能依赖。单技能 `npx skills add soia-team/soia-open-dev-skills -a <agent> -s soia-dev-draft-feature-spec`；整域 `claude plugin install soia-dev@soia` 或 `codex plugin add soia-dev@soia`（先接入市场 soia-team/soia-open-skills）；WorkBuddy 见[专家安装说明](https://github.com/soia-team/soia-open-skills/blob/main/docs/install/workbuddy.md)。完整步骤见[官方安装说明](https://github.com/soia-team/soia-open-skills#安装)；命令不构成安装授权。

**私密信息与中间数据：** 只用授权材料，引用脱敏；不需要凭据，不建配置/state/cache。要保存的交付物写批准位置，临时数据放系统临时目录，客户原文不进技能仓库。

**日志与完成回执：** 规格草稿本身是主要交付；说明关键依据、假设与待决项。
