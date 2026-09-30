---
name: soia-dev-github-ops
description: 查询和操作 GitHub PR、CI、Release 与协作者权限。触发：查 GitHub CI、处理 PR 生命周期、管理仓库协作者
version: 2.3.2
created_at: 2026-07-09 07:45:34
updated_at: 2026-09-30 13:14:57
created_by: claude opus 4.6
updated_by: claude opus 5.5
dependencies:
  optional: [soia-dev-review-code, soia-dev-implement-task]
---

# soia-dev-github-ops

## 客户可读说明

**这个技能可以做什么：** 用 gh CLI 查询或操作 GitHub issue、PR、checks、workflow、release 和协作者权限。纯本地 commit、rebase、worktree 管理不用本技能。

**客户如何使用：** 给仓库或对象 URL 和要做的动作。查询不授权修复或远端写入；已批准、范围未变的完整工作流连续推进，不逐命令重复确认。

### 依赖与安装

依赖已安装并认证的 `gh`。进入代码审查或修复时才用 `soia-dev-review-code` / `soia-dev-implement-task`，缺失只暂停需要它的部分，不自动安装。

单技能 `npx skills add soia-team/soia-open-dev-skills -a <agent> -s soia-dev-github-ops`；整域 `claude plugin install soia-dev@soia` 或 `codex plugin add soia-dev@soia`（先接入市场 soia-team/soia-open-skills）；WorkBuddy 见[专家安装说明](https://github.com/soia-team/soia-open-skills/blob/main/docs/install/workbuddy.md)。完整步骤见[官方安装说明](https://github.com/soia-team/soia-open-skills#安装)；命令不构成安装授权。

可选非秘密默认值用[配置模板](assets/config.example.yml)，位置 `~/.config/soia-skills/soia-dev-github-ops/config.yml`，覆盖变量 `SOIA_DEV_GITHUB_OPS_CONFIG_FILE`；不需要默认值就不建。

## 核心流程与安全边界

- **定位目标。** 显式 `--repo <owner>/<repo>` 优先，其次当前 checkout remote、`GITHUB_REPOSITORY` 或技能私有配置；仍有歧义才问。用 `--json` / `--jq` 只取必要字段。
- **认证一次。** 本任务首次 GitHub 操作查 `gh auth status`，凭据/账号变化或认证失败后再查。缺认证只阻断需认证的动作，走官方登录流程，不读取 token 值。
- **写入须明确授权。** 评论、review、push、PR、merge、release、workflow dispatch、关闭对象等须属于当前明确要求；已有计划明确覆盖目标与影响时复用授权。发布、生产操作、分支/标签删除等高影响动作未被明确覆盖时先展示计划并确认。合并不自动授权删分支，脚本附带的清理也要单独核对。
- **协作者权限是独立硬门。** 写前在当前交流中重述仓库、用户名和权限级别并取得明确确认，不从较早对话推断；执行前读下方协作者手册，完成后查实际 role。
- **按风险验证结果。** 写入后另做只读查询确认远端状态。合并前核对固定候选、仓库政策与当前 CI/review/mergeable；release 核对 tag、draft/prerelease 与发布时间。不改保护或削弱检查来绕过失败。
- **失败围绕当前原因处理。** CI 先定位失败 run/job 的首个可行动错误，有安全复现条件时只复现相关检查；无新证据不重复同一失败命令，普通 CI 查询不跑全仓测试。

## 按需分支

只读实际参与本次交付的手册：

| 当前工作 | 读取 |
|---|---|
| 需要 gh 查询、PR、CI 或 release 命令示例 | [命令模式](references/github-command-patterns.md) 中相应部分 |
| 合并前规则审查 | [Pre-Merge Rule Review](references/pre-merge-rule-review.md) |
| 已要求修复评审意见 | [Address Review Feedback](references/address-review-feedback.md) |
| 授予、撤销或核查协作者权限 | [Collaborator Access](references/collaborator-access.md) |

SOIA 技能正式发版另守发布技能和目标仓规则；本技能只提供 GitHub 操作，不替代版本列车、CI 或市场 pin 门禁。

## 私密信息与中间数据

凭据只由 `gh auth login` 官方存储或系统凭据库管理，不进配置、命令参数、源码、远端正文或日志。私有 PR/issue/成员/日志按任务最小读取与披露，默认结构化 stdout，不存完整响应；客户要导出时写其指定位置，临时响应放系统临时目录，不建 state/cache。

## 日志与完成回执

给结果、准确的 repo/对象编号或 URL、实际验证与阻塞；写操作说明实际变更。事实与 CI 原因推断分开，认证错误只报配置路径，不复述凭据。

维护本技能时的前向测试：改查询/操作流程后用真实只读对象核对编号、URL、分支与状态字段，并确认不存在的对象不会被报成成功；写流程只在客户明确授权时测，写后独立查询。
