---
name: soia-dev-agent-md-advisor
description: 诊断、起草或精简 AI 项目指令，解决无效规则、重复和入口冲突。触发：精简 AGENTS.md、CLAUDE.md 怎么组织、检查 AI 指令冲突
version: 1.1.0
created_at: 2026-07-10 09:10:23
updated_at: 2026-09-08 17:24:05
created_by: claude opus 4.6
updated_by: gpt-5
---

# soia-dev-agent-md-advisor

## 客户可读说明

**能做什么：** 判断 AGENTS/CLAUDE/GEMINI 等指令文件是否清楚、有效、职责合适；按请求诊断、起草或改写。跨文档状态对账归 doc-sync，项目初始化归 project-scaffold。

**如何使用：** 提供文件或目标项目及不满意之处。只问答就直接回答；审查默认只读；明确要求优化/重写时可直接修改已授权文件，不再让用户重复批准同一动作。

## 判断重点

- 删掉一条是否改变行为？删除不产生影响的背景、重复训话和固定回执，保留真正的不可回退边界。
- 规则能否执行与验证？命令/路径来自项目事实；确定性检查交已有工具，不用形容词代替标准。
- 根文件只管共享约束和路由，模块要求就近维护。不要为了短而把必需门藏到不可发现的文件。
- 同一事实只留一个真源；跨宿主入口保持语义一致。真实冲突标明层级与适用范围，不自行删除更严格的安全或授权要求。
- 引用的路径、命令和版本核实到本次实际范围；无法核实就标未知，不凭印象补产品规则。

## 起草与改写

先利用可读的项目事实，只有信息会改变目标结构时才问。给最小可用草稿或补丁；保留未知 frontmatter 与未授权配置，不默认增添 hooks、agents、commands 或长期状态文件。

批量搬移/删入口前检查消费者。修改后从 diff 核对用户意图、义务强度和有效限制均未丢失，检查相对引用与命令入口。

## 交付

只报告有证据的问题和必要改法，不固定评分、问题数或六维报告。说明已改还是建议、验证缺口及待决定事项；无需重复输出整个未改文件。

## 使用边界

### 依赖与安装

无强制软件或第三方技能依赖；使用已授权的项目材料。
默认项目单技能：`npx skills add soia-team/soia-open-dev-skills -a <agent> -s soia-dev-agent-md-advisor`，执行前核实当前参数。
整域需明确选择：Claude Code 使用 `claude plugin marketplace add` / `claude plugin install soia-dev@soia`，Codex 使用 `codex plugin marketplace add` / `codex plugin add soia-dev@soia`；市场为 soia-team/soia-open-skills，完整步骤见[官方安装说明](https://github.com/soia-team/soia-open-skills#安装)。
WorkBuddy 使用[专家安装说明](https://github.com/soia-team/soia-open-skills/blob/main/docs/install/workbuddy.md)，不由 npx 代装。上述命令不构成安装或发布授权。

**私密信息与中间数据：** 只使用授权材料并对引用脱敏；不需要凭据、不默认建立配置/state/cache。要求保存的交付物写批准位置，临时数据用 OS 临时目录；不将客户原文写进技能仓库。

**日志与完成回执：** 结果本身是主要交付；说明实际变更或未改动、关键依据与未验证部分，不强制额外报告。
