---
name: soia-dev-project-scaffold
description: 为 Git 项目补最小 AI 协作入口与文档导航，或诊断、起草、精简 AI 项目指令。触发：补项目协作基线、初始化 AGENTS、生成文档骨架、精简 AGENTS.md、CLAUDE.md 怎么组织、检查 AI 指令冲突
version: 1.2.0
created_at: 2026-07-20 11:52:54
updated_at: 2026-11-11 18:00:00
created_by: gpt-5.6-luna
updated_by: claude-fable-5-2
---

# soia-dev-project-scaffold

## 客户可读说明

**能做什么：** 两类活，按请求选一节，不必两节都做：

- **补协作基线**：为新/空项目建立最小协作入口，或给已有项目补真正缺少的规则与导航。不是应用框架生成器，不默认创建完整治理目录。
- **指令顾问**：判断 AGENTS/CLAUDE/GEMINI 等指令文件是否清楚、有效、职责合适；按请求诊断、起草或改写。

跨文档状态对账归 doc-sync。

**如何使用：** 补基线时给目标目录和希望补的内容；先看最近的 AGENTS/CLAUDE、README、构建/测试入口和已有文档布局，保留有效约定，不重建已有体系。做指令顾问时提供文件或目标项目及不满意之处：只问答就直接回答；审查默认只读；明确要求优化/重写时可直接修改已授权文件，不再让用户重复批准同一动作。

## 补协作基线：最小实施

- 已有项目只补缺项：一句项目定位、可验证常用命令、必要目录职责、特殊安全/完成门，以及已有文档入口。缺命令时写待确认，不发明脚本。
- 多宿主选择一个可维护真源，其他入口按宿主能力做短引用或链接；不盲目覆盖文件、增加 agent/hook/skills 全家桶。
- 已明确授权补齐时用最小补丁；未知同名内容或越界目标先停下确认。保留未提交工作，不自动 git init、安装依赖或提交。

空目录且客户需要下列完整基线时，可用现有脚本（从技能目录运行）：

    bash shells/init-project-baseline.sh <project-path>

它一次创建 AGENTS.md、docs/navigation.md、project-overview.md，以及 product/changelog/ai-workspace/templates 的 README；任一目标已存在即拒绝，不能用它“补一项”。只要少量文件时直接按项目约定创建，不强行运行全套。

### 基线的验证与交付

读回新增内容，核对引用及命令来源，再看 Git diff/status。脚本可用 --help 和 bash -n 检查；实际生成用临时空目录验证，并确认重跑拒绝覆盖。交付创建项、待填事实和未运行命令。

## 指令顾问：诊断、起草与精简

### 判断重点

- 删掉一条是否改变行为？删除不产生影响的背景、重复训话和固定回执，保留真正的不可回退边界。
- 规则能否执行与验证？命令/路径来自项目事实；确定性检查交已有工具，不用形容词代替标准。
- 根文件只管共享约束和路由，模块要求就近维护。不要为了短而把必需门藏到不可发现的文件。
- 同一事实只留一个真源；跨宿主入口保持语义一致。真实冲突标明层级与适用范围，不自行删除更严格的安全或授权要求。
- 引用的路径、命令和版本核实到本次实际范围；无法核实就标未知，不凭印象补产品规则。

### 起草与改写

先利用可读的项目事实，只有信息会改变目标结构时才问。给最小可用草稿或补丁；保留未知 frontmatter 与未授权配置，不默认增添 hooks、agents、commands 或长期状态文件。

批量搬移/删入口前检查消费者。修改后从 diff 核对用户意图、义务强度和有效限制均未丢失，检查相对引用与命令入口。

### 顾问的交付

只报告有证据的问题和必要改法，不固定评分、问题数或六维报告。说明已改还是建议、验证缺口及待决定事项；无需重复输出整个未改文件。

## 使用边界

### 依赖与安装

脚本需要 Bash 与标准文件工具；Git 用于检查，不自动初始化。
默认项目单技能：`npx skills add soia-team/soia-open-dev-skills -a <agent> -s soia-dev-project-scaffold`，执行前核实当前参数。
整域需明确选择：Claude Code 使用 `claude plugin marketplace add` / `claude plugin install soia-dev@soia`，Codex 使用 `codex plugin marketplace add` / `codex plugin add soia-dev@soia`；市场为 soia-team/soia-open-skills，完整步骤见[官方安装说明](https://github.com/soia-team/soia-open-skills#安装)。
WorkBuddy 使用[专家安装说明](https://github.com/soia-team/soia-open-skills/blob/main/docs/install/workbuddy.md)，不由 npx 代装。上述命令不构成安装或发布授权。

**私密信息与中间数据：** 只使用授权材料并对引用脱敏；不需要凭据、不默认建立配置/state/cache。要求保存的交付物写批准位置，临时数据用 OS 临时目录；不将客户原文写进技能仓库。

**日志与完成回执：** 结果本身是主要交付；说明实际变更或未改动、关键依据与未验证部分，不强制额外报告。
