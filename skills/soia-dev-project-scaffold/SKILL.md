---
name: soia-dev-project-scaffold
description: 为 Git 项目补最小 AI 协作入口与文档导航，优先沿用已有约定。触发：补项目协作基线、初始化 AGENTS、生成文档骨架
version: 1.1.0
created_at: 2026-07-20 11:52:54
updated_at: 2026-09-08 17:24:05
created_by: gpt-5.6-luna
updated_by: gpt-5
---

# soia-dev-project-scaffold

## 客户可读说明

**能做什么：** 为新/空项目建立最小协作入口，或给已有项目补真正缺少的规则与导航。不是应用框架生成器，不默认创建完整治理目录。

**如何使用：** 给目标目录和希望补的内容。先看最近的 AGENTS/CLAUDE、README、构建/测试入口和已有文档布局；保留有效约定，不重建已有体系。

## 最小实施

- 已有项目只补缺项：一句项目定位、可验证常用命令、必要目录职责、特殊安全/完成门，以及已有文档入口。缺命令时写待确认，不发明脚本。
- 多宿主选择一个可维护真源，其他入口按宿主能力做短引用或链接；不盲目覆盖文件、增加 agent/hook/skills 全家桶。
- 已明确授权补齐时用最小补丁；未知同名内容或越界目标先停下确认。保留未提交工作，不自动 git init、安装依赖或提交。

空目录且客户需要下列完整基线时，可用现有脚本（从技能目录运行）：

    bash shells/init-project-baseline.sh <project-path>

它一次创建 AGENTS.md、docs/navigation.md、project-overview.md，以及 product/changelog/ai-workspace/templates 的 README；任一目标已存在即拒绝，不能用它“补一项”。只要少量文件时直接按项目约定创建，不强行运行全套。

## 验证与交付

读回新增内容，核对引用及命令来源，再看 Git diff/status。脚本可用 --help 和 bash -n 检查；实际生成用临时空目录验证，并确认重跑拒绝覆盖。交付创建项、待填事实和未运行命令。

## 使用边界

### 依赖与安装

脚本需要 Bash 与标准文件工具；Git 用于检查，不自动初始化。
默认项目单技能：`npx skills add soia-team/soia-open-dev-skills -a <agent> -s soia-dev-project-scaffold`，执行前核实当前参数。
整域需明确选择：Claude Code 使用 `claude plugin marketplace add` / `claude plugin install soia-dev@soia`，Codex 使用 `codex plugin marketplace add` / `codex plugin add soia-dev@soia`；市场为 soia-team/soia-open-skills，完整步骤见[官方安装说明](https://github.com/soia-team/soia-open-skills#安装)。
WorkBuddy 使用[专家安装说明](https://github.com/soia-team/soia-open-skills/blob/main/docs/install/workbuddy.md)，不由 npx 代装。上述命令不构成安装或发布授权。

**私密信息与中间数据：** 只使用授权材料并对引用脱敏；不需要凭据、不默认建立配置/state/cache。要求保存的交付物写批准位置，临时数据用 OS 临时目录；不将客户原文写进技能仓库。

**日志与完成回执：** 结果本身是主要交付；说明实际变更或未改动、关键依据与未验证部分，不强制额外报告。
