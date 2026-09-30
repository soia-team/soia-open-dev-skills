---
name: soia-dev-design-ui
description: 设计界面结构、交互状态与视觉并交接实现，守住已批准的品牌与样式。触发：设计这个界面、梳理交互流程、做 UI 设计交接
version: 1.2.1
created_at: 2026-09-08 17:24:05
updated_at: 2026-09-30 13:14:57
created_by: gpt-5
updated_by: claude opus 5.5
---

# soia-dev-design-ui

## 客户可读说明

**能做什么：** 把用户任务变成界面结构、交互状态与视觉方案；按需交付状态说明、可见原型或实现交接。不默认重做整站，不代替产品规格和生产实现。

**如何使用：** 提供目标页面/流程、受众、平台、真实内容和现有设计。沿用已批准的品牌、组件、token 与文案规则；要求保持样式时只动获准部分。

## 设计约束

- 先定主要任务与下一步动作再选布局；关键内容可扫描，不为填空加卡片或装饰。
- 交互写清触发、结果、返回路径与状态归属，覆盖实际流程里的加载、空态、失败、重试、禁用、权限与长内容；不虚构后台能力。
- 复用已有设计系统；确需探索时给有实质差别的可见方向，不凑固定数量或全套变体。
- 窄屏、放大文字、键盘/焦点、触控与减少动态效果是设计的一部分；折叠或挪位不改变任务语义，图标动作有可理解名称。
- 内容或品牌资产缺失时标占位与影响；不猜品牌色，不把假数据或静态交互说成已接通。

量化下限（对比度、行宽、触控尺寸、动效时长档、性能阈值）见[工艺下限](references/craft-floor.md)，方向定稿后读。

## 交付与验证

用客户指定的工具与格式；指定 Open Design 原型、HTML deck 或动画而缺工具时，说明能交付的部分，不自动安装、不拿其他产物冒充。可见产物要实际渲染，在相关宽度核对层级、溢出与关键交互；图稿或原型通过不等于生产 UI 已验收，需要时由 `soia-dev-audit-ui` 另做验收。

交接写清组件/状态/token 对应与待决事项。要求实现或改稿时才改批准的设计产物，讨论或评审不改文件；不自动发布、替换正式稿或重设全局样式。

维护共享阈值时：`craft-floor.md` 与 audit-ui 的 `technical-checks.md` 中带 `ui-threshold` 标记的行由 `scripts/check_ui_thresholds.py` 核对（不一致非零退出，`--selftest` 跑夹具），改任一共享数值后跑一次。

## 使用边界

### 依赖与安装

无强制技能依赖。单技能 `npx skills add soia-team/soia-open-dev-skills -a <agent> -s soia-dev-design-ui`；整域 `claude plugin install soia-dev@soia` 或 `codex plugin add soia-dev@soia`（先接入市场 soia-team/soia-open-skills）；WorkBuddy 见[专家安装说明](https://github.com/soia-team/soia-open-skills/blob/main/docs/install/workbuddy.md)。完整步骤见[官方安装说明](https://github.com/soia-team/soia-open-skills#安装)；命令不构成安装授权。

**私密信息与中间数据：** 只用授权材料，引用脱敏；不需要凭据，不建配置/state/cache。要保存的交付物写批准位置，临时数据放系统临时目录，客户原文不进技能仓库。

**日志与完成回执：** 设计产物本身是主要交付；说明实际改动或未改动、关键依据与未验证部分。
