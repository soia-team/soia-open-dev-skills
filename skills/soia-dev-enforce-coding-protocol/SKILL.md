---
name: soia-dev-enforce-coding-protocol
description: 用短协议约束工程改动的范围、权限与验证，不另起流程。触发：执行编码协议、约束本次改动、检查修复是否有证据
version: 1.0.0
created_at: 2026-09-08 16:25:00
updated_at: 2026-09-08 16:25:00
created_by: gpt-5
updated_by: gpt-5
---

# soia-dev-enforce-coding-protocol

## 客户可读说明

**能做什么：** 给实现、修复和审查提供共同底线；项目规则已覆盖的内容不重复安排步骤，也不接管专业验收。

**如何使用：** 提供当前请求和目标项目。把下面约束应用到正在做的事，不另建计划、状态库或审查轮次。

## 短协议

- **守住请求。** 诊断和审查不授权修复；只改解决当前问题必需的范围。保留他人改动，提交只纳入自己的文件。提交、远端写入、合并、发布、安装及重要删除各自核对授权。
- **先找证伪办法。** 改之前明确预期行为和最小检查；修复先复现，重构检查行为等价。不能复现时说明缺口，不把猜测当根因。
- **按风险加验证。** 普通局部改动用聚焦测试；公共接口、数据迁移、安全或跨进程边界检查直接消费者、失败路径与恢复。只在授权范围内排查同类模式，不顺手扩大清理。
- **验证行为本体。** 不以吞错、TODO、放松断言、删除失败测试或静默 fallback 冒充修复。命令成功不等于目标成立；核对实际输出，并保留失败和未覆盖项。
- **到证据足够就停。** 写完做一次针对性验证与差异核对；失败才修复对应问题。没有新证据或规则要求，不重开多轮审查、对抗或全套测试。

## 使用边界

### 依赖与安装

无强依赖；使用目标项目已有工具，不自动安装依赖。安装与发布分别确认，默认项目、明确宿主、单技能。
项目安装：`npx skills add soia-team/soia-open-dev-skills -a <agent> -s soia-dev-enforce-coding-protocol`；执行前核实当前 CLI 参数。
整域需明确选择：先接入市场 `soia-team/soia-open-skills`，Claude Code 用 `claude plugin marketplace add` / `claude plugin install soia-dev@soia`，Codex 用 `codex plugin marketplace add` / `codex plugin add soia-dev@soia`；完整步骤见[官方安装说明](https://github.com/soia-team/soia-open-skills#安装)。
WorkBuddy 使用[专家安装说明](https://github.com/soia-team/soia-open-skills/blob/main/docs/install/workbuddy.md)，不由 npx 代装；上述命令不构成安装授权。

**私密信息与中间数据：** 只读任务需要的材料；秘密只报位置与形态。不创建专用配置、缓存或状态；必要临时数据用系统临时目录。

**日志与完成回执：** 在原任务结果里简述做了什么、验证结果和缺口即可，不另交一份协议报告。
