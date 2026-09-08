---
name: soia-dev-release-plan-checklist
description: 为软件发版设计预检、灰度、停止与回滚清单；只规划，不执行部署。触发：上线前检查什么、设计灰度方案、准备回滚预案
version: 2.1.0
created_at: 2026-07-23 00:03:23
updated_at: 2026-09-08 17:24:05
created_by: gpt-5.6-luna
updated_by: gpt-5
---

# soia-dev-release-plan-checklist

## 客户可读说明

**能做什么：** 为代码、服务或客户端发布形成可执行清单；不执行发布或生产操作。文章与媒体发布不属于本技能。

**如何使用：** 提供范围、版本/提交、制品、目标环境、依赖和已有发布机制。缺失项明确待确认，不猜发布窗口、负责人或阈值。

## 计划方法

- 对齐提交、制品、配置/数据变更与环境；区分已知事实、未验条件和审批，不把生成清单当成已过门。
- 每个关键预检有证据来源与阻断条件：制品可追溯、受影响测试、依赖健康、监控、兼容性和可用回退；沿用团队已有标准。
- 灰度批次说明范围、观察项、通过/停止条件和动作负责人；没有数值依据就标待定，不编造错误率或等待时间。
- 说明暂停、回滚或前向修复的可行边界。数据库/配置变更尤其检查新旧版本共存、不可逆步骤与数据保全，不能假设回滚镜像就能回滚数据。
- 发布后核对关键用户路径、错误/延迟、依赖与数据一致性；只选本次相关项。

## 完成边界

用最短清单交付发布顺序、预检缺口、停止与恢复方案。走读一条实际批次，确认谁根据什么证据决定继续或停止。

默认对话计划，保存到指定位置须在请求范围内；清单通过不授予部署、凭据或远端写入权限。

## 使用边界

### 依赖与安装

无强制软件或第三方技能依赖；使用已授权的项目材料。
默认项目单技能：`npx skills add soia-team/soia-open-dev-skills -a <agent> -s soia-dev-release-plan-checklist`，执行前核实当前参数。
整域需明确选择：Claude Code 使用 `claude plugin marketplace add` / `claude plugin install soia-dev@soia`，Codex 使用 `codex plugin marketplace add` / `codex plugin add soia-dev@soia`；市场为 soia-team/soia-open-skills，完整步骤见[官方安装说明](https://github.com/soia-team/soia-open-skills#安装)。
WorkBuddy 使用[专家安装说明](https://github.com/soia-team/soia-open-skills/blob/main/docs/install/workbuddy.md)，不由 npx 代装。上述命令不构成安装或发布授权。

**私密信息与中间数据：** 只使用授权材料并对引用脱敏；不需要凭据、不默认建立配置/state/cache。要求保存的交付物写批准位置，临时数据用 OS 临时目录；不将客户原文写进技能仓库。

**日志与完成回执：** 结果本身是主要交付；说明实际变更或未改动、关键依据与未验证部分，不强制额外报告。
