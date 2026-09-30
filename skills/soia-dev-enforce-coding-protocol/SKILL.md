---
name: soia-dev-enforce-coding-protocol
description: 给工程改动加范围、权限与验证底线，不另起流程。触发：执行编码协议、核对工程改动是否越界
version: 1.2.3
created_at: 2026-09-08 16:25:00
updated_at: 2026-09-30 13:14:57
created_by: gpt-5
updated_by: claude opus 5.5
---

# soia-dev-enforce-coding-protocol

## 客户可读说明

**能做什么：** 给实现、修复和审查一条共同底线；项目规则已覆盖的不重复安排，也不接管专业验收。

**如何使用：** 把下面约束直接应用到手头的工程改动，不另建计划、状态库、审查轮次或协议报告。只约束代码、配置、测试、Git 与行为契约的改动及其诊断/审查；混合任务只管相关部分，契约不变的纯文字修正、解释和状态汇报不适用。

## 短协议

- **守住请求。** 诊断和审查不授权修复；只改解决当前问题必需的范围。保留他人改动，提交只纳入自己的文件。提交、远端写入、合并、发布、安装及重要删除各自核对授权。
- **先找证伪办法。** 改之前明确预期行为和最小检查；修复先复现，重构检查行为等价。复现不了就说明缺口，不把猜测当根因。
- **按风险加验证。** 局部改动用聚焦测试；公共接口、数据迁移、安全或跨进程边界再查直接消费者、失败路径与恢复。同类模式只在授权范围内排查，不顺手扩大清理。
- **验证行为本体。** 不以吞错、TODO、放松断言、删失败测试或静默 fallback 冒充修复。命令成功不等于目标成立；核对实际输出，保留失败与未覆盖项。
- **到证据足够就停。** 一次针对性验证加差异核对；失败才修对应问题。没有新证据或规则要求，不重开多轮审查、对抗或全套测试。

起草或复审任务书、想知道某条在挡什么时读[失效模式索引](references/failure-modes.md)；设计、清点或复审守卫（pass→fail→pass 取证、台账、例外基线）时读[可证伪守卫](references/falsifiable-guards.md)。

## 使用边界

### 依赖与安装

无强依赖，用目标项目已有工具，不自动安装。单技能 `npx skills add soia-team/soia-open-dev-skills -a <agent> -s soia-dev-enforce-coding-protocol`；整域 `claude plugin install soia-dev@soia` 或 `codex plugin add soia-dev@soia`（先接入市场 soia-team/soia-open-skills）；WorkBuddy 见[专家安装说明](https://github.com/soia-team/soia-open-skills/blob/main/docs/install/workbuddy.md)。完整步骤见[官方安装说明](https://github.com/soia-team/soia-open-skills#安装)；命令不构成安装授权。

**私密信息与中间数据：** 只读任务需要的材料；秘密只报位置与形态。不建专用配置、缓存或状态，必要临时数据放系统临时目录。

**日志与完成回执：** 在原任务结果里简述做了什么、验证结果和缺口，不另交协议报告。
