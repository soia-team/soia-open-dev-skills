---
name: soia-dev-audit-ui
description: 只读验收界面，技术证据与 UX/视觉判断分开报告。触发：验收这个界面、检查键盘和布局、评审视觉体验
version: 1.2.2
created_at: 2026-09-08 17:24:05
updated_at: 2026-09-30 13:14:57
created_by: gpt-5
updated_by: claude opus 5.5
---

# soia-dev-audit-ui

## 客户可读说明

**能做什么：** 对固定页面、原型或截图做一次聚焦验收，给出可复现的问题和修复优先级。只读，不改页面。

**如何使用：** 提供目标、版本/入口、用户任务和已批准设计，并说明要技术验收、UX/视觉判断还是两者。两类结论分开，lint、截图与主观观感不互相替代。

## 技术验收

在真实可运行页面上走目标路径，按影响检查：

- 布局与状态：目标宽度、缩放、长内容，空/加载/错误/权限状态下的溢出、遮挡与可操作性。
- 键盘与语义：可访问名称、焦点可见与顺序、菜单/对话框的进入退出与 Escape、关闭后焦点恢复；要实际操作，不只看 DOM 属性。
- 跨端与主题：同一任务语义、对比度、可读性、触控目标、减少动态效果。
- 接缝：真实路由、遮罩/portal、滚动、事件传播与异步反馈。项目指定的自动化门照常执行，测试通过不替代运行检查。

只有截图时只判断可见内容，键盘、状态与交互标未验证，不断言可访问性通过。各项下限、WCAG 条款、证据来源标注与严重度判据见[技术验收判据](references/technical-checks.md)，需要定级或引条款时读。

## UX / 视觉判断

围绕用户能否理解当前状态并完成任务，看信息层级、主次动作、文案、排版节奏、密度、间距与跨页一致性。分清违反已批准设计、可观察的使用障碍和偏好建议；个人审美不报成缺陷。

## 输出与边界

每个问题写位置/状态、复现或视觉证据、影响与建议，按影响排序，只报能定位的。不固定评分、问题数量或审计面板，不起多 Agent 对抗；没问题就说明检查范围。修复是下一项获准的实施，验收本身不改文件、不提交、不发布。

维护共享阈值时：`technical-checks.md` 中带 `ui-threshold` 标记的行与 `soia-dev-design-ui` 的 `craft-floor.md` 由其 `scripts/check_ui_thresholds.py` 核对；普通验收不依赖设计技能。

## 使用边界

### 依赖与安装

无强制技能依赖。单技能 `npx skills add soia-team/soia-open-dev-skills -a <agent> -s soia-dev-audit-ui`；整域 `claude plugin install soia-dev@soia` 或 `codex plugin add soia-dev@soia`（先接入市场 soia-team/soia-open-skills）；WorkBuddy 见[专家安装说明](https://github.com/soia-team/soia-open-skills/blob/main/docs/install/workbuddy.md)。完整步骤见[官方安装说明](https://github.com/soia-team/soia-open-skills#安装)；命令不构成安装授权。

**私密信息与中间数据：** 只用授权材料，引用脱敏；不需要凭据，不建配置/state/cache。要保存的交付物写批准位置，临时数据放系统临时目录，客户原文不进技能仓库。

**日志与完成回执：** 分列实际技术证据、UX/视觉判断和未验证项；无需另建报告文件。
