---
name: soia-dev-draft-feature-spec
description: 把产品想法或需求材料整理成可验收的功能规格，并按需拆成纵向交付切片。触发：起草功能规格、把需求写成 PRD、拆分可验收功能
version: 3.1.0
created_at: 2026-07-23 00:02:50
updated_at: 2026-09-12 12:00:00
created_by: gpt-5
updated_by: deepseek-flash
---

# soia-dev-draft-feature-spec

## 客户可读说明

**能做什么：** 从想法或已有材料起草产品功能规格/PRD；需要实施计划时，再按可独立验证的用户结果拆分。交付是草稿与待确认项，不是立项、排期或实现承诺。

**如何使用：** 描述用户、问题、用途与已知约束，或给已有需求。只追问会改变范围、权限或验收的缺口；其余标明假设继续，不为填模板阻塞。

## 写清功能

- 从问题与证据出发，明确目标用户、成功信号、包含与排除范围。没有研究或指标基线就写未知，不编造数值。
- 描述主要场景、用户动作、系统反馈和状态/权限边界；异常、重试、取消和数据变化只覆盖真实相关路径。
- 每项必需能力对应可观察验收：前置条件、动作、结果及关键失败/边界。功能说明不提前锁死技术实现。
- 验收标准按[验收标准起草](references/acceptance-authoring.md)写：逐条可判定、独立可验证，并各配一条反例或负控说明。
- 标明依赖、风险、假设与待决事项；把用户明确要求和可选建议分开，保留已批准约束，不擅自删减全量要求。
- 先核对产品已有功能和规范，复用真源；不另建一套 PRODUCT/DESIGN 文档或复制治理系统。

## 按需拆分

只有用户要求计划或范围确需分阶段时才拆。每个切片尽量贯通一个用户结果、相关数据/API/UI 与验收，标出前置依赖和集成接缝；不要仅按“先全后端、再全前端”分层，也不强制每片都新增三层。

一次机械改动的爆炸半径横跨全库、没有纵向切片能单独保持绿时，按[横向重构例外](references/wide-refactor.md)出 expand–contract 三段与阻塞链；默认仍是纵向切片。

日期、人力、优先级和发布窗口没有依据就留待定。起草切片不代表已经建立或授权 Goal/Task；由目标项目既有准入流程承接。

## 交付

用客户模板或最短完整结构呈现问题、范围、行为、验收与开放项。逐项复核必需范围没有遗漏、矛盾已暴露、预期可验证。

通用提示词起草/消歧归 meta-prompt-clarity；技术架构归 govern-architecture；本技能不执行实现、部署或远端写入。默认对话草稿，要求保存时只写指定位置。

## 使用边界

### 依赖与安装

无强制第三方技能依赖；读取或编辑所选材料的能力由宿主提供。
默认项目单技能：`npx skills add soia-team/soia-open-dev-skills -a <agent> -s soia-dev-draft-feature-spec`，执行前核实当前参数。
整域需明确选择：Claude Code 使用 `claude plugin marketplace add` / `claude plugin install soia-dev@soia`，Codex 使用 `codex plugin marketplace add` / `codex plugin add soia-dev@soia`；市场为 soia-team/soia-open-skills，完整步骤见[官方安装说明](https://github.com/soia-team/soia-open-skills#安装)。
WorkBuddy 使用[专家安装说明](https://github.com/soia-team/soia-open-skills/blob/main/docs/install/workbuddy.md)，不由 npx 代装。上述命令不构成安装或发布授权。

**私密信息与中间数据：** 只使用授权材料并对引用脱敏；不需要凭据、不默认建立配置/state/cache。要求保存的交付物写批准位置，临时数据用 OS 临时目录；不将客户原文写进技能仓库。

**日志与完成回执：** 结果本身是主要交付；说明实际变更或未改动、关键依据与未验证部分，不强制额外报告。
